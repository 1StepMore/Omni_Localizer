> **Note:** This file covers OL internals only. For cross-module pipeline architecture
> (OPP → OL → ORF), see the [suite-level ARCHITECTURE.md](../../docs/ARCHITECTURE.md).

# OL Architecture

How Omni-Localizer (OL) is put together: module layout, the per-text pipeline, the model pool and its failover, and the design decisions that shaped the current shape. Source paths are relative to `Omni_Localizer/`.

OL is the **middle stage** of the Omni_Suite pipeline (extract → translate → backfill). It accepts Markdown and XLIFF from OPP, runs them through a shield → translate → repair → unshield pipeline, and emits files that ORF can reformat back to DOCX/PPTX.

---

## 1. Module map

```
src/
├── ol_cli.py                  # 2 092-line Typer CLI: 4 sub-commands
├── ol_review_extractor.py     # XLIFF review-comment extractor (packaged as a py-module)
│
├── ol_config/                 # YAML config + Pydantic schema + loader
│   ├── schema.py              # LLMModelConfig, LLMPoolConfig, ProjectConfig
│   └── loader.py              # load_config(path) -> (ProjectConfig, glossary_dict)
│
├── ol_pool/                   # LiteLLM-backed model pool with failover
│   └── router.py              # ModelPool singleton, circuit breakers, fallback chain
│
├── ol_md/                     # Markdown pipeline (shield / repair / restore)
│   ├── shield.py              # shield_markdown / unshield_markdown
│   ├── pipeline.py            # MDRepairPipeline: 4-layer repair
│   ├── token_stream.py        # Position tracker
│   ├── extractor.py           # MD chunk extraction
│   └── repair/
│       ├── level1.py          # regex cleanup
│       ├── level2.py          # span alignment
│       ├── level3.py          # LLM-based restoration
│       └── level4.py          # safe fallback
│
├── ol_xliff/                  # XLIFF 1.2 pipeline (parallel to ol_md/)
│   ├── parser.py              # parse <trans-unit> list
│   ├── pipeline.py            # XLIFFRepairPipeline
│   ├── shield.py              # XLIFF tag shielding
│   └── repair/                # 4 layers, same shape as ol_md/repair
│
├── ol_tm/                     # Translation memory (TMX)
│   ├── service.py             # TMService: load / search / add / flush
│   ├── _py_tmx.py             # Pure-Python TMX 1.4 stub (fallback for hypomnema)
│   └── auto_gen.py            # Auto-build TM from past output
│
├── ol_terminology/            # Glossary & term injection
│   ├── glossary.py            # load_glossary (legacy) + get_relevant_terms
│   ├── glossary_class.py      # Glossary v1 dataclass + Glossary.load
│   ├── schema.py              # Pydantic v1 schema
│   ├── rag_injector.py        # build_translate_prompt — pre-injects TM + glossary
│   ├── extractor.py           # YAKE term extraction
│   └── disambiguator.py       # LLM-based polyseme resolution
│
├── ol_batch/                  # Batch translate-md processor
│   ├── discovery.py           # File discovery (md, xliff, xlf)
│   ├── processor.py           # BatchProcessor with TM + glossary integration
│   ├── config.py              # BatchConfig
│   ├── progress.py            # Rich progress bar
│   └── summary.py             # print_summary (total / succeeded / failed)
│
├── ol_concurrency/            # Concurrency limiter
│   └── scheduler.py           # ConcurrencyLimiter (md + xliff semaphores)
│
├── ol_lqa/                    # LQA judge + QA rules
│   ├── judge.py               # JudgeService: LLM-based quality scoring
│   └── qa_rules.py            # translate-toolkit pofilter subset
│
├── ol_retry/                  # RetryManager for the LQA loop
├── ol_restoration/            # A12.4 post-translate placeholder restoration
├── ol_post/                   # Post-processing
│   └── punctuation.py         # normalize_to_english / normalize_to_chinese
├── ol_buses/                  # XLIFF bus + tag shield
│   ├── xliff_bus.py           # write_target_back
│   └── xliff_shield.py        # restore_tags
├── ol_core/                   # TranslationContext, TranslationUnit, ChannelType
├── ol_logging/                # python-json-logger setup
├── ol_checkpoint/             # .omni_cache/ reader/writer
├── ol_mcp/                    # MCP server
│   ├── server.py              # stdio_server() entry (29 lines)
│   ├── tools.py               # 8-tool registry (994 lines)
│   ├── security.py            # PathValidator
│   ├── auth.py                # shared-secret auth
│   ├── rate_limiter.py        # token-bucket DoS guard
│   ├── _errors.py             # @mcp_error_boundary decorator
│   └── config.py              # MCPConfig
│
└── .opencode/skills/ol-localizer/  # Skill manifest for OpenCode agents
```

