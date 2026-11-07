# AGENTS.md — Omni_Localizer (OL)

Developer + agent context for the **OL** sub-repo (translation step of the Omni
Suite pipeline: OPP produces MD + XLIFF, OL translates via LLM, ORF backfills).
The [suite AGENTS.md](https://github.com/1StepMore/e2e-test-suite/blob/main/AGENTS.md)
covers cross-module orchestration; this file is for working **inside** OL.

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

# Tests (OMNI_TEST_FAKE_LLM=1 set automatically by make test)
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

Full annotated tree: `docs/dev/source-layout.md`.

## CLI reference

Top commands; the full command + flag table lives in
[`docs/dev/cli-reference.md`](docs/dev/cli-reference.md).

- `ol translate-md <file> -s <src> -t <tgt> -o <dir>` — single MD file
- `ol translate-xliff <file> -s <src> -t <tgt>` — XLIFF file
- `ol translate-batch <dir> -s <src> -t <tgt> -o <out> --concurrency 10` — batch
- `ol init` / `ol doctor` — bootstrap + validate model-pool config (5 checks)

## MCP tools (21 total)

The Agent-facing surface. The runtime list is `get_capabilities`.

| Tool | Purpose |
|------|---------|
| `translate_md_text` | Translate markdown text directly without file I/O (text in, text out). |
| `translate_xliff` | Translate an XLIFF file (writes `<target>` elements to the output file). |
| `translate_file` | Translate a document file end-to-end (OPP → OL → ORF); shells out to the module CLIs and manages a temp workspace. |
| `batch_translate_texts` | Translate multiple texts in parallel. |
| `judge_text` | Evaluate translation quality using the LLM judge. |
| `load_glossary` | Load a JSON glossary file for use in translation. |
| `get_relevant_terms` | Extract relevant glossary terms for a given text. |
| `search_tm` | Search translation memory for similar past translations. |
| `add_tm_entries` | Add translation entries to a TMX file (creates the file if it doesn't exist). |
| `extract_terms` | Extract key terms from source texts using YAKE. |
| `shield_md_text` | Replace code/links/math/HTML/images in markdown with `[OL:TYPE:NNNN]` placeholders. |
| `unshield_md_text` | Restore `[OL:TYPE:NNNN]` placeholders using the shield_map from a prior `shield_md_text` call. |
| `extract_warnings` | Read a file (MD or XLIFF) and extract OL warning markers as structured entries. |
| `generate_report` | Generate HTML and CSV quality reports from translation warnings and model costs. |
| `inspect_config` | Inspect OL configuration: models, paths, LQA settings (API keys and hardcoded-token base_urls redacted). |
| `disambiguate` | Resolve polysemous terms in text using context-aware, confidence-based selection from a glossary. |
| `verify_terms` | Verify glossary term usage in translated content. |
| `profile_doc` | Profile a document's writing style using an LLM; returns a StyleGuide. |
| `get_translation_status` | Poll the status of an async translation task by request_id. |
| `get_capabilities` | Return OL module capabilities: roles, language pairs, available tools. |
| `ping` | Health check endpoint. |

The translation tools' responses carry a `quality_gates` field
(`ran` / `not_run` / `skipped`) and non-blocking `warnings`
(issue #115, `docs/API.md` § 2.1–2.2). The complete per-tool parameter
reference is [`docs/API.md`](docs/API.md).

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

- Cross-module orchestration + pre-commit hooks + compatibility matrix: [suite AGENTS.md](https://github.com/1StepMore/e2e-test-suite/blob/main/AGENTS.md)
- MCP tool full parameter reference: [`docs/API.md`](docs/API.md); user-facing guide: `AGENT_USAGE.md` (this repo)

## Issue conventions

- **`pinned` = 常开索引件, not a to-do.** A pinned issue stays open as a
  roadmap pointer; do not close it, and do not consume it as a work item.
- **Cross-repo reference check.** `scripts/doc_inventory.py` verifies
  backticked paths in `README.md` / `AGENTS.md`. Write another repo's path
  with a `suite:` / `opp:` / `ol:` / `orf:` prefix; an unprefixed path must
  exist in this repo. The checker's shared block is byte-identical across the
  three module repos — change rule: `suite:docs/dev/doc-inventory-copies.md`.

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
10-minute checklist: `suite:docs/dev/validation-director-loop.md` in the suite
repo. Per-repo validation delivery (run_meta, report card, delivery
package): `suite:docs/dev/per-repo-validation-delivery.md`. OL scenario fixes
now live HERE (in `scenarios/`); OL product-code fixes go through the
normal fix cycle in this repo.

## Role routing (A2 pointer model, 2026-11-08)

角色契约唯一事实源 = 套件根仓 `.agents/roles/`（coder/maintainer/tester/user，各 ≤30 行），本仓不设本地副本。
进入本仓的 agent：先读套件根 `AGENTS.md` 的 §0 安全与优先级 + 角色路由表，再按指派角色读对应契约；
期望映射层 = 套件根 `.agents/expectations/`，期望唯一事实源 = `scenarios/STANDARDS.md`（均 Owner 门禁）；standalone clone 按本仓 `docs/` 工作、边界按 §0 类推。
