# Omni-Localizer (OL)

AI-native localization pipeline that translates documents through intelligent LLM routing with built-in quality control.

## What It Does

- **Translate documents** (Markdown, XLIFF) using LLM APIs
- **Automatic failover** — switches to backup model if primary fails
- **Quality preservation** — shields code blocks, links, images during translation
- **LLM-based judging** — evaluates translation accuracy and fluency
- **Restoration layer** — uses LLM to restore placeholders after translation

## Quick Start

### 1. Install

```bash
pip install -e .
```

### 2. Configure API Keys

Set the required environment variables in your shell:

```bash
export ZHIPU_API_KEY=your_zhipu_api_key
export PYTHONPATH=src
```

See `.env.example` for the full list of supported provider keys.

### 3. Run

```bash
python -m ol_cli translate-md your_document.md -c config/default.yaml -s en -t zh -o output/
```

## Configuration

## BYOK (Bring Your Own Key) Configuration

OL supports environment variable substitution in `api_key` and `base_url` 
fields using `${ENV_VAR}` syntax. You only need to set env vars for 
providers you actually use.

**Two-layer behavior:**
1. `schema.py:_check_env_vars()` WARNS at startup if a `${VAR}` is unset
2. `router.py:_resolve_env_vars()` **raises `ValueError`** at runtime if a model with an unset var is actually invoked

Set `OMNI_TEST_FAKE_LLM=1` to bypass all env var checks for testing.

`config/default.yaml` — Example LLM pool configuration:

```yaml
llm_pool:
  translation:
    - provider: "openai"
      model: "glm-4-flash"
      priority: 1
      role: "translation"
      api_key: "${ZHIPU_API_KEY}"
      base_url: "https://open.bigmodel.cn/api/paas/v4"
      timeout: 120.0
    - provider: "openai"
      model: "agnes-2.0-flash"
      priority: 2
      role: "translation"
      api_key: "${AGNES_API_KEY}"
      base_url: "https://apihub.agnes-ai.com/v1"
      timeout: 120.0
    - provider: "openai"
      model: "deepseek-ai/deepseek-v4-flash"
      priority: 3
      role: "translation"
      api_key: "${NVIDIA_NIM_API_KEY}"
      base_url: "https://integrate.api.nvidia.com/v1"
      timeout: 120.0
    - provider: "openai"
      model: "moonshotai/kimi-k2.6"
      priority: 4
      role: "translation"
      api_key: "${NVIDIA_NIM_API_KEY}"
      base_url: "https://integrate.api.nvidia.com/v1"
      timeout: 120.0
    - provider: "openai"
      model: "deepseek-v4-flash"
      priority: 5
      role: "translation"
      api_key: "${OPENCODE_GO_KEY}"
      base_url: "${OPENCODE_GO_BASE_URL}"
      timeout: 120.0

  judging:
    - provider: "openai"
      model: "agnes-2.0-flash"
      priority: 1
      role: "judging"
      api_key: "${AGNES_API_KEY}"
      base_url: "https://apihub.agnes-ai.com/v1"
      timeout: 120.0
    - provider: "openai"
      model: "glm-4-flash"
      priority: 2
      role: "judging"
      api_key: "${ZHIPU_API_KEY}"
      base_url: "https://open.bigmodel.cn/api/paas/v4"
      timeout: 120.0
    - provider: "openai"
      model: "deepseek-v4-flash"
      priority: 3
      role: "judging"
      api_key: "${OPENCODE_GO_KEY}"
      base_url: "${OPENCODE_GO_BASE_URL}"
      timeout: 120.0

  restoration:
    - provider: "openai"
      model: "glm-4-flash"
      priority: 1
      role: "restoration"
      api_key: "${ZHIPU_API_KEY}"
      base_url: "https://open.bigmodel.cn/api/paas/v4"
      timeout: 120.0
    - provider: "openai"
      model: "agnes-2.0-flash"
      priority: 2
      role: "restoration"
      api_key: "${AGNES_API_KEY}"
      base_url: "https://apihub.agnes-ai.com/v1"
      timeout: 120.0
    - provider: "openai"
      model: "deepseek-v4-flash"
      priority: 3
      role: "restoration"
      api_key: "${OPENCODE_GO_KEY}"
      base_url: "${OPENCODE_GO_BASE_URL}"
      timeout: 120.0
```