The structure mirrors the OPP/ORF conventions: every concern (MD, XLIFF, pool, TM, terminology) is a self-contained package; the CLI and MCP are thin orchestrators on top.

---

## 2. The shield → translate → repair → unshield pipeline

OL's core invariant: **code blocks, links, images, math, HTML blocks, and autolinks must round-trip exactly**. The LLM is told to translate only the surrounding prose, but it occasionally eats a placeholder anyway. The four-stage repair catches the common cases without an extra LLM call.

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                          MARKDOWN CHANNEL                                    │
│                                                                              │
│   input.md                                                                   │
│      │                                                                       │
│      ▼                                                                       │
│   ┌──────────────────────────┐                                               │
│   │  1. shield_markdown()    │  ol_md/shield.py                             │
│   │                          │                                               │
│   │  replaces:               │  ```code```         → \x00OL_CODE_0000\x00    │
│   │                          │  `inline`           → \x00OL_CODE_i_0000\x00  │
│   │                          │  $math$             → \x00OL_MATH_0000\x00    │
│   │                          │  [text](url)        → \x00OL_LINK_0000\x00    │
│   │                          │  ![alt](url)        → \x00OL_IMG_0000\x00     │
│   │                          │  <html>...</html>   → \x00OL_HTML_0000\x00    │
│   │                          │  <https://…>        → \x00OL_AUTOLINK_0000\x00│
│   │                          │                                               │
│   │  returns: (shielded, shield_map)                                         │
│   └──────────────────────────┘                                               │
│      │                                                                       │
│      ▼                                                                       │
│   ┌──────────────────────────┐                                               │
│   │  2. RAG prompt build     │  ol_terminology/rag_injector.py              │
│   │                          │                                               │
│   │  - if glossary:          │  - find top-k matching terms                  │
│   │  - if tm_service:        │  - find top-3 TM matches (cosine ≥ 0.85)      │
│   │                          │  - format: "Use these terms: src→tgt, …"      │
│   │                          │                                               │
│   │  output: context (str)   │                                               │
│   └──────────────────────────┘                                               │
│      │                                                                       │
│      ▼                                                                       │
│   ┌──────────────────────────┐                                               │
│   │  3. ModelPool.translate  │  ol_pool/router.py                            │
│   │                          │                                               │
│   │  - wrap in [USER_TEXT]  │  (H1-H3 prompt-injection guard)               │
│   │  - call role="translation"                                              │
│   │  - on failure: 5x breaker, then next-priority fallback                    │
│   │  - on all fail: cross-role → restoration pool → safe error                │
│   │                          │                                               │
│   │  output: translated str  │                                               │
│   └──────────────────────────┘                                               │
│      │                                                                       │
│      ▼                                                                       │
│   ┌──────────────────────────┐                                               │
│   │  4. unshield_markdown()  │  ol_md/shield.py (reverse map)                │
│   │                          │                                               │
│   │  swaps each \x00OL_*_NNNN\x00                                               │
│   │  back to the original verbatim content.                                 │
│   │                          │                                               │
│   │  output: translated'     │                                               │
│   └──────────────────────────┘                                               │
│      │                                                                       │
│      ▼                                                                       │
│   ┌──────────────────────────────────────────────────────────────────┐       │
│   │  5. MDRepairPipeline.repair()  — 4 layers         src/ol_md/     │       │
│   │                                                                  │       │
│   │     L1  regex clean  (level1.py)        — strip stray markers    │       │
│   │     L2  span align   (level2.py)        — reinsert missing       │       │
│   │     L3  LLM restore  (level3.py)        — ask LLM to put back    │       │
│   │     L4  safe fallback(level4.py)        — verbatim from shield_map│       │
│   │                                                                  │       │
│   │  Early-exit at the end of any layer that completes the map.      │       │
│   └──────────────────────────────────────────────────────────────────┘       │
│      │                                                                       │
│      ▼                                                                       │
│   ┌──────────────────────────┐                                               │
│   │  6. Punctuation norm.    │  ol_post/punctuation.py                       │
│   │     (zh ↔ en only)       │  dispatch on tgt_lang prefix; O(1) per char  │
│   │                          │  fullwidth → ASCII or ASCII → fullwidth      │
│   └──────────────────────────┘                                               │
│      │                                                                       │
│      ▼                                                                       │
│   ┌──────────────────────────┐                                               │
│   │  7. Write to disk        │  output_dir/<input>.md (+ optional frontmatter)│
│   └──────────────────────────┘                                               │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

