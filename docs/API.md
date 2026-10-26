# OL API Reference

This document is the canonical reference for every command and tool exposed by **Omni-Localizer (OL)** v0.7.1. It covers the CLI, the MCP server, the LLM config format, the glossary format, and the TMX format. File paths are relative to the `Omni_Localizer/` repository root.

> **Status**: v0.7.1 (matches `pyproject.toml`). CLI and MCP contracts here are stable; minor flags may appear in patch releases.

---

## 1. CLI — `ol` / `python -m ol_cli`

The CLI is a `typer` application in `src/ol_cli.py` with a single Typer `app` and twenty-one sub-commands. The console script is registered in `pyproject.toml` as `ol = "ol_cli:main_entry"`.

Common help:

```bash
ol --help
ol translate-md --help
```

Global options:

| Flag | Effect |
|---|---|
| `--version` | Print `ol version <__version__>` and exit. Implemented in `src/ol_cli.py`. |

### 1.1 `ol translate-md`

Translate a single Markdown file through the shield → translate → repair → unshield pipeline.

```bash
ol translate-md <input.md> -o <output_dir> [flags]
```

Defined at `src/cli/translate_md.py`.

| Flag | Default | Purpose |
|---|---|---|
| `input` (positional) | — | Input Markdown file path. |
| `-o`, `--output-dir` | required | Output directory. Created if missing. |
| `-c`, `--config` | none | Path to YAML LLM config. Default: `config/default.yaml`. |
| `-s`, `--source-lang` | `en` | Source language code (`en`, `zh`, `ja`, …). |
| `-t`, `--target-lang` | `zh` | Target language code. |
| `--json` | `false` | Emit a one-line JSON status (for agent parsing). |
| `--frontmatter` / `--no-frontmatter` | `true` | Prepend YAML frontmatter (source/target lang, processor, version, timestamp). |
| `--no-cache` | `false` | Bypass `.omni_cache/` and force a fresh translation. |
| `--clear-cache` | `false` | Remove all cached OL outputs and exit. |
| `--glossary PATH` | none | Inject a v1-format JSON/YAML glossary (see §4). |
| `--no-glossary` | `false` | Skip glossary injection even if `--glossary` or config sets one. |
| `--no-restoration` | `false` | Skip the A12.4 post-translate placeholder restoration. |
| `--chunk-by-paragraph` | `false` | Split by blank lines and translate each paragraph separately (better for literary text). |
| `--styleguide PATH` | none | Inject a `StyleGuide` JSON (output of `profile_doc`) into the prompt. |
| `--no-styleguide` | `false` | Skip StyleGuide injection even if `--styleguide` or config sets one. |
| `--polish` | `false` | Run a post-translation cross-unit consistency pass (uses the cheapest model). |
| `--scorer NAME` | `none` | LQA scorer backend: `bleu`, `comet` (requires `unbabel-comet`), or `none`. |
| `--no-scorer` | `false` | Disable the scorer (overrides `--scorer`). |
| `--report-coverage` | `false` | Print a glossary coverage report (requires `--glossary`). |
| `--coverage-threshold FLOAT` | none | Warn when matched glossary coverage falls below this percentage (0–100). |
| `--images-json PATH` | none | Copy an `images.json` (e.g. from OPP) alongside the translated `.md`. |
| `--log-format console\|json` | `console` | Log output format (also `OMNI_LOG_FORMAT`). |
| `--glossary-max-terms N` | `5` | Top-N terms to inject per trans-unit (1 ≤ N). |
| `--fail-on-untranslated` | `false` | Exit `1` when any trans-unit came back untranslated (see below). |

Exit codes (see `ExitCode` in `src/cli/_shared.py`):

- `0` — success (`SUCCESS`)
- `1` — pipeline error (`PIPELINE_ERROR`: LLM call, repair failure, etc.)
- `2` — usage error (`CLI_USAGE_ERROR`: bad args, missing file, missing `--output-dir`)
- `3` — interrupted (`INTERRUPTED`: SIGINT / Ctrl+C)
- `4` — quality gate blocked (`QUALITY_GATE_BLOCKED`)

