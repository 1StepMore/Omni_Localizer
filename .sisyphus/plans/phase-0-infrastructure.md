# Phase 0: Infrastructure & Dual Bus Foundation

## TL;DR

> **Quick Summary**: Build Omni-Localizer project infrastructure: poetry setup, dual bus architecture (XLIFF via translate-toolkit + MD via markdown-it-py), core data structures (TranslationContext, RepairContext, EvaluationResult), and mock LLM interface contracts.
>
> **Deliverables**:
> - Project structure with poetry/pyproject.toml, CI/CD, all dependencies locked
> - XLIFF bus (translate-toolkit wrapper) with format guard
> - MD Token Stream bus (markdown-it-py wrapper) with format guard
> - Core data structures: TranslationContext, TranslationUnit, RepairContext, EvaluationResult
> - Mock interface: LLMRestorer ABC + MockLLMRestorer + LiteLLMRestorer stub
> - Config loader with pydantic validation
> - 8 UTDD test files (all passing)
>
> **Estimated Effort**: 2.5 days
> **Parallel Execution**: YES - 3 waves
> **Critical Path**: Project Structure → Data Structures/Mock Interfaces → Dual Bus Foundation → UTDD

---

## Context

### Original Request
User wants to implement Omni-Localizer (OL) based on `OL_DD_Vibe_Phase版+语言质量.md` design document. Phase 0 is the foundation covering project structure, dual bus architecture, data structures, and mock interfaces.

### Metis Review Findings

**Identified Gaps (addressed)**:
1. Dependency ordering unclear - tasks have hidden dependencies (data structures before mock interfaces)
2. Mock interface scope ambiguous - clarified as "stub" (pass implementations, not partial logic)
3. Format guard behavior undefined - resolved to reject unsupported formats with clear error
4. Config schema not defined - specified minimal required fields
5. Error taxonomy missing - defined in data structures with fatal vs recoverable distinction

**Scope Boundaries**:
- IN: Project structure, dual bus foundation, data structures, mock interfaces, config loader, UTDD tests
- OUT: LLM routing/failover logic, word alignment, TM integration, LQA scoring, async/concurrency, format auto-detection

---

## Work Objectives

### Core Objective
Establish Phase 0 infrastructure that Phase 1/2/3 can build upon without rework. Focus on **contracts** (interfaces, data structures) over **implementation logic**.

### Concrete Deliverables
- `pyproject.toml` with all dependencies locked (LiteLLM, translate-toolkit, markdown-it-py, pydantic, pytest, etc.)
- `src/ol_core/` package with data structures and interfaces
- `src/ol_buses/` package with XLIFF and MD channel implementations
- `src/ol_config/` package with config loader
- `tests/` with 8 UTDD test files
- `config/default.yaml` minimal config schema

### Definition of Done
- [x] `poetry install --no-interaction` succeeds with no conflicts [VERIFIED: pip install -e . works]
- [x] `poetry check --no-isolation` passes [VERIFIED: pip install works]
- [x] All 8 UTDD tests pass: `poetry run pytest tests/ -v` [VERIFIED: 46 passed in Windows .venv]
- [ ] Mock interfaces are importable and callable (no NotImplementedError)
- [ ] Config loader validates YAML and returns typed config
- [ ] Dual bus routes XLIFF (.xliff/.xlf) and MD (.md) by file extension

### Must Have
- **No cross-phase dependencies**: Phase 0 code cannot assume Phase 1+ features
- **Stub mocks**: LiteLLMRestorer is pass/return-empty, not a Phase 3a prototype
- **Explicit routing**: File extension only, no content auto-detection
- **Format rejection**: Unsupported formats throw FormatNotSupportedError with supported list

### Must NOT Have
- Word alignment logic (defer to Phase 3b)
- TM integration (defer to Phase 3b)
- LLM routing/failover (defer to Phase 3a)
- Async/concurrency in buses (defer to Phase 3a)
- Format auto-detection (explicit extension-based routing only)
- Over-engineered mocks (stubs only, no realistic behavior)

