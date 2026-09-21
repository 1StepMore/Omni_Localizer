# OL Cross-Module MCP Connection Template

> **Purpose:** Bridge the OPP, OL, and ORF MCP servers into a coordinated
> document localization pipeline. This template gives agents a single
> reference for configuring all three servers, choosing the right pipeline
> path, chaining tool calls, handling errors, propagating trace context,
> and setting up path security.

**Applies to:** OPP v0.9.1, OL v0.7.1, ORF v0.4.17, Suite v0.4.0.

---

## 1. Unified MCP Server Configuration

All three servers speak the same MCP protocol but use different naming
conventions. OPP and ORF include a `-server` suffix (`opp-mcp-server`,
`orf-mcp-server`), while OL omits it (`ol-mcp`). This is a historical
inconsistency; all three follow the same JSON-RPC stdio transport.

### 1.1 Claude Desktop

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "opp-mcp-server": {
      "command": "uvx",
      "args": ["opp-mcp"]
    },
    "ol-mcp": {
      "command": "uvx",
      "args": ["ol-mcp"]
    },
    "orf-mcp-server": {
      "command": "uvx",
      "args": ["orf-mcp"]
    }
  }
}
```

### 1.2 Cursor

Add to `.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "opp-mcp-server": {
      "command": "uvx",
      "args": ["opp-mcp"]
    },
    "ol-mcp": {
      "command": "uvx",
      "args": ["ol-mcp"]
    },
    "orf-mcp-server": {
      "command": "uvx",
      "args": ["orf-mcp"]
    }
  }
}
```

### 1.3 OpenCode

Add to `opencode.json`:

```json
{
  "mcpServers": {
    "opp-mcp-server": {
      "command": "uvx",
      "args": ["opp-mcp"]
    },
    "ol-mcp": {
      "command": "uvx",
      "args": ["ol-mcp"]
    },
    "orf-mcp-server": {
      "command": "uvx",
      "args": ["orf-mcp"]
    }
  }
}
```

### 1.4 Pip-Installed Variant

If the modules are installed locally rather than via uvx, use:

```json
{
  "mcpServers": {
    "opp-mcp-server": {
      "command": "opp",
      "args": ["mcp"]
    },
    "ol-mcp": {
      "command": "ol",
      "args": ["mcp"]
    },
    "orf-mcp-server": {
      "command": "orf",
      "args": ["mcp"]
    }
  }
}
```

### 1.5 Environment Variables for MCP Servers

Set these before starting any MCP server:

```bash
# Required: fake LLM for testing (omit in production with real API keys)
export OMNI_TEST_FAKE_LLM=1

# Path security (set all three for consistency)
export MCP_ALLOWED_DIRECTORIES=/data/documents:/data/output
export OPP_MCP_ALLOWED_DIRS=/data/documents:/data/output
export ORF_MCP_ALLOWED_DIRS=/data/documents:/data/output

# Shared-secret auth (optional, but if set, must be same for all 3)
export MCP_SHARED_SECRET=my-shared-secret

# OL-specific config (optional)
export OL_CONFIG_PATH=config/default.yaml
```

---

## 2. Pipeline Decision Tree for MCP Agents

```
                    ┌─────────────────────────────────────┐
                    │  Which pipeline path should I use?   │
                    └─────────────────────────────────────┘
                                 │
              ┌──────────────────┴──────────────────┐
              │                                     │
              ▼                                     ▼
   ┌─────────────────────┐             ┌───────────────────────┐
   │  XLIFF PATH         │             │  MD PATH              │
   │  (layout-faithful)  │             │  (text-first)         │
   └─────────────────────┘             └───────────────────────┘
              │                                     │
              │ Apply when:                         │ Apply when:
              │ - Source is DOCX/PPTX/EPUB          │ - Source is any format
              │ - Output must match original        │ - Speed matters over layout
              │   layout (fonts, styles,            │ - You want format conversion
              │   floating images)                  │   (DOCX -> EPUB, etc.)
              │ - You have a skeleton.zip           │ - Image placement can be
              │                                     │   approximate
              ▼                                     ▼
    OPP: target_format="xlf"              OPP: target_format="md"
    OL:  translate_xliff                  OL:  translate_md_text
    ORF: apply_xliff                      ORF: apply_md
    (needs skeleton.zip)                  (16 output formats)
