# OL Tutorial

Hands-on walkthroughs for Omni-Localizer. Every scenario is end-to-end and copy-pasteable. All paths are relative to the `Omni_Localizer/` repo root unless noted.

> **Prereq**: Python 3.13, `pip install -e .` (or `pip install -e ".[mcp]"` for the MCP server), and at least one LLM provider key (`ZHIPU_API_KEY` for the default config). When you don't have a real key, set `export OMNI_TEST_FAKE_LLM=1` and OL will use a placeholder model so the pipeline still runs.

---

## 1. 5-Minute Quickstart — translate one file

Translate `chapter1.md` from English to Simplified Chinese.

```bash
# 1. Activate the venv the Omni_Suite setup script built
source ../.venv_ol/bin/activate

# 2. (Hermetic) skip the real LLM — set this if you have no key
export OMNI_TEST_FAKE_LLM=1

# 3. (With a real key) export whatever the default config references
# export ZHIPU_API_KEY=sk-your-key

# 4. Translate
python -m ol_cli translate-md chapter1.md -o ./out/ -s en -t zh
```

What you get:

- `out/chapter1.md` — translated Markdown with a YAML frontmatter header:

  ```yaml
  ---
  source_lang: en
  target_lang: zh
  original_file: chapter1.md
  processor: "OL"
  version: "0.4.4"
  translated_at: 2026-06-22T15:00:00Z
  ---
  ```
- A one-line status on stdout: `Translated: chapter1.md -> ./out/chapter1.md (en -> zh)`.

`--no-frontmatter` strips the header; `--json` swaps the human line for a JSON status that an agent can parse.

---

## 2. Translate a document end-to-end (OPP → OL → ORF)

This is the canonical Omni_Suite pipeline. You start with a DOCX, end with a translated DOCX.

```bash
# Step 1 — extract to Markdown + XLIFF + skeleton.zip
opp document.docx --target-format both --source-lang en --target-lang zh \
    --output-dir /tmp/opp

# Step 2 — translate the Markdown (this tutorial!)
ol translate-md /tmp/opp/document.md -o /tmp/ol -s en -t zh

# Step 3 — translate the XLIFF (parallel path, preserves original layout)
ol translate-xliff /tmp/opp/document.xlf -o /tmp/ol -s en -t zh

# Step 4 — backfill translated content to DOCX
orf apply-xliff document.docx --xliff /tmp/ol/document.xlf --output result.docx
```

Tips for the OL step in the middle of this pipeline:

- `ol translate-md` keeps code blocks, images, links, math, and HTML blocks intact — the shield/unshield pair at `src/ol_md/shield.py:40` swaps them for `\x00OL_<TYPE>_<NNNN>\x00` placeholders, and the repair pipeline restores them after the LLM returns.
- If you only need the Markdown artifact (e.g. for a static site), stop after step 2. The XLIFF path (steps 3–4) is for round-tripping to the original DOCX layout with original fonts, tables, and styles.
- The output file name is `<input>.md` (not `translated_<input>.md`); ORF reads it back by that name.

---

## 3. Translation memory + glossary

When you have a domain-specific corpus (jargon, brand names, idioms), combine a TMX with a glossary for consistent, in-style translations.

### 3.1 Build a glossary (legacy format, what `load_glossary` reads)

```json
{
  "API endpoint":  { "translation": "API 端点",     "confidence": 0.95 },
  "renderer":      { "translation": "渲染器",        "confidence": 0.90 },
  "shader":        { "translation": "着色器" },
  "kernel":        { "translation": "内核" }
}
```

Save it as `glossary.json`. Confidence defaults to `1.0` when omitted; the `get_relevant_terms` selector boosts matches with higher confidence.

### 3.2 Build a translation memory (TMX)

The simplest path is to hand-author a TMX file, or harvest it from past translations:

```xml
<?xml version="1.0" encoding="utf-8"?>
<tmx version="1.4">
  <header srclang="en" tgtlang="zh" adminlang="en" datatype="plaintext" />
  <body>
    <tu>
      <tuv xml:lang="en"><seg>Click the button to continue.</seg></tuv>
      <tuv xml:lang="zh"><seg>点击按钮继续。</seg></tuv>
    </tu>
    <tu>
      <tuv xml:lang="en"><seg>The renderer uses a custom shader.</seg></tuv>
      <tuv xml:lang="zh"><seg>渲染器使用自定义着色器。</seg></tuv>
    </tu>
  </body>
</tmx>
```

Save as `memory.tmx`. The MCP `search_tm` tool uses `paraphrase-multilingual-MiniLM-L12-v2` embeddings and a default similarity threshold of `0.85` to find matches.

### 3.3 Run with both

CLI:

```bash
ol translate-md chapter1.md -o ./out/ -s en -t zh --glossary glossary.json
```

