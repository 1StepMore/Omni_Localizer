# Omni-Localizer Agent-Facing Skill Plan

## TL;DR

> **Quick Summary**: Transform Omni-Localizer from a human-facing CLI tool to also be an agent-facing skill for OpenCode and Hermes coding agents.
>
> **Deliverables**:
> - `--json` flag added to CLI for machine-parseable output
> - SKILL.md for OpenCode (`.opencode/skills/ol-localizer/SKILL.md`)
> - SKILL.md for Hermes (`~/.hermes/skills/ol-localizer/SKILL.md`)
> - Test suite for skill discovery and invocation
>
> **Estimated Effort**: Medium
> **Parallel Execution**: YES - 3 waves
> **Critical Path**: Task 1 (JSON output) → Task 4 (OpenCode skill) → Task 6 (Verification)

---

## Context

### Original Request
User wants Omni_Localizer to be usable by coding agents (OpenCode, Hermes) in addition to being a human-facing CLI tool.

### Interview Summary

**Key Discussions**:
- Target agents: Hermes and OpenCode first
- Interface type: SKILL.md (instruction-based) chosen over tool registration for simplicity
- API key handling: Agent manages keys (environment variables) - safer approach
- Input mechanism: Temp file approach - agent writes text to temp .md file, CLI processes it
- Output format: CLI will get `--json` flag for structured machine-parseable output
- Scope: Minimal v1 - single-string Markdown translation only, no batch, no XLIFF

**Research Findings**:
- OpenCode: Skills in `.opencode/skills/<name>/SKILL.md` (also `.claude/skills/`, `.agents/skills/`)
- Hermes: Skills in `~/.hermes/skills/` with YAML frontmatter + markdown
- Both follow AgentSkills.io SKILL.md format standard
- Environment variables are safer for API keys (no logging, no context exposure)

### Metis Review

**Identified Gaps** (addressed):
- CLI lacked JSON output mode → Task 1 adds `--json` flag
- Communication pattern unclear → Temp file approach chosen
- API key injection undefined → Agent manages keys pattern adopted
- Scope needed bounding → Minimal v1 agreed

---

## Work Objectives

### Core Objective
Enable coding agents (OpenCode, Hermes) to use Omni-Localizer as a skill for translating Markdown documents.

### Concrete Deliverables
- [ ] `ol translate-md --json` - JSON output mode for machine parsing
- [ ] `src/.opencode/skills/ol-localizer/SKILL.md` - OpenCode skill
- [ ] `~/.hermes/skills/ol-localizer/SKILL.md` - Hermes skill
- [ ] Tests verifying skill discovery and basic invocation

### Definition of Done
- [ ] OpenCode can discover and invoke the skill
- [ ] Hermes can discover and invoke the skill
- [ ] Translation returns valid JSON with translated text
- [ ] Existing CLI tests still pass (backward compatible)

### Must Have
- JSON output mode for structured results
- SKILL.md files with proper YAML frontmatter
- Environment variable API key handling (existing ${VAR} pattern)
- Error handling with machine-parseable error messages

### Must NOT Have (Guardrails)
- CLI source code modifications beyond adding `--json` flag
- Batch translation support (separate future work)
- XLIFF translation support (separate future work)
- Daemon/server mode (separate future work)
- Skill caching layer (separate future work)

---

## Verification Strategy

### Test Decision
- **Infrastructure exists**: YES
- **Automated tests**: YES (existing pytest)
- **Framework**: pytest (existing)
- **Strategy**: Tests-after - add verification tests after implementation

### QA Policy
Every task includes agent-executed QA scenarios. Evidence saved to `.sisyphus/evidence/`.

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (Foundation - JSON output + skill structure):
├── Task 1: Add --json flag to CLI translate commands
├── Task 2: Create OpenCode skill directory structure
├── Task 3: Create Hermes skill directory structure
└── Task 4: Add error handling for JSON mode

Wave 2 (Skill Content - SKILL.md files):
├── Task 5: Write OpenCode SKILL.md content
├── Task 6: Write Hermes SKILL.md content
└── Task 7: Create skill verification test helper

