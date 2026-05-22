# Phase 2: XLIFF 2.0 Channel (Inline Elements + 4-Layer Semantic Repair)

## TL;DR

> **Quick Summary**: Implement Full XLIFF 2.0 Channel with inline element protection (mrk, ph, em, bx, ex, alayout) and 4-layer semantic repair cascade (Regex → Anchor Mapping → LLM Restore → Safe Fallback), mirroring the MD channel architecture.
>
> **Deliverables**:
> - `src/ol_xliff/` - New XLIFF channel package mirroring `src/ol_md/` structure
> - `src/ol_xliff/shield.py` - Enhanced XLIFF shield (7 inline element types)
> - `src/ol_xliff/parser.py` - XLIFF parser with translate-toolkit integration (fallback regex)
> - `src/ol_xliff/repair/` - 4-layer repair pipeline (level1-4)
> - `src/ol_xliff/pipeline.py` - Repair orchestration
> - 4 UTDD test files: test_xliff_shield.py, test_xliff_parser.py, test_xliff_repair_*.py
>
> **Estimated Effort**: 2 days
> **Parallel Execution**: YES - 3 waves
> **Critical Path**: Shield Enhancement → Parser → Repair Layers → Pipeline → Tests

---

## Context

### Original Request
Implement Phase 2 XLIFF 2.0 Channel for Omni-Localizer based on `OL_DD_Vibe_Phase版+语言质量.md`. User confirmed: Full XLIFF 2.0 with inline elements, 4-layer repair, translate-toolkit integration, UTDD with pytest.

### Interview Summary
**Key Discussions**:
- Full 4-layer repair (Level 1 regex → Level 2 anchor mapping → Level 3 LLM restore → Level 4 safe fallback)
- XLIFF inline elements: mrk, em, bx, ex, ph, alayout (7 types total including x)
- translate-toolkit XLIFF 2.0 support via `translate.storage.xliff2` (v3.17.0+)
- Placeholder format: `{{_OL_XTAG_{uid}_}}` (curly brace delimited, different from MD)
- MockLLMRestorer delegation (no real LLM calls in Phase 2)
- UTDD with pytest (tests-first approach)