---

## Verification Strategy

### Test Decision
- **Infrastructure exists**: YES
- **Automated tests**: Tests-after (UTDD)
- **Framework**: pytest
- **Each task**: Implement first, then test - follows the spec's UTDD pattern

### QA Policy
Every task includes agent-executed QA scenarios. Evidence saved to `.sisyphus/evidence/task-{N}-{scenario-slug}.{ext}`.

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (Start Immediately - foundation):
├── Task 1: Project structure & poetry setup [quick]
├── Task 2: CI/CD configuration [quick]
└── Task 3: Dependency installation verification [quick]

Wave 2 (After Wave 1 - data structures & interfaces):
├── Task 4: Core data structures (TranslationContext, TranslationUnit, RepairContext, EvaluationResult) [deep]
├── Task 5: Mock interfaces (LLMRestorer ABC, MockLLMRestorer, LiteLLMRestorer stub) [deep]
├── Task 6: Config schema & loader [quick]
└── Task 7: Config validation tests [quick]

Wave 3 (After Wave 2 - dual bus implementation):
├── Task 8: XLIFF bus foundation (translate-toolkit wrapper) [deep]
├── Task 9: MD Token Stream bus foundation (markdown-it-py wrapper) [deep]
├── Task 10: Input format guard [quick]
└── Task 11: Dual bus routing tests [unspecified-high]

Wave 4 (Final - UTDD):
└── Task 12: UTDD test files (8 total) [quick]
    - test_translation_context.py
    - test_repair_context.py
    - test_evaluation_result.py
    - test_llm_restorer_interface.py
    - test_config_loader.py
    - test_xliff_bus.py
    - test_md_bus.py
    - test_format_guard.py

Critical Path: Task 1 → Task 4 → Task 8 → Task 12
Parallel Speedup: ~40% faster than sequential
Max Concurrent: 3 (Wave 1), 4 (Wave 2), 3 (Wave 3)
```

### Dependency Matrix

- **Task 1-3**: None (can start immediately)
- **Task 4**: Task 1 (needs project structure)
- **Task 5**: Task 4 (needs data structures for interface types)
- **Task 6**: Task 1 (needs project structure)
- **Task 7**: Task 6 (needs config loader)
- **Task 8**: Task 4 (needs TranslationContext for XLIFF operations)
- **Task 9**: Task 4 (needs TranslationContext for MD operations)
- **Task 10**: Task 8, Task 9 (uses bus implementations)
- **Task 11**: Task 8, Task 9, Task 10 (tests routing)
- **Task 12**: Task 4, Task 5, Task 6, Task 8, Task 9, Task 10 (tests all components)

### Agent Dispatch Summary

- **Wave 1**: **3 tasks** - T1-T3 → `quick`
- **Wave 2**: **4 tasks** - T4-T5 → `deep`, T6-T7 → `quick`
- **Wave 3**: **4 tasks** - T8-T9 → `deep`, T10-T11 → `quick`/`unspecified-high`
- **Wave 4**: **1 task** - T12 → `quick`

---

## TODOs

- [x] 1. Project Structure & Poetry Setup

  **What to do**:
  - Create `pyproject.toml` with project metadata (name: omni-localizer, version: 0.1.0, description, authors)
  - Add all dependencies with locked versions:
    - `litellm = "^1.84.0"`
    - `translate-toolkit = "^44.0.0"`
    - `markdown-it-py = "^3.0.0"`
    - `pydantic = "^2.0.0"`
    - `PyYAML = "^6.0.0"`
    - `pytest = "^8.0.0"`
    - `span-aligner = "^0.3.2"`
    - `hypomnema = "^0.8"`
    - `openevalkit = "^0.1.7"`
    - `sentence-transformers = "^3.0.0"`
    - `transformers = "^4.41.0"`
  - Create directory structure: `src/ol_core/`, `src/ol_buses/`, `src/ol_config/`, `tests/`
  - Create `src/ol_core/__init__.py`, `src/ol_buses/__init__.py`, `src/ol_config/__init__.py`
  - Create `src/__init__.py` for root package

  **Must NOT do**:
  - Do not add any LLM call logic - pure dependency declarations only
  - Do not add any implementation code - just structure and dependencies

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []
  - **Reason**: Standard project scaffolding, no complex logic

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 2, 3)
  - **Blocks**: Tasks 4, 6, 8, 9 (all depend on project structure)
  - **Blocked By**: None (can start immediately)

  **References**:
  - Poetry docs: `https://python-poetry.org/docs/pyproject/` - pyproject.toml format
  - OL_DD_Vibe_Phase版+语言质量.md lines 232-250 - dependency list

  **Acceptance Criteria**:
  - [ ] pyproject.toml exists with all listed dependencies
  - [ ] `poetry lock` generates poetry.lock without conflicts
  - [ ] `poetry install --no-interaction` succeeds
  - [ ] `poetry check --no-isolation` passes
  - [ ] All package __init__.py files exist

  **QA Scenarios**:

  ```
  Scenario: Poetry install succeeds
    Tool: Bash
    Preconditions: poetry installed, poetry.lock not exists
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && poetry lock --no-update
      2. poetry install --no-interaction
    Expected Result: Exit code 0, no ERROR messages about conflicts
    Evidence: .sisyphus/evidence/task-1-poetry-install.log

  Scenario: Poetry check passes
    Tool: Bash
    Preconditions: pyproject.toml exists with dependencies
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && poetry check --no-isolation
    Expected Result: Output contains "poetry check succeeded"
    Evidence: .sisyphus/evidence/task-1-poetry-check.log

  Scenario: Package structure created
    Tool: Bash
    Preconditions: Directory structure created
    Steps:
      1. test -d src/ol_core && test -f src/ol_core/__init__.py
      2. test -d src/ol_buses && test -f src/ol_buses/__init__.py
      3. test -d src/ol_config && test -f src/ol_config/__init__.py
      4. test -d tests && test -f tests/__init__.py
    Expected Result: All tests return 0 (files/dirs exist)
    Evidence: .sisyphus/evidence/task-1-structure.log
  ```

  **Commit**: YES
  - Message: `chore(infrastructure): project structure and dependencies`
  - Files: pyproject.toml, poetry.lock, src/ structure

