# OL MCP Server

Text-in/text-out MCP tools for Omni-Localizer, enabling agent-native localization without file I/O.

## Tools

| Tool | Description |
|------|-------------|
| `translate_md_text` | Translate markdown text directly (shield → translate → repair → unshield) |
| `translate_xliff` | Translate an XLIFF file, filling `<target>` elements |
| `judge_text` | Evaluate translation quality (adequacy, fluency, terminology, format) |
| `load_glossary` | Load a JSON glossary file |
| `get_relevant_terms` | Extract top-k relevant glossary terms for a source text |
| `search_tm` | Search TMX translation memory for similar past translations |
| `batch_translate_texts` | Translate multiple markdown texts in parallel |
| `verify_terms` | Verify glossary term usage in translated content (no LLM) |
| `profile_doc` | Profile a document's writing style via LLM, producing a StyleGuide |
| `extract_terms` | Extract key terms from source texts using YAKE |
| `add_tm_entries` | Add entries to a TMX translation memory file |
| `disambiguate` | Resolve polysemous glossary terms with LLM context understanding |
| `shield_md_text` | Shield markdown content (replace code, math, links with markers) |
| `unshield_md_text` | Unshield markdown content (restore markers from shield_map) |
| `translate_file` | End-to-end file translation (OPP→OL→ORF in one call) |
| `get_translation_status` | Poll the status of an async translation task |
| `extract_warnings` | Extract warning markers from an output file |
| `generate_report` | Generate a translation report (HTML + CSV) |
| `inspect_config` | Inspect the resolved OL configuration |
| `get_capabilities` | Return module capabilities (roles, language pairs, tools) |
| `ping` | Health check endpoint |

## Installation

```bash
pip install -e ".[mcp]"
```

## Running the Server

```bash
python -m ol_mcp
# or
ol-mcp
```

The server uses stdio transport — it communicates via JSON-RPC over stdin/stdout. Configure your MCP client to connect to this process.

## Configuration

The server uses `config/default.yaml` for LLM pool configuration by default. Override with environment variable:

```bash
OL_CONFIG_PATH=/path/to/config.yaml python -m ol_mcp
```

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `OL_MCP_ALLOWED_DIRS` | `[cwd, /tmp]` | Comma-separated allowlist of directories the MCP can read. Falls back to `OL_ALLOWED_DIRECTORIES` (deprecated). |
| `OL_CONFIG_PATH` | `config/default.yaml` | Config file path override. |
| `OL_LENGTH_RATIO_MIN` | `0.5` | Minimum length ratio for quality gate 3 (config override). |
| `OL_LENGTH_RATIO_MAX` | `3.0` | Maximum length ratio for quality gate 3 (config override). |
| `OL_TARGET_LOCALE` | (none) | Default target locale for quality gate 4 (e.g. `en-US`). |
| `MCP_SHARED_SECRET` | (none) | Shared-secret auth (omit for dev). |

## Tools Detail

### translate_md_text

Translate markdown text directly without file I/O.

```python
{
    "content": "# Hello World\nThis is a test.",
    "source_lang": "en",
    "target_lang": "zh",
    "glossary_path": "/path/to/glossary.json",  # optional
    "config_path": "config/default.yaml",        # optional
    "add_frontmatter": False,                     # optional
}
```

### judge_text

Evaluate translation quality after translation.

```python
{
    "source": "Click the button to continue",
    "target": "点击按钮继续",
    "source_lang": "en",
    "target_lang": "zh",
    "glossary": {"button": {"translation": "按钮"}},  # optional
}
```

### load_glossary

Load a JSON glossary file.

```python
{
    "path": "/path/to/glossary.json",
    "config_dir": "/path/to/config",  # optional, for relative paths
}
```

### get_relevant_terms

Extract relevant glossary terms for a text.

```python
{
    "text": "Click the API endpoint to proceed",
    "glossary": {...},  # from load_glossary
    "top_k": 5,         # optional
}
```

### search_tm

Search translation memory for similar past translations.

```python
{
    "source_text": "Click the button",
    "tmx_path": "/path/to/memory.tmx",
    "threshold": 0.85,  # optional
}
```

### batch_translate_texts

Translate multiple texts in parallel.

```python
{
    "texts": ["Chapter 1...", "Chapter 2...", "Chapter 3..."],
    "source_lang": "en",
    "target_lang": "zh",
    "glossary_path": "/path/to/glossary.json",  # optional
    "concurrency": 5,                           # optional
}
```

### translate_xliff

Translate an XLIFF file, writing `<target>` elements to the output file. Supports async mode.