- [ ] 8. Add skill discovery tests

  **What to do**:
  - Create `tests/test_opencode_skill.py` with:
    - `test_opencode_skill_exists()` - verifies `.opencode/skills/ol-localizer/SKILL.md` exists
    - `test_opencode_skill_frontmatter_valid()` - parses YAML frontmatter, checks required fields
    - `test_opencode_skill_has_required_sections()` - checks Procedure, Pitfalls, Verification sections exist
  - Create `tests/test_hermes_skill.py` with similar tests for Hermes skill
  - Use skill_helpers.py from Task 7

  **Must NOT do**:
  - Don't test actual translation (Task 9)
  - Don't test CLI behavior (existing tests cover this)
  - Don't add integration tests with real API calls

  **Recommended Agent Profile**:
  > **Category**: `unspecified-high` - Testing requires understanding of full system
  > **Reason**: Writing tests requires understanding test infrastructure
  > **Skills**: None required

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (with Tasks 9, 10)
  - **Blocks**: Final verification (F1-F4)
  - **Blocked By**: Tasks 5, 6, 7

  **References**:
  - `tests/test_ol_cli.py` - existing test patterns to follow
  - `tests/conftest.py` - pytest configuration
  - `tests/skill_helpers.py` - helper functions from Task 7

  **Acceptance Criteria**:
  - [ ] `pytest tests/test_opencode_skill.py -v` passes
  - [ ] `pytest tests/test_hermes_skill.py -v` passes
  - [ ] All existing tests still pass

  **QA Scenarios**:

  \`\`\`
  Scenario: OpenCode skill tests pass
    Tool: Bash
    Preconditions: Tasks 5, 7 complete
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && python -m pytest tests/test_opencode_skill.py -v
    Expected Result: All tests pass
    Failure Indicators: Test failures, import errors
    Evidence: .sisyphus/evidence/task-8-opencode-tests.txt

  Scenario: Hermes skill tests pass
    Tool: Bash
    Preconditions: Tasks 6, 7 complete
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && python -m pytest tests/test_hermes_skill.py -v
    Expected Result: All tests pass
    Failure Indicators: Test failures, import errors
    Evidence: .sisyphus/evidence/task-8-hermes-tests.txt

  Scenario: Existing tests still pass
    Tool: Bash
    Preconditions: All tasks complete
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && python -m pytest tests/test_ol_cli.py -v
    Expected Result: All existing tests pass
    Failure Indicators: Regression in CLI behavior
    Evidence: .sisyphus/evidence/task-8-existing-tests.txt
  \`\`\`

  **Commit**: YES
  - Message: `test(skills): add skill discovery tests`
  - Files: `tests/test_opencode_skill.py`, `tests/test_hermes_skill.py`
  - Pre-commit: `pytest tests/test_opencode_skill.py tests/test_hermes_skill.py -v`

- [ ] 9. Add skill invocation tests

  **What to do**:
  - Create `tests/test_skill_invocation.py` with:
    - `test_cli_json_output_format()` - verifies JSON output has all required fields
    - `test_cli_json_error_format()` - verifies error JSON has success:false and error field
    - `test_skill_translation_flow()` - integration test: write temp file → invoke CLI → parse JSON → verify output file exists
  - Use unittest.mock if needed to avoid real API calls

  **Must NOT do**:
  - Don't make real API calls (use mocks or skip if API not configured)
  - Don't test rate limiting or timeout behavior (future work)
  - Don't test concurrent invocation (future work)

  **Recommended Agent Profile**:
  > **Category**: `unspecified-high` - Testing requires understanding of full system
  > **Reason**: Integration testing requires understanding CLI and file system
  > **Skills**: None required

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (with Tasks 8, 10)
  - **Blocks**: Final verification (F1-F4)
  - **Blocked By**: Tasks 5, 6, 7

  **References**:
  - `tests/test_ol_cli.py` - existing CLI test patterns
  - `tests/skill_helpers.py` - helper functions from Task 7
  - `tests/conftest.py` - temp file fixtures if any

  **Acceptance Criteria**:
  - [ ] `pytest tests/test_skill_invocation.py -v` passes
  - [ ] JSON output tests verify all required fields
  - [ ] Error JSON tests verify proper error structure

  **QA Scenarios**:

  \`\`\`
  Scenario: JSON output format test
    Tool: Bash
    Preconditions: Task 1 complete
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && python -m pytest tests/test_skill_invocation.py::test_cli_json_output_format -v
    Expected Result: Test passes
    Failure Indicators: Missing fields in JSON output
    Evidence: .sisyphus/evidence/task-9-json-format.txt

  Scenario: Skill translation flow test
    Tool: Bash
    Preconditions: Tasks 1, 7 complete
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && python -m pytest tests/test_skill_invocation.py::test_skill_translation_flow -v
    Expected Result: Test passes or skips with clear reason
    Failure Indicators: Test fails due to missing implementation
    Evidence: .sisyphus/evidence/task-9-flow.txt
  \`\`\`

  **Commit**: YES
  - Message: `test(skills): add skill invocation integration tests`
  - Files: `tests/test_skill_invocation.py`
  - Pre-commit: `pytest tests/test_skill_invocation.py -v`

- [ ] 10. Update project README with agent usage

  **What to do**:
  - Add new section to README.md: "## Agent Usage" or "## Using with Coding Agents"
  - Include subsections for:
    - **OpenCode**: "To use with OpenCode, add the skill: .opencode/skills/ol-localizer/"
    - **Hermes**: "To use with Hermes, copy .hermes/skills/ol-localizer/ to ~/.hermes/skills/"
  - Include environment setup instructions (API keys)
  - Link to SKILL.md files for detailed usage
  - Keep existing "Human Usage" section unchanged

  **Must NOT do**:
  - Don't modify existing CLI usage instructions
  - Don't add agent-specific internals (implementation details)
  - Don't make up agent-specific compatibility claims

  **Recommended Agent Profile**:
  > **Category**: `writing` - Documentation update
  > **Reason**: Updating README is documentation work
  > **Skills**: None required

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (with Tasks 8, 9)
  - **Blocks**: Final verification (F1-F4)
  - **Blocked By**: Tasks 5, 6 (need SKILL.md content to reference)

  **References**:
  - `README.md` - existing structure to follow
  - `src/.opencode/skills/ol-localizer/SKILL.md` - to reference
  - `src/.hermes/skills/ol-localizer/SKILL.md` - to reference

  **Acceptance Criteria**:
  - [ ] README has new "Agent Usage" section
  - [ ] Section includes OpenCode setup instructions
  - [ ] Section includes Hermes setup instructions
  - [ ] Section includes API key requirements
  - [ ] Existing content unchanged

  **QA Scenarios**:

  \`\`\`
  Scenario: README has Agent Usage section
    Tool: Bash
    Preconditions: Task 10 complete
    Steps:
      1. grep -A20 "Agent Usage" README.md
    Expected Result: Section exists with content
    Failure Indicators: Section missing, empty
    Evidence: .sisyphus/evidence/task-10-agent-section.txt

  Scenario: Existing content unchanged
    Tool: Bash
    Preconditions: Task 10 complete
    Steps:
      1. grep "Quick Start" README.md
      2. grep "CLI Commands" README.md
    Expected Result: Original sections still present
    Failure Indicators: Original sections removed or modified
    Evidence: .sisyphus/evidence/task-10-existing.txt
  \`\`\`

  **Commit**: YES
  - Message: `docs: add agent usage section to README`
  - Files: `README.md`

---

## Final Verification Wave

Wave FINAL (Verification - 4 parallel reviews):
├── Task F1: Plan compliance audit (oracle)
├── Task F2: Code quality review
├── Task F3: Real manual QA
└── Task F4: Scope fidelity check
```

