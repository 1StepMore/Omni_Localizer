# AGENTS.md — Omni_Localizer (OL)

Developer + agent context for the **OL** sub-repo. The suite-level
[suite-level AGENTS.md](https://github.com/1StepMore/e2e-test-suite/blob/main/AGENTS.md) covers cross-module
orchestration (OPP → OL → ORF); this file is for working **inside**
OL.

> OL is the translation step of the Omni Suite pipeline. OPP
> produces MD + XLIFF, OL translates them via LLM, ORF backfills into
> the target format.

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
ol mcp            # or: python -m ol_mcp

# Tests (must set OMNI_TEST_FAKE_LLM=1 to avoid real LLM calls)
make test
# Or: OMNI_TEST_FAKE_LLM=1 uv run pytest tests/ -v
```

## Source layout

```
src/ol/
├── __init__.py              # __version__
├── cli.py                   # `ol` CLI entry (Typer)
├── config/                  # YAML config + Pydantic schema
│   ├── schema.py            # LLMPoolConfig, ProjectConfig
│   └── loader.py            # load_config() with ${ENV_VAR} resolution
├── pool/                    # ModelPool (litellm Router wrapper)
│   ├── __init__.py          # exports has_source_language_residual()
│   └── router.py            # E2E-83: pre-call check removed
├── md/                      # MD translation channel
│   ├── shield.py            # E2E-77/78: math regex + [OL:...] markers
│   ├── repair/              # 4-layer repair (regex → span → LLM → fallback)
│   ├── extractor.py         # Tokenize MD into translatable units
│   ├── pipeline.py          # MDRepairPipeline
│   └── shield/              # Lower-level shield utilities
├── xliff/                   # XLIFF translation channel
│   ├── repair/              # E2E-64: is_complete() checks actual XML
│   ├── bus.py               # XLIFF write_target_back
│   └── parser.py            # trans-unit iteration
├── buses/                   # Shared translation bus (md_bus, xliff_bus)
├── batch/                   # BatchProcessor
├── terminology/             # RAG-based prompt injection
│   ├── rag_injector.py      # build_translate_prompt with TM/glossary
│   ├── extractor.py         # YAKE term extraction
│   └── disambiguator.py     # LLM-based polysemy resolution
├── lqa/                     # Linguistic Quality Assurance
│   ├── judge.py             # JudgeService (score 0-100)
│   ├── scoring.py           # LQA rules
│   └── quality_gates.py     # OL#56: 8 quality gate functions (inline tags, terminology, length ratio, locale, source_copy, source_script_fragments, protocol_artifacts, terms_audit)
├── restoration/             # Post-translate placeholder restoration
├── concurrency/             # ConcurrencyLimiter (semaphores)
├── retry/                   # RetryManager
├── logging/                 # Structured JSON + console logger
├── checkpoint/              # Translation checkpointing
└── mcp_tools/               # MCP server (the Agent-facing surface)
```

## CLI reference

| Command | Purpose |
|---------|---------|
| `ol translate-md <file> -s <src> -t <tgt> -o <dir>` | Translate a single MD file |
| `ol translate-md <file> -s en -t zh --chunk-by-paragraph` | Translate paragraph-by-paragraph (better for literary text) |
| `ol translate-md <file> --no-glossary --no-restoration` | Disable optional stages |
| `ol translate-xliff <file> -s <src> -t <tgt>` | Translate an XLIFF file |
| `ol translate-batch <dir> -s <src> -t <tgt> --concurrency 10` | Batch translate a directory |
| `ol extract-warnings <file>` | Extract placeholder restoration warnings from an output |
| `ol init [--config -c PATH] [--non-interactive] [--force]` | Interactive wizard generating `config/local.yaml` with the unified model pool |
| `ol doctor [--config -c PATH] [--json]` | Validate model-pool config (5 checks) and print a pass/fail checklist |
| `ol mcp` | Start the MCP server (stdio) |

### Common flags

- `--config <path>` — path to YAML config (default `config/default.yaml`)
- `--glossary <path>` — glossary JSON file (overrides config)
- `--no-glossary` — disable glossary injection even if config has one
- `--chunk-by-paragraph` — split by blank lines, translate each separately
- `--concurrency <N>` — max concurrent translations
- `--no-frontmatter` — skip YAML frontmatter injection
- `--no-restoration` — skip post-translate placeholder restoration (Level 3 LLM)
- `--log-format console|json` — log output format

## MCP tools (21 total)

| Tool | Purpose |
|------|---------|
| `translate_md_text` | Translate markdown text (text-in/text-out). Returns optional `warnings` field with post-translation quality gate results. The primary Agent tool. |
| `translate_xliff` | Translate an XLIFF file (text-in/text-out). Per-unit quality gate notes written to `<note>` elements in output. |
| `judge_text` | Evaluate translation quality (returns adequacy/fluency/terminology/format scores) |
| `load_glossary` | Load a JSON glossary file |
| `get_relevant_terms` | Extract top-k relevant glossary terms for a source text |
| `search_tm` | Search TMX translation memory for similar past translations |
| `batch_translate_texts` | Translate multiple texts in parallel |
| `translate_file` | Translate a document file end-to-end (OPP → OL → ORF), shelling out to the `opp`/`ol`/`orf` CLIs |
| `extract_terms` | Extract key terms from source texts using YAKE (ML deps required) |
| `add_tm_entries` | Add translation entries to a TMX file, creating it if missing |
| `shield_md_text` | Replace code/links/math/HTML/images in markdown with `[OL:TYPE:NNNN]` placeholders |
| `unshield_md_text` | Restore `[OL:TYPE:NNNN]` placeholders using a prior `shield_map` |
| `generate_report` | Generate HTML + CSV quality reports from translation warnings and model costs |
| `inspect_config` | Inspect OL configuration (models, paths, LQA settings); API keys are redacted |
| `disambiguate` | Resolve polysemous terms in text using context-aware confidence-based selection from a glossary |
| `extract_warnings` | Read an MD/XLIFF file and extract OL warning markers as structured `WarningEntry` objects |
| `get_translation_status` | Poll the status of an async translation task by `request_id` |
| `verify_terms` | Verify glossary term usage in translated content |
| `profile_doc` | Profile a document's writing style, returning a `StyleGuide` |
| `get_capabilities` | Return OL module capabilities: roles, language pairs, and available MCP tools |
| `ping` | Health check |

For full per-tool parameter reference, see the suite-level
[AGENTS.md → MCP Tool Reference](https://github.com/1StepMore/e2e-test-suite/blob/main/AGENTS.md) table,
or [agent-pipeline-guide.md](https://github.com/1StepMore/e2e-test-suite/blob/main/docs/agent-pipeline-guide.md).

## Translation pipeline (MD channel)

OL's MD translation is a 4-stage pipeline:

```
   input.md
     │
     ▼
  ┌─────────────┐
  │  1. SHIELD   │  Replace code blocks, math ($..$), links, images,
  │             │  HTML, autolinks with [OL:TYPE:NNNN] markers
  └─────────────┘
     │  shielded.md + shield_map
     ▼
  ┌─────────────┐
  │  2. TRANSLATE│  LLM call (litellm Router → ModelPool)
  │             │  with retry + circuit breaker + rate limit
  └─────────────┘
     │  translated.md (with markers preserved)
     ▼
  ┌─────────────┐
  │  3. REPAIR   │  4-layer restoration of any markers the LLM
  │             │  mangled / dropped:
  │             │    Level 1: regex (fast)
  │             │    Level 2: span alignment
  │             │    Level 3: LLM-based (LiteLLMRestorer)
  │             │    Level 4: safe fallback (append at end with warning)
  └─────────────┘
     │  repaired.md
     ▼
  ┌─────────────┐
  │ 4. UNSHIELD  │  Replace [OL:TYPE:NNNN] markers with original content
  │             │  from shield_map. Missing markers → OL_WARN comment.
  └─────────────┘
     │  output.md
     ▼
   ┌─────────────┐
   │ 5. POSTPROC  │  zh↔en punctuation normalization (ol_post.punctuation)
   │             │  + YAML frontmatter injection (source/target lang, ...)
   └─────────────┘
      │
      ▼
   ┌──────────────┐
    │ 6. QUALITY   │  8 gates run after translation/repair, warnings
    │    GATES     │  appended during final output generation:
    │             │  • inline_tags — verify <bx>/<ex>/<x> tag parity
    │             │  • terminology — detect mixed source/glossary term usage
    │             │  • length_ratio — fail if OL_LENGTH_RATIO_MIN..MAX exceeded
    │             │  • locale — currency mixing, date leakage, digit grouping,
    │             │            unit spelling (en-US vs en-GB)
    │             │  • source_copy — detect unchanged source echo in target
    │             │  • source_script_fragments — detect CJK residue in non-CJK target locale
    │             │  • protocol_artifacts — detect LLM protocol markers leaked to output
    │             │  • terms_audit — full glossary term audit via verify_translation
   └──────────────┘
      │
      ▼
   output.md (final)
```

### E2E-65: Prompt injection strip

If the LLM echoes back `CRITICAL: Output ONLY the translation...` or
similar system-prompt fragments, the Level 1 repair strips them via
regex. Don't strip these patterns yourself; OL handles it.

### E2E-14: Base64 image dedup

After translation, if the LLM re-encoded `![…](…)` image refs as
fresh base64 lines, they're deduplicated. OPP already produced the
canonical refs in the input.

### E2E-64: XLIFF repair `is_complete()`

The XLIFF repair pipeline checks that the XLIFF has all `<target>`
elements filled. If not, it attempts restoration before writing the
output.

### E2E-77/78: Shield marker format + unshield fallback

- Math: `$..$` only matched if it contains a LaTeX marker
  (`\command`, `^`, or `_`) — currency text is not eaten.
- HTML: `[OL:HTML:NNNN]` ASCII-delimited markers (not NUL-delimited
  which LLMs would strip).
- Unshield: if a marker is missing, the original content is appended
  at the end under a `<!-- OL_WARN:missing_shields key1,key2,... -->`
  comment, never silently lost.

### E2E-83: litellm pre-call check removed

OL used to pass `optional_pre_call_checks=['enforce_model_rate_limits']`
to litellm's Router, which fast-rejected large requests (>~50KB /
>~20K tokens) and triggered 10/20/40s backoffs in the translate()
retry loop. This was removed; per-model RPM is still set in
`litellm_params['rpm']` but rejection now comes from the provider's
HTTP 429 (handled by the existing backoff).

## LLM model pool

OL is configured via `config/default.yaml` + `config/local.yaml`.
Each model has:
- `provider` (e.g., `openai`)
- `model` (e.g., `mimo-v2.5`)
- `priority` (1 = highest)
- `role` (`translation` | `judging` | `restoration`)
- `api_key` (use `${ENV_VAR}` syntax)
- `base_url` (for non-OpenAI providers)
- `timeout` (per-request, default 120s)
- `requests_per_minute` (default 500)

**Unified pool (OL#92, 2026-08-17)** — `ol init` writes `config/local.yaml`
with a single 3-provider pool shared across roles:

- **mimo-v2.5** → OpenCode Go (`OPENCODE_GO_KEY` + `OPENCODE_GO_BASE_URL`) — primary translation + judging
- **glm-4.7-flash** → Zhipu (`ZHIPU_API_KEY`, `https://open.bigmodel.cn/api/paas/v4`) — translation/restoration primary, judging fallback
- **z-ai/glm-5.2** → NVIDIA NIM (`NVIDIA_NIM_API_KEY`, `https://integrate.api.nvidia.com/v1`) — fallback

Every `api_key`/`base_url` is a `${ENV_VAR}` reference; literal keys are
never written. Each of `translation`, `judging`, and `restoration` must
have **≥2 models** — `ol doctor` enforces this as one of its 5 checks.

litellm Router with `routing_strategy="simple-shuffle"` and
`num_retries=2` picks a model within the role group. If it fails,
the next model in priority is tried.

**Free-tier note**: NVIDIA free models have `rpm=40`. If you have many
concurrent large requests, you'll hit the provider's 429; the existing
exponential backoff handles it.

## Env vars

| Variable | Default | Purpose |
|----------|---------|---------|
| `OMNI_TEST_FAKE_LLM=1` | unset | **Required** for tests. Mock LLM responses with the `_FakeModelPool` seam. |
| `OL_CONFIG_PATH` | `config/default.yaml` | Config file path override. |
| `ZHIPU_API_KEY` / `NVIDIA_NIM_API_KEY` | (none) | LLM provider API keys (glm-4.7-flash / z-ai/glm-5.2). |
| `OPENCODE_GO_KEY` / `OPENCODE_GO_BASE_URL` | (none) | OpenCode Go provider config (mimo-v2.5). |
| `OMNI_LOG_FORMAT` | `console` | `json` for structured logs. |
| `OPP_LOG_LEVEL` | `INFO` | Log level. |
| `OL_MAX_INPUT_SIZE_MB` | 50 | Reject CLI inputs larger than this. |
| `OL_LENGTH_RATIO_MIN` | 0.5 | Minimum acceptable translated/source length ratio (quality gates). |
| `OL_LENGTH_RATIO_MAX` | 3.0 | Maximum acceptable translated/source length ratio (quality gates). |
| `OL_TARGET_LOCALE` | (unset) | Target locale override for locale-specific quality gates (e.g. `en-US`, `en-GB`, `fr-FR`). Falls back to `locale.target_locale` in config. |
| `MCP_ALLOWED_DIRECTORIES` (or `OL_MCP_ALLOWED_DIRS`) | (none) | **REQUIRED for the MCP server** (`ol mcp` / `ol-mcp`). Comma-separated allowlist of directories the MCP may read/write. **Fail-CLOSED:** if all of `MCP_ALLOWED_DIRECTORIES` / `OL_MCP_ALLOWED_DIRS` / `OL_ALLOWED_DIRECTORIES` are unset, `get_default_validator()` raises `MCPNotConfiguredError` (error code `OL_MCP_NOT_CONFIGURED`; a `ValueError` subclass) — the server refuses to serve (no silent `cwd` + `/tmp` default). The MCP error envelope reports `OL_MCP_NOT_CONFIGURED` with recovery strategy `configure_environment`, NOT `OL_INVALID_INPUT`/`fix_input`. `OL_ALLOWED_DIRECTORIES` is a deprecated fallback. |
| `${VAR}` patterns in config | Per-provider | Env var references in `config/default.yaml` using `${VAR}` syntax. **Two-layer behavior:** (1) `schema.py:_check_env_vars()` WARNS at startup if a `${VAR}` is unset; (2) `router.py:_resolve_env_vars()` **raises `ValueError`** at runtime if a model with an unset var is actually invoked. Set `OMNI_TEST_FAKE_LLM=1` to bypass for testing. Only set env vars for providers you use. |

The MCP server is configured separately in `src/ol_mcp/config.py` —
OL's MCP server is `ol-mcp` (no `-server` suffix, **different** from
OPP's `opp-mcp-server` and ORF's `orf-mcp-server`). Startup additionally
requires `MCP_ALLOWED_DIRECTORIES` (fail-CLOSED; see the env-var table
above and `src/ol_mcp/security.py:get_default_validator`). When the
allowlist is missing, any tool call that builds a validator returns
`success=false` with `error.code == "OL_MCP_NOT_CONFIGURED"` and recovery
strategy `configure_environment` — set the env var, do not change the
request input.