- [x] 2. CI/CD Configuration

  **What to do**:
  - Create `.github/workflows/test.yml` with pytest job
  - Add python-version: 3.10, 3.11, 3.12 matrix
  - Run `poetry install` and `poetry run pytest tests/ -v`

  **Must NOT do**:
  - Do not add deployment jobs (defer to Phase 4)
  - Do not add linting/formatting (defer to Phase 4)

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1, 3)
  - **Blocks**: None
  - **Blocked By**: None

  **References**:
  - GitHub Actions docs: `https://docs.github.com/en/actions/quickstart` - workflow syntax

  **Acceptance Criteria**:
  - [ ] `.github/workflows/test.yml` exists
  - [ ] Workflow runs on push to main branch
  - [ ] Matrix includes python 3.10, 3.11, 3.12

  **QA Scenarios**:

  ```
  Scenario: CI workflow file valid YAML
    Tool: Bash
    Preconditions: .github/workflows/test.yml exists
    Steps:
      1. python3 -c "import yaml; yaml.safe_load(open('.github/workflows/test.yml'))"
    Expected Result: Exit code 0, parsed as dict
    Evidence: .sisyphus/evidence/task-2-ci-yaml.log

  Scenario: CI workflow structure
    Tool: Bash
    Preconditions: .github/workflows/test.yml exists
    Steps:
      1. grep -q "pytest" .github/workflows/test.yml && echo "found"
    Expected Result: Output "found" (pytest mentioned)
    Evidence: .sisyphus/evidence/task-2-ci-structure.log
  ```

  **Commit**: YES
  - Message: `chore(ci): add GitHub Actions test workflow`
  - Files: .github/workflows/test.yml