```

### Decision Table

| Condition | Recommended Path | OPP `target_format` | OL Tool | ORF Tool |
|-----------|-----------------|---------------------|---------|----------|
| Source is DOCX/PPTX/EPUB, need exact layout | XLIFF | `xlf` | `translate_xliff` | `apply_xliff` |
| Source is PDF | MD | `md` | `translate_md_text` | `apply_md` |
| Source is HTML, CSV, JSON, XML | MD | `md` | `translate_md_text` | `apply_md` |
| Source is EML / MSG | MD | `md` | `translate_md_text` | `apply_md` |
| Source is image (OCR) | MD | `md` | `translate_md_text` | `apply_md` |
| Source is YouTube URL | MD | `md` | `translate_md_text` | `apply_md` |
| Need format conversion (e.g. DOCX -> EPUB) | MD | `md` | `translate_md_text` | `apply_md` |
| Not sure | Both | `both` | Either | Either |

### The "Not Sure" Shortcut

When unsure, call `extract_document` with `target_format: "both"`. This
produces MD, XLIFF, and skeleton.zip in one pass. The extra disk space
is negligible, and you can switch paths downstream without re-extracting.

---

## 3. Full Pipeline JSON Templates

These templates use `${VARIABLE}` placeholders. Replace them with actual
values before calling the MCP tools.

### 3.1 MD Path Template

The MD path works for all 13 input formats and produces output in any
of the 16 formats that ORF supports via `apply_md`.

```json
[
  {
    "tool": "extract_document",
    "params": {
      "file_path": "${SOURCE_FILE}",
      "target_format": "both",
      "source_lang": "${SOURCE_LANG}",
      "target_lang": "${TARGET_LANG}",
      "output_dir": "${WORK_DIR}/opp"
    }
  },
  {
    "tool": "translate_md_text",
    "params": {
      "file_path": "${WORK_DIR}/opp/${BASENAME}.md",
      "source_lang": "${SOURCE_LANG}",
      "target_lang": "${TARGET_LANG}",
      "output_dir": "${WORK_DIR}/ol"
    }
  },
  {
    "tool": "apply_md",
    "params": {
      "input_md": "${WORK_DIR}/ol/${BASENAME}.md",
      "target_format": "${TARGET_FORMAT}",
      "output_path": "${OUTPUT_DIR}/result.${TARGET_FORMAT}"
    }
  }
]
```

**Variables:**

| Variable | Example | Description |
|----------|---------|-------------|
| `${SOURCE_FILE}` | `/data/report.docx` | Full path to the source document |
| `${SOURCE_LANG}` | `en` | Source language code |
| `${TARGET_LANG}` | `zh` | Target language code |
| `${WORK_DIR}` | `/tmp/my-pipeline` | Working directory for intermediate artifacts |
| `${BASENAME}` | `report` | File name without extension |
| `${TARGET_FORMAT}` | `docx` | One of 16 ORF output formats |
| `${OUTPUT_DIR}` | `/data/results` | Final output directory |

### 3.2 XLIFF Path Template

The XLIFF path preserves original document layout. Only works for
DOCX, PPTX, and EPUB inputs (the formats that produce skeleton.zip).

```json
[
  {
    "tool": "extract_document",
    "params": {
      "file_path": "${SOURCE_FILE}",
      "target_format": "xlf",
      "source_lang": "${SOURCE_LANG}",
      "target_lang": "${TARGET_LANG}",
      "output_dir": "${WORK_DIR}/opp"
    }
  },
  {
    "tool": "translate_xliff",
    "params": {
      "input_path": "${WORK_DIR}/opp/${BASENAME}.xlf",
      "output_path": "${WORK_DIR}/ol/${BASENAME}.xlf",
      "source_lang": "${SOURCE_LANG}",
      "target_lang": "${TARGET_LANG}"
    }
  },
  {
    "tool": "apply_xliff",
    "params": {
      "input_file": "${SOURCE_FILE}",
      "xliff_path": "${WORK_DIR}/ol/${BASENAME}.xlf",
      "output_path": "${OUTPUT_DIR}/result.${SOURCE_EXT}",
      "format": "${SOURCE_EXT}"
    }
  }
]
```

**Additional variables:**

| Variable | Example | Description |
|----------|---------|-------------|
| `${SOURCE_EXT}` | `docx` | Source file extension (must match output format for XLIFF path) |

### 3.3 Batch Pipeline Template

For processing multiple files in one pass:

```json
[
  {
    "tool": "batch_extract",
    "params": {
      "file_paths": ["${FILE_1}", "${FILE_2}", "${FILE_3}"],
      "output_formats": ["md"],
      "source_lang": "${SOURCE_LANG}",
      "target_lang": "${TARGET_LANG}"
    }
  },
  {
    "tool": "batch_translate_texts",
    "params": {
      "texts": ["${content_from_step_1_file_1}", "${content_from_step_1_file_2}"],
      "source_lang": "${SOURCE_LANG}",
      "target_lang": "${TARGET_LANG}",
      "concurrency": 5
    }
  },
  {
    "tool": "batch_convert",
    "params": {
      "input_dir": "${WORK_DIR}/ol",
      "target_format": "${TARGET_FORMAT}",
      "pattern": "*.md"
    }
  }
]
```

### 3.4 Data Flow Notes

1. **OPP output** from `extract_document` with `target_format: "both"`:
   - `${WORK_DIR}/opp/${BASENAME}.md` -- Markdown for the MD path
   - `${WORK_DIR}/opp/${BASENAME}.xlf` -- XLIFF for the XLIFF path
   - `${WORK_DIR}/opp/${BASENAME}_skeleton.zip` -- Skeleton (required by `apply_xliff`)
   - `${WORK_DIR}/opp/${BASENAME}_manifest.json` -- Extraction manifest

2. **OL output** from `translate_md_text`:
   - Returns JSON with `translated` (string), `source_lang`, `target_lang`, and optional `warnings` array
   - If `output_dir` was provided, writes to `${output_dir}/${BASENAME}.md`
   - To pipe directly to ORF without file I/O, pass the `translated` string as `content` to `apply_md`

3. **ORF apply_md** accepts either a file path (`input_md`) or inline content (`content`):
   ```json
   {
     "tool": "apply_md",
     "params": {
       "content": "${TRANSLATED_MARKDOWN}",
       "target_format": "html",
       "output_path": "${OUTPUT_DIR}/result.html"
     }
   }
   ```

---

## 4. Error Handling Patterns

### 4.1 Per-Stage Error Codes

All three MCP servers return errors in a uniform shape:

```json
{
  "success": false,
  "error_code": "OPP_FILE_NOT_FOUND",
  "message": "A required file was not found."
}
```

**Shared code (all 3 modules):**

| Code | Meaning | Caller Action |
|------|---------|---------------|
| `AUTH_FAILED` | Shared-secret auth rejected the call. Set `MCP_SHARED_SECRET` consistently across all three servers. | Re-issue with correct `auth_token`, or fix env var mismatch. |

**OPP errors (stage 1 -- extraction):**

| Code | Meaning | Caller Action |
|------|---------|---------------|
| `OPP_FILE_NOT_FOUND` | Input file does not exist. | Verify `file_path` is correct and the file exists. |
| `OPP_PERMISSION_DENIED` | File not readable by the server process. | Check file permissions. |
| `OPP_PATH_DENIED` | Path is outside the `OPP_MCP_ALLOWED_DIRS` allowlist. | Use a path within the allowed directories. |
| `OPP_INVALID_INPUT` | Bad input (corrupt file, wrong format). | Validate input against OPP's format support matrix. |
| `OPP_TIMEOUT` | Extraction took too long. | Retry with a smaller input, or increase server timeout. |
| `OPP_RESOURCE_EXHAUSTED` | Batch size or image size exceeded limits. | Split the batch or compress images. |

**OL errors (stage 2 -- translation):**

| Code | Meaning | Caller Action |
|------|---------|---------------|
| `OL_FILE_NOT_FOUND` | Glossary, TMX, or config path not found. | Verify the file path. |
| `OL_MCP_NOT_CONFIGURED` | Server has no allowed-directories allowlist (fail-CLOSED). This is a server-side misconfiguration, not bad input. | Set `MCP_ALLOWED_DIRECTORIES` (or `OL_MCP_ALLOWED_DIRS`) to a comma-separated allowlist before starting the server, then re-issue. Do NOT change the request input. |
| `OL_INVALID_INPUT` | Bad input or LLM returned unparseable output. | Validate input; retry may succeed if LLM transient. |
| `OL_TIMEOUT` | LLM call exceeded timeout. | Retry with backoff; consider increasing timeout for large batches. |
| `OL_PERMISSION_DENIED` | File not readable. | Check file permissions. |

**ORF errors (stage 3 -- backfill):**

| Code | Meaning | Caller Action |
|------|---------|---------------|
| `PATH_NOT_ALLOWED` | Path is outside `ORF_MCP_ALLOWED_DIRS`. | Use a path within the allowed directories. |
| `FILE_PATH_NOT_ALLOWED` | Image `file_path` rejected during XLIFF backfill. | Put image files under the same directory as the XLIFF. |
| `CLI_ERROR` | Underlying CLI subprocess failed. | Check the error field for stderr; install missing dependencies. |

### 4.2 Retry Strategy

| Error Pattern | Strategy |
|---------------|----------|
| `OL_TIMEOUT` | Retry up to 3 times with exponential backoff (1s, 2s, 4s). |
| `OL_INVALID_INPUT` (LLM transient) | Retry once. If same error, fail. |
| `OPP_TIMEOUT` | Retry once with increased timeout. |
| `CLI_ERROR` (missing dependency) | Install the missing tool and retry. |
| `AUTH_FAILED` | Check MCP_SHARED_SECRET across all servers. Do not retry without fixing config. |
| `PATH_NOT_ALLOWED`, `OPP_PATH_DENIED` | Do not retry. Fix the path to be within allowed directories. |
| `OL_MCP_NOT_CONFIGURED` | Do not retry. Configure the server: set `MCP_ALLOWED_DIRECTORIES` (or `OL_MCP_ALLOWED_DIRS`), restart, then re-issue. |
| `OPP_FILE_NOT_FOUND`, `OL_FILE_NOT_FOUND` | Verify path exists. Do not retry without fixing the path. |

### 4.3 Graceful Degradation

- If OL is unavailable (timeout), **do not skip translation**. Wait and
  retry. The pipeline cannot produce output without translation.
- If ORF is unavailable, the pipeline can stop after OL. The translated
  MD/XLIFF is still useful as text output.
- If OPP fails on a specific format, try `detect_format_tool` first to
  verify the file is recognized before calling `extract_document`.

---

## 5. W3C Trace Context Propagation

All three MCP servers support W3C Trace Context propagation via an
optional `traceparent` parameter. This links spans across the pipeline
into a single distributed trace.

### 5.1 How It Works

1. OPP's `extract_document` returns a `traceparent` field in its response
   (format: `00-${trace_id}-${span_id}-01`).
2. Pass this `traceparent` to OL's `translate_md_text` or `translate_xliff`.
   OL creates a child span with the same `trace_id`.
3. OL returns its own `traceparent` in the response.
4. Pass this to ORF's `apply_md` or `apply_xliff`. ORF creates a grandchild
   span.

```
OPP (root span)          OL (child span)          ORF (grandchild)
     │                        │                        │
     │── traceparent ────────▶│                        │
     │                        │── traceparent ────────▶│
     │                        │                        │
     │◀─────── response ──────│◀─────── response ──────│
     │  (with traceparent)    │  (with traceparent)    │  (with traceparent)
