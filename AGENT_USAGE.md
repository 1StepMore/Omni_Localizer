# Omni-Localizer Agent Usage Guide

## Overview

Omni-Localizer is an AI-native localization pipeline that translates Markdown documents. It now supports agent integration via SKILL.md files for OpenCode and Hermes.

---

## Quick Start

### For Agents

1. **Discover the skill**
   ```
   Look for: src/.opencode/skills/ol-localizer/SKILL.md
   Look for: src/.hermes/skills/ol-localizer/SKILL.md
   ```

2. **Read the SKILL.md** for instructions on how to invoke

3. **Configure API keys** in environment:
   ```
   export ZHIPU_API_KEY=...   # if using Zhipu AI (primary)
   export AGNES_API_KEY=...   # if using Agnes AI (judging)
   export NVIDIA_NIM_API_KEY=... # if using NVIDIA NIM (free-tier)
   export OPENCODE_GO_KEY=...    # if using OpenCode Go (backup)
   export OPENCODE_GO_BASE_URL=...
   ```

4. **Invoke via CLI**:
   ```
   python -m ol_cli translate-md <file.md> -c config/default.yaml -s en -t zh -o output/ --json
   ```

---

## CLI Commands

### Basic Translation

```bash
# Translate Markdown (human-readable output)
python -m ol_cli translate-md input.md -c config/default.yaml -s en -t zh -o output/

# Translate with JSON output (for agents)
python -m ol_cli translate-md input.md -c config/default.yaml -s en -t zh -o output/ --json

# Translate XLIFF
python -m ol_cli translate-xliff input.xlf -c config/default.yaml -s en -t zh -o output/
```

### JSON Output Format

When `--json` is used, output is:
```json
{
  "success": true,
  "input_file": "input.md",
  "output_file": "output/input.md",
  "source_lang": "en",
  "target_lang": "zh"
}
```

On error:
```json
{
  "success": false,
  "error": "Error message here"
}
```

---

## Configuration

### Default Config Location
`config/default.yaml`

### Environment Variables
Set in shell before running:
```bash
export ZHIPU_API_KEY=your-zhipu-key    # required for primary model
export AGNES_API_KEY=your-agnes-key    # required for judging
export NVIDIA_NIM_API_KEY=...          # optional, for free-tier fallback
export OPENCODE_GO_KEY=...             # optional, for backup
export OPENCODE_GO_BASE_URL=...
```

### Config Structure
```yaml
project_id: "your-project"
source_lang: "en"
target_lang: "zh"
llm_pool:
  translation:
    - provider: "openai"
      model: "glm-4-flash"
      priority: 1
      api_key: "${ZHIPU_API_KEY}"
      base_url: "https://open.bigmodel.cn/api/paas/v4"
      role: "translation"
  judging:
    - provider: "openai"
      model: "agnes-2.0-flash"
      priority: 1
      api_key: "${AGNES_API_KEY}"
      base_url: "https://apihub.agnes-ai.com/v1"
      role: "judging"
  restoration:
    - provider: "openai"
      model: "glm-4-flash"
      priority: 1
      api_key: "${ZHIPU_API_KEY}"
      base_url: "https://open.bigmodel.cn/api/paas/v4"
      role: "restoration"
```

---

## Agent Integration

### OpenCode

1. Copy skill to project:
   ```bash
   cp -r src/.opencode/skills/ol-localizer <your-project>/.opencode/skills/
   ```

2. Read `SKILL.md` in that directory for detailed instructions

### Hermes

1. Copy skill to Hermes:
   ```bash
   cp -r src/.hermes/skills/ol-localizer ~/.hermes/skills/
   ```

2. Restart Hermes to activate

---

## Testing

### Run All Skill Tests
```bash
pytest tests/test_opencode_skill.py tests/test_hermes_skill.py tests/test_skill_invocation.py -v
```

### Test Individual Skill
```bash
pytest tests/test_opencode_skill.py -v
pytest tests/test_hermes_skill.py -v
```

### Verify JSON Output
```bash
python -m ol_cli translate-md nonexistent.md -o /tmp/out --json
```

Expected: JSON error output

---

## Common Scenarios

### Scenario 1: Agent Needs to Translate a File

