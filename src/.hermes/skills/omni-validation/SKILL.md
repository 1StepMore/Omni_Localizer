---
name: omni-validation
description: Validate the Omni Suite (scenario library; agent-user conformance + human-quality conformance). Thin pointer — the authoritative SOP with gate-enforced counts lives at the Omni Suite checkout root, not in this OL-side copy.
compatibility: hermes
---

# Omni-Validation (pointer)

This is a **thin pointer**: it carries no counts, no format lists, and
no thresholds — those drifted here before (2026-10-30 audit), so they
now live only in the gated source at the Omni Suite checkout root:

    <suite checkout root>/.opencode/skills/omni-validation/SKILL.md

Read that skill first. It owns: the scenario-library SOP (`--list` /
`--scenario <stem> --tier 1` / `--check`), the coverage audit, the
director report, the two verdict families (agent-user conformance +
human-quality conformance), and the honesty rules.

Quick shape — run everything from the **suite checkout root** (the
directory containing `scenarios/`, `scripts/validation/`, `omni_mcp/`;
NOT this OL repo's root):

```bash
python scripts/validation/run_validation.py --list                  # enumerate (no execution)
python scripts/validation/run_validation.py --scenario <name> --tier 1
python scripts/validation/run_validation.py --check                 # contract-lint the library
python scripts/validation/coverage_audit.py                         # every live MCP tool exercised
```

Honesty rules that never drift: no mocks and no `OMNI_TEST_FAKE_LLM` as
quality evidence; tier-2/3 scenarios without real LLM keys report
`unconfigured` — never a pass, never a silent skip; every step cites
`standard: STANDARDS.md#<anchor>` from `scenarios/STANDARDS.md`.

Standards bar: `scenarios/STANDARDS.md`. Director loop:
`docs/dev/validation-director-loop.md`.
