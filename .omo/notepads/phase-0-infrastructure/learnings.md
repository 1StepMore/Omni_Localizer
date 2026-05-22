# Phase 0 Learnings

## Session: phase-0-infrastructure
**Date**: 2026-05-15

## Key Findings

### Environment Issues (BLOCKER)
- `poetry` not available in shell environment
- Cannot run `poetry install`, `poetry check`, `poetry run pytest`
- All dependency verification tasks (Task 3) could not be completed
- This is an ENVIRONMENT CONSTRAINT, not a code issue

### Version Fixes Applied
1. **Python version**: Changed `^3.10` → `^3.13` (hypomnema ^0.8 requires Python >=3.13)
2. **translate-toolkit version**: Changed `^44.0.0` → `^3.19.9` (version 44.0.0 never existed)
3. **CI workflow**: Updated from Python 3.10/3.11/3.12 → Python 3.13 only

### Code Structure
All source files are syntactically valid Python. 8 test files created with proper pytest structure.

### Files Created (27 total)
- src/ol_core/: dataclass.py, interfaces.py, exceptions.py, __init__.py
- src/ol_buses/: xliff_bus.py, xliff_shield.py, md_bus.py, md_shield.py, format_guard.py, __init__.py
- src/ol_config/: schema.py, loader.py, __init__.py
- config/: default.yaml
- tests/: 8 test files + fixtures
- .github/workflows/test.yml
- pyproject.toml

## Issues Encountered

### Blocker: poetry unavailable
- poetry not in PATH
- Cannot verify dependency installation
- Cannot run tests

### Workaround Applied
- Fixed pyproject.toml versions manually
- Verified syntax with `python3 -m py_compile`
- Verified structure exists via ls and file reads

## Recommendations for Next Session

1. **Verify in environment with poetry**: Run these commands:
   ```bash
   poetry install --no-interaction
   poetry check --no-isolation
   poetry run pytest tests/ -v
   ```

2. **CI needs update**: .github/workflows/test.yml should match plan's Python 3.10/3.11/3.12 matrix OR update plan to match reality (Python 3.13 only)

3. **poetry.lock missing**: Should be generated after `poetry lock --no-update`

## Scope Creep Observations
None - Phase 0 implementation stayed within scope. Phase references in comments (e.g., "Phase 1/2 mock") are acceptable documentation.

## Test Coverage
8 test files created covering:
- test_translation_context.py
- test_repair_context.py
- test_evaluation_result.py
- test_llm_restorer_interface.py
- test_config_loader.py
- test_xliff_bus.py
- test_md_bus.py
- test_format_guard.py

All tests require `poetry run pytest` to verify execution.