## Tests

```bash
make test                            # all tests via uv run pytest tests/ -v
pytest tests/test_e2e_74_translate_context.py  # specific E2E regression
pytest tests/test_e2e_77_math_shield.py
pytest tests/test_e2e_78_html_shield_unshield.py
pytest tests/test_e2e_83_large_content.py
```

Coverage target ≥90%.

Key test files:
- `tests/test_e2e_74_translate_context.py` — context type handling
- `tests/test_e2e_77_math_shield.py` — math regex false positives
- `tests/test_e2e_78_html_shield_unshield.py` — marker format + unshield
- `tests/test_e2e_83_large_content.py` — large content + Router config
- `tests/test_md_shield.py` — shield basics
- `tests/test_xliff_repair_pipeline.py` — XLIFF repair (some tests broken pre-existing CWD issue)
- `tests/test_ol_cli.py` — CLI entry
- `tests/test_ol_cache.py` — content-addressed prompt cache

## Known issues / gotchas

- **E2E-65**: prompt injection strip in Level 1 repair. Don't strip
  `CRITICAL/IMPORTANT/NOTE: Output ONLY...` patterns yourself; the
  repair handles it.
- **E2E-74**: `ModelPool.translate(context=...)` — `context=None` and
  `context=dict` both work (pre-fix: UnboundLocalError); `context=str`
  is used verbatim (pre-fix: AttributeError from str.get()).