**Agent action:**
1. Read SKILL.md for instructions
2. Check if API keys are set
3. Write source text to temp .md file
4. Run CLI with --json flag
5. Parse JSON response
6. Read translated file from output directory

**Example invocation:**
```bash
# Agent writes temp file
echo "# Hello" > /tmp/test.md

# Agent runs translation
python -m ol_cli translate-md /tmp/test.md -c config/default.yaml -s en -t zh -o /tmp/ --json

# Agent parses JSON output
# Reads /tmp/test.md for translated content
```

### Scenario 2: Agent Wants to Verify Skill is Available

**Agent action:**
```bash
ls src/.opencode/skills/ol-localizer/SKILL.md
ls src/.hermes/skills/ol-localizer/SKILL.md
```

### Scenario 3: Agent Needs to Configure API Keys

**Agent action:**
1. Read SKILL.md Configuration section
2. Set required environment variables:
```bash
export ZHIPU_API_KEY=your-zhipu-key
```

### Scenario 4: Translation Fails

**Agent checks:**
1. JSON output for error message:
```bash
python -m ol_cli translate-md input.md -c config/default.yaml -s en -t zh -o output/ --json 2>/dev/null
```

2. Common fixes:
   - Missing API key → Set `ZHIPU_API_KEY` (or one of the other provider keys)
   - Invalid config → Check `config/default.yaml` exists
   - File not found → Verify input path
   - Rate limit → Wait and retry

### Scenario 5: Agent Wants to Use Different LLM Provider

**Agent action:**
1. Modify `config/default.yaml`:
```yaml
llm_pool:
  translation:
    - provider: "openai"        # or "anthropic", "deepseek", etc.
      model: "gpt-4o"          # or "claude-3-sonnet", etc.
      api_key: "${PROVIDER_API_KEY}"
```

2. Set appropriate API key:
```bash
export PROVIDER_API_KEY=sk-...
```

---

## Troubleshooting

### "No module named ol_cli"

**Cause:** Running without `PYTHONPATH=src`

**Fix:**
```bash
PYTHONPATH=src python -m ol_cli translate-md ...
```

### JSON Output Not Valid

**Cause:** Error occurred before JSON could be generated

**Fix:** Check stderr for error message, fix issue, retry

### Tests Failing

**Agent action:**
```bash
# Run specific failing test
pytest tests/test_opencode_skill.py::TestOpenCodeSkill::test_opencode_skill_exists -v

# Run all tests
pytest tests/test_opencode_skill.py tests/test_hermes_skill.py -v
```

### Skill Not Discovered by Agent

**Agent checks:**
1. File exists:
```bash
ls src/.opencode/skills/ol-localizer/SKILL.md
```

2. YAML frontmatter valid:
```bash
python -c "import yaml; yaml.safe_load(open('src/.opencode/skills/ol-localizer/SKILL.md').read().split('---')[1])"
```

3. Required fields present:
```bash
grep -q "name:" src/.opencode/skills/ol-localizer/SKILL.md
grep -q "description:" src/.opencode/skills/ol-localizer/SKILL.md
```

---

## File Locations

| Component | Path |
|-----------|------|
| OpenCode Skill | `src/.opencode/skills/ol-localizer/SKILL.md` |
| Hermes Skill | `src/.hermes/skills/ol-localizer/SKILL.md` |
| CLI Entry | `src/ol_cli.py` |
| Default Config | `config/default.yaml` |
| Test Helpers | `tests/skill_helpers.py` |
| OpenCode Tests | `tests/test_opencode_skill.py` |
| Hermes Tests | `tests/test_hermes_skill.py` |
| Invocation Tests | `tests/test_skill_invocation.py` |

---

## Key Design Decisions

1. **SKILL.md format** - Universal skill format supported by OpenCode and Hermes
2. **JSON output** - Machine-readable for agent parsing
3. **Environment variables** - API keys never in code or config files
4. **Shell invocation** - Agents invoke via `python -m ol_cli` with CLI arguments
5. **No daemon/server** - Stateless single-shot invocations
6. **Failover** - Multiple LLM providers configured, automatic fallback

---

## Security Notes

- API keys stored in environment, never in code
- `PYTHONPATH=src` required when running from repo root
- Temp files should be cleaned up after use
- No persistent state - each invocation is independent
