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

## Architecture

- **MD Channel**: Token Stream + 4-layer semantic repair
- **XLIFF Channel**: translate-toolkit based
- **LLM Routing**: LiteLLM with model pool failover
- **LQA**: openevalkit Scorer→Judge + COMET
- **TM**: hypomnema (TMX)
- **Alignment**: span-aligner + VectorAlign

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