- **E2E-83**: large content (>~50K chars) emits a WARNING log but
  is not blocked.
- **LQA**: `enable_lqa: true` in config triggers auto-judging with
  retry on low scores. Slow.
- **TM/TB/SG**: Translation memory + glossary injection. Set
  `glossary_path` in config or pass `--glossary <path>`.
- **Routing**: litellm Router randomizes within role group. If you
  need deterministic model selection, set `priority: 1` on only one
  model per role.
- **Circuit breaker**: 5 consecutive failures → open for 60s.

### OL#53: Polish language guard

`polish_translated_units()` and `polish_md_text()` now skip corrections
that would revert translated text back to the source language (zh→en
direction). The `has_source_language_residual()` helper is exported
from `ol.pool` for reuse.

### OL#54: Truncation detection

`ModelPool.translate()` now applies a secondary truncation heuristic
when the API reports `finish_reason="stop"` but the output looks
incomplete (trailing ellipsis, non-terminal punctuation on long inputs,
or `completion_tokens >= 90%` of `max_tokens`). `judge()` and
`profile()` fail-closed on `finish_reason="length"`.

### OL#55: XLIFF raw XML tag normalization

XLIFF Level 1 repair normalizes raw LLM-emitted inline tags
(`<x/>`, `<bx/>`, `<ex/>`) back to placeholders when a `shield_map` is
available. Level 4 safe fallback is now bx/ex-pair-aware and avoids
duplicating tag halves already restored by Level 3.