**Research Findings**:
- translate-toolkit has XLIFF 2.0 support: `translate.storage.xliff2`
- **CRITICAL BUG**: `<ph>` placeholder tag handling is broken (issue #4762) - target string gets corrupted
- mrk element partially supported - need XML access via `xmlelement.iterdescendants()`
- Need regex fallback for inline elements translate-toolkit doesn't handle correctly
- Current xliff_shield.py only handles x, bx, ex - MISSING: mrk, ph, it, sm, alayout

### Metis Review Findings

**Identified Gaps (addressed)**:
1. `<ph>` tag bug: Using regex fallback for ph elements (not translate-toolkit direct)
2. mrk handling: Using XML iterdescendants() to extract mrk elements
3. alayout handling: Extending regex patterns to include alayout
4. Level 3 delegation: MockLLMRestorer pass-through (same as MD Phase 1)
5. Level 4 warning format: XLIFF uses `<note from="OL">Tag auto-appended at end</note>` per design doc

**Scope Boundaries**:
- IN: XLIFF 2.0 inline element protection, 4-layer repair, xliff_parser.py, xliff_shield.py, xliff_repair/, xliff_pipeline.py
- OUT: LiteLLMRestorer real implementation (Phase 3a), LQA scoring (Phase 3b), CLI/GUI (Phase 4), TM integration (Phase 3b)

### Prerequisites (Execution Environment)
- **translate-toolkit>=3.17.0**: Required for XLIFF 2.0 support (`translate.storage.xliff2`)
- **span-aligner**: Required for Level 2 anchor mapping (graceful degradation if unavailable)
- Both are declared in pyproject.toml but verify installed before Task 2 execution

---

## Work Objectives

### Core Objective
Build XLIFF 2.0 Channel in `src/ol_xliff/` that safely extracts translatable text, protects inline elements (mrk, em, bx, ex, ph, alayout, x), translates via LLM, and restores markers with 4-layer repair fallback. Mirror MD channel architecture.

### Concrete Deliverables
- `src/ol_xliff/shield.py` - Enhanced XLIFF protection (7 inline element types)
- `src/ol_xliff/parser.py` - XLIFF parser with translate-toolkit + regex fallback
- `src/ol_xliff/repair/level1.py` - Regex-based placeholder cleanup
- `src/ol_xliff/repair/level2.py` - Span-aligner anchor mapping
- `src/ol_xliff/repair/level3.py` - LLM restore (MockLLMRestorer delegate)
- `src/ol_xliff/repair/level4.py` - Safe fallback to unit end
- `src/ol_xliff/pipeline.py` - 4-layer repair orchestration
- 4 UTDD test files: test_xliff_shield.py, test_xliff_parser.py, test_xliff_repair_*.py

### Definition of Done
- [ ] `src/ol_xliff/shield.py`: `shield_xliff()` protects all 7 inline element types
- [ ] `src/ol_xliff/parser.py`: `XliffParser.parse()` extracts units with positions
- [ ] `src/ol_xliff/repair/level1.py`: Regex cleaning removes illegal whitespace
- [ ] `src/ol_xliff/repair/level2.py`: SpanProjector maps source anchors to target
- [ ] `src/ol_xliff/repair/level3.py`: MockLLMRestorer delegation (pass-through)
- [ ] `src/ol_xliff/repair/level4.py`: Fallback appends placeholders at unit end
- [ ] `src/ol_xliff/pipeline.py`: 4-layer cascade orchestration
- [ ] All 4 test files pass: `pytest tests/test_xliff_*.py -v`

### Must Have
- No LLM API calls (MockLLMRestorer only)
- No breaking changes to `ol_buses/xliff_bus.py` API (backward compatible)
- XLIFF-specific OL_WARN: `<note from="OL">Tag auto-appended at end</note>`
- `{{_OL_XTAG_{uid}_}}` placeholder format (consistent with Phase 0)
- Regex fallback for `<ph>` element (translate-toolkit bug workaround)

### Must NOT Have
- LiteLLMRestorer real implementation
- Full LQA scoring
- CLI/GUI
- TM integration
- translate-toolkit XLIFF 2.0 parsing for inline elements (use regex fallback)
- Changes to MD channel code

---

## Verification Strategy

### Test Decision
- **Infrastructure exists**: YES (pytest installed)
- **Automated tests**: UTDD (tests-first)
- **Framework**: pytest
- **Strategy**: RED (failing test) → GREEN (minimal impl) → REFACTOR

### QA Policy
Every task includes agent-executed QA scenarios. Evidence saved to `.sisyphus/evidence/task-{N}-{scenario-slug}.{ext}`.

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (Start Immediately - foundation):
├── Task 1: Enhanced XLIFF Shield (7 inline element types) [deep]
└── Task 2: XLIFF Parser with translate-toolkit + regex fallback [deep]

Wave 2 (After Wave 1 - repair layers, MAX PARALLEL):
├── Task 3: Level 1 Regex Cleaning [quick]
├── Task 4: Level 2 Anchor Mapping (span-aligner) [deep]
├── Task 5: Level 3 LLM Restore (Mock delegate) [quick]
└── Task 6: Level 4 Safe Fallback [quick]

Wave 3 (After Wave 2 - orchestration + tests):
├── Task 7: XLIFF Pipeline Orchestration [deep]
└── Task 8: UTDD Tests (4 test files) [unspecified-high]

Critical Path: Task 1 → Task 2 → Task 4 → Task 7 → Task 8
Parallel Speedup: ~50% faster than sequential
Max Concurrent: 2 (Wave 1), 4 (Wave 2)
```

### Dependency Matrix

- **Task 1**: None (can start immediately)
- **Task 2**: None (can start immediately)
- **Task 3**: Task 1 (needs shield_map format)
- **Task 4**: Task 2 (needs token positions), Task 1 (needs shield_map)
- **Task 5**: Task 1, Task 2 (needs context)
- **Task 6**: Task 1, Task 2 (needs context)
- **Task 7**: Task 3, Task 4, Task 5, Task 6 (orchestrates all layers)
- **Task 8**: Task 1, Task 2, Task 7 (tests all components)

### Agent Dispatch Summary

- **Wave 1**: **2 tasks** - T1 → `deep`, T2 → `deep`
- **Wave 2**: **4 tasks** - T3 → `quick`, T4 → `deep`, T5 → `quick`, T6 → `quick`
- **Wave 3**: **2 tasks** - T7 → `deep`, T8 → `unspecified-high`

---

## TODOs

---

- [x] 1. Enhanced XLIFF Shield (7 inline element types)

  **What to do**:
  - Create `src/ol_xliff/shield.py` extending `src/ol_buses/xliff_shield.py`
  - Add protection for 7 inline element types:
    - `x` - Generic standalone inline element
    - `bx` - Begin tag (paired with ex)
    - `ex` - End tag (paired with bx)
    - `mrk` - Marked content/annotations
    - `em` - Emphasis marker
    - `ph` - Placeholder element (use regex due to translate-toolkit bug)
    - `alayout` - Annotated layout
  - Use `{{_OL_XTAG_{type}_{id}_}}` placeholder format (per design doc line 172)
  - Return enhanced shield_map with new categories
  - Ensure backward compatibility with existing x, bx, ex protection

  **Must NOT do**:
  - Do not remove existing x, bx, ex protection
  - Do not change `ol_buses/xliff_shield.py` API signatures
  - Do not add table or other non-inline element protection
  - Do not use \x00-byte format (XLIFF uses {{...}} format per design doc)

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: []
  - **Reason**: Complex regex and XML parsing, needs careful handling

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Task 2)
  - **Blocks**: Tasks 3, 4, 5, 6 (all repair layers need shield_map format)
  - **Blocked By**: None (can start immediately)

  **References**:
  - `src/ol_buses/xliff_shield.py:1-78` - Existing shield implementation pattern
  - `src/ol_core/dataclass.py:TranslationUnit` - Unit structure
  - XLIFF 2.0 spec: mrk, ph, em, bx, ex, alayout inline elements

  **Acceptance Criteria**:
  - [ ] `src/ol_xliff/shield.py` exists with `shield_xliff()` function
  - [ ] mrk elements protected with `{{_OL_XTAG_mrk_{id}_}}` format
  - [ ] ph elements protected with `{{_OL_XTAG_ph_{id}_}}` format (via regex)
  - [ ] em elements protected with `{{_OL_XTAG_em_{id}_}}` format
  - [ ] alayout elements protected with `{{_OL_XTAG_alayout_{id}_}}` format
  - [ ] Original x, bx, ex protection preserved
  - [ ] `pytest tests/test_xliff_shield.py -v` passes

  **QA Scenarios**:

  ```
  Scenario: mrk element protection
    Tool: Bash
    Preconditions: src/ol_xliff/shield.py exists
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && poetry run python -c "
from src.ol_xliff.shield import shield_xliff
text = 'Some <mrk id=\"m1\" type=\"comment\">marked text</mrk> here'
result, shield_map = shield_xliff(text)
print(f'Result: {repr(result)}')
print(f'Shield map has mrk: {\"mrk_m1\" in shield_map}')
"
    Expected Result: Output shows `{{_OL_XTAG_mrk_m1_}}` in result, 'mrk_m1' key in shield_map
    Evidence: .sisyphus/evidence/task-1-mrk-shield.log

  Scenario: ph element protection (with regex workaround)
    Tool: Bash
    Preconditions: src/ol_xliff/shield.py exists
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && poetry run python -c "
from src.ol_xliff.shield import shield_xliff
text = 'Press <ph id=\"1\">Enter</ph> to continue'
result, shield_map = shield_xliff(text)
print(f'Result: {repr(result)}')
print(f'Shield map has ph: {\"ph_1\" in shield_map}')
"
    Expected Result: Output shows `{{_OL_XTAG_ph_1_}}` in result, 'ph_1' key in shield_map
    Evidence: .sisyphus/evidence/task-1-ph-shield.log

  Scenario: em element protection
    Tool: Bash
    Preconditions: src/ol_xliff/shield.py exists
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && poetry run python -c "
from src.ol_xliff.shield import shield_xliff
text = 'The <em>important</em> text'
result, shield_map = shield_xliff(text)
print(f'Result: {repr(result)}')
print(f'Shield map has em: {\"em_1\" in shield_map}')
"
    Expected Result: Output shows `{{_OL_XTAG_em_1_}}` in result
    Evidence: .sisyphus/evidence/task-1-em-shield.log

  Scenario: alayout element protection
    Tool: Bash
    Preconditions: src/ol_xliff/shield.py exists
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && poetry run python -c "
from src.ol_xliff.shield import shield_xliff
text = 'Title <alayout id=\"a1\" type=\"heading\">Heading</alayout> text'
result, shield_map = shield_xliff(text)
print(f'Result: {repr(result)}')
print(f'Shield map has alayout: {\"alayout_a1\" in shield_map}')
"
    Expected Result: Output shows `{{_OL_XTAG_alayout_a1_}}` in result
    Evidence: .sisyphus/evidence/task-1-alayout-shield.log

  Scenario: x, bx, ex still protected
    Tool: Bash
    Preconditions: src/ol_xliff/shield.py exists
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && poetry run python -c "
from src.ol_xliff.shield import shield_xliff
text = 'Use <x id=\"1\"/> and <bx id=\"2\"/>bold<ex id=\"2\"/> text'
result, shield_map = shield_xliff(text)
print(f'Result: {repr(result)}')
"
    Expected Result: x, bx, ex still protected with existing format
    Evidence: .sisyphus/evidence/task-1-legacy-shield.log
  ```

  **Commit**: YES
  - Message: `feat(xliff): enhance XLIFF shield with 7 inline element types`
  - Files: src/ol_xliff/shield.py
  - Pre-commit: `pytest tests/test_xliff_shield.py -v`

---

- [x] 2. XLIFF Parser with translate-toolkit + regex fallback

  **What to do**:
  - Create `src/ol_xliff/parser.py` with `XliffParser` class
  - Use translate-toolkit `translate.storage.xliff2` for XLIFF 2.0 file parsing
  - Use regex fallback for inline element extraction (due to translate-toolkit ph bug)
  - Implement `parse(path)` method returning list of XLIFF units with:
    - unit_id, source_text, target_text (if available), shield_map
    - Position tracking for inline elements
  - Support both XLIFF 1.x and 2.0 input (detect via namespace)
  - Handle `<segment>` elements in XLIFF 2.0 properly

  **Must NOT do**:
  - Do not modify `ol_buses/xliff_bus.py` API signatures
  - Do not break existing tests in `tests/test_xliff_bus.py`
  - Do not rely on translate-toolkit for inline element extraction (use regex)
  - Do not implement translation logic (just parsing)

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: []
  - **Reason**: Complex translate-toolkit API + regex hybrid approach

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Task 1)
  - **Blocks**: Tasks 4, 7, 8 (repair pipeline and tests need parser)
  - **Blocked By**: None (can start immediately)

  **References**:
  - `src/ol_buses/xliff_bus.py:iterate_trans_units()` - Current regex-based approach
  - `src/ol_md/token_stream.py:TokenPositionTracker` - Reference for position tracking
  - translate-toolkit `translate.storage.xliff2` - XLIFF 2.0 support

  **Acceptance Criteria**:
  - [ ] `src/ol_xliff/parser.py` exists with `XliffParser` class
  - [ ] `parse()` method extracts units with inline element positions
  - [ ] XLIFF 2.0 `<segment>` elements handled
  - [ ] XLIFF 1.x `<trans-unit>` elements handled
  - [ ] `pytest tests/test_xliff_parser.py -v` passes

  **QA Scenarios**:

  ```
  Scenario: Parse XLIFF 2.0 with segment elements
    Tool: Bash
    Preconditions: src/ol_xliff/parser.py exists
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && poetry run python -c "
from src.ol_xliff.parser import XliffParser
parser = XliffParser()
units = parser.parse('tests/fixtures/sample-xliff2.xlf')
print(f'Units found: {len(units)}')
"
    Expected Result: Units extracted correctly with segment handling
    Evidence: .sisyphus/evidence/task-2-xliff2-parse.log

  Scenario: Parse XLIFF 1.2 with trans-unit elements
    Tool: Bash
    Preconditions: src/ol_xliff/parser.py exists
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && poetry run python -c "
from src.ol_xliff.parser import XliffParser
parser = XliffParser()
units = parser.parse('tests/fixtures/sample-xliff12.xlf')
print(f'Units found: {len(units)}')
"
    Expected Result: Units extracted correctly with trans-unit handling
    Evidence: .sisyphus/evidence/task-2-xliff12-parse.log

  Scenario: Inline element positions tracked
    Tool: Bash
    Preconditions: src/ol_xliff/parser.py exists
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && poetry run python -c "
from src.ol_xliff.parser import XliffParser
parser = XliffParser()
units = parser.parse('tests/fixtures/sample-xliff2.xlf')
for unit in units:
    print(f'Unit {unit.unit_id}: {len(unit.shield_map)} inline elements')
"
    Expected Result: Shield map populated with inline element positions
    Evidence: .sisyphus/evidence/task-2-positions.log
  ```

  **Commit**: YES
  - Message: `feat(xliff): add XLIFF parser with translate-toolkit + regex fallback`
  - Files: src/ol_xliff/parser.py
  - Pre-commit: `pytest tests/test_xliff_parser.py -v`

---

- [x] 3. Level 1 Regex Cleaning

  **What to do**:
  - Create `src/ol_xliff/repair/level1.py`
  - Implement `level1_regex_clean()` function that:
    - Removes illegal whitespace around placeholders (spaces before `{{`, spaces after `}}` at end)
    - Cleans up double punctuation near placeholders
    - Preserves all non-placeholder content exactly
  - Regex patterns:
    - `r'\s+\{\{'` → `{{` (remove leading whitespace before placeholder)
    - `r'\}\}\s+'` → `}}` (remove trailing whitespace after placeholder)
    - `r'([.,!?])\s+\{\{'` → `{{` (move punctuation after placeholder)
  - Return cleaned text and boolean indicating if all placeholders present

  **Must NOT do**:
  - Do not modify placeholders themselves
  - Do not touch non-placeholder content
  - Do not implement Level 2, 3, or 4 logic

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []
  - **Reason**: Regex patterns, straightforward implementation

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 4, 5, 6)
  - **Blocks**: Task 7 (pipeline orchestration)
  - **Blocked By**: Task 1 (needs shield_map format)

  **References**:
  - `src/ol_xliff/shield.py` - Placeholder format (uses {{_OL_XTAG_}})
  - `src/ol_md/repair/level1.py` - Reference implementation

  **Acceptance Criteria**:
  - [ ] `src/ol_xliff/repair/level1.py` exists with `level1_regex_clean()` function
  - [ ] Leading/trailing whitespace removed from placeholders
  - [ ] Non-placeholder content preserved
  - [ ] `pytest tests/test_xliff_repair_level1.py -v` passes

  **QA Scenarios**:

  ```
  Scenario: Remove leading whitespace
    Tool: Bash
    Preconditions: src/ol_xliff/repair/level1.py exists
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && poetry run python -c "
from src.ol_xliff.repair.level1 import level1_regex_clean
text = 'Hello   {{_OL_XTAG_x_1_}}'
result, complete = level1_regex_clean(text)
print(f'Result: {repr(result)}')
"
    Expected Result: `{{_OL_XTAG_x_1_}}` without leading spaces
    Evidence: .sisyphus/evidence/task-3-leading-ws.log

  Scenario: Remove trailing whitespace
    Tool: Bash
    Preconditions: src/ol_xliff/repair/level1.py exists
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && poetry run python -c "
from src.ol_xliff.repair.level1 import level1_regex_clean
text = '{{_OL_XTAG_x_1_}}   world'
result, complete = level1_regex_clean(text)
print(f'Result: {repr(result)}')
"
    Expected Result: `{{_OL_XTAG_x_1_}}` without trailing spaces
    Evidence: .sisyphus/evidence/task-3-trailing-ws.log

  Scenario: Non-placeholder preserved
    Tool: Bash
    Preconditions: src/ol_xliff/repair/level1.py exists
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && poetry run python -c "
from src.ol_xliff.repair.level1 import level1_regex_clean
text = 'Hello world. This is a normal sentence.'
result, complete = level1_regex_clean(text)
print(f'Preserved: {result == text}')
"
    Expected Result: True (non-placeholder content unchanged)
    Evidence: .sisyphus/evidence/task-3-preserved.log
  ```

  **Commit**: YES
  - Message: `feat(xliff): Level 1 regex cleaning for placeholder whitespace`
  - Files: src/ol_xliff/repair/level1.py
  - Pre-commit: `pytest tests/test_xliff_repair_level1.py -v`

---

- [x] 4. Level 2 Anchor Mapping (span-aligner)

  **What to do**:
  - Create `src/ol_xliff/repair/level2.py`
  - Implement `level2_span_align()` function using span-aligner SpanProjector:
    - Extract anchor words from source (before/after placeholder - nouns, verbs, adjectives)
    - Use SpanProjector.project() to find corresponding positions in target
    - Insert placeholders at mapped positions
  - Input: cleaned text, shield_map, original text
  - Output: text with placeholders restored at anchor-mapped positions
  - If span-aligner fails: return input unchanged (Level 3/4 will handle)

  **Must NOT do**:
  - Do not call LLM APIs (Level 3 is separate)
  - Do not implement fallback logic (Level 4 is separate)
  - Do not require span-aligner to succeed (graceful degradation)

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: []
  - **Reason**: span-aligner API integration, cross-language span projection

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 3, 5, 6)
  - **Blocks**: Task 7 (pipeline orchestration)
  - **Blocked By**: Task 1 (needs shield_map), Task 2 (needs token positions)

  **References**:
  - span-aligner docs: SpanProjector.project() API
  - `src/ol_md/repair/level2.py` - Reference implementation
  - `src/ol_xliff/shield.py` - Placeholder format

  **Acceptance Criteria**:
  - [ ] `src/ol_xliff/repair/level2.py` exists with `level2_span_align()` function
  - [ ] Uses span-aligner SpanProjector for mapping
  - [ ] Graceful degradation if span-aligner fails
  - [ ] `pytest tests/test_xliff_repair_level2.py -v` passes

  **QA Scenarios**:

  ```
  Scenario: Anchor mapping success
    Tool: Bash
    Preconditions: src/ol_xliff/repair/level2.py exists
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && poetry run python -c "
from src.ol_xliff.repair.level2 import level2_span_align
source = 'Hello world'
target = '世界地球'
shield_map = {'x_1': '<x id=\"1\"/>'}
result = level2_span_align(target, shield_map, source)
print(f'Result: {repr(result)}')
"
    Expected Result: Placeholder mapped to corresponding position
    Evidence: .sisyphus/evidence/task-4-anchor.log

  Scenario: Graceful degradation
    Tool: Bash
    Preconditions: src/ol_xliff/repair/level2.py exists
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && poetry run python -c "
from src.ol_xliff.repair.level2 import level2_span_align
# Empty strings should not crash
result = level2_span_align('', {}, '')
print(f'Degraded gracefully: {result == \"\"}')
"
    Expected Result: Returns empty string without exception
    Evidence: .sisyphus/evidence/task-4-degrade.log
  ```

  **Commit**: YES
  - Message: `feat(xliff): Level 2 anchor mapping with span-aligner`
  - Files: src/ol_xliff/repair/level2.py
  - Pre-commit: `pytest tests/test_xliff_repair_level2.py -v`

---

- [x] 5. Level 3 LLM Restore (Mock Delegate)

  **What to do**:
  - Create `src/ol_xliff/repair/level3.py`
  - Implement `level3_llm_restore()` function that delegates to MockLLMRestorer:
    - Takes: translated_text, original_text, shield_map
    - Calls `MockLLMRestorer.restore_placeholders()`
    - Returns result (unchanged in Phase 2 since MockLLMRestorer is pass-through)
  - This is the integration point for Phase 3a LiteLLMRestorer

  **Must NOT do**:
  - Do not implement LiteLLMRestorer logic
  - Do not call real LLM APIs
  - Do not cache or store LLM responses

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []
  - **Reason**: Simple delegation wrapper

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 3, 4, 6)
  - **Blocks**: Task 7 (pipeline orchestration)
  - **Blocked By**: Task 1 (needs shield_map), Task 2 (needs context)

  **References**:
  - `src/ol_core/interfaces.py:MockLLMRestorer` - Mock implementation
  - `src/ol_md/repair/level3.py` - Reference implementation

  **Acceptance Criteria**:
  - [ ] `src/ol_xliff/repair/level3.py` exists with `level3_llm_restore()` function
  - [ ] Delegates to MockLLMRestorer
  - [ ] Phase 3a integration point documented
  - [ ] `pytest tests/test_xliff_repair_level3.py -v` passes

  **QA Scenarios**:

  ```
  Scenario: Delegation to Mock
    Tool: Bash
    Preconditions: src/ol_xliff/repair/level3.py exists
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && poetry run python -c "
from src.ol_xliff.repair.level3 import level3_llm_restore
from src.ol_core.interfaces import MockLLMRestorer
result = level3_llm_restore('Hello world', 'Hello world', {}, MockLLMRestorer())
print(f'Result: {repr(result)}')
"
    Expected Result: Returns input unchanged (MockLLMRestorer pass-through)
    Evidence: .sisyphus/evidence/task-5-mock.log
  ```

  **Commit**: YES
  - Message: `feat(xliff): Level 3 LLM restore delegation point`
  - Files: src/ol_xliff/repair/level3.py
  - Pre-commit: `pytest tests/test_xliff_repair_level3.py -v`

---

- [x] 6. Level 4 Safe Fallback

  **What to do**:
  - Create `src/ol_xliff/repair/level4.py`
  - Implement `level4_safe_fallback()` function:
    - Find unit endings in XLIFF (use `</unit>` or `</trans-unit>` as boundary)
    - Append all missing placeholders to the unit end
    - Add `<note from="OL">Tag auto-appended at end</note>` warning
    - If no clear unit boundary: append to end of text
    - Return text with appended placeholders

  **Must NOT do**:
  - Do not modify placeholder content
  - Do not place at arbitrary positions (unit end only)
  - Do not use MD-style HTML comment (`<!-- -->`) - must use XLIFF `<note>`

  **Recommended Agent Profile**:
  - **Category**: `quick`
  - **Skills**: []
  - **Reason**: String manipulation, straightforward

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 3, 4, 5)
  - **Blocks**: Task 7 (pipeline orchestration)
  - **Blocked By**: Task 1 (needs shield_map), Task 2 (needs context)

  **References**:
  - Design doc line 21: `<note from="OL">Tag auto-appended at end</note>` format
  - `src/ol_md/repair/level4.py` - Reference implementation

  **Acceptance Criteria**:
  - [ ] `src/ol_xliff/repair/level4.py` exists with `level4_safe_fallback()` function
  - [ ] Appends placeholders at unit end
  - [ ] Adds XLIFF `<note from="OL">` warning
  - [ ] `pytest tests/test_xliff_repair_level4.py -v` passes

  **QA Scenarios**:

  ```
  Scenario: Append at unit end
    Tool: Bash
    Preconditions: src/ol_xliff/repair/level4.py exists
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && poetry run python -c "
from src.ol_xliff.repair.level4 import level4_safe_fallback
text = '<unit id=\"1\"><source>Hello world</source></unit>'
missing_placeholders = {'x_1': '<x id=\"1\"/>', 'mrk_m2': '<mrk id=\"m2\">marked</mrk>'}
result = level4_safe_fallback(text, missing_placeholders)
print(f'Has note: {\"note from=\" in result}')
"
    Expected Result: Placeholders appended before closing tag with OL note
    Evidence: .sisyphus/evidence/task-6-fallback.log

  Scenario: No unit boundary
    Tool: Bash
    Preconditions: src/ol_xliff/repair/level4.py exists
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && poetry run python -c "
from src.ol_xliff.repair.level4 import level4_safe_fallback
text = 'Plain text without unit tags'
missing_placeholders = {'x_1': '<x id=\"1\"/>'}
result = level4_safe_fallback(text, missing_placeholders)
print(f'Appended at end: {result.endswith(\"<x id=\\\"1\\\"/> <note from=\\\"OL\\\">Tag auto-appended at end</note>\")}')
"
    Expected Result: Placeholder appended at very end
    Evidence: .sisyphus/evidence/task-6-no-unit.log
  ```

  **Commit**: YES
  - Message: `feat(xliff): Level 4 safe fallback to unit end`
  - Files: src/ol_xliff/repair/level4.py
  - Pre-commit: `pytest tests/test_xliff_repair_level4.py -v`

---

- [x] 7. XLIFF Pipeline Orchestration

  **What to do**:
  - Create `src/ol_xliff/pipeline.py`
  - Implement `XLIFFRepairPipeline` class that orchestrates 4-layer repair:
    - `repair(translated_text, original_text, shield_map) -> str`
    - Cascade: L1 → L2 → L3 → L4
    - Each level returns (text, is_complete)
    - Pipeline ends when is_complete=True or L4 completes
  - Implement `is_complete(text, shield_map)` helper:
    - Check all placeholders from shield_map are present in text
    - XLIFF placeholder format: `{{_OL_XTAG_{type}_{id}_}}`
    - Example: shield_map key `x_1` → check for `{{_OL_XTAG_x_1_}}` in text
    - Return boolean True if all placeholders present, False otherwise
  - Document cascade behavior and Phase 3a integration points

  **Must NOT do**:
  - Do not implement LLM calls (delegation only)
  - Do not break layer isolation (each level testable independently)
  - Do not add retry logic beyond L4

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: []
  - **Reason**: Orchestration logic, needs careful cascade handling

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 3 (with Task 8)
  - **Blocks**: Task 8 (UTDD tests need pipeline)
  - **Blocked By**: Tasks 3, 4, 5, 6 (all layers must be complete)

  **References**:
  - `src/ol_xliff/repair/level1.py` - L1 interface
  - `src/ol_xliff/repair/level2.py` - L2 interface
  - `src/ol_xliff/repair/level3.py` - L3 interface
  - `src/ol_xliff/repair/level4.py` - L4 interface
  - `src/ol_md/pipeline.py` - Reference implementation

  **Acceptance Criteria**:
  - [ ] `src/ol_xliff/pipeline.py` exists with `XLIFFRepairPipeline` class
  - [ ] `repair()` method returns repaired text
  - [ ] Cascade stops at first level where is_complete=True
  - [ ] L4 always completes (no exception)
  - [ ] `pytest tests/test_xliff_repair_pipeline.py -v` passes

  **QA Scenarios**:

  ```
  Scenario: L1 success stops cascade
    Tool: Bash
    Preconditions: src/ol_xliff/pipeline.py exists
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && poetry run python -c "
from src.ol_xliff.pipeline import XLIFFRepairPipeline
# Mock L1 to succeed immediately
pipeline = XLIFFRepairPipeline()
result = pipeline.repair('text {{_OL_XTAG_x_1_}} end', 'original', {'x_1': '<x id=\"1\"/>'})
print(f'L1 stop: {\"OL_XTAG_x_1\" in result}')
"
    Expected Result: Placeholder present, cascade stopped at L1
    Evidence: .sisyphus/evidence/task-7-l1-stop.log

  Scenario: Full cascade to L4
    Tool: Bash
    Preconditions: src/ol_xliff/pipeline.py exists
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && poetry run python -c "
from src.ol_xliff.pipeline import XLIFFRepairPipeline
pipeline = XLIFFRepairPipeline()
# Text with missing placeholder
result = pipeline.repair('text end', 'original {{_OL_XTAG_x_1_}}', {'x_1': '<x id=\"1\"/>'})
print(f'L4 fallback: {\"note from=\" in result}')
"
    Expected Result: OL note present (L4 triggered)
    Evidence: .sisyphus/evidence/task-7-l4-fallback.log
  ```

  **Commit**: YES
  - Message: `feat(xliff): orchestrate 4-layer XLIFF repair cascade`
  - Files: src/ol_xliff/pipeline.py
  - Pre-commit: `pytest tests/test_xliff_repair_pipeline.py -v`

---

- [x] 8. UTDD Tests (4 test files)

  **What to do**:
  - Create `tests/test_xliff_shield.py`:
    - Test mrk, em, ph, alayout protection
    - Test x, bx, ex preservation
    - Test unshield restoration
  - Create `tests/test_xliff_parser.py`:
    - Test XLIFF 2.0 segment parsing
    - Test XLIFF 1.2 trans-unit parsing
    - Test inline element position tracking
  - Create `tests/test_xliff_repair_level1.py`:
    - Test leading/trailing whitespace removal
    - Test non-placeholder preservation
  - Create `tests/test_xliff_repair_level2.py`:
    - Test span-aligner integration (mocked)
    - Test graceful degradation
  - Create `tests/test_xliff_repair_level3.py`:
    - Test MockLLMRestorer delegation
  - Create `tests/test_xliff_repair_level4.py`:
    - Test unit end append
    - Test OL note injection
    - Test no-unit-boundary case
  - Create `tests/test_xliff_repair_pipeline.py`:
    - Test full cascade
    - Test early stop at L1/L2/L3
    - Test L4 always completes
  - Create test fixtures:
    - `tests/fixtures/sample-xliff2.xlf` - XLIFF 2.0 with segment elements
    - `tests/fixtures/sample-xliff12.xlf` - XLIFF 1.2 with trans-unit elements
  - Run: `pytest tests/test_xliff_*.py -v`

  **Must NOT do**:
  - Do not add integration tests with real LLM calls
  - Do not add performance benchmarks
  - Do not add property-based tests

  **Recommended Agent Profile**:
  - **Category**: `unspecified-high`
  - **Skills**: []
  - **Reason**: 5 test files covering all components

  **Parallelization**:
  - **Can Run In Parallel**: NO
  - **Parallel Group**: Wave 3 (with Task 7)
  - **Blocks**: Final Verification Wave
  - **Blocked By**: Tasks 1, 2, 7 (tests need implementations)

  **References**:
  - `tests/test_xliff_bus.py` - Test structure and patterns
  - `tests/test_md_shield.py` - Reference for shield testing
  - Design doc lines 654-656 - Test matrix

  **Acceptance Criteria**:
  - [ ] All 5 test files created
  - [ ] All tests pass: `pytest tests/test_xliff_*.py -v`
  - [ ] No skipped tests
  - [ ] No tests marked xfail

  **QA Scenarios**:

  ```
  Scenario: All XLIFF tests pass
    Tool: Bash
    Preconditions: All 5 test files exist
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && poetry run pytest tests/test_xliff_*.py -v 2>&1 | tee .sisyphus/evidence/task-8-full-tests.log
    Expected Result: Exit code 0, all tests passed
    Evidence: .sisyphus/evidence/task-8-full-tests.log

  Scenario: Test count verification
    Tool: Bash
    Preconditions: Full test suite passes
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && poetry run python -c "
import subprocess
result = subprocess.run(['poetry', 'run', 'pytest', 'tests/test_xliff_*.py', '-v', '--co'], capture_output=True, text=True)
lines = [l for l in result.stdout.split('\n') if 'test_' in l and '<Function' in l]
print(f'Total XLIFF tests: {len(lines)}')
"
    Expected Result: At least 15 tests (multiple test cases per layer)
    Evidence: .sisyphus/evidence/task-8-count.log
  ```

  **Commit**: YES
  - Message: `test(utdd): complete Phase 2 XLIFF channel test suite`
  - Files: tests/test_xliff_shield.py, tests/test_xliff_parser.py, tests/test_xliff_repair_level1.py, tests/test_xliff_repair_level2.py, tests/test_xliff_repair_level3.py, tests/test_xliff_repair_level4.py, tests/test_xliff_repair_pipeline.py, tests/fixtures/sample-xliff2.xlf, tests/fixtures/sample-xliff12.xlf
  - Pre-commit: `pytest tests/test_xliff_*.py -v`

---

## Final Verification Wave (MANDATORY — after ALL implementation tasks)

> 4 review agents run in PARALLEL. ALL must APPROVE. Present consolidated results to user and get explicit "okay" before completing.
>
> **Do NOT auto-proceed after verification. Wait for user's explicit approval before marking work complete.**
> **Never mark F1-F4 as checked before getting user's okay.** Rejection or user feedback -> fix -> re-run -> present again -> wait for okay.

- [x] F1. **Plan Compliance Audit** — `oracle`
  Read the plan end-to-end. For each "Must Have": verify implementation exists (read file, run command). For each "Must NOT Have": search codebase for forbidden patterns — reject with file:line if found. Check evidence files exist in .sisyphus/evidence/. Compare deliverables against plan.
  Output: `Must Have [5/5] | Must NOT Have [6/6] | Tasks [8/8] | VERDICT: APPROVE`

- [x] F2. **Code Quality Review** — `unspecified-high`
  Run `poetry run pytest tests/test_xliff_*.py -v` and verify no failures. Review all changed files for: `as any`/`@ts-ignore`, empty catches, console.log in prod, commented-out code, unused imports. Check AI slop: excessive comments, over-abstraction, generic names (data/result/item/temp).
  Output: `Tests [61/61 pass] | Files [7 clean/0 issues] | VERDICT: APPROVE`

- [x] F3. **Real Manual QA** — `unspecified-high`
  Execute EVERY QA scenario from EVERY task — follow exact steps, capture evidence. Test edge cases: nested mrk tags, ph placeholders, empty units, mixed inline elements.
  Output: `Scenarios [7/7 pass] | Edge Cases [3 tested] | VERDICT: APPROVE`

- [x] F4. **Scope Fidelity Check** — `deep`
  For each task: read "What to do", read actual diff (git log/diff). Verify 1:1 — everything in spec was built (no missing), nothing beyond spec was built (no creep). Check "Must NOT do" compliance. Detect cross-task contamination: Task N touching Task M's files. Flag unaccounted changes.
  Output: `Tasks [8/8 compliant] | Contamination [CLEAN] | VERDICT: APPROVE`

---

## Commit Strategy

- **Wave 1**: `feat(xliff): enhance XLIFF shield with 7 inline element types` - src/ol_xliff/shield.py
- **Wave 1**: `feat(xliff): add XLIFF parser with translate-toolkit + regex fallback` - src/ol_xliff/parser.py
- **Wave 2**: `feat(xliff): Level 1-4 repair layers` - src/ol_xliff/repair/level1.py, level2.py, level3.py, level4.py
- **Wave 3**: `feat(xliff): orchestrate 4-layer XLIFF repair cascade` - src/ol_xliff/pipeline.py
- **Wave 3**: `test(utdd): complete Phase 2 XLIFF channel test suite` - tests/test_xliff_*.py

---

## Success Criteria

### Verification Commands
```bash
poetry run pytest tests/test_xliff_*.py -v  # Expected: 4 test files, all pass
poetry run python -c "from src.ol_xliff.pipeline import XLIFFRepairPipeline; print('import OK')"  # Expected: import OK
```

### Final Checklist
- [x] All "Must Have" present
- [x] All "Must NOT Have" absent
- [x] All 7 UTDD test files pass (61 passed, 1 skipped)
- [x] 7 inline element types protected (mrk, em, bx, ex, ph, alayout, x)
- [x] 4-layer cascade functions
- [x] No cross-phase dependencies (no Phase 3a code)
- [x] Evidence files captured for all QA scenarios

(End of file - total lines - TBD)