#### Untranslated units

When a trans-unit's LLM call fails (provider 429/5xx, retry budget exhausted,
empty output), OL degrades gracefully and emits the **source** text for that
unit rather than dropping it. That content is delivered, but it is *not*
translated, so it is always reported:

- `--json` gains `"untranslated_units": <N>`
- the output frontmatter gains `untranslated_units: <N>` (omitted when `0`)
- one `<!-- OL_WARN: UNTRANSLATED_UNITS — N of M unit(s) ... -->` line is appended

Detection is per-unit and compares each unit's own output against its own source
through the canonical Gate 5 comparator, so it catches every fallback path
(exception, empty output, retry exhaustion) with one check. Units whose source
carries no alphabetic characters (pure numbers, symbols) are never counted.

By default a degraded run still exits `0` — the content is present, and turning
a partial result into a hard failure would break callers that deliberately accept
degraded output. Pass `--fail-on-untranslated` to make it exit `1` instead; use
it in CI and batch pipelines where an untranslated unit is unacceptable.

Example:

```bash
ol translate-md chapter1.md -o ./out/ -s en -t zh --glossary terms.json
```

```bash
# strict: fail the run if any unit came back untranslated
ol translate-md chapter1.md -o ./out/ -s en -t zh --json --fail-on-untranslated
```

### 1.2 `ol translate-batch`

Translate every `*.md`, `*.xliff`, and `*.xlf` in a directory. Defined at `src/cli/batch.py`.

```bash
ol translate-batch <dir> -o <output_dir> [flags]
```

| Flag | Default | Purpose |
|---|---|---|
| `directory` (positional) | — | Input directory path. |
| `-o`, `--output-dir` | required | Output directory. |
| `-c`, `--config` | none | YAML LLM config. |
| `-s`, `--source-lang` | `en` | Source language. |
| `-t`, `--target-lang` | `zh` | Target language. |
| `-j`, `--concurrency` | `5` | Max parallel translations (forwarded to `ConcurrencyLimiter(max_translation=…)`). |
| `--frontmatter` / `--no-frontmatter` | `true` | Add YAML frontmatter to translated files. |
| `--detect-language` / `--no-detect-language` | `true` | Skip files already detected as the target language. Skipped files get `skipped: true` frontmatter. |
| `--json` | `false` | Emit a one-line JSON summary. |

JSON output (batch):

```json
{"success": true, "duration_seconds": 12.5, "total_files": 10, "succeeded": 9, "failed": 1}
```

### 1.3 `ol translate-xliff`

Translate an XLIFF 1.2 file: each `<trans-unit>` is sent to the LLM, the result is written back to `<target>`, and `<note from="OL">` is added to the header. Defined at `src/cli/translate_xliff.py`.

```bash
ol translate-xliff <file.xlf> -o <output_dir> [flags]
```

Flags mirror `translate-md` minus the MD-specific ones (no `--frontmatter`, no `--detect-language`; same `--glossary` / `--no-glossary` / `--no-restoration` / `--glossary-max-terms` / `--no-cache` / `--clear-cache` set).

Example:

```bash
ol translate-xliff doc.xlf -o ./out/ -s en -t zh --json
```

### 1.4 `ol extract-warnings`

Scan a translated file for embedded `<!-- OL_WARN: ... -->` (MD) or `<note from="OL">…</note>` (XLIFF) markers and print them, or write them to a file. Defined at `src/cli/batch.py`.

```bash
ol extract-warnings <file> [-o warnings.md]
```

| Flag | Default | Purpose |
|---|---|---|
| `input` (positional) | — | MD or XLIFF file. |
| `-o`, `--output` | none | Write warnings to this file. If absent, prints to stdout. If no warnings, prints `# No warnings found`. |

