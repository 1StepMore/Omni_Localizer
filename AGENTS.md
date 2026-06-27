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
│   ├── extractor.py         # KeyBERT/YAKE term extraction
│   └── disambiguator.py     # LLM-based polysemy resolution
├── lqa/                     # Linguistic Quality Assurance
│   ├── judge.py             # JudgeService (score 0-100)
│   └── scoring.py           # LQA rules
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

## MCP tools (8 total)

| Tool | Purpose |
|------|---------|
| `translate_md_text` | Translate markdown text directly (text-in/text-out). The primary Agent tool. |
| `translate_xliff` | Translate an XLIFF file (text-in/text-out) |
| `judge_text` | Evaluate translation quality (returns adequacy/fluency/terminology/format scores) |
| `load_glossary` | Load a JSON glossary file |
| `get_relevant_terms` | Extract top-k relevant glossary terms for a source text |
| `search_tm` | Search TMX translation memory for similar past translations |
| `batch_translate_texts` | Translate multiple texts in parallel |
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
- `model` (e.g., `glm-4-flash`)
- `priority` (1 = highest)
- `role` (`translation` | `judging` | `restoration`)
- `api_key` (use `${ENV_VAR}` syntax)
- `base_url` (for non-OpenAI providers)
- `timeout` (per-request, default 120s)
- `requests_per_minute` (default 500)

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
| `OPENAI_API_KEY` / `ZHIPU_API_KEY` / `AGNES_API_KEY` / `NVIDIA_NIM_API_KEY` | (none) | LLM provider API keys. |
| `OPENCODE_GO_KEY` / `OPENCODE_GO_BASE_URL` | (none) | OPENCODE_GO provider config. |
| `OMNI_LOG_FORMAT` | `console` | `json` for structured logs. |
| `OPP_LOG_LEVEL` | `INFO` | Log level. |
| `OL_MAX_INPUT_SIZE_MB` | 50 | Reject CLI inputs larger than this. |
| `${VAR}` patterns in config | Per-provider | Env var references in `config/default.yaml` using `${VAR}` syntax. **Two-layer behavior:** (1) `schema.py:_check_env_vars()` WARNS at startup if a `${VAR}` is unset; (2) `router.py:_resolve_env_vars()` **raises `ValueError`** at runtime if a model with an unset var is actually invoked. Set `OMNI_TEST_FAKE_LLM=1` to bypass for testing. Only set env vars for providers you use. |

The MCP server is configured separately in `src/ol_mcp/config.py` —
OL's MCP server is `ol-mcp` (no `-server` suffix, **different** from
OPP's `opp-mcp-server` and ORF's `orf-mcp-server`).

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