The XLIFF channel is the same shape, with two differences: (1) the shield is XML-tag-aware (`restore_tags` in `ol_buses/xliff_shield.py`); (2) the final write goes through `write_target_back` in `ol_buses/xliff_bus.py`, which XML-escapes the LLM's `<target>` text before merging into the output XLIFF (`_escape_xml_entities`).

### 2.1 Why four repair layers, not one

Real LLM output is messy:

- ~95% of placeholder loss is recoverable by regex (L1) or by aligning the surviving markers with the original span (L2). Both are O(n) and cost nothing.
- Another ~4% needs the LLM to put a missing `{{_OL_LINK_0001_}}` back in the right place — L3 asks the restoration pool for a small targeted edit.
- The last ~1% is hopeless; L4 reinserts the original verbatim, which is always at least as good as the missing construct.

Skipping L1/L2 and going straight to LLM restore would burn API calls for the 95% that regex handles for free. Skipping L4 would leave the user with broken links and missing images.

### 2.2 Why shield in the first place

LLMs degrade in inverse proportion to how "text-like" a construct looks:

- Fenced code blocks survive reasonably well, but a stray backtick in the LLM output breaks the block boundary.
- Inline `code` is the worst — a single misplaced space from the LLM changes a UI label's meaning.
- Image alt text and link URLs almost always get paraphrased by an LLM that's been told to "make this flow naturally."

Shielding extracts them as opaque placeholders. The LLM only sees the surrounding prose, so it can't touch the protected content. The repair layer's only job is to put them back.

---

## 3. Model pool and failover

`ModelPool` (`src/ol_pool/router.py:216`) is the central LLM router. It wraps a LiteLLM `Router` configured from the YAML pool, with three role groups:

- **translation** — primary translation model
- **judging** — used by `JudgeService` for LQA
- **restoration** — used by the A12.4 post-translate restoration step (re-asks the LLM to reinsert missing placeholders)

Each role can list multiple models, each with a `priority` (1 = highest). Failover inside a role is automatic:

```
translation priority=1 (glm-4-flash)
       │
       │  fail / 429 / 5xx
       ▼
translation priority=2 (agnes-2.0-flash)
       │
       │  fail
       ▼
translation priority=3 (deepseek-v4-flash)
       │
       │  fail
       ▼
restoration pool  (cross-role safety net, router.py:373-385)
       │
       │  fail
       ▼
raises the last error
```

### 3.1 Circuit breaker

A `pybreaker.CircuitBreaker` is created per role (router.py:237-245):

- 5 consecutive failures → open for 60 s
- On open, `pybreaker.CircuitBreakerError` is raised immediately, skipping LiteLLM
- After 60 s, the breaker half-opens: one call through; if it succeeds, close again

The breaker is per-process and per-role. Restarting the CLI resets it.

### 3.2 RPM enforcement

Each `LLMModelConfig` has a `requests_per_minute` field (default 500). It's passed to the LiteLLM Router and enforced by `enforce_model_rate_limits`. When the cap is reached, the Router raises `litellm.RateLimitError` immediately rather than waiting on a provider 429 + backoff. This prevents one model's rate storm from starving siblings.

Set the value to your provider's actual quota (e.g. NVIDIA free tier = 40). Hardcoding 500 for a free-tier account is a recipe for cascade failures.

### 3.3 Cross-role safety net

If a role's own pool is exhausted (all models failing, breaker open), the router falls back to the **translation** role's models. This trades quality for liveness — the judging role using the translation model is dumber, but it returns *something*. Implemented in `router.py:373-385`.