```

### 5.2 Enabling Tracing

Set the following environment variables on all three MCP servers:

```bash
export OMNI_TRACING_ENABLED=1
export OMNI_TRACES_DIR=/tmp/omni-traces
```

Each server writes its spans to a separate JSONL file:
- OPP: `${OMNI_TRACES_DIR}/opp.jsonl`
- OL: `${OMNI_TRACES_DIR}/ol.jsonl`
- ORF: `${OMNI_TRACES_DIR}/orf.jsonl`

### 5.3 MD Path With Trace Context

```json
[
  {
    "tool": "extract_document",
    "params": {
      "file_path": "${SOURCE_FILE}",
      "target_format": "both",
      "source_lang": "${SOURCE_LANG}",
      "target_lang": "${TARGET_LANG}",
      "output_dir": "${WORK_DIR}/opp"
    }
  },
  {
    "tool": "translate_md_text",
    "params": {
      "file_path": "${WORK_DIR}/opp/${BASENAME}.md",
      "source_lang": "${SOURCE_LANG}",
      "target_lang": "${TARGET_LANG}",
      "output_dir": "${WORK_DIR}/ol",
      "traceparent": "${TRACEPARENT_FROM_OPP}"
    }
  },
  {
    "tool": "apply_md",
    "params": {
      "input_md": "${WORK_DIR}/ol/${BASENAME}.md",
      "target_format": "${TARGET_FORMAT}",
      "output_path": "${OUTPUT_DIR}/result.${TARGET_FORMAT}",
      "traceparent": "${TRACEPARENT_FROM_OL}"
    }
  }
]
```

### 5.4 Extracting traceparent From OPP Response

After calling `extract_document`, parse the response:

```json
{
  "success": true,
  "md_content": "# ...",
  "traceparent": "00-abc123...-def456...-01"
}
```

Extract `${TRACEPARENT_FROM_OPP}` from `response.traceparent` and pass it
to the first OL call. Then extract `${TRACEPARENT_FROM_OL}` from OL's
response and pass it to ORF.

### 5.5 When traceparent Is Not Provided

If `traceparent` is omitted or empty, each module creates its own
independent root span with a new `trace_id`. The spans are still
recorded but cannot be correlated across modules. This is fine for
ad-hoc testing but should not be used in production orchestration.

---

## 6. Path Security Checklist

Each module handles file system access differently. Set all variables
consistently to avoid confusing failures.

### 6.1 Per-Module Env Vars

| Server | Env Variable | Behavior if Unset | Recommended |
|--------|-------------|-------------------|-------------|
| OPP MCP | `MCP_ALLOWED_DIRECTORIES` or `OPP_MCP_ALLOWED_DIRS` (colon- or semicolon-separated) | Raises `ValueError` -- server refuses to start (fail-closed) | **Always set** |
| OL MCP | `MCP_ALLOWED_DIRECTORIES` (comma-separated), falls back to `OL_MCP_ALLOWED_DIRS`, then `OL_ALLOWED_DIRECTORIES` | Raises `MCPNotConfiguredError` (error code `OL_MCP_NOT_CONFIGURED`) -- server refuses to start (fail-closed) | **Always set** |
| ORF MCP | `MCP_ALLOWED_DIRECTORIES` or `ORF_MCP_ALLOWED_DIRS` (colon- or semicolon-separated) | Raises `ValueError` -- server refuses to start (fail-closed) | **Always set** |

### 6.2 Recommendation: Set All Three to the Same Root

```bash
# Unified approach: set MCP_ALLOWED_DIRECTORIES for OL,
# and module-specific vars for OPP and ORF.
export SHARED_WORK_DIR=/data/documents

