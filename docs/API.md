# OL API Reference

This document is the canonical reference for every command and tool exposed by **Omni-Localizer (OL)** v0.4.4. It covers the CLI, the MCP server, the LLM config format, the glossary format, and the TMX format. File paths are relative to the `Omni_Localizer/` repository root.

> **Status**: v0.4.4 (matches `pyproject.toml`). CLI and MCP contracts here are stable; minor flags may appear in patch releases.

---

## 1. CLI — `ol` / `python -m ol_cli`

The CLI is a `typer` application in `src/ol_cli.py:606` with a single Typer `app` and four sub-commands. The console script is registered in `pyproject.toml:64` as `ol = "ol_cli:main_entry"`.

Common help:

```bash
ol --help
ol translate-md --help
```

Global options:

| Flag | Effect |
|---|---|
| `--version` | Print `ol version <__version__>` and exit. Implemented in `src/ol_cli.py:2077`. |

### 1.1 `ol translate-md`

Translate a single Markdown file through the shield → translate → repair → unshield pipeline.

```bash
ol translate-md <input.md> -o <output_dir> [flags]
```

Defined at `src/ol_cli.py:1541`.

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
| `--glossary-max-terms N` | `5` | Top-N terms to inject per trans-unit (1 ≤ N). |

Exit codes (see `src/ol_cli.py:ExitCode`):

- `0` — success
- `2` — usage error (bad args, missing file, missing `--output-dir`)
- `3` — pipeline error (LLM call, repair failure, etc.)

Example:

```bash
ol translate-md chapter1.md -o ./out/ -s en -t zh --glossary terms.json
```

### 1.2 `ol translate-batch`

Translate every `*.md`, `*.xliff`, and `*.xlf` in a directory. Defined at `src/ol_cli.py:1776`.

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

Translate an XLIFF 1.2 file: each `<trans-unit>` is sent to the LLM, the result is written back to `<target>`, and `<note from="OL">` is added to the header. Defined at `src/ol_cli.py:1871`.

```bash
ol translate-xliff <file.xlf> -o <output_dir> [flags]
```

Flags mirror `translate-md` minus the MD-specific ones (no `--frontmatter`, no `--detect-language`; same `--glossary` / `--no-glossary` / `--no-restoration` / `--glossary-max-terms` / `--no-cache` / `--clear-cache` set).

Example:

```bash
ol translate-xliff doc.xlf -o ./out/ -s en -t zh --json
```

### 1.4 `ol extract-warnings`