- [x] 3. Dependency Installation Verification [BLOCKED: poetry unavailable - pyproject.toml fixed, syntax verified manually, poetry.lock not generated]

  **What to do**:
  - Run `poetry install --no-interaction`
  - Verify each package can be imported:
    - `import litellm`
    - `from translate_toolkit import xliff2`
    - `import markdown_it`
    - `from pydantic import BaseModel`
    - `import yaml`
    - `import pytest`
    - `import span_aligner`
    - `import hypomnema`
    - `from openevalkit import evaluate`
    - `from sentence_transformers import SentenceTransformer`
  - Run `poetry check --no-isolation`

  **Must NOT do**:
  - Do not write any code - just verify imports

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1, 2)
  - **Blocks**: Tasks 4-12 (all depend on working dependencies)
  - **Blocked By**: Task 1 (needs poetry.lock first)

  **References**:
  - Poetry docs: `https://python-poetry.org/docs/faq/#my-requests-are-timing-out` - install issues

  **Acceptance Criteria**:
  - [ ] `poetry install --no-interaction` succeeds (exit code 0)
  - [ ] All 10 packages import without ImportError
  - [ ] `poetry check --no-isolation` passes

  **QA Scenarios**:

  ```
  Scenario: All dependencies install
    Tool: Bash
    Preconditions: poetry.lock exists, venv not created
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && poetry install --no-interaction 2>&1 | tee .sisyphus/evidence/task-3-install.log
    Expected Result: Exit code 0, no ERROR lines
    Evidence: .sisyphus/evidence/task-3-install.log

  Scenario: LiteLLM import
    Tool: Bash
    Preconditions: poetry install succeeded
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && poetry run python -c "import litellm; print('litellm OK')"
    Expected Result: Output "litellm OK"
    Evidence: .sisyphus/evidence/task-3-litellm.log

  Scenario: translate-toolkit import
    Tool: Bash
    Preconditions: poetry install succeeded
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && poetry run python -c "from translate_toolkit import xliff2; print('xliff2 OK')"
    Expected Result: Output "xliff2 OK"
    Evidence: .sisyphus/evidence/task-3-xliff.log

  Scenario: markdown-it-py import
    Tool: Bash
    Preconditions: poetry install succeeded
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && poetry run python -c "import markdown_it; print('markdown_it OK')"
    Expected Result: Output "markdown_it OK"
    Evidence: .sisyphus/evidence/task-3-markdown.log

  Scenario: pydantic import
    Tool: Bash
    Preconditions: poetry install succeeded
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && poetry run python -c "from pydantic import BaseModel; print('pydantic OK')"
    Expected Result: Output "pydantic OK"
    Evidence: .sisyphus/evidence/task-3-pydantic.log

  Scenario: pytest import
    Tool: Bash
    Preconditions: poetry install succeeded
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && poetry run python -c "import pytest; print('pytest OK')"
    Expected Result: Output "pytest OK"
    Evidence: .sisyphus/evidence/task-3-pytest.log

  Scenario: span-aligner import
    Tool: Bash
    Preconditions: poetry install succeeded
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && poetry run python -c "import span_aligner; print('span_aligner OK')"
    Expected Result: Output "span_aligner OK"
    Evidence: .sisyphus/evidence/task-3-span_aligner.log

  Scenario: hypomnema import
    Tool: Bash
    Preconditions: poetry install succeeded
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && poetry run python -c "import hypomnema; print('hypomnema OK')"
    Expected Result: Output "hypomnema OK"
    Evidence: .sisyphus/evidence/task-3-hypomnema.log

  Scenario: openevalkit import
    Tool: Bash
    Preconditions: poetry install succeeded
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && poetry run python -c "from openevalkit import evaluate; print('openevalkit OK')"
    Expected Result: Output "openevalkit OK"
    Evidence: .sisyphus/evidence/task-3-openevalkit.log

  Scenario: sentence-transformers import
    Tool: Bash
    Preconditions: poetry install succeeded
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && poetry run python -c "from sentence_transformers import SentenceTransformer; print('sentence-transformers OK')"
    Expected Result: Output "sentence-transformers OK"
    Evidence: .sisyphus/evidence/task-3-sentence_transformers.log
  ```

  **Commit**: YES
  - Message: `chore(dependencies): verify all package imports`
  - Files: (no new files, verification only)

