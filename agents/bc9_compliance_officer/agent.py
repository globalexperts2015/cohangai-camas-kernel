"""BC9 Compliance Officer agent.

Pre-publish 7 layer compliance check (MARA + Privacy + Financial + Platform
+ LegendCom + Brand + Facts). Verdict APPROVE / FLAG / BLOCK.

Architecture:
- requires_voice_gate = False vì BC9 chạy SAU BC2 trong pipeline.
- requires_compliance_gate = False vì BC9 CHÍNH LÀ compliance gate (recursion guard).
- Hybrid 2-layer: Layer 1 deterministic regex (fast, catches 80% hard violation)
  + Layer 2 LLM Opus semantic (catches paraphrased / contextual violation).
- Conflict resolution per Constitution Section E: BC9 BLOCK thắng BC2 APPROVE.

LLM injection qua constructor để Scheduler share 1 client duy nhất.
Rule YAML load 1 lần tại constructor để giảm I/O per-run.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from kernel.base_agent import (
    AgentResult,
    AutonomyLevel,
    BaseBC,
    EscalationTarget,
    ExecutionContext,
)
from kernel.llm_layer import LLMLayer

from .prompt_template import (
    COMPLIANCE_TOOL,
    build_review_prompt,
    load_rules,
)

log = logging.getLogger("camas.bc9_compliance_officer")

DEFAULT_MODEL = "claude-opus-4-7"
DEFAULT_MAX_TOKENS = 2500
DEFAULT_TIMEOUT = 60.0

LAYER_ORDER = [
    "mara",
    "privacy",
    "financial",
    "platform",
    "legend_com",
    "brand",
    "facts",
]


class BC9ComplianceOfficer(BaseBC):
    """BC9 compliance officer, pre-publish 7 layer compliance check.

    Verdict: APPROVE (clean) / FLAG (soft) / BLOCK (hard violation).
    """

    name = "bc9_compliance_officer"
    scope = (
        "Pre-publish 7-layer compliance check "
        "(MARA + Privacy + Financial + Platform + LegendCom + Brand + Facts)"
    )
    autonomy_level = AutonomyLevel.L1_AUTO  # BLOCK auto reject; FLAG escalate Anna
    escalate_to = EscalationTarget.TELEGRAM_OPS
    tools: list[str] = []
    requires_voice_gate = False
    requires_compliance_gate = False  # BC9 IS compliance gate, recursion guard

    def __init__(
        self,
        llm: LLMLayer,
        model: str = DEFAULT_MODEL,
    ) -> None:
        super().__init__()
        self.llm = llm
        self.model = model
        # Load 7 layer YAML 1 lần khi khởi tạo
        self.rules = load_rules()
        # Pre-compile regex cho deterministic layer
        self._compiled_rules = self._compile_rules(self.rules)

    async def run(self, ctx: ExecutionContext) -> AgentResult:
        """Review content trong ctx.payload["content"] qua 2 layer."""
        content = ctx.payload.get("content", "") if ctx.payload else ""
        meta = ctx.payload.get("meta", {}) if ctx.payload else {}

        if not content or not str(content).strip():
            return AgentResult(
                success=False,
                output_text="Missing content",
                output_payload={
                    "verdict": "ERROR",
                    "error": "payload.content thiếu hoặc rỗng",
                },
            )

        # Layer 1: deterministic regex scan
        det_violations = self._deterministic_scan(content, meta)

        # Layer 2: LLM semantic check (only if LLM ready)
        if self.llm.ready:
            llm_review = await self._llm_review(content, meta, det_violations)
        else:
            llm_review = {
                "verdict": None,
                "layers": {},
                "violations": [],
                "suggested_fixes": [],
                "notes": "LLM skip, ANTHROPIC_API_KEY chưa set",
            }

        # Combine: Layer 1 hard violation always BLOCK; else trust LLM
        merged = self._merge_verdicts(det_violations, llm_review)
        verdict = merged["verdict"]

        summary = (
            f"verdict={verdict} "
            f"hard={merged['count_hard']} soft={merged['count_soft']}"
        )

        # emit_memories entry for shared memory
        violated_rule_ids = [v["rule_id"] for v in det_violations][:5]
        memory = {
            "agent_name": self.name,
            "content_summary": (
                f"verdict={verdict} "
                f"layers_flagged={merged['count_layers_flagged']} "
                f"channel={meta.get('channel')} "
                f"venture={meta.get('venture')}"
            ),
            "keywords": violated_rule_ids,
            "tags": [
                verdict,
                meta.get("channel", "unknown") or "unknown",
                meta.get("venture", "all") or "all",
            ],
            "venture": meta.get("venture"),
        }

        return AgentResult(
            success=True,
            output_text=summary,
            output_payload=merged,
            emitted_memories=[memory],
        )

    # ------------------------------------------------------------------ #
    # Layer 1, deterministic regex                                       #
    # ------------------------------------------------------------------ #
    def _compile_rules(
        self, rules: dict[str, dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Pre-compile regex patterns cho speed."""
        compiled: list[dict[str, Any]] = []
        for layer_name, ruleset in rules.items():
            for section in ("banned_phrases", "soft_warnings"):
                for rule in ruleset.get(section) or []:
                    pattern = rule.get("pattern")
                    if not pattern:
                        continue
                    try:
                        regex = re.compile(pattern, flags=re.IGNORECASE)
                    except re.error as exc:
                        log.warning(
                            "BC9 rule %s regex fail: %r",
                            rule.get("id"),
                            exc,
                        )
                        continue
                    compiled.append(
                        {
                            "layer": layer_name,
                            "rule_id": rule.get("id", ""),
                            "severity": rule.get("severity", "soft"),
                            "reason": rule.get("reason", ""),
                            "regex": regex,
                            "trigger_keywords": rule.get(
                                "trigger_keywords", []
                            ),
                        }
                    )
        return compiled

    def _deterministic_scan(
        self, content: str, meta: dict
    ) -> list[dict[str, Any]]:
        """Layer 1, run regex over content. Skip rule nếu có trigger_keywords
        mà content không match keyword nào (giảm false positive cho layer)."""
        violations: list[dict[str, Any]] = []
        content_lower = content.lower()
        meta_blob = " ".join(
            str(v) for v in (meta or {}).values() if v
        ).lower()
        scope_blob = content_lower + " " + meta_blob

        for rule in self._compiled_rules:
            triggers = rule.get("trigger_keywords") or []
            if triggers:
                if not any(kw.lower() in scope_blob for kw in triggers):
                    continue
            match = rule["regex"].search(content)
            if match is None:
                continue
            violations.append(
                {
                    "layer": rule["layer"],
                    "rule_id": rule["rule_id"],
                    "severity": rule["severity"],
                    "reason": rule["reason"],
                    "match": match.group(0)[:200],
                }
            )
        return violations

    # ------------------------------------------------------------------ #
    # Layer 2, LLM semantic                                              #
    # ------------------------------------------------------------------ #
    async def _llm_review(
        self,
        content: str,
        meta: dict,
        det_violations: list[dict[str, Any]],
    ) -> dict[str, Any]:
        prompt = build_review_prompt(
            content=content,
            meta=meta,
            rules=self.rules,
            deterministic_violations=det_violations,
        )
        try:
            response = await self.llm.client.messages.create(
                model=self.model,
                max_tokens=DEFAULT_MAX_TOKENS,
                messages=[{"role": "user", "content": prompt}],
                tools=[COMPLIANCE_TOOL],
                tool_choice={
                    "type": "tool",
                    "name": "submit_compliance_review",
                },
                timeout=DEFAULT_TIMEOUT,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("BC9 LLM call fail: %r", exc)
            return {
                "verdict": None,
                "layers": {},
                "violations": [],
                "suggested_fixes": [],
                "notes": f"LLM call fail: {exc}",
            }
        return self._parse_tool_response(response)

    def _parse_tool_response(self, response) -> dict[str, Any]:
        tool_block = None
        text_fallback = ""
        for block in response.content or []:
            block_type = getattr(block, "type", None)
            block_name = getattr(block, "name", None)
            if (
                block_type == "tool_use"
                and block_name == "submit_compliance_review"
            ):
                tool_block = block
                break
            if block_type == "text":
                text_fallback += getattr(block, "text", "")

        if tool_block is None:
            return {
                "verdict": None,
                "layers": {},
                "violations": [],
                "suggested_fixes": [],
                "notes": "No submit_compliance_review tool_use block",
                "raw_response": text_fallback[:500],
            }

        data = tool_block.input or {}
        return {
            "verdict": data.get("verdict"),
            "layers": data.get("layers", {}),
            "violations": data.get("violations", []),
            "suggested_fixes": data.get("suggested_fixes", []),
            "notes": data.get("notes", ""),
            "raw_response": json.dumps(data, ensure_ascii=False),
        }

    # ------------------------------------------------------------------ #
    # Merge layer 1 + layer 2                                            #
    # ------------------------------------------------------------------ #
    def _merge_verdicts(
        self,
        det_violations: list[dict[str, Any]],
        llm_review: dict[str, Any],
    ) -> dict[str, Any]:
        """Layer 1 hard violation ALWAYS BLOCK. Else trust LLM verdict.
        Build per-layer status from both layers."""
        layers: dict[str, str] = {layer: "clean" for layer in LAYER_ORDER}

        # Apply deterministic violations
        for v in det_violations:
            layer = v["layer"]
            current = layers.get(layer, "clean")
            new_sev = "hard" if v["severity"] == "hard" else "soft"
            # hard wins over soft, soft wins over clean
            if new_sev == "hard" or current == "clean":
                layers[layer] = new_sev

        # Merge LLM per-layer (LLM may detect paraphrased violation)
        llm_layers = llm_review.get("layers") or {}
        for layer, status in llm_layers.items():
            if layer not in layers:
                continue
            status_clean = (status or "").strip().lower()
            if status_clean not in {"clean", "soft", "hard"}:
                continue
            current = layers[layer]
            if status_clean == "hard" or (
                status_clean == "soft" and current == "clean"
            ):
                layers[layer] = status_clean

        count_hard = sum(1 for s in layers.values() if s == "hard")
        count_soft = sum(1 for s in layers.values() if s == "soft")
        count_layers_flagged = count_hard + count_soft

        # Verdict logic
        if count_hard > 0:
            verdict = "BLOCK"
        elif count_soft > 0:
            verdict = "FLAG"
        else:
            verdict = "APPROVE"

        # Override: if LLM explicitly said BLOCK and we missed hard, trust LLM
        llm_verdict = (llm_review.get("verdict") or "").upper()
        if llm_verdict == "BLOCK" and verdict != "BLOCK":
            verdict = "BLOCK"

        # Combine violations
        det_ids = [
            f"{v['layer']}.{v['rule_id']} ({v['severity']})"
            for v in det_violations
        ]
        llm_ids = list(llm_review.get("violations") or [])
        all_violations = det_ids + llm_ids

        # Build suggested fixes (LLM only, since deterministic doesn't suggest)
        suggested_fixes = list(llm_review.get("suggested_fixes") or [])

        return {
            "verdict": verdict,
            "layers": layers,
            "violations": all_violations,
            "suggested_fixes": suggested_fixes,
            "notes": llm_review.get("notes", ""),
            "count_hard": count_hard,
            "count_soft": count_soft,
            "count_layers_flagged": count_layers_flagged,
            "deterministic_violations": det_violations,
        }
