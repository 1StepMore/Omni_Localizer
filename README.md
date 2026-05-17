# Omni-Localizer (OL)

AI-native localization pipeline with automated quality control.

## Quick Start

### 1. Setup Environment

```bash
# Install dependencies (Windows)
.venv\Scripts\pip install torch sentence-transformers

# Or via poetry
poetry install
```

### 2. Configure API Keys

Create `.bat` files with your API keys (gitignored):

```bat
# test_en_to_zh.bat
set MINIMAX_API_KEY=your_minimax_key
set MINIMAX_BASE_URL=https://api.minimaxi.com/v1
set BAIDU_API_KEY=your_baidu_key
set BAIDU_BASE_URL=https://qianfan.baidubce.com/v2
python -m ol_cli translate-md input.md -c config/test_universal.yaml -s en -t zh
```

```bat
# test_zh_to_en.bat
set MINIMAX_API_KEY=your_minimax_key
set MINIMAX_BASE_URL=https://api.minimaxi.com/v1
set BAIDU_API_KEY=your_baidu_key
set BAIDU_BASE_URL=https://qianfan.baidubce.com/v2
python -m ol_cli translate-md input.md -c config/test_universal.yaml -s zh -t en
```

### 3. Run Translation

```cmd
test_en_to_zh.bat your_file.md
```

## Configuration

`config/test_universal.yaml` - Universal LLM pool config (no language pair hardcoded)

Uses MiniMax (priority 1) + Baidu ERNIE (priority 2) for translation, with OpenAI/Anthropic for judging and restoration roles.

API keys use `${VAR}` syntax - set actual values in `.bat` files before running.

## Architecture

- **MD Channel**: Token Stream reconstruction + 4-layer semantic repair
- **XLIFF Channel**: translate-toolkit based
- **LQA**: openevalkit (Scorer→Judge two-layer) + COMET
- **LLM Routing**: LiteLLM with model pool failover
- **TM**: hypomnema (TMX)
- **Alignment**: span-aligner + VectorAlign

## CLI Commands

```bash
# Translate markdown
ol translate-md <file.md> -c <config.yaml> -s <source_lang> -t <target_lang>

# Translate XLIFF
ol translate-xliff <file.xlf> -c <config.yaml> -s <source_lang> -t <target_lang>

# Extract warnings
ol extract-warnings <file> -o <output.md>
```

## Test

```bash
# Windows venv
.venv\Scripts\python.exe -m pytest tests/ -q

# Or via poetry
poetry run pytest
```

## Development Phases

| Phase | Description | Duration |
|-------|-------------|----------|
| M0 | Infrastructure + data structures + mock interfaces | 2.5 days |
| M1 | MD native channel | 3 days |
| M2 | XLIFF channel | 2 days |
| M3a | Routing + model pool + concurrency | 1.5 days |
| M3b | LQA + TM + checkpoint | 1.5 days |
| M4 | UX + E2E + PyPI | 1.5 days |

**Total**: 10 days

## License

MIT