### 3.4 Singleton lifecycle

`ModelPool.get_instance(config_path)` is a process-wide singleton, keyed by `config_path`. The mtime of the config file is also cached; if the file changes, a fresh pool is built on the next call. This is the only correct way to use the pool — instantiating `ModelPool` directly bypasses the cache and the cross-process reload.

The MCP server uses `OL_CONFIG_PATH` env to pick the path; the CLI uses `--config`. Both end up in the same `ModelPool` instance.

---

## 4. TM / TB / SG flow

TM = translation memory. TB = terminology base (glossary). SG = (in the agent path) "similar" / "saw it" — i.e. the prior-translation examples that look like the current source.

```
                    source text
                         │
              ┌──────────┴──────────┐
              ▼                     ▼
   ┌───────────────────┐   ┌────────────────────┐
   │ TMService.search  │   │ get_relevant_terms │
   │ (TMX, cosine ≥ t) │   │ (substring + conf) │
   └───────────────────┘   └────────────────────┘
              │                     │
              │   top-3 matches     │   top-5 terms
              ▼                     ▼
   ┌──────────────────────────────────────────────┐
   │ build_translate_prompt(text, src, tgt,       │
   │                         tm_matches, terms)   │
   │                                              │
   │ prepends:                                    │
   │   "Use these terms: API→API 端点, …"          │
   │   "Similar past translations: …"              │
   └──────────────────────────────────────────────┘
                         │
                         ▼
                ModelPool.translate
```

TM matches are found by `TMService.search` (sentence-transformer embeddings, default threshold 0.85). Glossary matches are substring + confidence weighted (see `glossary.py:115-161`). Both are top-k, not exhaustive — the LLM is biased, not constrained.

If either is unavailable, OL degrades gracefully: translation proceeds without that pre-injection. No blocking errors, no LLM-call failures from a missing TM file.

---

## 5. MCP transport

`src/ol_mcp/server.py` is 29 lines on purpose: it does nothing except wire the stdio transport to the `Server` instance defined in `tools.py`. The earlier `mcp.server.fastmcp.FastMCP` was abandoned in Phase 1.4 because it swallowed the first JSON-RPC handshake on stdio; the raw `mcp.server.Server` + `stdio_server()` pattern works reliably when the subprocess is unbuffered (`python -u -m ol_mcp`, `bufsize=0`).

8 tools, all in `TOOL_REGISTRY` (`tools.py:88`):

| Tool | Input model | Returns |
|---|---|---|
| `translate_md_text` | `TranslateInput` | `{success, translated, warnings, source_lang, target_lang}` |
| `translate_xliff` | `TranslateXliffInput` | `{success, output_path, units_processed, warnings}` |
| `judge_text` | `JudgeInput` | `{success, score, reason, judge_scores, warnings}` |
| `load_glossary` | `LoadGlossaryInput` | `{success, glossary, term_count, warnings}` |
| `get_relevant_terms` | `GetRelevantTermsInput` | `{success, terms, count}` |
| `search_tm` | `SearchTMInput` | `{success, matches, count}` |
| `batch_translate_texts` | `BatchTranslateInput` | `{success, results, total, succeeded, failed, assembled_document}` |
| `ping` | none | `{success, module, version}` |

The dispatcher (`tools.py:_invoke_tool`) validates the arguments against the tool's Pydantic model and returns `error_code: "OL_INVALID_INPUT"` on schema failure. Every tool returns a JSON string wrapped in `TextContent` — the OL tool contract is **str out, always**, which makes the agent's life simple: `r.content[0].text` is always valid JSON.

### 5.1 Path validation and rate limiting

- `PathValidator` (`src/ol_mcp/security.py`) restricts file-path inputs (`glossary_path`, `tmx_path`, `load_glossary.path`) to the server's CWD by default. The CLI does not enforce this — ad-hoc file paths work there.
- `check_rate_limit` (`src/ol_mcp/rate_limiter.py`) is a token-bucket DoS guard on every tool call. A misbehaving client gets `OL_RATE_LIMITED` instead of GPU time.
- `check_auth` (`src/ol_mcp/auth.py`) optionally enforces a `MCP_SHARED_SECRET` — enabled only when the env var is set, so dev clients don't need it.

---

