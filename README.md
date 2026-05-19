# Omni-Localizer (OL)

AI-native localization pipeline that translates documents through intelligent LLM routing with built-in quality control.

## What It Does

- **Translate documents** (Markdown, XLIFF) using MiniMax/Baidu ERNIE APIs
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

Create a `.bat` file (gitignored):

```bat
@echo off
set MINIMAX_API_KEY=your_minimax_key
set MINIMAX_BASE_URL=https://api.minimaxi.com/v1
set BAIDU_API_KEY=your_baidu_key
set BAIDU_BASE_URL=https://qianfan.baidubce.com/v2
set PYTHONPATH=src
python -m ol_cli translate-md %* -c config/test_universal.yaml -s en -t zh
```

### 3. Run

```cmd
test_en_to_zh.bat your_document.md -o output/
```

## Configuration

`config/test_universal.yaml` — LLM pool with MiniMax (primary) + Baidu ERNIE (backup):

```yaml
llm_pool:
  translation:
    - provider: "openai"
      model: "MiniMax-M2.7"
      priority: 1
      api_key: "${MINIMAX_API_KEY}"
      base_url: "${MINIMAX_BASE_URL}"
      role: "translation"
    - provider: "openai"
      model: "ernie-4.5-turbo-32k"
      priority: 2
      api_key: "${BAIDU_API_KEY}"
      base_url: "${BAIDU_BASE_URL}"
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

Omni-Localizer can be used as a skill by coding agents (OpenCode, Hermes).

### OpenCode

To use with OpenCode:

1. Add the skill to your project:
   ```
   cp -r src/.opencode/skills/ol-localizer <your-project>/.opencode/skills/
   ```

2. Or reference it in your OpenCode configuration

For detailed usage instructions, see `src/.opencode/skills/ol-localizer/SKILL.md`

### Hermes

To use with Hermes:

1. Copy or symlink the skill:
   ```
   cp -r src/.hermes/skills/ol-localizer ~/.hermes/skills/
   ```

2. Restart Hermes to activate

For detailed usage instructions, see `src/.hermes/skills/ol-localizer/SKILL.md`

### Configuration

Both agents require the following environment variables:

- `MINIMAX_API_KEY` - API key for MiniMax translation service
- `BAIDU_API_KEY` - API key for Baidu ERNIE translation service (backup)

Set these before invoking the skill.

### JSON Output

When used by agents, the CLI should be invoked with the `--json` flag for machine-readable output:

```bash
python -m ol_cli translate-md <file.md> -c config/default.yaml -s en -t zh -o output/ --json
```

## License

MIT