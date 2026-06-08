# L2MVOCohortLauncher Spec

## Mục đích

L2.5 MVO Cohort Launcher (NEW), Cohangai cohort 1 week 5-6.

## Tier

P2 L2 Cohort 1 wizard

## Agent metadata

- **name**: `l2_mvo_cohort_launcher`
- **class**: `L2MVOCohortLauncher`
- **scope**: MVO cohort launch playbook Stage 8 (NEW wizard cohort 1 week 5-6)
- **autonomy_level**: `L1_AUTO`
- **model**: `claude-opus-4-7`

## Trigger events

- `cohort.mvo_launch_plan`

## Required output fields (tool_use schema)

- `student_id`
- `mvo_name`
- `mvo_price_vnd`
- `cohort_size_target`
- `weekly_curriculum`
- `first_30d_action_plan`
- `markdown_playbook`
- `summary`

## Framework encoded

(See agent.py module docstring + knowledge_base.md if exists for full framework reference.)

## Input schema

```json
{
  "agent_name": "l2_mvo_cohort_launcher",
  "trigger_event": "cohort.mvo_launch_plan",
  "venture_context": "breakout|speakout|cohangai|migration|bmcorner|dahafa",
  "payload": { ... }
}
```

## Output behavior

- `success`: bool
- `output_text`: human-readable summary
- `output_payload`: full structured output (tool_use schema)
- `emitted_memories`: list of canonical fact entries → Postgres agent_memory
- `escalation_required`: bool (true nếu quality_check fail hoặc threshold breached)

## Quality criteria

- [ ] All required fields populated
- [ ] No em-dash (universal Anna brand)
- [ ] No forbidden term (mẹ đơn thân/Perth/Adelaide/Gold Coast)
- [ ] Specific (not generic)
- [ ] Vietnamese language native

## Acceptance criteria

- [ ] Compile + import without error
- [ ] Register vào main.py + scheduler
- [ ] Smoke test 1 valid event pass với mock data
- [ ] Anna validate 3-5 sample output quality ≥ 7/10
- [ ] Deploy Railway production verify agents_registered count +1

## Performance benchmark

- **Latency p50**: TBD post Sprint 14 validation
- **Latency p99**: TBD
- **Token usage typical**: ~input 3000-8000, output 1500-6000
- **Cost per call**: ~$0.05-0.15 USD (Opus) hoặc ~$0.01-0.03 (Haiku)

## Production deployment checklist

- [ ] `agent.py` module docstring complete
- [ ] `knowledge_base.md` rich content (nếu Tier 2)
- [ ] `prompt_template.py` extracted (nếu Tier 2)
- [ ] Memory layer wired (canonical fact retrieve)
- [ ] Register `main.py` + scheduler
- [ ] Logging structured
- [ ] Escalation chain wired (Telegram Breakout Ops)
- [ ] Smoke test pass

## References

- Sprint reference: `cohangai/aios/aios-build-instructions-sprint-13.md` (Sprint 13 spec)
- Tier 2 spec: `wiki/concepts/breakoutos-tier-2-spec.md`
- BreakoutOS pattern: `wiki/concepts/breakoutos.md`
- Framework v2: `wiki/concepts/solo-business-growth-system-v2.md`