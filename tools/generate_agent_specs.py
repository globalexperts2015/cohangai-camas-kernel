"""Generate SPEC.md per agent từ agent.py docstring + tool schema.

Reads agent.py + prompt_template.py if exists + generates SPEC.md with:
- Mục đích (from docstring)
- Framework encoded (from module docstring)
- Input schema (from EXPECTED_EVENTS + payload patterns)
- Output schema (from SUBMIT_*_TOOL input_schema)
- Acceptance criteria template
- Performance benchmark template
- Production deployment checklist template

Usage:
    cd cohangai/services/camas-kernel
    python3 tools/generate_agent_specs.py --all
    python3 tools/generate_agent_specs.py --agent bc12_consciousness_tracker
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


AGENTS_DIR = Path(__file__).parent.parent / "agents"

SPRINT_13_AGENTS = [
    "offer_engineer",
    "financial_modeler",
    "niche_validator",
    "demand_research",
    "content_distributor",
    "trust_capital_tracker",
    "overlay_a_cohort_comparison",
    "overlay_a_antifragility",
]

TIER_2_AGENTS = [
    "bc12_consciousness_tracker",
    "bc13_pain_scorer",
    "bc14_joy_mapper",
    "bc15_character_builder",
    "bc16_value_ladder",
    "bc17_grand_slam_offer",
    "bc18_value_equation",
    "bc19_funnel_architect",
    "bc20_copy_stack",
]

L2_AGENTS = [
    "l2_vision_clarity",
    "l2_niche_validator_student",
    "l2_transformation_mapper_7d",
    "l2_vpc_fit_checker",
    "l2_mvo_cohort_launcher",
    "l2_offer_engineer_student",
    "l2_referral_engine_template",
]

ALL_AGENTS = SPRINT_13_AGENTS + TIER_2_AGENTS + L2_AGENTS


def extract_docstring(agent_py: Path) -> str:
    """Extract module-level docstring from agent.py."""
    text = agent_py.read_text()
    m = re.match(r'"""(.+?)"""', text, re.DOTALL)
    if not m:
        return ""
    return m.group(1).strip()


def extract_expected_events(agent_py: Path) -> list[str]:
    """Find EXPECTED_EVENTS = {"..."} set."""
    text = agent_py.read_text()
    m = re.search(r"EXPECTED_EVENTS\s*=\s*\{([^}]+)\}", text)
    if not m:
        return []
    raw = m.group(1)
    events = re.findall(r'"([^"]+)"', raw)
    return events


def extract_class_name(agent_py: Path) -> str:
    """Find class XxxYyy(BaseBC) line."""
    text = agent_py.read_text()
    m = re.search(r"^class\s+(\w+)\(BaseBC\)", text, re.MULTILINE)
    return m.group(1) if m else ""


def extract_agent_name(agent_py: Path) -> str:
    """Find name = '...' attribute."""
    text = agent_py.read_text()
    m = re.search(r'^\s+name\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return m.group(1) if m else ""


def extract_scope(agent_py: Path) -> str:
    text = agent_py.read_text()
    m = re.search(r'^\s+scope\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return m.group(1) if m else ""


def extract_autonomy(agent_py: Path) -> str:
    text = agent_py.read_text()
    m = re.search(r"autonomy_level\s*=\s*AutonomyLevel\.(\w+)", text)
    return m.group(1) if m else "L1_AUTO"


def extract_default_model(agent_py: Path) -> str:
    text = agent_py.read_text()
    m = re.search(r'DEFAULT_MODEL\s*=\s*"([^"]+)"', text)
    if m:
        return m.group(1)
    m = re.search(r'DEFAULT_LLM_MODEL\s*=\s*"([^"]+)"', text)
    return m.group(1) if m else "claude-opus-4-7"


def extract_tool_schema_required(agent_dir: Path) -> list[str]:
    """Find tool schema 'required' fields."""
    prompt_template = agent_dir / "prompt_template.py"
    target = prompt_template if prompt_template.exists() else agent_dir / "agent.py"
    if not target.exists():
        return []
    text = target.read_text()
    m = re.search(r'"required"\s*:\s*\[(.+?)\]', text, re.DOTALL)
    if not m:
        return []
    raw = m.group(1)
    fields = re.findall(r'"([^"]+)"', raw)
    return fields


def determine_tier(agent_name: str) -> str:
    if agent_name in SPRINT_13_AGENTS:
        return "Sprint 13 P0/P1"
    if agent_name in TIER_2_AGENTS or agent_name == "bc11_vpc_builder":
        return "Tier 2 (WHO/WHAT)"
    if agent_name in L2_AGENTS:
        return "P2 L2 Cohort 1 wizard"
    return "Tier 1 base"


def generate_spec(agent_dir: Path) -> str:
    """Generate SPEC.md content."""
    agent_py = agent_dir / "agent.py"
    if not agent_py.exists():
        return ""

    agent_name = extract_agent_name(agent_py) or agent_dir.name
    class_name = extract_class_name(agent_py)
    scope = extract_scope(agent_py)
    autonomy = extract_autonomy(agent_py)
    model = extract_default_model(agent_py)
    events = extract_expected_events(agent_py)
    required = extract_tool_schema_required(agent_dir)
    tier = determine_tier(agent_name)
    docstring = extract_docstring(agent_py)

    # First line of docstring as one-liner
    one_liner = docstring.split("\n")[0] if docstring else scope

    events_md = "\n".join(f"- `{e}`" for e in events) or "- (none defined)"
    required_md = "\n".join(f"- `{f}`" for f in required) or "- (no required fields)"

    sections = [
        f"# {class_name or agent_name} Spec",
        "",
        f"## Mục đích",
        "",
        one_liner,
        "",
        f"## Tier",
        "",
        tier,
        "",
        f"## Agent metadata",
        "",
        f"- **name**: `{agent_name}`",
        f"- **class**: `{class_name}`",
        f"- **scope**: {scope}",
        f"- **autonomy_level**: `{autonomy}`",
        f"- **model**: `{model}`",
        "",
        f"## Trigger events",
        "",
        events_md,
        "",
        f"## Required output fields (tool_use schema)",
        "",
        required_md,
        "",
        f"## Framework encoded",
        "",
        "(See agent.py module docstring + knowledge_base.md if exists for full framework reference.)",
        "",
        f"## Input schema",
        "",
        "```json",
        "{",
        f'  "agent_name": "{agent_name}",',
        f'  "trigger_event": "{events[0] if events else "EVENT_NAME"}",',
        '  "venture_context": "breakout|speakout|cohangai|migration|bmcorner|dahafa",',
        '  "payload": { ... }',
        "}",
        "```",
        "",
        f"## Output behavior",
        "",
        "- `success`: bool",
        "- `output_text`: human-readable summary",
        "- `output_payload`: full structured output (tool_use schema)",
        "- `emitted_memories`: list of canonical fact entries → Postgres agent_memory",
        "- `escalation_required`: bool (true nếu quality_check fail hoặc threshold breached)",
        "",
        f"## Quality criteria",
        "",
        "- [ ] All required fields populated",
        "- [ ] No em-dash (universal Anna brand)",
        "- [ ] No forbidden term (mẹ đơn thân/Perth/Adelaide/Gold Coast)",
        "- [ ] Specific (not generic)",
        "- [ ] Vietnamese language native",
        "",
        f"## Acceptance criteria",
        "",
        "- [ ] Compile + import without error",
        "- [ ] Register vào main.py + scheduler",
        "- [ ] Smoke test 1 valid event pass với mock data",
        "- [ ] Anna validate 3-5 sample output quality ≥ 7/10",
        "- [ ] Deploy Railway production verify agents_registered count +1",
        "",
        f"## Performance benchmark",
        "",
        "- **Latency p50**: TBD post Sprint 14 validation",
        "- **Latency p99**: TBD",
        "- **Token usage typical**: ~input 3000-8000, output 1500-6000",
        "- **Cost per call**: ~$0.05-0.15 USD (Opus) hoặc ~$0.01-0.03 (Haiku)",
        "",
        f"## Production deployment checklist",
        "",
        "- [ ] `agent.py` module docstring complete",
        "- [ ] `knowledge_base.md` rich content (nếu Tier 2)",
        "- [ ] `prompt_template.py` extracted (nếu Tier 2)",
        "- [ ] Memory layer wired (canonical fact retrieve)",
        "- [ ] Register `main.py` + scheduler",
        "- [ ] Logging structured",
        "- [ ] Escalation chain wired (Telegram Breakout Ops)",
        "- [ ] Smoke test pass",
        "",
        f"## References",
        "",
        f"- Sprint reference: `cohangai/aios/aios-build-instructions-sprint-13.md` (Sprint 13 spec)",
        f"- Tier 2 spec: `wiki/concepts/breakoutos-tier-2-spec.md`",
        f"- BreakoutOS pattern: `wiki/concepts/breakoutos.md`",
        f"- Framework v2: `wiki/concepts/solo-business-growth-system-v2.md`",
    ]

    return "\n".join(sections)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true", help="Generate for all agents")
    parser.add_argument("--agent", type=str, help="Generate for 1 agent")
    parser.add_argument("--force", action="store_true", help="Overwrite existing SPEC.md")
    args = parser.parse_args()

    targets = []
    if args.all:
        targets = ALL_AGENTS
    elif args.agent:
        targets = [args.agent]
    else:
        parser.print_help()
        return 1

    generated = 0
    skipped = 0
    for agent_name in targets:
        agent_dir = AGENTS_DIR / agent_name
        if not agent_dir.exists():
            print(f"SKIP: {agent_name} (folder not found)")
            continue
        spec_path = agent_dir / "SPEC.md"
        if spec_path.exists() and not args.force:
            print(f"SKIP: {agent_name} (SPEC.md exists, use --force)")
            skipped += 1
            continue
        spec = generate_spec(agent_dir)
        if not spec:
            print(f"SKIP: {agent_name} (agent.py missing)")
            continue
        spec_path.write_text(spec)
        print(f"WRITE: {agent_name}/SPEC.md")
        generated += 1

    print(f"\nDone: {generated} generated, {skipped} skipped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