## CLI Commands

```bash
# Translate markdown (single file)
ol translate-md <file.md> -c <config.yaml> -s en -t zh -o output/

# Translate markdown (batch)
ol translate-batch <directory> -c <config.yaml> -s en -t zh -o output/

# Translate XLIFF
ol translate-xliff <file.xlf> -c <config.yaml> -s en -t zh -o output/

# Extract warnings from file
ol extract-warnings <file> -o warnings.md
```

## MCP Tools

For agent-native text-in/text-out translation (no file I/O):

```bash
# Install with MCP support
pip install -e ".[mcp]"

# Run the MCP server (stdio transport)
python -m ol_mcp
# or
ol-mcp
```

| Tool | Description |
|------|-------------|
| `translate_md_text` | Translate markdown text directly |
| `judge_text` | Evaluate translation quality |
| `load_glossary` | Load a JSON glossary file |
| `get_relevant_terms` | Extract relevant terms from text |
| `search_tm` | Search translation memory |
| `batch_translate_texts` | Batch translate multiple texts in parallel |

**Example usage** (in an MCP-capable agent):

```
Tool: translate_md_text
Parameters:
  content: "# Hello World\nThis is a test."
  source_lang: "en"
  target_lang: "zh"
```

## Output Metadata

### YAML Frontmatter (Markdown)

When translating Markdown files, OL automatically adds YAML frontmatter to the output by default:

```yaml
---
source_lang: en
target_lang: zh
original_file: input.md
processor: "OL"
version: "0.2.3"
translated_at: 2026-05-22T15:00:00Z
---

# Content follows...
```

**CLI Control:**

```bash
# Enable frontmatter (default)
ol translate-md input.md -s en -t zh -o output/

# Disable frontmatter
ol translate-md input.md -s en -t zh -o output/ --no-frontmatter
```

### XLIFF Header Note

When translating XLIFF files, OL adds a header note with translation metadata:

```xml
<?xml version="1.0" encoding="utf-8"?>
<xliff version="1.2" xmlns="urn:oasis:names:tc:xliff:document:1.2">
  <header>
    <note from="OL">Translated from en to zh by OL</note>
  </header>
  <file original="input.xlf" source-language="en" target-language="zh">
    ...
  </file>
</xliff>
```

### Batch Processing

Batch translate multiple files with the `translate-batch` command:

```bash
# Translate all markdown files in a directory (frontmatter enabled by default)
ol translate-batch ./docs/ -s en -t zh -o output/

# Disable frontmatter
ol translate-batch ./docs/ -s en -t zh -o output/ --no-frontmatter

# Control concurrency (default: 5)
ol translate-batch ./docs/ -s en -t zh -o output/ --concurrency 10

# Skip language detection (translate all files)
ol translate-batch ./docs/ -s en -t zh -o output/ --no-detect-language

# Machine-readable output for agents
ol translate-batch ./docs/ -s en -t zh -o output/ --json
```

**Language detection**: When `--detect-language` (default), files already in target language are skipped automatically with `skipped: true` frontmatter metadata.

## Key Features

| Feature | Description |
|---------|-------------|
| **Model Pool Failover** | LiteLLM router with primary + backup models per role |
| **Content Shielding** | Code blocks, links, images preserved during translation |
| **4-Layer Repair** | Regex → Span alignment → LLM restoration → Safe fallback |
| **Translation + Judging** | JudgeService evaluates quality (adequacy, fluency, terminology) |
| **TM Integration** | hypomnema for translation memory lookups |
| **TM/TB/SG Automation** | Pre-injection of TM matches + glossary terms for context-aware translation |
| **Term Disambiguation** | LLM-based polyseme resolution with confidence fallback |
| **QA Rules Subset** | translate-toolkit pofilter rules (accelerators, brackets, printf, variables, xmltags) |

## Quality Assurance & Robustness

Omni-Localizer now ships with **automatic LQA (Linguistic Quality Assurance)** in the CLI pipeline. When enabled via config, every translation produced by `translate-md` or `translate-xliff` is judged by a `JudgeService` against the original source; if the score falls below `lqa_threshold` (default `7.0` on a 1-10 scale), the translation is retried up to `lqa_max_retries` times (default `2`) through a `RetryManager`. This makes the CLI self-correcting on the common "LLM produced a low-quality first pass" failure mode without requiring manual review.

