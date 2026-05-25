---
name: ol-localizer
description: Translate Markdown documents between languages using AI-powered localization with quality control. Handles code blocks, links, and technical content preservation.
metadata:
  hermes:
    tags: [translation, localization, markdown]
    category: tools
    requires_toolsets: [terminal]
---

# Omni-Localizer

## When to Use

Use this skill when you need to translate Markdown documents between languages. The skill preserves code blocks, links, and images while translating only the natural language content. It supports automatic failover between translation providers and includes quality evaluation.

Common use cases:
- Translating documentation from English to Chinese, Japanese, or other languages
- Localizing user-facing markdown content
- Batch translating multiple markdown files

## Procedure

1. Write the source text to a temporary `.md` file

2. Invoke the CLI:
   ```
   python -m ol_cli translate-md <file.md> -c config/default.yaml -s <source_lang> -t <target_lang> -o <output_dir> --json
   ```

3. Parse the JSON output for success/error status

4. If successful, read the translated file from `<output_dir>/<original_filename>`

## MCP Tools (Recommended for Pipeline Use)

For text-in/text-out translation without file I/O, use the MCP interface. This is the recommended approach for pipeline scenarios (batch chapter translation, smart chunking loops).

### Available Tools

| Tool | Description |
|------|-------------|
| `translate_md_text` | Translate markdown text directly (text-in/text-out) |
| `judge_text` | Evaluate translation quality |
| `load_glossary` | Load a JSON glossary file |
| `get_relevant_terms` | Extract relevant terms from text against glossary |
| `search_tm` | Search translation memory (.tmx file) |
| `batch_translate_texts` | Batch translate multiple texts in parallel |

### Quick Example

```
Tool: translate_md_text
Parameters:
  content: |
    # Hello World

    This is a test paragraph with `code` and [a link](url).
  source_lang: "en"
  target_lang: "zh"
```

Returns:
```json
{"success": true, "translated": "...", "warnings": [], "source_lang": "en", "target_lang": "zh"}
```

### Workflow: Translate with Glossary

```python
# 1. Load glossary (once, cache the result)
Tool: load_glossary
Parameters:
  path: "/path/to/glossary.json"

# 2. Translate with glossary context
Tool: translate_md_text
Parameters:
  content: "Click the API endpoint to proceed"
  source_lang: "en"
  target_lang: "zh"
  glossary_path: "/path/to/glossary.json"
```

### Workflow: Batch Chapter Translation

```python
Tool: batch_translate_texts
Parameters:
  texts: [
    "Chapter 1 content here...",
    "Chapter 2 content here...",
    "Chapter 3 content here..."
  ]
  source_lang: "en"
  target_lang: "zh"
  glossary_path: "/path/to/glossary.json"
  concurrency: 5
```

### Workflow: Quality Check

```python
Tool: judge_text
Parameters:
  source: "Click the button to continue"
  target: "点击按钮继续"
  source_lang: "en"
  target_lang: "zh"
```

### MCP Server Setup

The MCP server runs via stdio transport:

```bash
# Option 1: Direct
python -m ol_mcp

# Option 2: Via installed entry point (after pip install -e ".[mcp]")
ol-mcp
```

Configure your agent to connect to this server process. The server communicates via JSON-RPC over stdin/stdout.

### MCP vs CLI

| Aspect | MCP Tools | CLI |
|--------|--------|-----|
| Interface | text-in/text-out | file-based |
| File I/O | None | Read/write temp files |
| Overhead | Low (direct call) | Higher (subprocess + file) |
| Use case | Pipeline / chapter-by-chapter | Single file translation |
| Tool count | 6 tools | 4 commands |

### translate-batch

1. Specify the source directory containing `.md` files

2. Invoke the CLI:
   ```
   python -m ol_cli translate-batch <directory> -c config/default.yaml -s <source_lang> -t <target_lang> -o <output_dir> --json
   ```

3. Parse the JSON output for success/error status

4. If successful, translated files are in `<output_dir>/` with the same relative paths as source files

## Installation

Copy or symlink this directory to `~/.hermes/skills/ol-localizer/` to activate.

For example:
```bash
cp -r src/.hermes/skills/ol-localizer ~/.hermes/skills/
```

Or create a symlink:
```bash
ln -s src/.hermes/skills/ol-localizer ~/.hermes/skills/ol-localizer
```

## Configuration

Required environment variables:
- `OPENAI_API_KEY` - API key for your LLM provider

Optional environment variables:
- `OPENAI_BASE_URL` - Custom endpoint for your LLM provider

Optional environment variable:
- `PYTHONPATH` - Must include `src` directory when running from project root

The CLI uses a config file to specify the LLM pool. See `config/default.yaml` for an example.

## CLI Options

| Option | Short | Description |
|--------|-------|-------------|
| `--config` | `-c` | Path to config YAML file |
| `--source-lang` | `-s` | Source language code (e.g., en, zh) |
| `--target-lang` | `-t` | Target language code (e.g., en, zh) |
| `--output-dir` | `-o` | Output directory for translated files |
| `--json` | | Output JSON instead of human-readable text |
| `--frontmatter` / `--no-frontmatter` | | Add YAML frontmatter to output (default: yes) |

### translate-batch

Batch translate all Markdown files in a directory.

**Example:**
```
python -m ol_cli translate-batch <directory> -c config/default.yaml -s en -t zh -o output/ --json
```

Same CLI options as `translate-md` except the first argument is a directory instead of a file.

## Pitfalls

- **API keys not set**: Ensure OPENAI_API_KEY is in environment before running. Without it, the translation will fail with a ModelPool initialization error.

- **Input file not found**: The CLI validates that the input file exists and is a regular file before processing. Use an absolute path or ensure the relative path is correct.

- **Output directory not specified**: The `--output-dir` option is required. The directory will be created if it does not exist.

- **Input file too large**: Recommend files under 100KB for optimal performance. Very large files may cause API timeouts.

- **Only Markdown supported**: The `translate-md` command only handles `.md` files. For XLIFF files, use `translate-xliff` instead.

- **JSON output parsing**: When using `--json`, stdout contains the JSON result. stderr may contain log messages. Parse accordingly in your automation.

## Verification

1. Check JSON output has `"success": true`

2. Verify translated file exists in output directory

3. For programmatic verification, parse the JSON output:
   ```json
   {"success": true, "input_file": "example.md", "output_file": "output/example.md", "source_lang": "en", "target_lang": "zh"}
   ```

4. On failure, the JSON includes an error message:
   ```json
   {"success": false, "input_file": "example.md", "error": "error description"}
   ```