(The CLI's `--glossary` flag expects the v1 `{"terms": […]}` shape — see `docs/glossary_format.md` for that format. To use the legacy dict shape, drive the MCP server instead.)

MCP — inject both into the prompt automatically:

```python
# in an MCP-aware agent
{
  "tool": "translate_md_text",
  "params": {
    "content": open("chapter1.md").read(),
    "source_lang": "en",
    "target_lang": "zh",
    "glossary_path": "/abs/path/to/glossary.json"
  }
}
```

The `BatchProcessor` path (`ol translate-batch`) queries the TM and extracts relevant glossary terms before each LLM call, then injects up to 5 terms (or `--glossary-max-terms N`) into the prompt. The MCP `translate_md_text` does the same with a `glossary_path` argument.

### 3.4 Verify with a judge

After translating, score the result with the LLM judge:

```python
{
  "tool": "judge_text",
  "params": {
    "source": "The renderer uses a custom shader.",
    "target": "渲染器使用自定义着色器。",
    "source_lang": "en",
    "target_lang": "zh"
  }
}
```

Returns a 0–100 score split across `adequacy`, `fluency`, `terminology_consistency`, and `format_preservation`.

---

## 4. Use OL with Claude / Cursor / OpenCode via MCP

The MCP server speaks stdio JSON-RPC. The following examples assume you have OL installed (`pip install -e ".[mcp]"`) and the Omni_Suite venv active.

### 4.1 Claude Desktop

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "ol-mcp": {
      "command": "/absolute/path/to/.venv_ol/bin/ol-mcp",
      "env": {
        "OMNI_TEST_FAKE_LLM": "1"
      }
    }
  }
}
```

If you have a real key, drop the `OMNI_TEST_FAKE_LLM` env line and set `ZHIPU_API_KEY` (or whichever your `config/default.yaml` references). Restart Claude Desktop. You'll then see eight tools under the OL server:

- `translate_md_text`, `translate_xliff`, `judge_text`
- `load_glossary`, `get_relevant_terms`, `search_tm`
- `batch_translate_texts`
- `ping`

### 4.2 Cursor

Add to `.cursor/mcp.json` in your project:

```json
{
  "mcpServers": {
    "ol-mcp": {
      "command": "uvx",
      "args": ["ol-mcp"],
      "env": { "OMNI_TEST_FAKE_LLM": "1" }
    }
  }
}
```

Cursor picks up MCP servers on the next reload.

### 4.3 OpenCode

Add to `opencode.json`:

```json
{
  "mcpServers": {
    "ol-mcp": {
      "command": "ol-mcp",
      "env": { "OMNI_TEST_FAKE_LLM": "1" }
    }
  }
}
```

OpenCode also ships a project-level skill at `src/.opencode/skills/ol-localizer/SKILL.md`. Copy it into your project's `.opencode/skills/` to give the agent explicit invocation guidance:

```bash
cp -r src/.opencode/skills/ol-localizer <your-project>/.opencode/skills/
```

### 4.4 A complete MCP session (in a Python REPL)

For local sanity-checking without a real client:

```bash
.venv_ol/bin/python - <<'PY'
import asyncio, json
from mcp.client.stdio import stdio_client, ClientSession

async def main():
    async with stdio_client(lambda: (
        __import__("subprocess").Popen(
            [".venv_ol/bin/python", "-u", "-m", "ol_mcp"],
            env={"OMNI_TEST_FAKE_LLM": "1", "PATH": "/usr/bin:/bin"},
            bufsize=0,
        )
    )) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = await s.list_tools()
            print("tools:", [t.name for t in tools.tools])
            r = await s.call_tool("translate_md_text", {
                "content": "# Hello\n\nThis is a test.",
                "source_lang": "en",
                "target_lang": "zh",
            })
            print("result:", r.content[0].text)

asyncio.run(main())
PY
```

This is the same pattern the Omni_Suite matrix verifier uses (`scripts/mcp_matrix_verifier.py`).

---

## 5. Quick reference — copy-paste recipes

| I want to… | Run |
|---|---|
| Translate a file, keep frontmatter | `ol translate-md in.md -o out/ -s en -t zh` |
| Translate a file, no frontmatter | `ol translate-md in.md -o out/ -s en -t zh --no-frontmatter` |
| Translate a directory | `ol translate-batch ./docs/ -o ./out/ -s en -t zh -j 10` |
| Translate XLIFF | `ol translate-xliff doc.xlf -o ./out/ -s en -t zh` |
| Machine-readable status | add `--json` to any of the above |
| Bypass the cache | add `--no-cache` |
| Use a glossary | add `--glossary glossary.json` |
| Skip glossary injection | add `--no-glossary` |
| Skip placeholder restoration | add `--no-restoration` |
| Clear the cache | add `--clear-cache` (exits after clearing) |
| Run without a real key | `export OMNI_TEST_FAKE_LLM=1` first |
| Run the MCP server | `ol-mcp` (or `python -m ol_mcp`) |
| Test the MCP server | see §4.4 |
| Translate a single text in an agent | call MCP `translate_md_text` with `content`, `source_lang`, `target_lang` |
| Score a translation | call MCP `judge_text` with `source`, `target`, both language codes |