Opt-in via three new fields on `ProjectConfig` (see `config/default.yaml` for an example):

```yaml
enable_lqa: true        # master switch (default: false)
lqa_threshold: 7.0      # minimum acceptable score
lqa_max_retries: 2      # max retry attempts
```

Robustness against **real LLM output quirks**: `write_target_back()` in the XLIFF bus now applies an `_escape_xml_entities()` helper to LLM-produced target text **before** placeholder restoration. Real LLMs occasionally emit unescaped `&`, `<`, or `>` (e.g., `R&D`, `AT&T`) that would otherwise cause `lxml.etree.XMLSyntaxError: xmlParseEntityRef: no name` on round-trip. This change unblocks the real-LLM nightly test that was previously crashing on the LQA judge path.

## Post-Processing (Punctuation Normalizer)

For the zh↔en direction, the MD translator runs a deterministic post-processing step after repair, before the output file is written:

```python
from ol_post.punctuation import normalize_to_english, normalize_to_chinese
```

| Function | Maps | Direction |
|---|---|---|
| `normalize_to_english(text)` | Full-width Chinese punctuation → ASCII | zh→en |
| `normalize_to_chinese(text)` | ASCII `,.;:""''` → Chinese equivalents | en→zh |

Implemented with `str.maketrans` for O(1) per-character translation (no regex, no LLM call, zero API cost). Wired into `_translate_md_async` in `src/ol_cli.py` and dispatched on `tgt_lang` prefix. Resolves the 82/1865-char (4.4%) Chinese punctuation contamination previously observed in English-mode output, and the symmetric ASCII-in-Chinese problem in the en→zh direction.

## Architecture

- **MD Channel**: Token Stream + 4-layer semantic repair
- **XLIFF Channel**: translate-toolkit based
- **LLM Routing**: LiteLLM with model pool failover
- **LQA**: openevalkit Scorer→Judge + COMET
- **TM**: hypomnema (TMX)
- **Alignment**: span-aligner + VectorAlign
- **TM/TB/SG Automation**: Plan B pre-injection (query TM/glossary before translate(), inject into prompt)

## TM/TB/SG Automation (MVP Phase 1)

Omni-Localizer supports agent-native translation memory and terminology workflows for higher-quality, consistent translations.

### Glossary Format

JSON glossary with nested structure:

```json
{
  "API endpoint": {
    "translation": "API 端点",
    "variants": {"API endpoint": "API 端点", "API endpoints": "API 端点"},
    "confidence": 0.95
  }
}
```

### Translation Memory + Glossary Injection

When `BatchProcessor` is initialized with a `tm_service` and `glossary`:

1. TM lookup: `TMService.search()` queries source text against TMX translation memory
2. Top-3 matches (threshold 0.85) are selected
3. Relevant glossary terms are extracted via `get_relevant_terms()` (top-5, relevance-selected, not random)
4. `build_translate_prompt()` pre-injects context into the LLM prompt

### Terminology Extraction

Auto-build glossary from source texts using YAKE:

```python
from ol_terminology.extractor import extract_terms
terms = extract_terms(["source text 1", "source text 2"])
# Returns dict[str, float]: term -> importance_score
```

### Term Disambiguation

Resolve polysemous terms with LLM-based context understanding:

```python
from ol_terminology.disambiguator import disambiguate
resolved = disambiguate(text, glossary, model_pool=model_pool)
# Returns dict[str, str]: term -> resolved_translation
```

### QA Rules Subset

Run a focused set of translate-toolkit pofilter checks:

```python
from ol_lqa.qa_rules import check_pair, QAWarning
warnings = check_pair(source, target)
# Selected rules: accelerators, brackets, printf, variables, xmltags
```

### Graceful Degradation

If TM service or glossary is unavailable, translation proceeds without context injection—no blocking errors.

### Dependencies

TM/TB/SG features require additional packages:

```bash
pip install -e ".[ml]"  # sentence-transformers + torch + yake
```

