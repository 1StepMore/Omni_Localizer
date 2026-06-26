# OL MCP Server

Text-in/text-out MCP tools for Omni-Localizer, enabling agent-native localization without file I/O.

## Tools

| Tool | Description |
|------|-------------|
| `translate_md_text` | Translate markdown text directly |
| `judge_text` | Evaluate translation quality |
| `load_glossary` | Load a JSON glossary |
| `get_relevant_terms` | Extract relevant terms from text |
| `search_tm` | Search translation memory |
| `batch_translate_texts` | Batch translate multiple texts |

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

## Architecture

The MCP server is a thin wrapper over existing OL infrastructure:

```
MCP Tool Call
    │
    ▼
ol_mcp/tools.py     ← Tool implementation (input validation, error handling)
    │
    ▼
ol_pool.router.ModelPool.translate()    ← LLM translation
ol_md.shield.shield_markdown()          ← Content preservation
ol_md.pipeline.MDRepairPipeline.repair() ← 4-layer repair
ol_terminology.glossary.load_glossary() ← Terminology
ol_tm.service.TMService.search()        ← Translation memory
```

No new translation logic — all requests route to existing, tested OL components.