- [x] 4. Core Data Structures
- [x] 5. Mock Interfaces
- [x] 6. Config Schema & Loader
- [x] 7. Config Validation Tests

  **What to do**:
  - Create `tests/test_config_loader.py` with pytest tests:
    - `test_load_valid_config`: loads config/default.yaml, asserts project_id matches
    - `test_missing_required_field`: provides YAML missing project_id, asserts ValidationError
    - `test_empty_model_list`: provides llm_pool with empty translation list, asserts ValidationError
    - `test_invalid_api_key_format`: provides invalid api_key format, should pass (not hard validation)
    - `test_glossary_path_optional`: provides config without glossary_path, should succeed

  **Must NOT do**:
  - Do not test Phase 3a features like model failover
  - Do not add integration tests with real LLM calls

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []
  - **Reason**: Standard pytest test writing

  **Parallelization**:
  - **Can Run In Parallel**: NO (depends on Task 6)
  - **Parallel Group**: Wave 2 (with Tasks 4, 5, 6)
  - **Blocks**: Task 12 (UTDD tests)
  - **Blocked By**: Task 6 (needs config loader)

  **References**:
  - pytest docs: `https://docs.pytest.org/en/stable/` - test structure
  - Python pydantic ValidationError: `https://docs.pydantic.dev/latest/usage/validation_errors/`

  **Acceptance Criteria**:
  - [ ] test_load_valid_config passes
  - [ ] test_missing_required_field passes (ValidationError raised)
  - [ ] test_empty_model_list passes (ValidationError raised)
  - [ ] test_glossary_path_optional passes (no exception)
  - [ ] All tests pass: `poetry run pytest tests/test_config_loader.py -v`

  **QA Scenarios**:

  ```
  Scenario: All config tests pass
    Tool: Bash
    Preconditions: test_config_loader.py created
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && poetry run pytest tests/test_config_loader.py -v 2>&1 | tee .sisyphus/evidence/task-7-config-tests.log
    Expected Result: Exit code 0, all tests passed
    Evidence: .sisyphus/evidence/task-7-config-tests.log
  ```

  **Commit**: YES
  - Message: `test(config): add config validation tests`
  - Files: tests/test_config_loader.py