## 6. Cache and idempotency

`ol_checkpoint` (the `.omni_cache/` reader/writer) makes `translate-md` / `translate-xliff` idempotent for unchanged inputs:

- Cache key = `sha256(input_bytes + config_path + flags)` plus the output path.
- `--no-cache` skips the check and forces a fresh translation.
- `--clear-cache` removes all cached outputs and exits.

This is critical for batch re-runs (e.g. a CI job that re-translates on each PR): only the changed files pay the LLM cost.

---

## 7. Key design decisions

| Decision | Rationale |
|---|---|
| **Shield + repair over "just don't translate code"** | LLMs don't reliably skip code even when told. Shielding is the only way to *guarantee* round-trip integrity. |
| **Four repair layers, not one** | 95% of placeholder loss is regex-recoverable. Burning an LLM call for the common case is wasteful. |
| **LiteLLM with simple-shuffle, not bespoke routing** | LiteLLM already handles provider-specific quirks (timeouts, retries, streaming) for 5+ providers. Re-implementing is a maintenance trap. |
| **Pydantic v2 schema with `extra="forbid"` on the v1 glossary** | Catches typos at load time, not at 3 AM in production. |
| **Model pool, not single model** | Providers rate-limit and 503. Multi-model failover turns a per-minute outage into a degraded-but-working service. |
| **Circuit breaker per role, not per model** | A single bad model shouldn't take down the whole pool. Per-role breakers give judges and translators independent failure domains. |
| **TMX for memory, JSON for glossary** | TMX is an industry standard (translation memory exchange). Glossaries are short, hand-edited, and version-controlled alongside the project — JSON/YAML beats a TMX-style XML for that. |
| **TM/TB injection in the prompt, not in post-processing** | Post-edit can't fix a mistranslated term; prompt-bias is the only lever. |
| **Graceful degradation of TM/glossary** | A missing TM file should never block a translation. The CLI prints a warning, the prompt drops the injection, the call proceeds. |
| **MCP tool contract: `str` out, always** | Agents parse `r.content[0].text` as JSON. Tools that return `dict` would require the agent to know which tools are which. |
| **Two glossary shapes (v1 CLI + legacy dict)** | The legacy dict is what `BatchProcessor` and the original RAG path use. The v1 shape is a stricter, schema-validated form for the CLI. Both are load-equivalent for the simple cases. |
| **Cyrillic-safe frontmatter date** | Use `datetime.now(timezone.utc).isoformat()` — never `str(datetime.now())` — so the YAML frontmatter is locale-independent. |
| **Cross-role fallback (judging → translation)** | If all judging models are down, the worst case is a noisier judge score, not a crashed CLI. The cross-role fallback is the last safety net. |
| **Pure-python TMX stub (`_py_tmx.py`)** | Some test envs don't have `hypomnema`. The stub installs onto the `hypomnema` module at import time so the rest of the code doesn't know. |

---

## 8. Data flow at a glance

```
┌────────────┐    ┌─────────────┐    ┌────────────┐    ┌────────────┐
│ OPP        │───▶│ OL          │───▶│ ORF        │───▶│ Final doc  │
│ (extract)  │ MD │ (translate) │ MD │ (backfill) │ DOCX│            │
│            │ XLF│             │ XLF│            │ PPTX│            │
│ + skel.zip │    │ + front-    │    │            │     │            │
│            │    │   matter    │    │            │     │            │
└────────────┘    └─────────────┘    └────────────┘    └────────────┘
                        │
                        │ internal:
                        │
                ┌───────┴────────────────────────┐
                │                                │
                ▼                                ▼
        ┌───────────────┐               ┌──────────────────┐
        │  ModelPool    │               │  ModelPool       │
        │  translation  │               │  judging         │
        │  + restor.    │               │  (LQA loop)      │
        └───────────────┘               └──────────────────┘
                │                                │
                │   consult before each call:    │
                │                                │
        ┌───────┴─────────┐             ┌────────┴────────┐
        │ TMService (TMX) │             │ Glossary (JSON) │
        └─────────────────┘             └─────────────────┘
```

OL is the only step in the pipeline that calls an LLM. Its design is shaped by the cost and the unreliability of that call: the shield makes the input safe, the pool makes the call survivable, the repair makes the output correct, and the cache makes the next call free.