### OL#56: Quality gates

Eight config-driven checks run after translation/repair and append
non-blocking warnings to the output:

| Gate | Description | Warning codes |
|------|-------------|---------------|
| `inline_tags` | Verify `<bx>`, `<ex>`, `<x>` tag parity between source and target | `INLINE_TAG_MISMATCH` |
| `terminology` | Detect mixed source/glossary term usage in target | `TERMINOLOGY_INCONSISTENCY` |
| `length_ratio` | Check translated/source length ratio is within bounds | `LENGTH_RATIO` |
| `locale` | Currency mixing, CJK date leakage, digit grouping (EU vs US), GB/US spelling | `CURRENCY_MIXING`, `DATE_LEAKAGE`, `DIGIT_GROUPING`, `UNIT_SPELLING` |
| `source_copy` | Detect when LLM echoes source text back unchanged | `SOURCE_COPY` |
| `source_script_check` | Detect CJK characters that leaked into a non-CJK target locale | `SOURCE_SCRIPT_FRAGMENT` |
| `protocol_artifact_check` | Detect LLM protocol/metadata markers in translated text | `PROTOCOL_ARTIFACT` |
| `terms_audit` | Full glossary term audit via verify_translation (mismatches, absent, inconsistencies, low confidence) | `TERM_AUDIT_MISMATCH`, `TERM_AUDIT_ABSENT`, `TERM_AUDIT_INCONSISTENCY`, `TERM_AUDIT_LOW_CONFIDENCE` |