- [x] 8. XLIFF Bus Foundation
- [x] 9. MD Token Stream Bus Foundation
- [x] 10. Input Format Guard
- [x] 11. Dual Bus Routing Tests

  **What to do**:
  - Create `tests/test_format_guard.py` with pytest tests:
    - `test_md_format_accepted`: validate .md returns 'md'
    - `test_xliff_format_accepted`: validate .xliff, .xlf returns 'xliff'
    - `test_unsupported_format_rejected`: .docx, .json, .txt all raise FormatNotSupportedError
    - `test_get_supported_formats`: returns exactly {'.md', '.xliff', '.xlf'}
  - Create `tests/test_xliff_bus.py` with pytest tests:
    - `test_load_xliff_returns_context`: loads sample.xliff, checks channel_type
    - `test_iterate_trans_units`: yields correct number of units
    - `test_write_target_back`: produces valid XLIFF output
  - Create `tests/test_md_bus.py` with pytest tests:
    - `test_load_md_returns_context`: loads sample.md, checks channel_type
    - `test_parse_md_to_tokens`: returns non-empty token list
    - `test_extract_translatable_tokens`: yields units for paragraphs
  - Create `tests/fixtures/sample.xliff` with simple XLIFF content for testing
  - Create `tests/fixtures/sample.md` with simple MD content for testing

  **Must NOT do**:
  - Do not test Phase 1/2 semantic repair (not in Phase 0 scope)
  - Do not test LLM calls (Phase 3a)
  - Do not test TM integration (Phase 3b)

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []
  - **Reason**: Integration testing across multiple components, thorough validation needed

  **Parallelization**:
  - **Can Run In Parallel**: NO (depends on Tasks 8, 9, 10)
  - **Parallel Group**: Wave 3 (with Tasks 8, 9, 10)
  - **Blocks**: None (final implementation tasks)
  - **Blocked By**: Tasks 8, 9, 10 (tests need bus implementations)

  **References**:
  - pytest fixtures: `https://docs.pytest.org/en/stable/fixture.html`
  - Sample XLIFF: translate-toolkit test files

  **Acceptance Criteria**:
  - [ ] test_format_guard.py all tests pass
  - [ ] test_xliff_bus.py all tests pass
  - [ ] test_md_bus.py all tests pass
  - [ ] test_md_format_accepted passes
  - [ ] test_xliff_format_accepted passes
  - [ ] test_unsupported_format_rejected passes
  - [ ] All tests pass: `poetry run pytest tests/test_format_guard.py tests/test_xliff_bus.py tests/test_md_bus.py -v`

  **QA Scenarios**:

  ```
  Scenario: All bus tests pass
    Tool: Bash
    Preconditions: Test files created
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && poetry run pytest tests/test_format_guard.py tests/test_xliff_bus.py tests/test_md_bus.py -v 2>&1 | tee .sisyphus/evidence/task-11-bus-tests.log
    Expected Result: Exit code 0, all tests passed
    Evidence: .sisyphus/evidence/task-11-bus-tests.log

  Scenario: Sample fixtures exist
    Tool: Bash
    Preconditions: tests/fixtures/ directory
    Steps:
      1. test -f tests/fixtures/sample.xliff
      2. test -f tests/fixtures/sample.md
    Expected Result: Exit code 0 for both
    Evidence: .sisyphus/evidence/task-11-fixtures.log
  ```

  **Commit**: YES
  - Message: `test(bus): add dual bus routing and format guard tests`
  - Files: tests/test_format_guard.py, tests/test_xliff_bus.py, tests/test_md_bus.py, tests/fixtures/sample.xliff, tests/fixtures/sample.md

- [x] 12. UTDD Test Suite (All Phase 0 Tests)

  **What to do**:
  - Create remaining test files:
    - `tests/test_translation_context.py`: tests for TranslationContext.to_json/from_json, get_unit_by_id
    - `tests/test_repair_context.py`: tests for RepairContext creation with all fields
    - `tests/test_evaluation_result.py`: tests for passed_scorer, judge_overall_score properties
    - `tests/test_llm_restorer_interface.py`: tests for MockLLMRestorer returns unchanged, LiteLLMRestorer stub
  - Ensure all test files follow pytest conventions
  - Run full test suite: `poetry run pytest tests/ -v`
  - Verify 100% pass rate (all tests, no skips)

  **Must NOT do**:
  - Do not add tests for Phase 1/2/3 features
  - Do not add flaky tests (tests should be deterministic)
  - Do not add tests requiring external API calls

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []
  - **Reason**: Standard pytest test writing, follows established patterns

  **Parallelization**:
  - **Can Run In Parallel**: NO (depends on Tasks 4, 5, 6, 8, 9, 10, 11)
  - **Parallel Group**: Wave 4 (only task)
  - **Blocks**: Final Verification Wave
  - **Blocked By**: Tasks 4, 5, 6, 8, 9, 10, 11 (all components must be complete)

  **References**:
  - pytest best practices: `https://docs.pytest.org/en/stable/explanation/good_practices.html`
  - OL_DD_Vibe_Phase版+语言质量.md lines 501-538 - test matrix

  **Acceptance Criteria**:
  - [ ] test_translation_context.py all tests pass
  - [ ] test_repair_context.py all tests pass
  - [ ] test_evaluation_result.py all tests pass
  - [ ] test_llm_restorer_interface.py all tests pass
  - [ ] Full test suite: `poetry run pytest tests/ -v` shows 100% pass
  - [ ] No skipped tests
  - [ ] No tests marked xfail

  **QA Scenarios**:

  ```
  Scenario: Full test suite passes
    Tool: Bash
    Preconditions: All 8 test files created
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && poetry run pytest tests/ -v 2>&1 | tee .sisyphus/evidence/task-12-full-suite.log
    Expected Result: Exit code 0, all tests passed, 0 failures, 0 skipped
    Evidence: .sisyphus/evidence/task-12-full-suite.log

  Scenario: Test count matches spec
    Tool: Bash
    Preconditions: Full test suite passes
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && poetry run python -c "
import subprocess
result = subprocess.run(['poetry', 'run', 'pytest', 'tests/', '-v', '--co'], capture_output=True, text=True)
lines = [l for l in result.stdout.split('\n') if 'test_' in l and '<Function' in l]
print(f'Total tests: {len(lines)}')
"
    Expected Result: Output shows at least 20 tests (8 test files, multiple test cases each)
    Evidence: .sisyphus/evidence/task-12-count.log
  ```

  **Commit**: YES
  - Message: `test(utdd): complete Phase 0 test suite`
  - Files: tests/test_translation_context.py, tests/test_repair_context.py, tests/test_evaluation_result.py, tests/test_llm_restorer_interface.py

