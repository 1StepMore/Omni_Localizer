# AGENTS.md — Omni_Localizer (OL)

Developer + agent context for the **OL** sub-repo. The suite-level
[suite-level AGENTS.md](https://github.com/1StepMore/e2e-test-suite/blob/main/AGENTS.md) covers cross-module
orchestration (OPP → OL → ORF); this file is for working **inside**
OL.

> OL is the translation step of the Omni Suite pipeline. OPP
> produces MD + XLIFF, OL translates them via LLM, ORF backfills into
> the target format.

This file is an **index + invariants** file (≤200 lines, #162): detail
lives in `docs/dev/*.md` and `docs/API.md`, not here.

## Quick start

```bash
# Install
bash scripts/setup_dev.sh

# Bootstrap config + verify (run 'ol init' to generate config/local.yaml, then 'ol doctor' to verify)
ol init
ol doctor

# CLI: translate a single MD file
ol translate-md document.md -s en -t zh -o /tmp/out

# CLI: batch translate a directory
ol translate-batch ./docs/ -s en -t zh -o ./translated/

# CLI: translate XLIFF (advanced)
ol translate-xliff doc.xlf -s en -t zh -o ./translated/

# MCP server (stdio)
ol-mcp            # or: python -m ol_mcp

# Tests (must set OMNI_TEST_FAKE_LLM=1 to avoid real LLM calls)
make test
```

## Source layout

```
src/
├── ol_cli.py / cli/         # `ol` CLI entry (Typer) — 21 sub-commands
├── ol_config/               # YAML config + Pydantic schema (LLMPoolConfig)
├── ol_pool/                 # ModelPool (litellm Router) + prompts/*.txt store
├── ol_md/                   # MD channel: shield → translate → repair → unshield
├── ol_xliff/                # XLIFF channel (parser, repair, polish)
├── ol_lqa/                  # Judge + 8 quality gates (quality_gates.py)
├── ol_mcp/                  # MCP server (the Agent-facing surface)
└── …                        # buses, batch, terminology, restoration, tm, style…
```

Full annotated tree: `docs/dev/source-layout.md` (regenerate motivation:
see `git log --follow src/` for anything not covered here).

## CLI reference

Top commands; the full command + flag table lives in
[`docs/dev/cli-reference.md`](docs/dev/cli-reference.md).

- `ol translate-md <file> -s <src> -t <tgt> -o <dir>` — single MD file
- `ol translate-xliff <file> -s <src> -t <tgt>` — XLIFF file
- `ol translate-batch <dir> -s <src> -t <tgt> -o <out> --concurrency 10` — batch
- `ol init` / `ol doctor` — bootstrap + validate model-pool config (5 checks)

## MCP tools (21 total)

The Agent-facing surface. The complete per-tool parameter reference is
[`docs/API.md`](docs/API.md); the runtime list is `get_capabilities`.

- Primary: `translate_md_text` / `translate_xliff` — text-in/text-out;
  responses carry a `quality_gates` field (`ran` / `not_run` / `skipped`)
  and non-blocking `warnings` (issue #115, `docs/API.md` § 2.1–2.2).
- Support: `judge_text`, `load_glossary`, `get_relevant_terms`, `search_tm`,
  `batch_translate_texts`, `translate_file` (full OPP → OL → ORF chain),
  `shield_md_text` / `unshield_md_text`, `extract_warnings`,
  `verify_terms`, `profile_doc`, `get_capabilities`, `ping`, …

## Translation pipeline (MD channel)

6 stages: **shield → translate → repair (4 levels) → unshield → postproc
→ 8 quality gates**. The stage diagram, prompt-store rules (prompts are
`string.Template` files under `src/ol_pool/prompts/`, fail-loud
rendering), the E2E regression contracts (E2E-65/14/64/77/78/83) and the
channel-selection decision table live in
[`docs/dev/pipeline.md`](docs/dev/pipeline.md).

## Model pool + env vars (critical invariants)

Full tables: [`docs/dev/llm-pool.md`](docs/dev/llm-pool.md).

- **`OMNI_TEST_FAKE_LLM=1` is required for tests** (mock LLM seam); unset
  it only for real-LLM validation. Decision matrix:
  [`docs/dev/gotchas.md`](docs/dev/gotchas.md).
- **`MCP_ALLOWED_DIRECTORIES` (or `OL_MCP_ALLOWED_DIRS`) is REQUIRED and
  fail-CLOSED** for `ol-mcp` — unset ⇒ `OL_MCP_NOT_CONFIGURED`, the
  server refuses to serve. Recovery = set the env var, never loosen the
  request.
- **BYOK gate is OR, not AND**: the CLI pre-check passes when at least
  one referenced provider key is set (`AMD_API_KEY` / `ZHIPU_API_KEY`).
- Provider/rate-limit semantics and the two-layer `${VAR}` resolution:
  [`docs/dev/llm-pool.md`](docs/dev/llm-pool.md).

## Tests

```bash
make test                            # all tests via uv run pytest tests/ -v
OMNI_TEST_FAKE_LLM=1 pytest tests/test_e2e_77_math_shield.py   # one regression
```

Coverage target ≥90%. Key regression files (E2E-74 context handling,
E2E-77 math shield, E2E-78 html shield/unshield, E2E-83 large content):
see `tests/test_e2e_*.py`; the full key-file list lives in
[`docs/dev/gotchas.md`](docs/dev/gotchas.md).

## Known issues / gotchas

The full list (OL#53 polish guard, OL#54 truncation detection, OL#55
XLIFF tag normalization, OL#56 quality-gate table with warning codes,
circuit breaker, FAKE_LLM decision matrix) lives in
[`docs/dev/gotchas.md`](docs/dev/gotchas.md). The three agents hit most:

- Prompt-injection echo is stripped by repair (E2E-65) — don't strip it
  yourself.
- `large content (>~50K chars)` warns but is not blocked (E2E-83).
- Circuit breaker: 5 consecutive failures → open for 60s.

## Pointers to the suite-level docs

- Cross-module orchestration: [AGENTS.md](https://github.com/1StepMore/e2e-test-suite/blob/main/AGENTS.md)
- MCP tool full parameter reference: [`docs/API.md`](docs/API.md)
- Pre-commit hooks: [.pre-commit-config.yaml](https://github.com/1StepMore/e2e-test-suite/blob/main/.pre-commit-config.yaml)
- Compatibility matrix: [COMPATIBILITY.md](https://github.com/1StepMore/e2e-test-suite/blob/main/COMPATIBILITY.md)
- User-facing guide (not developer): `AGENT_USAGE.md` in this repo

## How to validate this module

OL ships its own validation scenario library **in this repo** at
`scenarios/` — 5 tier-2 `ol-translation` scenarios with their own
`scenarios/STANDARDS.md` + `scenarios/_fixtures/`. They need real LLM
keys (`requires_env`: the 2 canonical provider vars `AMD_API_KEY` /
`ZHIPU_API_KEY`) and report `unconfigured` without them — never a fake
green. The suite validation engine runs them via `--repo ol`.

```bash
# From the Omni Suite root (clone: https://github.com/1StepMore/e2e-test-suite)
source .venv_ol/bin/activate

# List OL's in-repo scenarios
python scripts/validation/run_validation.py --repo ol --list

# Run OL's tier-2 translation scenarios (real LLM keys required;
# reports `unconfigured` without them)
python scripts/validation/run_validation.py --repo ol --tier 2

# Full quality bar (suite-level, real LLM keys; reports `unconfigured` without them)
python scripts/validation/run_validation.py --module suite --tier 2

# Coverage: every OL MCP tool must be scenario-exercised
python scripts/validation/coverage_audit.py   # ol row must show 21/21, 0 missing
```

The standards bar is `scenarios/STANDARDS.md` (AGENT-SURFACE family for
the tool scenarios; HUMAN-QUALITY family — lqa-threshold, para-ratio,
cjk-density, punct-hygiene — for the pipeline scenarios). Director loop +
10-minute checklist: `docs/dev/validation-director-loop.md` in the suite
repo. Per-repo validation delivery (run_meta, report card, delivery
package): `docs/dev/per-repo-validation-delivery.md`. OL scenario fixes
now live HERE (in `scenarios/`); OL product-code fixes go through the
normal fix cycle in this repo.