Warnings are collected and returned in the `warnings` output field
(MCP) or appended to the output file as HTML comments / `<note>`
elements (CLI). Configure via `quality_gates:` in `config/default.yaml`
or override with `OL_LENGTH_RATIO_MIN`, `OL_LENGTH_RATIO_MAX`, and
`OL_TARGET_LOCALE` env vars.

### FAKE_LLM decision matrix

`OMNI_TEST_FAKE_LLM=1` enables mock translation (no API calls).
Use this table to decide when to set it:

| Scenario | Set `OMNI_TEST_FAKE_LLM=1`? | Why |
|----------|---------------------------|-----|
| Running unit tests | **YES** | Required. All pipeline tests use `_FakeModelPool`. |
| Running E2E tests with FAKE_LLM | **YES** | Validates pipeline orchestration without API cost. |
| Running E2E tests with real LLM | NO | Set real API keys, ensure `OMNI_TEST_FAKE_LLM` is UNSET. |
| Debugging translation quality | NO | Need real LLM responses to evaluate output. |
| Config validation / env var check | **YES** | Bypasses `${VAR}` resolution errors during `_check_env_vars()`. |
| MCP server testing | **YES** | Zero-cost smoke testing of MCP tools. |
| CI (pull request) | **YES** | Required. Prevents API key leakage in CI logs. |
| CI (nightly regression) | NO | Nightly runs test against real LLMs. |
| Production deployment | NO | Real translation requires real LLM calls. |
| Development / iteration | **YES** | Avoid burning through API quota during active development. |