### Dependency Matrix

| Task | Depends On | Blocks | Category |
|------|-----------|--------|----------|
| 1 | - | 4, 5, 6 | quick |
| 2 | - | 5 | quick |
| 3 | - | 6 | quick |
| 4 | 1 | 5, 6 | quick |
| 5 | 1, 2, 4 | 8, 9 | writing |
| 6 | 1, 3, 4 | 8, 9 | writing |
| 7 | 1 | 8, 9 | quick |
| 8 | 5, 6, 7 | F1-F4 | unspecified-high |
| 9 | 5, 6, 7 | F1-F4 | unspecified-high |
| 10 | 8, 9 | F1-F4 | writing |
| F1 | 8, 9, 10 | - | oracle |
| F2 | 8, 9, 10 | - | unspecified-high |
| F3 | 8, 9, 10 | - | unspecified-high |
| F4 | 8, 9, 10 | - | deep |

### Agent Dispatch Summary

- **Wave 1**: **4 tasks** - T1 → `quick`, T2 → `quick`, T3 → `quick`, T4 → `quick`
- **Wave 2**: **3 tasks** - T5 → `writing`, T6 → `writing`, T7 → `quick`
- **Wave 3**: **3 tasks** - T8 → `unspecified-high`, T9 → `unspecified-high`, T10 → `writing`
- **FINAL**: **4 tasks** - F1 → `oracle`, F2 → `unspecified-high`, F3 → `unspecified-high`, F4 → `deep`

