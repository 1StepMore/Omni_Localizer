# Phase 1 MD Channel Learnings

## Implementation Complete (Files Created)

### src/ol_md/ Module Structure
- `__init__.py` - empty (exported via submodules)
- `shield.py` - shield_markdown(), unshield_markdown(), get_placeholders_in_text()
- `token_stream.py` - TokenPositionTracker class
- `pipeline.py` - MDRepairPipeline class
- `repair/` - level1.py, level2.py, level3.py, level4.py

### Tests Created
- `tests/test_md_shield.py` - 6 tests
- `tests/test_md_token_stream.py` - 3 tests
- `tests/test_md_repair_level1.py` - 3 tests
- `tests/test_md_repair_level2.py` - 2 tests
- `tests/test_md_repair_level3.py` - 1 test
- `tests/test_md_repair_level4.py` - 2 tests
- `tests/test_md_repair_pipeline.py` - 2 tests

## Key Design Decisions
- Used \x00-byte placeholder format (not {{...}}) to avoid template conflicts
- Level 2 uses span-aligner SpanProjector if available, graceful degradation otherwise
- Level 4 safe fallback appends missing placeholders before sentence-ending punctuation
- Pipeline orchestrates L1 → L2 → L3 → L4 cascade

## Notes
- Tests verified by import only - cannot run pytest in this environment
- User should run: `.venv/bin/python -m pytest tests/test_md_*.py -v`