---

## 2. MCP server — `python -m ol_mcp` / `ol-mcp`

A stdio-transport MCP server that wraps OL's text-in/text-out translation primitives. Implementation in `src/ol_mcp/tools.py` (registry + tool bodies) and `src/ol_mcp/server.py` (transport entry). Requires `pip install -e ".[mcp]"` and `mcp>=1.0.0` in the runtime.

Run:

```bash
ol-mcp                       # console-script entry point from pyproject.toml
# or
python -m ol_mcp             # with PYTHONPATH=src if running from a checkout
```

The server registers 21 tools (`TOOL_REGISTRY` in `src/ol_mcp/tools.py`). All tools return a JSON string wrapped in MCP `TextContent`; arguments are validated against a Pydantic model and rejected with `error_code: "OL_INVALID_INPUT"` on schema failure. See the dispatcher in `src/ol_mcp/tools.py`. The complete list is enumerated in `AGENTS.md` (see "MCP tools (21 total)") and readable at runtime via the `get_capabilities` tool; §2 below documents the pipeline-critical subset.

### 2.1 `translate_md_text`

Translate a Markdown string end-to-end. **Text in, text out** — no file I/O.

| Field | Type | Required | Description |
|---|---|---|---|
| `content` | string | yes | Markdown text to translate. |
| `source_lang` | string | yes | Source language code. |
| `target_lang` | string | yes | Target language code. |
| `glossary_path` | string \| null | no | Path to a JSON glossary (legacy format, see §4.2). |
| `config_path` | string \| null | no | Path to LLM config YAML. Default: `config/default.yaml` (or `OL_CONFIG_PATH` env). |
| `add_frontmatter` | bool | no | Prepend YAML frontmatter. Default: `false`. |
| `glossary_max_terms` | int (1–50) | no | Top-N glossary terms. Default: `5`. |
| `no_glossary` | bool | no | Disable glossary injection. |
| `no_restoration` | bool | no | Skip A12.4 placeholder restoration. |
| `styleguide_path` | string \| null | no | Path to a `StyleGuide` JSON file (output of `profile_doc`); its rules are injected into the translation prompt. |
| `no_styleguide` | bool | no | Skip StyleGuide injection even if `styleguide_path` is set. |
| `polish` | bool | no | After translation, run a lightweight cross-unit consistency pass. |
| `no_quality_gates` | bool | no | Deliberately skip the post-translation quality gates. Default: `false`. The response reports `quality_gates.status: "skipped"`. |
| `shared_secret` | string \| null | no | Required if `MCP_SHARED_SECRET` env var is set. |

Returns:

```json
{
  "success": true,
  "content": {
    "translated": "# 你好世界\n这是一个测试。",
    "warnings": [],
    "source_lang": "en",
    "target_lang": "zh",
    "quality_gates": {"status": "ran", "reason": ""}
  },
  "translated": "# 你好世界\n这是一个测试。"
}
```

`translated` is duplicated at the top level as a backward-compat alias.