# OPP (fail-closed, required)
export OPP_MCP_ALLOWED_DIRS="${SHARED_WORK_DIR}"

# OL (uses MCP_ALLOWED_DIRECTORIES as primary)
export MCP_ALLOWED_DIRECTORIES="${SHARED_WORK_DIR}"

# ORF (fail-closed, required)
export ORF_MCP_ALLOWED_DIRS="${SHARED_WORK_DIR}"

# Also allow /tmp for test artifacts
export OPP_MCP_ALLOWED_DIRS="${SHARED_WORK_DIR}:/tmp"
export MCP_ALLOWED_DIRECTORIES="${SHARED_WORK_DIR},/tmp"
export ORF_MCP_ALLOWED_DIRS="${SHARED_WORK_DIR}:/tmp"
```

### 6.3 OL Path Validation Details

OL's `PathValidator` (in `src/ol_mcp/security.py`) checks (in order):

1. Path format is valid
2. No path traversal components (`..`)
3. Path resolves without error
4. Not a system directory (`/etc`, `/usr`, `/var`, ...)
5. Within allowed directories
6. Symlinks point inside allowed directories
7. Extension not blocked (`.exe`, `.bat`, `.sh`, ...)
8. Extension is in allowed set (`.json`, `.tmx`, `.xlf`, `.xliff`, `.md`)
   -- overridable via `MCP_ALLOWED_EXTENSIONS` env var
9. File exists (unless `allow_missing=True`)
10. File size within limit (default 100MB)

### 6.4 Environment Variable Reference

| Variable | Module | Format | Default | Notes |
|----------|--------|--------|---------|-------|
| `MCP_ALLOWED_DIRECTORIES` | All (unified) | Comma-separated for OL; colon- or semicolon-separated for OPP/ORF | None | Preferred unified name for Phase 2. Parsed with each module's own separator. |
| `OPP_MCP_ALLOWED_DIRS` | OPP | Colon- or semicolon-separated paths | None (required) | OPP is fail-closed. Server won't start without this. |
| `OL_MCP_ALLOWED_DIRS` | OL | Comma-separated paths | Falls back to `OL_ALLOWED_DIRECTORIES` | Secondary fallback for OL. |
| `OL_ALLOWED_DIRECTORIES` | OL | Comma-separated paths | None (fail-closed if all OL allowlist vars are unset) | Deprecated. Use `MCP_ALLOWED_DIRECTORIES` instead. |
| `ORF_MCP_ALLOWED_DIRS` | ORF | Colon- or semicolon-separated paths | None (required) | ORF is fail-closed. Server won't start without this. |
| `MCP_SHARED_SECRET` | All | String | None (auth disabled) | Must match across all 3 servers if set. |
| `MCP_ALLOWED_EXTENSIONS` | OL | Comma-separated extensions | `.json,.tmx,.xlf,.xliff,.md` | Overrides OL's default allowed extension set. |

> **Note:** the unified `MCP_ALLOWED_DIRECTORIES` variable is parsed by each
> module's own parser -- OL splits on commas, OPP and ORF split on `:` or `;`.

---

## 7. Common Pitfalls and Workarounds

| Pitfall | Symptom | Fix |
|---------|---------|-----|
| OPP MCP server won't start | `ValueError: allowed_directories cannot be empty` | Set `OPP_MCP_ALLOWED_DIRS` before starting. |
| OL MCP server won't start | `MCPNotConfiguredError: MCP_ALLOWED_DIRECTORIES (or OL_MCP_ALLOWED_DIRS / OL_ALLOWED_DIRECTORIES) must be set (fail-CLOSED security policy)` (error code `OL_MCP_NOT_CONFIGURED`) | Set `MCP_ALLOWED_DIRECTORIES` (comma-separated) before starting. |
| ORF MCP server won't start | `ValueError: MCP_ALLOWED_DIRECTORIES (or ORF_MCP_ALLOWED_DIRS) must be set (fail-CLOSED security policy)` | Set `MCP_ALLOWED_DIRECTORIES` or `ORF_MCP_ALLOWED_DIRS` (colon/semicolon-separated) before starting. |
| MCP server not responding to stdio | Silent failure, no JSON-RPC handshake | Use `scripts/mcp_bridge.py` workaround (FastMCP 3.4.2 stdio bug). See `ACCEPTED_GAPS.md`. |
| Cross-format XLIFF fails | ORF rejects format mismatch | Use `orf apply-xliff --force` (e.g. DOCX XLIFF -> PPTX). |
| PDF -> XLIFF blocked | OPP returns `OPP_NOT_IMPLEMENTED` | Use MD path for PDF. PDF->XLIFF is intentionally blocked. |
| ORF MSG output fails | Missing `aspose-email-foss` | Use `.eml` instead (open standard, fully supported). |
| Real LLM timeout in tests | OL returns `OL_TIMEOUT` | Set `OMNI_TEST_FAKE_LLM=1` for testing. |
| XLIFF `apply-xliff` reports SKIPPED units | Text length mismatch between XLIFF source and document | Retry with ORF v0.4.16+ (fuzzy match tolerates 5-char diff, 0.85 ratio). |
| Quality gate warnings in output | `OL_WARN: ...` annotations | These are non-blocking info messages. Check gate config in `quality_gates:` section. |
| `translate_md_text` returns no output_dir | File not written to disk | Use `content` parameter with `apply_md` instead of `input_md` to pipe text directly. |

---

## 8. Quick Reference Card

| Action | Tool | Server |
|--------|------|--------|
| Extract single document | `extract_document` | OPP |
| Extract multiple documents | `batch_extract` | OPP |
| Detect file format | `detect_format_tool` | OPP |
| Save skeleton ZIP | `save_skeleton` | OPP |
| Generate XLIFF | `generate_xliff` | OPP |
| Convert document to Markdown | `generate_markdown` | OPP |
| Validate XLIFF | `validate_xliff` | OPP |
| Translate markdown (text) | `translate_md_text` | OL |
| Translate markdown (file) | `translate_md_text` with `file_path` | OL |
| Translate XLIFF | `translate_xliff` | OL |
| Judge translation quality | `judge_text` | OL |
| Load glossary | `load_glossary` | OL |
| Batch translate texts | `batch_translate_texts` | OL |
| Backfill MD to format | `apply_md` | ORF |
| Backfill XLIFF to document | `apply_xliff` | ORF |
| Batch convert MD files | `batch_convert` | ORF |
| Get document info | `info` | ORF |
| Detect document format | `detect_format` | ORF |
| Get module capabilities | `get_capabilities` | OPP / OL / ORF |
| Health check (any server) | `ping` | OPP / OL / ORF |

**MCP server names:**
- OPP: `opp-mcp-server`
- OL: `ol-mcp` (no `-server` suffix)
- ORF: `orf-mcp-server`

**Tool counts:** OPP 9, OL 21, ORF 7 (37 total).

---

*Generated for OL Issue #79. Source references: suite AGENTS.md,
ERROR_CODES.md, agent-pipeline-guide.md, distributed tracing tests,
and per-module security modules.*