**Decision flow:**

1. Are you running in CI on a PR? → **YES** (no API keys in CI)
2. Are you just testing the pipeline orchestration? → **YES** (no need to call real LLMs)
3. Are you validating translation quality or running nightly tests? → **NO** (need real LLM output)
4. Unsure? → **YES** (safe default — set it unless you specifically need real translations)

### translate-md vs translate-xliff

OL offers two translation channels for different pipeline paths:

| Aspect | `translate-md` | `translate-xliff` |
|--------|---------------|-------------------|
| Input | `.md` file | `.xlf` / `.xliff` file |
| Output | Translated `.md` | XLIFF with `<target>` filled |
| Downstream | ORF `apply-md` (16 formats) | ORF `apply-xliff` (needs skeleton) |
| Layout preservation | Text-only (pandoc renders) | Full original layout retained |
| Image handling | Via `images.json` + `--separate-images` | Auto-reinjected from skeleton |
| When to use | Web content, docs, e-books | Contracts, branded docs, exact-layout |

**Decision flow:**

1. Is your source an OPP XLIFF that came with a skeleton.zip? → **`translate-xliff`**
2. Do you need the output to look exactly like the source? → **`translate-xliff`**
3. Otherwise → **`translate-md`** (faster, more format choices)

**Both paths can run in parallel** if OPP extracted with `--target-format both`.
The MD and XLIFF channels share no state — translate both simultaneously.

**Full pipeline comparison**: See the suite-level
[Pipeline Selection Strategy](https://github.com/1StepMore/e2e-test-suite/blob/main/README.md#pipeline-selection-strategy)
for the complete decision tree and format support matrix.

## Pointers to the suite-level docs

- Cross-module orchestration: [AGENTS.md](https://github.com/1StepMore/e2e-test-suite/blob/main/AGENTS.md)
- MCP tool full parameter reference: [agent-pipeline-guide.md](https://github.com/1StepMore/e2e-test-suite/blob/main/docs/agent-pipeline-guide.md)
- Pre-commit hooks: [.pre-commit-config.yaml](https://github.com/1StepMore/e2e-test-suite/blob/main/.pre-commit-config.yaml)
- Compatibility matrix: [COMPATIBILITY.md](https://github.com/1StepMore/e2e-test-suite/blob/main/COMPATIBILITY.md)
- User-facing guide (not developer): `AGENT_USAGE.md` in this repo
- Per-Agent skill files: `src/.opencode/skills/ol-localizer/SKILL.md`
  and `src/.hermes/skills/ol-localizer/SKILL.md`

## How to validate this module

OL ships its own validation scenario library **in this repo** at
`scenarios/` — 5 tier-2 `ol-translation` scenarios (translate-md happy
path, translate-xliff, judge-text quality, glossary + quality gates,
empty-input edge) with their own `scenarios/STANDARDS.md` +
`scenarios/_fixtures/`. They need real LLM keys (`requires_env`: the 5
provider vars) and report `unconfigured` without them — never a fake
green. The suite validation engine runs them via `--repo ol`. The suite's
own `tool-ol-*` agent-surface scenarios + the HUMAN-QUALITY pipeline
scenarios still live in the suite repo, covered by the suite-level
`--module` filter. Any agent or the human director can validate OL:

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
