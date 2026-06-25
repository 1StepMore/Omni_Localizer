# OL Troubleshooting

Common OL failures and their fixes. Every section names the symptom first, then the root cause, then the smallest possible fix. File paths are relative to `Omni_Localizer/`.

If the failure you hit isn't listed, capture the full command, the exit code, the JSON output (if `--json` was used), and the last 50 lines of stderr and open a GitHub issue: <https://github.com/1StepMore/Omni_Localizer/issues>.

---

## 1. `ModuleNotFoundError: No module named 'ol_cli'`

**Symptom**

```
$ ol translate-md in.md -o out/ -s en -t zh
ModuleNotFoundError: No module named 'ol_cli'
```

**Cause**

You ran the command from a checkout but `src/` is not on `PYTHONPATH`. The wheel build (`pip install -e .`) only takes effect inside the active venv.

**Fix**

Activate the Omni_Suite venv (it has all three submodules installed):

```bash
source ../.venv_ol/bin/activate
python -m ol_cli translate-md in.md -o out/ -s en -t zh
```

If you must run from a fresh checkout, prepend `PYTHONPATH=src`:

```bash
PYTHONPATH=src python -m ol_cli translate-md in.md -o out/ -s en -t zh
```

The Omni_Suite `.bat` file from the README wraps exactly this pattern.

---

## 2. `Environment variable 'X' referenced in api_key but not set`

**Symptom**

```
ValueError: Environment variable 'ZHIPU_API_KEY' referenced in api_key but not set
```

**Cause**

`config/default.yaml` references `${ZHIPU_API_KEY}` in the `api_key` field. The schema validator in `src/ol_config/schema.py:17` walks every `${VAR}` in the loaded config and raises if the env var is unset.

**Fix**

Either set the key, or run in fake-LLM mode (which short-circuits the check, see `schema.py:23`):

```bash
# Option A — real key
export ZHIPU_API_KEY=sk-your-key

# Option B — hermetic, no LLM call
export OMNI_TEST_FAKE_LLM=1
```

The same applies to `AGNES_API_KEY`, `NVIDIA_NIM_API_KEY`, `OPENCODE_GO_KEY`, `OPENCODE_GO_BASE_URL`, etc. The default config uses ZHIPU/AGNES/NVIDIA/OPENCODE; replace the pool if you want a different provider.

---

## 3. `litellm.RateLimitError` / HTTP 429

**Symptom**

```
litellm.RateLimitError: Rate limit reached for model glm-4-flash
```

**Cause**

The primary model returned 429 (too many requests). OL's `ModelPool` should fall back to the next-priority model automatically, but if every model in the pool hits its RPM cap the call eventually fails.

**Fix (short term)**

Wait 30 s and re-run. For batch jobs, lower concurrency:

```bash
ol translate-batch ./docs/ -o ./out/ -s en -t zh -j 2
```

**Fix (long term)**

Set `requests_per_minute` to the provider's actual cap in `config/default.yaml`:

```yaml
- provider: "openai"
  model: "deepseek-ai/deepseek-v4-flash"
  requests_per_minute: 40   # NVIDIA free tier
```

The `pybreaker`-backed circuit breaker (router.py:237-245) opens the role for 60 s after 5 consecutive failures, preventing a retry storm — let it cool.

---

## 4. `Translation failed for X: Glossary validation failed at terms.0.source`

**Symptom**

```
Error: failed to load glossary glossary.json: Glossary validation failed at terms.0.source: Input should be a valid string
```

**Cause**

You passed a file in the **legacy** dict shape (`{"API endpoint": {"translation": "API 端点"}}`) to the CLI's `--glossary` flag. The CLI expects the **v1** shape `{"terms": [{"source": "API endpoint", "targets": ["API 端点"]}]}`. See `docs/glossary_format.md` for the full spec.

**Fix**

Convert to v1:

```json
{
  "terms": [
    { "source": "API endpoint", "targets": ["API 端点"] }
  ]
}
```

The legacy shape is still accepted by the MCP `load_glossary` tool and by the `BatchProcessor`. If you want to keep your existing file as-is, drive the MCP server instead of the CLI.

---

## 5. `Malformed glossary JSON` / `glossary file not found`

**Symptom**

```
Error: failed to load glossary glossary.json: Malformed JSON in glossary.json: Expecting ',' delimiter
# or
Error: glossary file not found: glossary.json
```

**Cause**

Either the file path is wrong, or the JSON has a syntax error (trailing comma, missing quote, BOM, etc.).