`quality_gates.status` reports whether the 7 gates (§ OL#56 in `AGENTS.md`) actually
executed, so a caller never has to guess (issue #115):

| `status` | Meaning | `reason` |
|---|---|---|
| `ran` | The gates ran. Any findings are in `warnings` as `OL_WARN: <CODE>`; a clean pass gives `warnings: []`. | `""` |
| `not_run` | Gates were requested but never ran: the config is missing or failed to load, or the gate invocation raised. **The translation is still returned** — this is not a failure, but it is not a clean pass either. | starts with `config_load_failed:` or `gate_invocation_failed:` |
| `skipped` | The caller set `no_quality_gates: true`. | `disabled by caller (no_quality_gates=true)` |

Any non-`ran` status also appends exactly one namespaced entry to `warnings`, so
callers that only read `warnings` still see it:

- `OL_GATES_NOT_RUN: <reason>`
- `OL_GATES_SKIPPED: disabled by caller (no_quality_gates=true)`

Gate *warnings* remain non-blocking in every case — `not_run` never turns into a
failed response.

### 2.2 `translate_xliff`

Translate an XLIFF file. **File in, file out** — unlike `translate_md_text`, this writes the result to disk.

| Field | Type | Required | Description |
|---|---|---|---|
| `input_path` | string | yes | Input `.xlf` / `.xliff` file. |
| `output_path` | string \| null | no | Output path. `None` → derive `<stem>_translated.xlf`. |
| `source_lang` | string | no | Default: `zh`. |
| `target_lang` | string | no | Default: `en`. |
| `glossary_path` | string \| null | no | JSON glossary. |
| `config_path` | string \| null | no | LLM config YAML. |
| `no_quality_gates` | bool | no | Deliberately skip the post-translation quality gates. Default: `false`. The response reports `quality_gates.status: "skipped"`. |
| `shared_secret` | string \| null | no | MCP auth. |

Returns:

```json
{"success": true, "content": {"output_path": "/tmp/doc_translated.xlf", "units_processed": 42,
 "warnings": [], "quality_gates": {"status": "ran", "reason": ""}}}
```

Per-unit gate findings are written to `<note from="OL">` elements in the output
file, not to `warnings`. `warnings` carries run-level conditions only — glossary
load failures, path denials, and the `OL_GATES_NOT_RUN` / `OL_GATES_SKIPPED`
markers. `quality_gates.status` means exactly what it does in § 2.1.

### 2.3 `judge_text`

LLM judge: scores a source/target pair on adequacy, fluency, terminology consistency, and format preservation (0–100 each). Implementation in `src/ol_mcp/tools.py`.

| Field | Type | Required | Description |
|---|---|---|---|
| `source` | string | yes | Source text. |
| `target` | string | yes | Translated text. |
| `source_lang` | string | no | Default `en`. |
| `target_lang` | string | no | Default `en`. |
| `glossary` | dict \| null | no | Inline glossary (same shape as `load_glossary` output). |
| `shared_secret` | string \| null | no | MCP auth. |

### 2.4 `load_glossary`

Read a JSON glossary file (legacy format, §4.2) and return the parsed dict.

| Field | Type | Required | Description |
|---|---|---|---|
| `path` | string | yes | Glossary file path. Subject to `PathValidator` (fail-CLOSED: must sit under `MCP_ALLOWED_DIRECTORIES` / `OL_MCP_ALLOWED_DIRS`). |
| `config_dir` | string \| null | no | Base dir for resolving relative paths. |
| `shared_secret` | string \| null | no | MCP auth. |

### 2.5 `get_relevant_terms`

Pick the top-k glossary terms that are most relevant to a piece of text. Returns up to `top_k` terms scored by exact-match (3.0) > case-insensitive (2.0) > variant match (1.5), with a small `confidence * 0.1` tiebreaker. Implementation in `src/ol_terminology/glossary.py`.

| Field | Type | Required | Description |
|---|---|---|---|
| `text` | string | yes | Source text to match against. |
| `glossary` | dict | yes | Glossary dict (use `load_glossary` first). |
| `top_k` | int | no | Default `5`. |
| `shared_secret` | string \| null | no | MCP auth. |

### 2.6 `search_tm`

Find similar past translations in a TMX file. Uses `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` for embeddings; cosine similarity ≥ `threshold`. Implementation in `src/ol_tm/service.py`.

| Field | Type | Required | Description |
|---|---|---|---|
| `source_text` | string | yes | Query text. |
| `tmx_path` | string | yes | Path to the `.tmx` file. |
| `threshold` | float | no | Default `0.85`. |
| `shared_secret` | string \| null | no | MCP auth. |

Returns a list of `TMMatch` (`source`, `target`, `similarity`, `language_pair`).

### 2.7 `batch_translate_texts`

Translate multiple short Markdown texts in series (with shared `ModelPool`). For high-throughput parallelism, prefer `ol translate-batch` instead.

| Field | Type | Required | Description |
|---|---|---|---|
| `texts` | list[string] | yes | Inputs. |
| `source_lang` | string | yes | Source language. |
| `target_lang` | string | yes | Target language. |
| `glossary_path` | string \| null | no | Legacy JSON glossary. |
| `concurrency` | int | no | Default `5` (reserved; current impl is sequential). |
| `shared_secret` | string \| null | no | MCP auth. |

### 2.8 `ping`

Health check. No required input. Returns:

```json
{"success": true, "content": {"module": "ol", "version": "0.7.1"}}
```

`auth_token` (a `shared_secret` alias) is accepted but optional unless `MCP_SHARED_SECRET` is set in the server environment.

---

## 3. LLM config format (`config/default.yaml`)

Schema: `src/ol_config/schema.py`. Pydantic v2 with strict validators. API keys can be inlined or referenced as `${ENV_VAR}` strings; OL resolves the env vars at startup (skipped when `OMNI_TEST_FAKE_LLM=1`).

Top-level fields:

| Field | Type | Required | Description |
|---|---|---|---|
| `project_id` | string | no | Tag for logs and cache keys. Default `default-project`. |
| `source_lang` | string | no | Default `en`. |
| `target_lang` | string | no | Default `zh`. |
| `glossary_path` | string \| null | no | Default glossary. |
| `llm_pool` | object | yes | Four role buckets (see below). |
| `enable_lqa` | bool | no | Run the LQA judge + retry loop. Default `false`. |
| `lqa_threshold` | float | no | Min pass score (0–10). Default `7.0`. |
| `lqa_max_retries` | int | no | Default `2`. |
| `cache_system_prompt` | bool | no | Default `true`. |
| `max_input_size_mb` | float | no | Pre-flight file size limit. |

`llm_pool` has four role buckets, each a list of `LLMModelConfig`:

```yaml
llm_pool:
  translation:   # role: translation | judging | restoration | profiling
    - provider: "openai"            # OpenAI-compatible endpoint; or anthropic, zhipu, …
      model: "glm-4.7-flash"
      priority: 1                   # 1 = highest, lower = higher
      role: "translation"           # MUST match the parent bucket
      api_key: "${ZHIPU_API_KEY}"   # env-var reference recommended
      base_url: "https://open.bigmodel.cn/api/paas/v4"
      timeout: 120.0
      requests_per_minute: 500      # routing weight; NOT a hard cap
      max_parallel_requests: null   # enforced cap on concurrent in-flight requests
```

Provider strings map 1:1 to LiteLLM. `config/default.yaml` uses `provider: "openai"` for both entries — AMD Radeon and Zhipu are reached as OpenAI-compatible endpoints (`nvidia_nim` was retired with its `minimaxai/minimax-m3` model). Pool validity rules:

- **At least 2 models per role** (`translation`, `judging`, `restoration`) — `LLMPoolConfig.check_min_models_per_role` in `src/ol_config/schema.py` raises `ValueError` otherwise.
- `priority: 1` is tried first; on failure, the model is opened in the per-role circuit breaker (5 consecutive failures → 60 s open).
- A cross-role safety net in `src/ol_pool/router.py` lets `judging`, `restoration`, and `profiling` fall back to the translation pool if their own models are exhausted. `translation` is the rescue target and never falls back elsewhere.

Full working example: `config/default.yaml`.

---

## 4. Glossary format

OL supports **two** glossary shapes. The `--glossary` CLI flag and the v1 `Glossary.load()` accept the structured v1 form. The legacy form is still supported by `ol_terminology.glossary.load_glossary()` and is what the MCP `load_glossary` tool reads. The complete v1 specification lives in `docs/glossary_format.md`.

### 4.1 v1 (CLI `--glossary`)

```json
{
  "terms": [
    { "source": "API",       "targets": ["API", "应用程序接口"] },
    { "source": "rendering", "targets": ["渲染"] },
    { "source": "shader",    "targets": ["着色器"] }
  ]
}
```

YAML form is also accepted (extension-based parser dispatch). Per-trans-unit, the top-`--glossary-max-terms` matches (substring count) are appended to the prompt as `Use these terms: src→tgt, …`. See `docs/glossary_format.md` for the full rules and ranking algorithm.

### 4.2 Legacy (MCP `load_glossary`, batch path)

```json
{
  "API endpoint": {
    "translation": "API 端点",
    "variants": {"API endpoint": "API 端点", "API endpoints": "API 端点"},
    "confidence": 0.95
  },
  "renderer": { "translation": "渲染器" }
}
```

Each value is `{translation, variants, confidence}`. Selection is substring + variant + confidence weighted (see `src/ol_terminology/glossary.py`).

### 4.3 Combined behavior

- CLI (`--glossary`): v1 only; legacy silently ignored unless converted.
- MCP `load_glossary` / `get_relevant_terms` / `translate_md_text` / `batch_translate_texts`: legacy dict shape.
- `BatchProcessor` (`ol_batch`): legacy dict shape.

---

## 5. TMX format

`TMService` reads and writes **TMX 1.4** via the `hypomnema` library (fallback stub in `src/ol_tm/_py_tmx.py`). Files have one `<header>` and one `<body>`; each segment is a `<tu>` with two `<tuv xml:lang="…">` children.

```xml
<?xml version="1.0" encoding="utf-8"?>
<tmx version="1.4">
  <header
    creationtool="ol-tm"
    creationtoolversion="1.0"
    segtype="sentence"
    srclang="en"
    tgtlang="zh"
    adminlang="en"
    datatype="plaintext"
  />
  <body>
    <tu>
      <tuv xml:lang="en"><seg>Click the button to continue.</seg></tuv>
      <tuv xml:lang="zh"><seg>点击按钮继续。</seg></tuv>
    </tu>
    <tu>
      <tuv xml:lang="en"><seg>API endpoint</seg></tuv>
      <tuv xml:lang="zh"><seg>API 端点</seg></tuv>
    </tu>
  </body>
</tmx>
```

Source/target language is stored on the `TMXFile` instance and emitted as `xml:lang` on each `<tuv>`. The stub does **not** understand all TMX 1.4 features (namespaces, `<note>`, multi-language `<tuv>`); use a real TMX tool to author your corpus, then point `search_tm` at it.

`TMService.add(source, target)` is in-memory only until `flush()` / `close()` / context-manager exit. A hard kill (SIGKILL) before flush drops the in-memory additions since the last successful save — see `src/ol_tm/service.py` for the durability trade-off.

---

## 6. Environment variables

| Variable | Effect |
|---|---|
| `OMNI_TEST_FAKE_LLM=1` | Skip real LLM calls; `ModelPool` returns placeholders. Required for hermetic tests. |
| `OL_CONFIG_PATH=path` | Override default LLM config for the MCP server. |
| `OMNI_CACHE_DIR=path` | Override the cache root (default `~/.omni_cache`); OL stores entries under `<root>/ol/`. |
| `AMD_API_KEY`, `ZHIPU_API_KEY` | Resolved at config-load time when referenced as `${VAR}`. |
| `OL_COMMANDCODE_API_KEY` | Key for the optional third (free `stealth/cat-jam:free`) tier present in an operator's gitignored `config/local.yaml`. |
| `MCP_SHARED_SECRET=…` | Enable shared-secret auth on the MCP server; every tool must then pass `shared_secret`. |

---

## 7. CLI environment loading

The CLI runs `_load_env_for_cli()` before the first LLM call (see `src/cli/translate_md.py`), which reads a local `.env` file (if present) so a checkout run with `python -m ol_cli …` picks up keys without exporting them in the shell. Production usage should still set keys in the shell or a secret manager.