```python
{
    "input_path": "/path/to/document.xlf",          # path to input XLIFF
    "output_path": "/path/to/translated.xlf",       # optional (auto-generated if None)
    "source_lang": "zh",
    "target_lang": "en",
    "glossary_path": "/path/to/glossary.json",     # optional
    "styleguide_path": "/path/to/styleguide.json", # optional
    "polish": False,                                # optional, consistency pass
    "config_path": "config/default.yaml",           # optional
    "async_mode": False,                            # optional, run in background
}
```

### verify_terms

Verify glossary term usage in translated content. No LLM, no network. Uses the `ol_terminology.verifier.verify_translation` engine.

```python
{
    "source": "Click the button to continue",
    "target": "点击按钮继续",
    "glossary": {"button": {"translation": "按钮"}},   # optional, inline glossary
    "glossary_path": "/path/to/glossary.json",         # optional, alternative
    "confidence_threshold": 0.7,                       # optional, 0-1
    "source_lang": "en",
    "target_lang": "zh",
}
```

Returns a JSON report with `verified`, `mismatches`, `absent`, `inconsistencies`, and `low_confidence` lists.

### profile_doc

Profile a document's writing style using an LLM. Returns a StyleGuide object with tone, register, target audience, key conventions, vocabulary, terms to avoid, and summary. The output can be fed back as `styleguide_path` to `translate_md_text` or `translate_xliff`.

```python
{
    "content": "# Full document text to profile...",
    "source_lang": "en",          # optional
    "config_path": "config/default.yaml",   # optional
    "use_cache": True,                      # optional, enable in-process caching
}
```

## Quality Gate Warnings

Both `translate_md_text` and `translate_xliff` run a set of **post-translation quality gates** when the OL config has a `quality_gates:` section. These gates are pure functions (no LLM calls, no network I/O):

| Gate | Check | Warning Code |
|------|-------|-------------|
| 1 — Inline tags | Parity of `<bx>`, `<ex>`, `<x>` tags between source and target | `OL_WARN: INLINE_TAG_MISMATCH` |
| 2 — Terminology | Both source term and translation appear in target (inconsistency) | `OL_WARN: TERMINOLOGY_INCONSISTENCY` |
| 3 — Length ratio | `len(target) / len(source)` within configured bounds | `OL_WARN: LENGTH_RATIO` |
| 4 — Locale conventions | Currency mixing, CJK date leakage, digit grouping, GB/US spelling | `OL_WARN: {CURRENCY_MIXING,DATE_LEAKAGE,DIGIT_GROUPING,UNIT_SPELLING}` |

**`translate_md_text`** returns gate warnings in an optional `warnings` array in the JSON response:

```json
{
  "success": true,
  "content": {
    "translated": "...",
    "warnings": [
      "OL_WARN: LENGTH_RATIO — target/source length ratio 0.32 is below minimum 0.5",
      "OL_WARN: CURRENCY_MIXING — multiple currency symbols found: $ €"
    ],
    "source_lang": "en",
    "target_lang": "zh"
  }
}
```

**`translate_xliff`** injects per-unit gate warnings as `<note from="OL">` elements inside the corresponding `<trans-unit>`:

```xml
<trans-unit id="u1">
  <source>...</source>
  <target>...</target>
  <note from="OL">OL_WARN: INLINE_TAG_MISMATCH — tag <bx count differs</note>
</trans-unit>
```

Quality gates are controlled via YAML config:

```yaml
quality_gates:
  inline_tags: true
  terminology: true
  length_ratio:
    enabled: true
    min: 0.5
    max: 3.0
  locale:
    enabled: true
    target_locale: "en-US"
```

## Architecture

The MCP server is a thin wrapper over existing OL infrastructure:

```
MCP Tool Call
    │
    ▼
ol_mcp/tools.py     ← Tool implementation (input validation, error handling)
    │
    ├──→ ol_pool.router.ModelPool.translate()          ← LLM translation
    ├──→ ol_md.shield.shield_markdown()                ← Content preservation
    ├──→ ol_md.pipeline.MDRepairPipeline.repair()      ← 4-layer repair (MD)
    ├──→ ol_xliff.pipeline.XLIFFRepairPipeline.repair() ← 4-layer repair (XLIFF)
    ├──→ ol_lqa.quality_gates.run_quality_gates()      ← Post-translation quality checks
    ├──→ ol_terminology.glossary.load_glossary()       ← Terminology
    ├──→ ol_terminology.verifier.verify_translation()  ← Term verification
    ├──→ ol_tm.service.TMService.search()              ← Translation memory
    ├──→ ol_style.doc_profiler.profile_document()      ← Style profiling
    └──→ ol_style.schema.StyleGuide.to_prompt_section() ← StyleGuide injection
```

No new translation logic — all requests route to existing, tested OL components.