**Fix**

```bash
# 1. Verify the file exists
ls -l glossary.json

# 2. Verify it's valid JSON
python -c "import json; json.load(open('glossary.json'))"

# 3. Or run from the right working directory — paths are resolved
#    against cwd, not the config file's location
cd /path/to/your/project
ol translate-md in.md -o out/ -s en -t zh --glossary glossary.json
```

The CLI resolves relative paths from `Path.cwd()`, not from `--config`'s directory. Pass an absolute path or `cd` first.

---

## 6. `TMX path '/path/to/memory.tmx' is not in the allowed directories`

**Symptom**

```
{"success": false, "matches": [], "count": 0,
 "warnings": ["OL_PATH_NOT_ALLOWED: …"]}
```

**Cause**

The MCP server enforces a `PathValidator` whitelist (`src/ol_mcp/security.py`). By default only paths inside the server's CWD are accepted. The CLI does **not** apply this restriction; it has full filesystem access.

**Fix**

Use the CLI for ad-hoc file paths, or call the MCP tool with an absolute path inside the allowed directories. The validator is intentionally strict to prevent a rogue prompt from reading `/etc/passwd` and exfiltrating it through a translation.

---

## 7. `Circuit breaker 'translation' is open`

**Symptom**

```
pybreaker.CircuitBreakerError: Circuit breaker 'translation' is open
```

**Cause**

Five consecutive LLM failures on the translation role (router.py:237-245) tripped the breaker. It auto-resets after 60 s.

**Fix**

1. Check the cause of the underlying 5 failures (most often auth, rate limit, or model-name typo).
2. Wait 60 s, or use a different config to bypass:

```bash
ol translate-md in.md -o out/ -c config/local.yaml -s en -t zh
```

The breaker is per-process and per-role. Restarting the CLI resets it.

---

## 8. Translation contains `{{_OL_LINK_0001_}}` instead of the actual link

**Symptom**

The translated Markdown has un-substituted placeholders like `{{_OL_LINK_0001_}}` left over from the shield step.

**Cause**

The LLM occasionally eats placeholders. The `--no-restoration` flag, or a missing `restoration` pool, will leave them in the output. The 4-layer repair in `src/ol_md/pipeline.py` covers most cases, but if the `restoration` role has no working models, layer 3 (LLM restoration) is skipped.

**Fix**

- Don't pass `--no-restoration` unless you have a reason.
- Ensure your config has at least 2 `restoration` models. If a single model is failing, add a backup:

  ```yaml
  llm_pool:
    restoration:
      - provider: "openai"
        model: "glm-4-flash"
        priority: 1
        api_key: "${ZHIPU_API_KEY}"
        base_url: "https://open.bigmodel.cn/api/paas/v4"
      - provider: "openai"
        model: "deepseek-v4-flash"
        priority: 2
        api_key: "${OPENCODE_GO_KEY}"
        base_url: "${OPENCODE_GO_BASE_URL}"
  ```

- The repair pipeline will fall back to layer 4 (safe substitution) only if layers 1–3 leave missing placeholders. In the worst case the original link/image/code block is reinserted verbatim — the output is never worse than the input for that construct.

---

## 9. `No translation units found in XLIFF file`

**Symptom**

```
{"success": false, "units_processed": 0,
 "warnings": ["No translation units found in XLIFF file"]}
```

**Cause**

The XLIFF has no `<trans-unit>` elements. Either the file is empty, the parser failed silently on malformed XML, or the namespace is wrong (XLIFF 1.2 vs 2.x).

**Fix**

1. Open the file in a text editor; check it has `<file>` → `<body>` → `<trans-unit>` → `<source>`.
2. Validate it:

   ```bash
   python -c "from lxml import etree; etree.parse('doc.xlf'); print('OK')"
   ```

3. If the XLIFF came from OPP, regenerate it with `--target-format both`:

   ```bash
   opp document.docx --target-format both --source-lang en --target-lang zh --output-dir /tmp/opp
   ```

The parser at `src/ol_xliff/parser.py` handles XLIFF 1.2 (`urn:oasis:names:tc:xliff:document:1.2`). XLIFF 2.x files need to be downgraded.

---

## 10. LQA judge never passes (`lqa_threshold` not met)

**Symptom**

```
Translation retried 2 times but score stayed below 7.0; emitting best attempt.
```

**Cause**

`enable_lqa: true` runs the `JudgeService` on every translation; if the score is below `lqa_threshold` (default `7.0`), it retries up to `lqa_max_retries` times. If the LLM judge is itself noisy, you can hit infinite-ish retry loops.