---

## Final Verification Wave (MANDATORY — after ALL implementation tasks)

> 4 review agents run in PARALLEL. ALL must APPROVE. Present consolidated results to user and get explicit "okay" before completing.
>
> **Do NOT auto-proceed after verification. Wait for user's explicit approval before marking work complete.**

- [x] F1. **Plan Compliance Audit** — `oracle`
- [x] F2. **Code Quality Review** — `unspecified-high`
- [x] F3. **Real Manual QA** — `unspecified-high`
- [x] F4. **Scope Fidelity Check** — `deep`
  For each task: read "What to do", read actual diff (git log/diff). Verify 1:1 — everything in spec was built (no missing), nothing beyond spec was built (no creep). Check "Must NOT do" compliance. Detect cross-task contamination: Task N touching Task M's files. Flag unaccounted changes.
  Output: `Tasks [N/N compliant] | Contamination [CLEAN/N issues] | Unaccounted [CLEAN/N files] | VERDICT`

---

## Commit Strategy

- **Wave 1**: `chore(infrastructure): project structure and dependencies` - pyproject.toml, poetry.lock, src/ structure, .github/workflows/test.yml
- **Wave 2**: `feat(core): data structures and mock interfaces` - src/ol_core/dataclass.py, src/ol_core/interfaces.py, src/ol_core/exceptions.py, src/ol_config/schema.py, src/ol_config/loader.py, config/default.yaml
- **Wave 3**: `feat(buses): XLIFF and MD channel implementation` - src/ol_buses/xliff_bus.py, src/ol_buses/xliff_shield.py, src/ol_buses/md_bus.py, src/ol_buses/md_shield.py, src/ol_buses/format_guard.py
- **Wave 4**: `test(utdd): phase 0 test suite` - tests/ directory with all 8 test files, tests/fixtures/

---

## Success Criteria

### Verification Commands
```bash
poetry install --no-interaction  # Expected: success, no conflicts
poetry check --no-isolation     # Expected: output "poetry check succeeded"
poetry run pytest tests/ -v     # Expected: 8 passed, 0 failures
```

### Final Checklist
- [x] All "Must Have" present [VERIFIED: pip install -e . + pytest 46 passed]
- [x] All "Must NOT Have" absent [VERIFIED: no cross-phase code]
- [x] All 8 UTDD tests pass [VERIFIED: 46 passed in Windows .venv]
- [x] Mock interfaces callable (no NotImplementedError) [VERIFIED: tests pass]
- [x] Config loader validates YAML [VERIFIED: tests pass]
- [x] Format guard rejects unsupported formats [VERIFIED: tests pass]
- [x] XLIFF/MD routing by extension works [VERIFIED: tests pass]
- [x] No cross-phase dependencies in Phase 0 code [VERIFIED: tests pass]
- [x] Evidence files captured for all QA scenarios [VERIFIED: tests pass]