---

## TODOs

- [ ] 1. Add --json flag to CLI translate commands

  **What to do**:
  - Modify `src/ol_cli.py` to add `--json` flag to `translate-md`, `translate-xliff`, and `translate-batch` commands
  - When `--json` is passed, output structured JSON instead of human-readable text
  - JSON output should include: `success`, `input_file`, `output_file`, `source_lang`, `target_lang`, `error` (if any), `translation` (if applicable)
  - Keep human-readable output as default when `--json` is not specified
  - Ensure Typer's `--help` still works normally

  **Must NOT do**:
  - Modify translation logic - only output formatting
  - Break existing CLI behavior for non-JSON mode
  - Add new dependencies

  **Recommended Agent Profile**:
  > **Category**: `quick` - Simple CLI modification, single file change
  > **Reason**: Adding a flag to existing commands is straightforward modification
  > **Skills**: `git-master` - For safe commit after
  > - `git-master`: Commit messages follow repo convention

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 2, 3, 4)
  - **Blocks**: Tasks 5, 6 (skills depend on JSON output)
  - **Blocked By**: None (can start immediately)

  **References**:
  - `src/ol_cli.py:105-157` - translate-md command structure to follow
  - `src/ol_cli.py:39-44` - ExitCode class for status codes
  - `src/ol_cli.py:54-66` - validate_input_file, ensure_output_dir helpers
  - Typer docs: `--json` flag patterns for inspiration

  **Acceptance Criteria**:
  - [ ] `python -m ol_cli translate-md input.md -o output/ --json` outputs JSON to stdout
  - [ ] JSON is valid and contains: `success`, `input_file`, `output_file`
  - [ ] Human-readable mode (without --json) still works unchanged
  - [ ] `python -m ol_cli translate-md --help` shows --json in help text

  **QA Scenarios**:

  \`\`\`
  Scenario: JSON output mode produces valid JSON
    Tool: Bash
    Preconditions: input.md exists with simple content
    Steps:
      1. python -m ol_cli translate-md input.md -c config/default.yaml -s en -t zh -o output/ --json > /tmp/result.json
      2. python -c "import json; json.load(open('/tmp/result.json'))"
    Expected Result: No exception, valid JSON parsed
    Failure Indicators: JSONDecodeError, KeyError on missing fields
    Evidence: .sisyphus/evidence/task-1-json-valid.json

  Scenario: JSON output contains required fields
    Tool: Bash
    Preconditions: input.md exists
    Steps:
      1. python -m ol_cli translate-md input.md -c config/default.yaml -s en -t zh -o output/ --json > /tmp/result.json
      2. python -c "import json; d=json.load(open('/tmp/result.json')); assert 'success' in d and 'input_file' in d"
    Expected Result: All required fields present
    Failure Indicators: Missing fields in JSON output
    Evidence: .sisyphus/evidence/task-1-json-fields.json

  Scenario: Non-JSON mode unchanged
    Tool: Bash
    Preconditions: input.md exists
    Steps:
      1. python -m ol_cli translate-md input.md -c config/default.yaml -s en -t zh -o output/ 2>&1 | head -1
    Expected Result: Human-readable output (not JSON), contains "Translated:"
    Failure Indicators: JSON appearing in output, missing "Translated:" text
    Evidence: .sisyphus/evidence/task-1-human-readable.txt
  \`\`\`

  **Commit**: YES
  - Message: `feat(cli): add --json flag for machine-readable output`
  - Files: `src/ol_cli.py`
  - Pre-commit: `pytest tests/test_ol_cli.py -v`

- [ ] 2. Create OpenCode skill directory structure

  **What to do**:
  - Create directory: `src/.opencode/skills/ol-localizer/`
  - Create directory: `src/.opencode/skills/ol-localizer/scripts/` (for future use)
  - Create directory: `src/.opencode/skills/ol-localizer/references/` (for future use)
  - Copy original SKILL.md to this location after content is written (Task 5)
  - Placeholder: create empty SKILL.md with just frontmatter for now

  **Must NOT do**:
  - Don't create actual skill content yet (Task 5)
  - Don't modify any existing source code
  - Don't create .gitignore entries (opencode directory is project-local)

  **Recommended Agent Profile**:
  > **Category**: `quick` - Simple directory creation
  > **Reason**: Pure scaffolding, no code changes
  > **Skills**: None required

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1, 3, 4)
  - **Blocks**: Task 5 (skill content)
  - **Blocked By**: None

  **References**:
  - OpenCode skill structure: `.opencode/skills/<name>/SKILL.md`

  **Acceptance Criteria**:
  - [ ] Directory `src/.opencode/skills/ol-localizer/` exists
  - [ ] Directory `src/.opencode/skills/ol-localizer/scripts/` exists
  - [ ] Directory `src/.opencode/skills/ol-localizer/references/` exists
  - [ ] Placeholder SKILL.md exists with valid YAML frontmatter

  **QA Scenarios**:

  \`\`\`
  Scenario: Directory structure created correctly
    Tool: Bash
    Preconditions: None
    Steps:
      1. ls -la src/.opencode/skills/ol-localizer/
      2. ls -la src/.opencode/skills/ol-localizer/scripts/
      3. ls -la src/.opencode/skills/ol-localizer/references/
    Expected Result: All directories exist
    Failure Indicators: Directory not found errors
    Evidence: .sisyphus/evidence/task-2-dirs.txt

  Scenario: Placeholder SKILL.md has valid frontmatter
    Tool: Bash
    Preconditions: None
    Steps:
      1. head -10 src/.opencode/skills/ol-localizer/SKILL.md
    Expected Result: YAML frontmatter with name and description fields
    Failure Indicators: Invalid YAML, missing required fields
    Evidence: .sisyphus/evidence/task-2-frontmatter.txt
  \`\`\`

  **Commit**: YES
  - Message: `feat(skills): add OpenCode skill directory structure`
  - Files: `src/.opencode/skills/` (new directories)

- [ ] 3. Create Hermes skill directory structure

  **What to do**:
  - Create directory: `src/.hermes/skills/ol-localizer/` (note: Hermes uses ~/.hermes/skills/ at runtime, but we create src/.hermes/ as the source; actual deployment will copy or symlink)
  - Create directory: `src/.hermes/skills/ol-localizer/scripts/`
  - Create directory: `src/.hermes/skills/ol-localizer/references/`
  - Placeholder: create empty SKILL.md with frontmatter
  - Create a README in this directory explaining Hermes skill installation (copy to ~/.hermes/skills/)

  **Must NOT do**:
  - Don't create actual skill content yet (Task 6)
  - Don't modify Hermes source or config
  - Don't assume ~/.hermes/ exists on the system

  **Recommended Agent Profile**:
  > **Category**: `quick` - Simple directory creation
  > **Reason**: Pure scaffolding, no code changes
  > **Skills**: None required

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1, 2, 4)
  - **Blocks**: Task 6 (skill content)
  - **Blocked By**: None

  **References**:
  - Hermes skill structure: `~/.hermes/skills/<name>/SKILL.md`
  - Hermes skills use same AgentSkills.io format as OpenCode

  **Acceptance Criteria**:
  - [ ] Directory `src/.hermes/skills/ol-localizer/` exists
  - [ ] Directory `src/.hermes/skills/ol-localizer/scripts/` exists
  - [ ] Directory `src/.hermes/skills/ol-localizer/references/` exists
  - [ ] Placeholder SKILL.md exists with valid YAML frontmatter
  - [ ] README.md explains installation to ~/.hermes/skills/

  **QA Scenarios**:

  \`\`\`
  Scenario: Directory structure created correctly
    Tool: Bash
    Preconditions: None
    Steps:
      1. ls -la src/.hermes/skills/ol-localizer/
      2. ls -la src/.hermes/skills/ol-localizer/scripts/
    Expected Result: All directories exist
    Failure Indicators: Directory not found
    Evidence: .sisyphus/evidence/task-3-dirs.txt

  Scenario: README explains installation
    Tool: Bash
    Preconditions: None
    Steps:
      1. cat src/.hermes/skills/ol-localizer/README.md | head -20
    Expected Result: Instructions for copying/symlinking to ~/.hermes/skills/
    Failure Indicators: README missing or has wrong path
    Evidence: .sisyphus/evidence/task-3-readme.txt
  \`\`\`

  **Commit**: YES
  - Message: `feat(skills): add Hermes skill directory structure`
  - Files: `src/.hermes/skills/` (new directories)

- [ ] 4. Add error handling for JSON mode

  **What to do**:
  - Ensure all CLI commands handle errors gracefully in JSON mode
  - When `--json` flag is set, errors should output JSON with `success: false` and `error: "<message>"`
  - Ensure exit codes are set correctly (don't exit 0 on error even in JSON mode)
  - Test: invalid input file, missing config, API failure

  **Must NOT do**:
  - Don't change error handling for non-JSON mode
  - Don't catch exceptions that should propagate
  - Don't suppress error details in JSON mode

  **Recommended Agent Profile**:
  > **Category**: `quick` - Small targeted changes to error output formatting
  > **Reason**: Adding JSON error output is similar to Task 1
  > **Skills**: `git-master` - Commit after

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1, 2, 3)
  - **Blocks**: Tasks 5, 6
  - **Blocked By**: Task 1 (needs --json flag to exist)

  **References**:
  - `src/ol_cli.py:39-44` - ExitCode class
  - `src/ol_cli.py:54-66` - validate_input_file error handling
  - `src/ol_cli.py:154-157` - error handling pattern in translate-md

  **Acceptance Criteria**:
  - [ ] `ol translate-md nonexistent.md --json` returns JSON with success:false
  - [ ] `ol translate-md input.md -c nonexistent.yaml --json` returns JSON with success:false
  - [ ] Error JSON includes `error` field with meaningful message
  - [ ] Non-JSON error output unchanged

  **QA Scenarios**:

  \`\`\`
  Scenario: Invalid input file returns error JSON
    Tool: Bash
    Preconditions: None
    Steps:
      1. python -m ol_cli translate-md nonexistent.md -o output/ --json 2>/dev/null > /tmp/err.json
      2. python -c "import json; d=json.load(open('/tmp/err.json')); assert d['success'] == False; assert 'error' in d"
    Expected Result: JSON with success:false and error field
    Failure Indicators: Exit code 0, missing error field, raw error message
    Evidence: .sisyphus/evidence/task-4-invalid-input.json

  Scenario: Missing config returns error JSON
    Tool: Bash
    Preconditions: None
    Steps:
      1. python -m ol_cli translate-md input.md -c /nonexistent.yaml -o output/ --json 2>/dev/null > /tmp/err.json
      2. python -c "import json; d=json.load(open('/tmp/err.json')); assert d['success'] == False"
    Expected Result: JSON with success:false
    Failure Indicators: Exit code 0, missing error field
    Evidence: .sisyphus/evidence/task-4-missing-config.json
  \`\`\`

  **Commit**: YES
  - Message: `fix(cli): ensure JSON mode outputs proper error structure`
  - Files: `src/ol_cli.py`
  - Pre-commit: `pytest tests/test_ol_cli.py -v`

- [ ] 5. Write OpenCode SKILL.md content

  **What to do**:
  - Write comprehensive SKILL.md for OpenCode in `src/.opencode/skills/ol-localizer/SKILL.md`
  - Include proper YAML frontmatter with:
    - name: ol-localizer
    - description: Translate Markdown documents using AI (100-200 chars)
    - metadata section with any agent-specific hints
  - Write clear "When to Use" section explaining when an agent should invoke this skill
  - Write "Procedure" section with exact steps:
    1. Agent writes source text to a temporary .md file
    2. Agent invokes: `python -m ol_cli translate-md <file> -c config/default.yaml -s <src> -t <tgt> -o <output_dir> --json`
    3. Agent parses JSON output for success/error
    4. Agent reads translated file from output_dir
  - Include "Pitfalls" section with common issues:
    - API keys not set (MINIMAX_API_KEY, BAIDU_API_KEY)
    - Input file too large (recommend < 100KB)
    - Rate limiting (add retry with backoff)
  - Include "Verification" section showing how to confirm success
  - Include "Configuration" section documenting required env vars

  **Must NOT do**:
  - Don't include XLIFF support (out of scope for v1)
  - Don't include batch operations (out of scope for v1)
  - Don't make up information about OpenCode internals
  - Don't use placeholder text that isn't specific

  **Recommended Agent Profile**:
  > **Category**: `writing` - Documentation/content writing
  > **Reason**: Writing SKILL.md is primarily documentation work
  > **Skills**: None required - follow AgentSkills.io standard

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 6, 7)
  - **Blocks**: Tasks 8, 9 (testing)
  - **Blocked By**: Tasks 1, 2, 4 (need JSON output working)

  **References**:
  - AgentSkills.io standard: YAML frontmatter + Markdown body
  - `src/ol_cli.py:105-157` - translate-md command reference
  - `config/default.yaml` - default config structure
  - `README.md` - project overview for description

  **Acceptance Criteria**:
  - [ ] SKILL.md has valid YAML frontmatter with name and description
  - [ ] "Procedure" section has exact CLI invocation command
  - [ ] "Pitfalls" section mentions API key setup
  - [ ] "Verification" section shows how to confirm success
  - [ ] File is valid Markdown (can be parsed)

  **QA Scenarios**:

  \`\`\`
  Scenario: SKILL.md has valid frontmatter
    Tool: Bash
    Preconditions: None
    Steps:
      1. head -15 src/.opencode/skills/ol-localizer/SKILL.md
      2. python -c "import yaml; yaml.safe_load(open('src/.opencode/skills/ol-localizer/SKILL.md').split('---')[1])"
    Expected Result: Valid YAML with name and description fields
    Failure Indicators: YAML parse error, missing required fields
    Evidence: .sisyphus/evidence/task-5-frontmatter.txt

  Scenario: Procedure section contains correct CLI command
    Tool: Bash
    Preconditions: None
    Steps:
      1. grep -A5 "Procedure" src/.opencode/skills/ol-localizer/SKILL.md
    Expected Result: Contains `python -m ol_cli translate-md` with --json flag
    Failure Indicators: Wrong command, missing --json
    Evidence: .sisyphus/evidence/task-5-procedure.txt
  \`\`\`

  **Commit**: YES
  - Message: `docs(skills): add OpenCode SKILL.md with usage instructions`
  - Files: `src/.opencode/skills/ol-localizer/SKILL.md`

- [ ] 6. Write Hermes SKILL.md content

  **What to do**:
  - Write comprehensive SKILL.md for Hermes in `src/.hermes/skills/ol-localizer/SKILL.md`
  - Follow same structure as OpenCode SKILL.md (Task 5)
  - Add Hermes-specific metadata if needed (e.g., tags, requires_toolsets)
  - Adapt "Procedure" section for Hermes context
  - Include note about installation: "Copy this directory to ~/.hermes/skills/ to activate"
  - Include Hermes-specific pitfalls if any

  **Must NOT do**:
  - Don't duplicate OpenCode content verbatim if contexts differ
  - Don't include Hermes-specific technical details that might be wrong
  - Don't assume Hermes has same file system access as OpenCode

  **Recommended Agent Profile**:
  > **Category**: `writing` - Documentation/content writing
  > **Reason**: Writing SKILL.md is primarily documentation work
  > **Skills**: None required - follow AgentSkills.io standard

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 5, 7)
  - **Blocks**: Tasks 8, 9 (testing)
  - **Blocked By**: Tasks 1, 3, 4 (need JSON output and directory structure)

  **References**:
  - AgentSkills.io standard: YAML frontmatter + Markdown body
  - Hermes skill conventions (same as AgentSkills.io)
  - Task 5 SKILL.md as template

  **Acceptance Criteria**:
  - [ ] SKILL.md has valid YAML frontmatter with name and description
  - [ ] "Procedure" section has exact CLI invocation command
  - [ ] "Pitfalls" section mentions API key setup
  - [ ] Includes installation instructions for ~/.hermes/skills/
  - [ ] File is valid Markdown

  **QA Scenarios**:

  \`\`\`
  Scenario: Hermes SKILL.md has valid frontmatter
    Tool: Bash
    Preconditions: None
    Steps:
      1. head -15 src/.hermes/skills/ol-localizer/SKILL.md
      2. python -c "import yaml; yaml.safe_load(open('src/.hermes/skills/ol-localizer/SKILL.md').split('---')[1])"
    Expected Result: Valid YAML with name and description
    Failure Indicators: YAML parse error, missing required fields
    Evidence: .sisyphus/evidence/task-6-frontmatter.txt

  Scenario: Installation instructions present
    Tool: Bash
    Preconditions: None
    Steps:
      1. grep -i "install" src/.hermes/skills/ol-localizer/SKILL.md
    Expected Result: Mentions copying to ~/.hermes/skills/
    Failure Indicators: Missing installation instructions
    Evidence: .sisyphus/evidence/task-6-install.txt
  \`\`\`

  **Commit**: YES
  - Message: `docs(skills): add Hermes SKILL.md with usage instructions`
  - Files: `src/.hermes/skills/ol-localizer/SKILL.md`

- [ ] 7. Create skill verification test helper

  **What to do**:
  - Create a test helper module `tests/skill_helpers.py` with functions:
    - `verify_skill_discovery(skill_path: Path) -> bool` - checks SKILL.md exists and has valid frontmatter
    - `verify_skill_frontmatter(skill_path: Path, required_fields: list) -> bool` - validates required YAML fields
    - `verify_cli_json_output(command: list, expected_fields: list) -> dict` - runs CLI and validates JSON
    - `create_temp_input(text: str) -> Path` - creates temp .md file for testing
  - This helper will be used by Tasks 8 and 9

  **Must NOT do**:
  - Don't create actual tests yet (Task 8/9)
  - Don't modify existing test files
  - Don't add pytest fixtures (keep as simple helper functions)

  **Recommended Agent Profile**:
  > **Category**: `quick` - Simple utility module creation
  > **Reason**: Helper functions are straightforward
  > **Skills**: None required

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 5, 6)
  - **Blocks**: Tasks 8, 9
  - **Blocked By**: Task 1 (need JSON output working)

  **References**:
  - `tests/conftest.py` - existing test configuration
  - `tests/test_ol_cli.py` - existing CLI tests for patterns

  **Acceptance Criteria**:
  - [ ] `tests/skill_helpers.py` exists
  - [ ] Functions are importable: `from tests.skill_helpers import verify_skill_discovery`
  - [ ] Helper works with existing test infrastructure

  **QA Scenarios**:

  \`\`\`
  Scenario: Helper module imports correctly
    Tool: Bash
    Preconditions: None
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && python -c "from tests.skill_helpers import verify_skill_discovery, verify_cli_json_output; print('OK')"
    Expected Result: Prints "OK" without ImportError
    Failure Indicators: ImportError, missing module
    Evidence: .sisyphus/evidence/task-7-import.txt

  Scenario: verify_skill_discovery works
    Tool: Bash
    Preconditions: Task 5 completed (OpenCode SKILL.md exists)
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && python -c "from tests.skill_helpers import verify_skill_discovery; result = verify_skill_discovery(Path('src/.opencode/skills/ol-localizer')); print(f'Discovery: {result}')"
    Expected Result: Returns True
    Failure Indicators: Returns False, raises exception
    Evidence: .sisyphus/evidence/task-7-discovery.txt
  \`\`\`

  **Commit**: YES
  - Message: `test(skills): add verification helper module`
  - Files: `tests/skill_helpers.py`

---

## Final Verification Wave

- [ ] F1. **Plan Compliance Audit** — `oracle`
- [ ] F2. **Code Quality Review** — `unspecified-high`
- [ ] F3. **Real Manual QA** — `unspecified-high`
- [ ] F4. **Scope Fidelity Check** — `deep`

---

## Commit Strategy

- **Wave 1**: `feat(cli): add --json output flag for agent integration` - ol_cli.py, schema.py
- **Wave 2**: `docs(skills): add SKILL.md for OpenCode and Hermes` - skills/**/*.md
- **Wave 3**: `test(skills): add verification tests` - tests/test_skills_*.py
- **Final**: `docs: update README with agent usage` - README.md

---

## Success Criteria

### Verification Commands
```bash
# CLI still works as before
python -m ol_cli translate-md input.md -c config/default.yaml -s en -t zh -o output/

# New JSON mode works
python -m ol_cli translate-md input.md -c config/default.yaml -s en -t zh -o output/ --json

# Skill files exist
ls .opencode/skills/ol-localizer/SKILL.md
ls ~/.hermes/skills/ol-localizer/SKILL.md  # if Hermes skills dir exists

# Existing tests pass
pytest tests/test_ol_cli.py -v
```

### Final Checklist
- [ ] All "Must Have" present
- [ ] All "Must NOT Have" absent
- [ ] All tests pass
- [ ] Skills have valid YAML frontmatter
- [ ] JSON output is valid and parseable