Scan a translated file for embedded `<!-- OL_WARN: ... -->` (MD) or `<note from="OL">…</note>` (XLIFF) markers and print them, or write them to a file. Defined at `src/ol_cli.py:2028`.

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
ol-mcp                       # entry point from pyproject.toml:65
# or
python -m ol_mcp             # with PYTHONPATH=src if running from a checkout
```

The server registers 8 tools (`TOOL_REGISTRY` at `src/ol_mcp/tools.py:88`). All tools return a JSON string wrapped in MCP `TextContent`; arguments are validated against a Pydantic model and rejected with `error_code: "OL_INVALID_INPUT"` on schema failure. See `src/ol_mcp/tools.py:933-945` for the dispatcher.

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
| `shared_secret` | string \| null | no | Required if `MCP_SHARED_SECRET` env var is set. |

Returns:

```json
{
  "success": true,
  "translated": "# 你好世界\n这是一个测试。",
  "warnings": [],
  "source_lang": "en",
  "target_lang": "zh"
}
```

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
| `shared_secret` | string \| null | no | MCP auth. |

Returns:

```json
{"success": true, "output_path": "/tmp/doc_translated.xlf", "units_processed": 42, "warnings": []}
```

### 2.3 `judge_text`

LLM judge: scores a source/target pair on adequacy, fluency, terminology consistency, and format preservation (0–100 each). Implementation in `src/ol_mcp/tools.py:354`.

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
| `path` | string | yes | Glossary file path. Subject to `PathValidator` (default: cwd-relative). |
| `config_dir` | string \| null | no | Base dir for resolving relative paths. |
| `shared_secret` | string \| null | no | MCP auth. |

### 2.5 `get_relevant_terms`

Pick the top-k glossary terms that are most relevant to a piece of text. Returns up to `top_k` terms scored by exact-match (3.0) > case-insensitive (2.0) > variant match (1.5), with a small `confidence * 0.1` tiebreaker. Implementation in `src/ol_terminology/glossary.py:115`.

| Field | Type | Required | Description |
|---|---|---|---|
| `text` | string | yes | Source text to match against. |
| `glossary` | dict | yes | Glossary dict (use `load_glossary` first). |
| `top_k` | int | no | Default `5`. |
| `shared_secret` | string \| null | no | MCP auth. |

### 2.6 `search_tm`

Find similar past translations in a TMX file. Uses `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` for embeddings; cosine similarity ≥ `threshold`. Implementation in `src/ol_tm/service.py:190`.

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
{"success": true, "module": "ol", "version": "0.4.4"}
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
| `llm_pool` | object | yes | Three role buckets (see below). |
| `enable_lqa` | bool | no | Run the LQA judge + retry loop. Default `false`. |
| `lqa_threshold` | float | no | Min pass score (0–10). Default `7.0`. |
| `lqa_max_retries` | int | no | Default `2`. |
| `cache_system_prompt` | bool | no | Default `true`. |
| `max_input_size_mb` | float | no | Pre-flight file size limit. |

`llm_pool` has three role buckets, each a list of `LLMModelConfig`:

```yaml
llm_pool:
  translation:   # role: translation | judging | restoration
    - provider: "openai"            # or anthropic, zhipu, agnes, nvidia_nim, …
      model: "glm-4-flash"
      priority: 1                   # 1 = highest, lower = higher
      role: "translation"           # MUST match the parent bucket
      api_key: "${ZHIPU_API_KEY}"   # env-var reference recommended
      base_url: "https://open.bigmodel.cn/api/paas/v4"
      timeout: 120.0
      requests_per_minute: 500      # hard RPM cap; set to provider's real value
```

Provider strings map 1:1 to LiteLLM. Validated providers in production: `openai`, `anthropic`, `zhipu`, `agnes`, `nvidia_nim`. Pool validity rules:

- **At least 2 models per role** — `LLMPoolConfig.check_min_models_per_role` (schema.py:72) raises `ValueError` otherwise.
- `priority: 1` is tried first; on failure, the model is opened in the per-role circuit breaker (5 consecutive failures → 60 s open).
- A cross-role safety net (router.py:373-385) lets `judging` and `restoration` fall back to the translation pool if their own models are exhausted.

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

Each value is `{translation, variants, confidence}`. Selection is substring + variant + confidence weighted (see `src/ol_terminology/glossary.py:115-161`).

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
    creationtoolversion="0.4.4"
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

`TMService.add(source, target)` is in-memory only until `flush()` / `close()` / context-manager exit. A hard kill (SIGKILL) before flush drops the in-memory additions since the last successful save — see `src/ol_tm/service.py:119-148` for the durability trade-off.

---

## 6. Environment variables

| Variable | Effect |
|---|---|
| `OMNI_TEST_FAKE_LLM=1` | Skip real LLM calls; `ModelPool` returns placeholders. Required for hermetic tests. |
| `OL_CONFIG_PATH=path` | Override default LLM config for the MCP server. |
| `MCP_SHARED_SECRET=…` | Enable shared-secret auth on the MCP server; every tool must then pass `shared_secret`. |
| `OPENAI_API_KEY`, `ZHIPU_API_KEY`, `AGNES_API_KEY`, `NVIDIA_NIM_API_KEY`, `OPENCODE_GO_KEY`, `OPENCODE_GO_BASE_URL` | Resolved at config-load time when referenced as `${VAR}`. |

---

## 7. CLI environment loading

The CLI runs `_load_env_for_cli()` before the first LLM call (see `src/ol_cli.py:1982`), which reads a local `.env` file (if present) so a checkout run with `python -m ol_cli …` picks up keys without exporting them in the shell. Production usage should still set keys in the shell or a secret manager.
