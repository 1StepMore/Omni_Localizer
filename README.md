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

Create a `.bat` file (gitignored) with your API keys:

```bat
@echo off
set OPENAI_API_KEY=your_api_key
set PYTHONPATH=src
python -m ol_cli translate-md %* -c config/default.yaml -s en -t zh
```

### 3. Run

```cmd
test_en_to_zh.bat your_document.md -o output/
```

## Configuration

`config/default.yaml` — Example LLM pool configuration:

```yaml
llm_pool:
  translation:
    - provider: "openai"
      model: "gpt-4o-mini"
      priority: 1
      api_key: "${OPENAI_API_KEY}"
      role: "translation"
    - provider: "openai"
      model: "gpt-4o"
      priority: 2
      api_key: "${OPENAI_API_KEY}"
      role: "translation"
  judging:
    - provider: "openai"
      model: "gpt-4o-mini"
      priority: 1
      api_key: "${OPENAI_API_KEY}"
      role: "judging"
  restoration:
    - provider: "openai"
      model: "gpt-4o-mini"
      priority: 1
      api_key: "${OPENAI_API_KEY}"
      role: "restoration"
```

## CLI Commands

```bash
# Translate markdown
ol translate-md <file.md> -c <config.yaml> -s en -t zh -o output/

# Translate XLIFF
ol translate-xliff <file.xlf> -c <config.yaml> -s en -t zh -o output/

# Extract warnings from file
ol extract-warnings <file> -o warnings.md
```

## Output Metadata

### YAML Frontmatter (Markdown)

When translating Markdown files, OL automatically adds YAML frontmatter to the output:

```yaml
---
source_lang: en
target_lang: zh
original_file: input.md
processor: "OL"
version: "0.2.0"
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

Batch translate supports the same frontmatter options:

```bash
# With frontmatter (default)
ol translate-batch ./docs/ -s en -t zh -o output/

# Without frontmatter
ol translate-batch ./docs/ -s en -t zh -o output/ --no-frontmatter
```

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

Auto-build glossary from source texts using KeyBERT (with sentence-transformers) or YAKE fallback:

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
pip install -e ".[ml]"  # sentence-transformers + torch
pip install keybert>=0.9.0 yake>=0.5.0
```

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
python -m ol_cli translate-md input.md -c config/default.yaml -s en -t zh -o output/ --json
```

Expected JSON output:
```json
{"success": true, "input_file": "input.md", "output_file": "output/input.md", "source_lang": "en", "target_lang": "zh"}
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