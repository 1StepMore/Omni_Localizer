---
name: omni-validation
description: Run the Omni Suite validation framework — 83 scenario checks covering every agent-facing MCP tool (41), all 14 OPP input formats, 16 ORF output formats, XLIFF backfills, and the human-quality bar. Drive it from the CLI without reading engine source.
compatibility: hermes
---

# Omni-Validation

## When to Use
Use this skill when you need to prove the Omni Suite works, or verify a change did not
break it. Examples:
- Confirming every agent-facing MCP tool works as an agent would use it (agent-user conformance)
- Checking end-to-end translations meet the human-quality bar (LQA, fidelity, punctuation)
- Confirming a regression guard still holds (e.g. PDF → XLIFF blocked)

The framework lives at the Omni Suite checkout root (the directory containing
`scenarios/`, `scripts/validation/`, and `omni_mcp/`). Run every command from that root.

## How to validate

### 1. See what is available (no execution)
1. Run `--list` to enumerate scenarios by name, tier, and required env:
   ```
   python scripts/validation/run_validation.py --list
   ```
2. Run `--check` to lint the scenario library without executing: every step must be
   falsifiable, no command self-echoes PASS/FAIL, and every `standard:` citation must
   resolve to a `scenarios/STANDARDS.md` anchor. Exit 0 = clean; exit 1 = findings.
   ```
   python scripts/validation/run_validation.py --check
   ```

### 2. Run scenarios
1. Run the hermetic, no-key tier (structural checks only — no LLM, no API keys):
   ```
   python scripts/validation/run_validation.py --tier 1
   ```
2. Run a focused subset with `--scenario <substr>` (matches the scenario FILENAME stem,
   case-insensitive). Use real stems:
   - `--scenario tool-` — all 41 per-tool agent-surface checks
   - `--scenario opp` — 14 OPP extraction formats
   - `--scenario orf-md` — 16 ORF backfill formats
   - `--scenario orf-xliff` — XLIFF backfill + cross-format `--force`
   - `--scenario pipeline` — 3 end-to-end quality-bar scenarios (tier 2, needs LLM keys)
   - `--scenario regression` — the T2 PDF→XLIFF guard
   `agent-surface` itself matches no stem; use `tool-`. Add `--verbose` for per-step detail.
3. Exit code 0 means no failures; `passed` / `recovered` / `partial-pass` / `unconfigured`
   are NOT failures. Exit 1 means a scenario failed or the lint found a violation.

### 3. Read the report
1. Each run is persisted under `validation-runs/<ts>/` with `scenarios.json`; the
   `latest.txt` file holds the timestamp of the newest run:
   ```
   cat validation-runs/latest.txt
   ```
2. Generate the director report (no args = newest run from `latest.txt`):
   ```
   python scripts/validation/validation_report.py
   # or explicitly: python scripts/validation/validation_report.py validation-runs/<ts>/scenarios.json
   ```
3. Read `validation-runs/<ts>/report.md`. It renders TWO verdict families side by side:
   - **agent-user conformance** — every agent-facing surface works as an agent would use it
   - **human-quality conformance** — the pipeline output meets the end-user bar
   Markers: GREEN / RED / UNCONFIGURED / PARTIAL-PASS / GREEN (recovered). Blockers are
   findings only (no auto-fix); every step line reads `checked <surface> against <standard> → <actual>`.

### 4. Standards and checklist pointers
- Every scenario step cites the bar it enforces as `standard: STANDARDS.md#<anchor>`. The
  authoritative thresholds live in `scenarios/STANDARDS.md`: AGENT-SURFACE (`#tool-contract`,
  `#json-parseable`, `#error-clarity`, `#path-security`, `#exit-codes`) and HUMAN-QUALITY
  (`#lqa-threshold`, `#para-ratio`, `#cjk-density`, `#punct-hygiene`, `#drawing-count`,
  `#opens-docx`). Read it when you need the exact threshold.
- The human director's 10-minute checklist (per-run standards-conformance pass) is at
  `docs/dev/validation-director-loop.md`.

## Pitfalls
- **Honesty rule**: tier-2/3 scenarios (LLM quality bar) report `unconfigured` when API
  keys are absent — that is the honest result, not a failure, and NOT a green. Never fake
  a green; never set `OMNI_TEST_FAKE_LLM` to make quality scenarios pass. Real evidence only.
- **`--scenario` is filename-substring**: `--scenario agent-surface` matches no stem and
  exits 0 without running anything. Use a real stem (`tool-`, `opp`, `orf-md`, ...).
- **Working directory**: all commands run from the suite checkout root, not this repo's root.
- Use `.venv_ol/bin/python` in place of `python` if `python` is not on your PATH.

## Verification
1. `python scripts/validation/run_validation.py --check` exits 0.
2. `python scripts/validation/run_validation.py --tier 1` exits 0 (hermetic structural
   checks green; gated env scenarios may report `unconfigured`).
3. `python scripts/validation/validation_report.py` prints `REPORT: validation-runs/<ts>/report.md`.
4. The report contains both "agent-user conformance" and "human-quality conformance" families.