**Fix**

- Lower the threshold: `lqa_threshold: 6.0` in your config.
- Add a better `judging` model — `glm-4-flash` is fast but noisy on the judge role; `agnes-2.0-flash` tends to be more stable.
- Disable for one-off runs: pass `--no-lqa` (or set `enable_lqa: false` in the config you're using).

The retry is bounded by `lqa_max_retries`; you will not loop forever.

---

## 11. MCP server returns `OL_INVALID_INPUT`

**Symptom**

```json
{"success": false, "error_code": "OL_INVALID_INPUT",
 "message": "Invalid arguments: …"}
```

**Cause**

The Pydantic schema for the tool rejected your arguments. Typical causes: a required field is missing, a string is passed where an int is expected, or `top_k` is out of range.

**Fix**

Cross-check your call against the tool's schema (`session.list_tools()` returns them in JSON Schema form). Common mistakes:

- `glossary_max_terms` must be `1 ≤ N ≤ 50` (default 5).
- `concurrency` for `batch_translate_texts` must be a positive int.
- `source_lang` / `target_lang` are required strings — pass `"en"`, not `""` or `null`.

The full set of constraints lives in `src/ol_mcp/tools.py` (one `*Input` class per tool).

---

## 12. MCP server returns `OL_UNKNOWN_TOOL`

**Symptom**

```json
{"success": false, "error_code": "OL_UNKNOWN_TOOL",
 "message": "Unknown tool: translate_md"}
```

**Cause**

Tool-name typo. The 8 registered tools are:

`translate_md_text`, `translate_xliff`, `judge_text`, `load_glossary`, `get_relevant_terms`, `search_tm`, `batch_translate_texts`, `ping`. Note the exact names — `translate_md` (no `_text`) is the CLI subcommand, not the MCP tool.

---

## 13. MCP server hangs (no response to `list_tools`)

**Symptom**

`session.list_tools()` never resolves; `ps` shows `python -m ol_mcp` consuming CPU or stuck.

**Cause**

The fastmcp stdio handshake bug (or, on very old builds, an unbuffered subprocess). Fixed by Phase 1.4 (`src/ol_mcp/server.py:1-10`) — the server now uses `mcp.server.Server` + `stdio_server()`.

**Fix**

1. Verify your install has the fix:

   ```bash
   grep -n "stdio_server" src/ol_mcp/server.py
   # expect: async with stdio_server() as ...
   ```

2. Always spawn the server with `python -u -m ol_mcp` and `bufsize=0`:

   ```python
   import subprocess
   p = subprocess.Popen(
       ["python", "-u", "-m", "ol_mcp"],
       env={..., "PATH": "/usr/bin:/bin"},
       bufsize=0,
   )
   ```

3. If you're running the server directly in a terminal (for debugging), use `python -u -m ol_mcp`, **not** `python -m ol_mcp` — buffered stdout will mask the JSON-RPC frames.

---

## 14. `BatchProcessor` silently skips every file

**Symptom**

`ol translate-batch ./docs/ -o out/ -s en -t zh` prints `Found 0 files to process`.

**Cause**

The discovery step (`ol_batch.discovery.discover_files`) only matches `*.md`, `*.xliff`, and `*.xlf`. A directory of `.markdown`, `.MD.txt`, or hidden files is invisible to it.

**Fix**

- Rename files to use a supported extension.
- Or copy / symlink them:

  ```bash
  for f in docs/*.markdown; do cp "$f" "${f%.markdown}.md"; done
  ol translate-batch ./docs/ -o ./out/ -s en -t zh
  ```

---

## 15. `--json` output isn't valid JSON

**Symptom**

`ol translate-md … --json` prints a stack trace instead of a JSON line.

**Cause**

An error fired **before** the success branch ran. The `--json` flag only affects the success-line path; an exception during the pipeline prints a Python traceback to stderr and exits non-zero.

**Fix**

Run without `--json` first to see the human-readable error, then re-run with `--json` once it's fixed. The most common pre-success error is "Input file not found" (the validator at `validate_input_file` exits with `CLI_USAGE_ERROR = 2`).

---

## 16. Where to get more help

- Read `docs/glossary_format.md` for the full glossary spec and validation rules.
- Read `docs/real_llm_runbook.md` for cost-controlled real-LLM testing.
- Open a bug report at <https://github.com/1StepMore/Omni_Localizer/issues> with: full command, exit code, the JSON output if any, and the last 50 lines of stderr.