> **Python 3.13 note**: `sentence-transformers` (via its `transformers`
> dependency) may hang on import in Python 3.13 due to a circular import
> in `regex._regex`. If you hit this:
> - Set `TRANSFORMERS_OFFLINE=1` and `HF_HUB_OFFLINE=1` as workarounds, OR
> - Use Python 3.12 for ML features (the suite as a whole still requires 3.13+
>   for OPP/ORF/CLI, but TM/terminology features can run on 3.12 in an isolated
>   venv).
>
> See `CHANGELOG.md` (entry mentioning `import transformers` hang) for details.

## Pipeline — Omni Localization Suite

OL is **Step 2** of the Omni Localization Suite pipeline:

```
┌────────────────────────────────────────────────────────────────────────┐
│                     OMNI LOCALIZATION SUITE                             │
│                                                                        │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐               │
│  │     OPP     │───▶│     OL      │───▶│     ORF      │               │
│  │  (提取)     │    │   (翻译)    │    │   (回写)    │               │
│  └─────────────┘    └─────────────┘    └─────────────┘               │
│                                                                        │
│  Step 1: OPP        Step 2: OL            Step 3: ORF                  │
│  Extract →          Translate →           Backfill →                  │
│  MD + XLIFF +       MD + XLIFF            DOCX/PPTX                   │
│  skeleton.zip                                                    │
└────────────────────────────────────────────────────────────────────────┘
```

### Complete Workflow

```bash
# Step 1: OPP - Extract document to MD/XLIFF + skeleton.zip
opp --target-format=both --source-lang=en --target-lang=zh document.docx

# Step 2: OL - Translate to target language ← YOU ARE HERE
ol translate-md document.md -s en -t zh -o translated/

# Step 3: ORF - Backfill translated content to target format
orf apply-xliff document.docx --xliff translated/document.xlf --output result.docx
```

## Related Projects

- [OPP (Omni-Pre-Processor)](https://github.com/1StepMore/Omni_Pre_Processor) - **PREREQUISITE**. Produces MD/XLIFF that OL translates.
- [ORF (Omni-Re-Formatter)](https://github.com/1StepMore/Omni_Re_Formatter) - **NEXT STEP**. Backfills OL's translated MD/XLIFF to DOCX/PPTX.

## For AI Agents

OL processes artifacts from OPP and outputs for ORF:

| Input (from OPP) | Output (to ORF) |
|------------------|-----------------|
| `{name}.md` | `translated_{name}.md` (with YAML frontmatter) |
| `{name}.xlf` | `translated_{name}.xlf` (with `<target>` filled) |

**SKILL.md Available:** `src/.opencode/skills/ol-localizer/SKILL.md` for OpenCode agents.

## Agent Usage

Omni-Localizer can be used as a **skill** by coding agents (OpenCode, Hermes). Agents read the SKILL.md file to understand how to invoke translation.

### OpenCode

1. Add the skill to your project:
   ```bash
   cp -r src/.opencode/skills/ol-localizer <your-project>/.opencode/skills/
   ```

2. Reference it in your OpenCode configuration if needed

For detailed usage, see `src/.opencode/skills/ol-localizer/SKILL.md`

### Hermes

1. Copy or symlink the skill:
   ```bash
   cp -r src/.hermes/skills/ol-localizer ~/.hermes/skills/
   ```

2. Restart Hermes to activate

For detailed usage, see `src/.hermes/skills/ol-localizer/SKILL.md`

### Environment Variables

Configure your LLM provider API keys in your shell environment.

### Testing the Agent Integration

**Verify skill files exist:**
```bash
ls src/.opencode/skills/ol-localizer/SKILL.md
ls src/.hermes/skills/ol-localizer/SKILL.md
```

**Test JSON output (machine-readable for agents):**
```bash
# Single file
python -m ol_cli translate-md input.md -c config/default.yaml -s en -t zh -o output/ --json

# Batch (agents can parse summary from output)
python -m ol_cli translate-batch ./docs/ -c config/default.yaml -s en -t zh -o output/ --json
```

Expected JSON output (single):
```json
{"success": true, "input_file": "input.md", "output_file": "output/input.md", "source_lang": "en", "target_lang": "zh"}
```

Expected JSON output (batch):
```json
{"success": true, "duration_seconds": 12.5, "total_files": 10, "succeeded": 9, "failed": 1}
```

**Run skill tests:**
```bash
pytest tests/test_opencode_skill.py tests/test_hermes_skill.py -v
```

**Verify --json flag in help:**
```bash
python -m ol_cli translate-md --help | grep json
```

## License

MIT