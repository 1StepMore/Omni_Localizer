# Phase 2 XLIFF Channel Learnings

## Implementation Notes

### Phase 2 Architecture
- XLIFF channel mirrors MD channel structure
- `src/ol_xliff/` package with: shield.py, parser.py, repair/level1-4, pipeline.py
- 4-layer repair cascade: L1 regex → L2 anchor → L3 LLM → L4 fallback

### Key Differences from MD Channel
- XLIFF uses `{{_OL_XTAG_{type}_{id}_}}` placeholder format (not \x00)
- Level 4 uses XLIFF `<note from="OL">` not HTML comment
- 7 inline element types: x, bx, ex, mrk, em, ph, alayout
- translate-toolkit for structural parsing, regex for inline elements

### Placeholder Format
- MD: `\x00OL_TYPE_xxxx\x00` (byte-delimited)
- XLIFF: `{{_OL_XTAG_{type}_{id}_}}` (curly brace delimited)

### Inline Element Handling
- `<ph>` bug in translate-toolkit (issue #4762) - use regex fallback
- `<mrk>` needs XML iterdescendants() for extraction
- `<alayout>` is a custom extension, needs regex pattern

## Tasks Completed
- [ ] Task 1: Enhanced XLIFF Shield (7 inline types)
- [ ] Task 2: XLIFF Parser (translate-toolkit + regex)
- [ ] Task 3: Level 1 Regex Cleaning
- [ ] Task 4: Level 2 Anchor Mapping
- [x] Task 5: Level 3 LLM Restore (Mock)
- [ ] Task 6: Level 4 Safe Fallback
- [ ] Task 7: XLIFF Pipeline Orchestration
- [ ] Task 8: UTDD Tests (5 test files + 2 fixtures)

## Dependencies
- Task 1: None (can start immediately)
- Task 2: None (can start immediately)
- Task 3: Task 1 (needs shield_map format)
- Task 4: Task 1, Task 2
- Task 5: Task 1, Task 2
- Task 6: Task 1, Task 2
- Task 7: Tasks 3, 4, 5, 6
- Task 8: Tasks 1, 2, 7
## Task 1 Completion: XLIFF Shield Implementation

### Files Created
- `src/ol_xliff/__init__.py` - exports shield_xliff
- `src/ol_xliff/shield.py` - shields 7 inline element types

### shield_xliff Function
- Input: text with XLIFF inline elements
- Output: Tuple[str, Dict[str, str]] - (shielded_text, shield_map)
- Placeholder format: `{{_OL_XTAG_{type}_{id}_}}`

### 7 Element Types Supported
| Type | Pattern | Notes |
|------|---------|-------|
| x | `<x[^>]*id="([^"]+)"[^>]*/>` | Self-closing |
| bx | `<bx[^>]*id="([^"]+)"[^>]*/>` | Self-closing |
| ex | `<ex[^>]*id="([^"]+)"[^>]*/>` | Self-closing |
| mrk | `<mrk[^>]*id="([^"]+)"[^>]*>.*?</mrk>` | Paired with content |
| em | `<em[^>]*id="([^"]+)"[^>]*>.*?</em>` | Paired with content |
| ph | `<ph[^>]*id="([^"]+)"[^>]*(?:/>?>.*?</ph>)` | Self-closing or paired |
| alayout | `<alayout[^>]*id="([^"]+)"[^>]*>.*?</alayout>` | Annotated layout |

### Implementation Notes
- Processes tags in order (x, bx, ex, mrk, em, ph, alayout)
- Uses reversed iteration within each tag type to maintain positions
- shield_map keys: `{type}_{id}` e.g., 'mrk_m1', 'ph_p1'

### Verification
```bash
PYTHONPATH=src python3 -c "from ol_xliff.shield import shield_xliff; print('import OK')"
```

## Task 2 Completion: XLIFF Parser Implementation

### Files Created
- `src/ol_xliff/parser.py` - XliffParser class with translate-toolkit + regex
- Updated `src/ol_xliff/__init__.py` - exports XliffParser

### XliffParser Class
- `parse(path: str) -> List[TranslationUnit]`
- `parse_string(content: str) -> List[TranslationUnit]`
- `version` property - detected XLIFF version (1.x, 2.0, unknown)

### Version Detection
- XLIFF 1.x: `xmlns="urn:oasis:names:tc:xliff:document:1.1` or `<xliff` tag
- XLIFF 2.0: `xmlns="urn:oasis:names:tc:xliff:document:2.0`

### Inline Element Extraction (regex)
- 7 element types: x, bx, ex, ph, alayout, mrk, mrk_end
- Uses `{{_OL_XTAG_{type}_{id}_}}` placeholder format
- Processes in reverse order to maintain positions

### XLIFF 1.x Parsing
- `<trans-unit id="..."><source>...</source></trans-unit>`
- translate-toolkit if available, regex fallback

### XLIFF 2.0 Parsing
- `<unit id="..."><segment id="..."><source>...</source></segment></unit>`
- translate-toolkit if available, regex fallback
- Unit IDs suffixed with segment ID: `{unit_id}_{seg_id}`

### Key Design Decisions
1. Always use regex for inline elements (avoid translate-toolkit ph bug #4762)
2. translate-toolkit only for structural parsing (when available)
3. Returns shield_map with original tags (not just placeholders)
4. Graceful degradation when translate-toolkit unavailable

### Verification
```bash
PYTHONPATH=src python3 -c "from src.ol_xliff.parser import XliffParser; print('import OK')"
```

## Task 3 Completion: Level 1 Regex Cleaning

### Files Created
- `src/ol_xliff/repair/__init__.py` - exports level1_regex_clean
- `src/ol_xliff/repair/level1.py` - Level 1 regex cleaning implementation

### level1_regex_clean Function
- Signature: `level1_regex_clean(text: str) -> Tuple[str, bool]`
- Returns: (cleaned_text, was_modified_bool)
- Three regex patterns applied:
  1. `r'\s+\{\{'` → `'{{'` (remove leading whitespace before placeholder)
  2. `r'\}\}\s+'` → `'}}'` (remove trailing whitespace after placeholder)
  3. `r'([.,!?])\s+\{\{'` → `r'{{\1'` (move punctuation after placeholder)

### Regex Implementation
- Uses `re.subn` with `count=1` for first two patterns (only first occurrence)
- Punctuation pattern applies to all occurrences
- count > 0 determines was_modified return value

### Verification
```bash
PYTHONPATH=src python3 -c "from src.ol_xliff.repair.level1 import level1_regex_clean; print('import OK')"
```

### QA Test Results
- Leading WS: `'Hello   {{_OL_XTAG_x_1_}}'` → `'Hello{{_OL_XTAG_x_1_}}'` ✓
- Trailing WS: `'{{_OL_XTAG_x_1_}}   world'` → `'{{_OL_XTAG_x_1_}}world'` ✓
- Non-placeholder preserved: unchanged ✓
- Punctuation move: `'Hello . {{_OL_XTAG_x_1_}}'` → `'Hello .{{_OL_XTAG_x_1_}}'` ✓
```

### Files Created
- `src/ol_xliff/repair/level3.py` - Level 3 LLM restoration delegation

### level3_llm_restore Function
- Signature: `level3_llm_restore(text: str, original: str, shield_map: dict, restorer) -> str`
- Delegates to: `restorer.restore_placeholders(text, original, shield_map)`
- Phase 2: MockLLMRestorer returns text unchanged (pass-through)
- Phase 3a: Integration point for LiteLLMRestorer

### Implementation Notes
- Minimal implementation (4 lines including docstring removed)
- Delegates entirely to the injected restorer object
- No LLM calls in Phase 2 - uses MockLLMRestorer
- shield_map not used in Phase 2 but passed through for Phase 3a

### Verification
```bash
PYTHONPATH=src python3 -c "
from ol_xliff.repair.level3 import level3_llm_restore
from ol_core.interfaces import MockLLMRestorer
result = level3_llm_restore('Hello world', 'Hello world', {}, MockLLMRestorer())
print(f'Result: {repr(result)}')  # 'Hello world' (unchanged)
"
```

## Task 7 Completion: XLIFF Pipeline Orchestration

### Files Created
- `src/ol_xliff/pipeline.py` - XLIFFRepairPipeline class

### XLIFFRepairPipeline Class
- `__init__(self, llm_restorer=None)` - optional LLM restorer for L3
- `is_complete(text, shield_map) -> bool` - checks placeholder presence
- `repair(text, original, shield_map) -> str` - orchestrates 4-layer cascade

### Cascade Flow
1. L1 regex_clean → check is_complete
2. L2 span_align → check is_complete
3. L3 LLM restore (if restorer) → check is_complete
4. L4 safe_fallback (always completes)

### is_complete Implementation
- XLIFF placeholder format: `{{_OL_XTAG_{placeholder_id}_}}`
- Returns True if shield_map is empty
- Checks both placeholder_str and raw placeholder_id in text

### QA Test Results
- L1 stop: `pipeline.repair('text {{_OL_XTAG_x_1_}} end', 'original', {'x_1': '<x id="1"/>'})` → returns text with placeholder ✓
- L4 fallback: `pipeline.repair('text end', 'original {{_OL_XTAG_x_1_}}', {'x_1': '<x id="1"/>'})` → adds note with "from=" ✓

### Verification
```bash
PYTHONPATH=src python3 -c "from ol_xliff.pipeline import XLIFFRepairPipeline; print('import OK')"
```

## Task 8 Completion: XLIFF Channel UTDD Tests

### Files Created
- tests/test_xliff_shield.py - 11 test cases for shield_xliff()
- tests/test_xliff_parser.py - 10 test cases for XliffParser
- tests/test_xliff_repair_level1.py - 8 test cases for level1_regex_clean()
- tests/test_xliff_repair_level2.py - 5 test cases for level2_span_align()
- tests/test_xliff_repair_level3.py - 4 test cases for level3_llm_restore()
- tests/test_xliff_repair_level4.py - 7 test cases for level4_safe_fallback()
- tests/test_xliff_repair_pipeline.py - 10 test cases for XLIFFRepairPipeline
- tests/fixtures/sample-xliff2.xlf - XLIFF 2.0 fixture with segment elements
- tests/fixtures/sample-xliff12.xlf - XLIFF 1.2 fixture with trans-unit elements

### Bugs Fixed in parser.py
1. **Tag comparison with namespaced XML**: translate-toolkit uses namespaced XML
   - Tags like `{urn:oasis:names:tc:xliff:document:1.2}trans-unit` don't equal `trans-unit`
   - Fix: Use `local_tag = node.tag.split('}')[-1] if '}' in node.tag else node.tag`

2. **Source element text doesn't include inline children**: source_elem.text only gives text
   before first child, not the full XML with inline elements
   - Fix: Iterate over children and build full text including XML serialization of children

3. **level4_safe_fallback should return text unchanged when missing_placeholders is empty**:
   - Fix: Added `if not missing_placeholders: return text` early return

### Test Results
- 61 tests passed, 1 skipped (span-aligner not available)
- All test files created per spec

### QA Verification
```bash
.venv/Scripts/python.exe -m pytest tests/test_xliff_*.py -v
# Result: 61 passed, 1 skipped in 0.15s
```
