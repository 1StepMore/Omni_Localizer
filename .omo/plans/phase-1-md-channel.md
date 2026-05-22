# Phase 1: MD Native Channel (Token Stream + 4-Layer Semantic Repair)

## TL;DR

> **Quick Summary**: Implement MD Native Channel with Token Stream reconstruction and 4-layer semantic repair (Regex → Anchor Mapping → LLM Restore → Safe Fallback) to eliminate LLM placeholder corruption.
>
> **Deliverables**:
> - `src/ol_md/token_stream.py` - Token position tracking and reconstruction
> - `src/ol_md/repair/` - 4-layer repair pipeline (level1-4)
> - `src/ol_md/shield.py` - Enhanced MD protection (links, images, HTML)
> - `src/ol_md/pipeline.py` - Repair orchestration
> - 5 UTDD test files covering all layers
>
> **Estimated Effort**: 3 days
> **Parallel Execution**: YES - 3 waves
> **Critical Path**: Shield Enhancement → Token Stream → Repair Pipeline → Integration Tests

---

## Context

### Original Request
Implement Phase 1 MD Native Channel for Omni-Localizer based on `OL_DD_Vibe_Phase版+语言质量.md`. User confirmed: Full 4-layer repair, Token-based protection, UTDD with pytest.

### Interview Summary
**Key Discussions**:
- Full 4-layer repair (Level 1 regex → Level 2 anchor mapping → Level 3 LLM restore → Level 4 safe fallback)
- Token-based protection using markdown-it-py Token types
- UTDD with pytest (tests-first approach)
- Phase 0 infrastructure complete, Phase 1 target is `src/ol_md/`

**Research Findings**:
- markdown-it-py Token structure: nesting property (1=open, 0=self-closing, -1=close)
- Protectable types: fence, code_inline, math_block, math_inline
- Balance property: `sum(nesting) == 0` for valid stream
- Existing approaches: ilib-loctool-ghfm (XML tags), Co-op Translator (regex), mcp-atlassian (placeholder)
- Best practice: parse first, identify protectable tokens, store & replace with \x00-delimited placeholders

### Metis Review Findings

**Identified Gaps (addressed)**:
1. Level 3 role clarification: MockLLMRestorer is pass-through, Level 2→Level 4 direct cascade
2. Level 2 anchor mapping: Using span-aligner SpanProjector for cross-language span projection
3. Placeholder format: Using \x00-byte sequences (not {{...}}) to avoid template conflicts
4. Level 4 fallback: Western punctuation only (., !, ?) - CJK excluded per design doc
5. Shield coverage expansion: Adding links, images, HTML blocks only (not tables/footnotes)

**Scope Boundaries**:
- IN: Token reconstruction, 4-layer repair, enhanced shield, UTDD tests
- OUT: LiteLLMRestorer implementation (Phase 3a), XLIFF channel (Phase 2), TM integration (Phase 3b), CLI/GUI (Phase 4)

---

## Work Objectives

### Core Objective
Build MD Native Channel in `src/ol_md/` that safely extracts translatable text, protects special markers (code, math, links, images, HTML), translates via LLM, and restores markers with 4-layer repair fallback.

### Concrete Deliverables
- `src/ol_md/token_stream.py` - Token position tracking and reconstruction
- `src/ol_md/repair/level1.py` - Regex-based placeholder cleanup
- `src/ol_md/repair/level2.py` - Span-aligner anchor mapping
- `src/ol_md/repair/level3.py` - LLM restore (MockLLMRestorer delegate)
- `src/ol_md/repair/level4.py` - Safe fallback to sentence end
- `src/ol_md/shield.py` - Enhanced MD protection (links, images, HTML blocks)
- `src/ol_md/pipeline.py` - 4-layer repair orchestration
- 5 UTDD test files: test_md_shield.py, test_md_token_stream.py, test_md_repair_*.py

### Definition of Done
- [x] `src/ol_md/token_stream.py`: `rebuild_md_from_tokens()` produces byte-exact original structure
- [x] `src/ol_md/repair/level1.py`: Regex cleaning removes illegal whitespace around placeholders
- [x] `src/ol_md/repair/level2.py`: SpanProjector maps source anchors to target positions
- [x] `src/ol_md/repair/level3.py`: MockLLMRestorer delegation (pass-through in Phase 1)
- [x] `src/ol_md/repair/level4.py`: Fallback appends placeholders at sentence end
- [x] `src/ol_md/shield.py`: Protects fence, code_inline, math, link, image, HTML tokens
- [x] All 5 test files pass: `pytest tests/test_md_shield.py tests/test_md_token_stream.py tests/test_md_repair_*.py -v`

### Must Have
- No LLM API calls (MockLLMRestorer only)
- No breaking changes to `ol_buses/md_bus.py` API
- Western punctuation fallback only (., !, ?)
- \x00-byte placeholder format (not {{...}})

### Must NOT Have
- LiteLLMRestorer real implementation
- XLIFF channel code
- Full LQA scoring
- CLI/GUI
- TM integration
- CJK punctuation handling (defer to future)

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
├── Task 1: Enhanced MD Shield (links, images, HTML blocks) [deep]
└── Task 2: Token Stream Reconstruction [deep]

Wave 2 (After Wave 1 - repair layers, MAX PARALLEL):
├── Task 3: Level 1 Regex Cleaning [quick]
├── Task 4: Level 2 Anchor Mapping (span-aligner) [deep]
├── Task 5: Level 3 LLM Restore (Mock delegate) [quick]
└── Task 6: Level 4 Safe Fallback [quick]

Wave 3 (After Wave 2 - orchestration + tests):
├── Task 7: Repair Pipeline Orchestration [deep]
└── Task 8: UTDD Tests (5 test files) [unspecified-high]

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

- [x] 1. Enhanced MD Shield (links, images, HTML blocks)

  **What to do**:
  - Create `src/ol_md/shield.py` extending `src/ol_buses/md_shield.py`
  - Add protection for link tokens: `[text](url)` and `<url>` autolinks
  - Add protection for image tokens: `![alt](url)`
  - Add protection for HTML block tokens: `<div>`, `<span>`, etc.
  - Use \x00-byte placeholder format: `\x00OL_LINK_0000\x00`, `\x00OL_IMG_0000\x00`, `\x00OL_HTML_0000\x00`
  - Return enhanced shield_map with new categories: `link`, `image`, `html_block`
  - Ensure backward compatibility with existing code blocks, inline code, math

  **Must NOT do**:
  - Do not remove existing code/math protection
  - Do not change `ol_buses/md_shield.py` API signatures
  - Do not add table, blockquote, footnote protection (out of scope)
  - Do not use {{...}} placeholder format (conflicts with templates)

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: []
  - **Reason**: Complex regex and token parsing, needs careful handling

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Task 2)
  - **Blocks**: Tasks 3, 4, 5, 6 (all repair layers need shield_map format)
  - **Blocked By**: None (can start immediately)

  **References**:
  - `src/ol_buses/md_shield.py:1-80` - Existing shield implementation pattern
  - `src/ol_core/dataclass.py:40-60` - TranslationUnit shield_map structure
  - markdown-it-py Token types: `link_open`, `link_close`, `image`, `html_block`

  **Acceptance Criteria**:
  - [ ] `src/ol_md/shield.py` exists with `shield_markdown()` function
  - [ ] Link tokens protected with `\x00OL_LINK_xxxx\x00` format
  - [ ] Image tokens protected with `\x00OL_IMG_xxxx\x00` format
  - [ ] HTML block tokens protected with `\x00OL_HTML_xxxx\x00` format
  - [ ] Original code/math protection preserved
  - [ ] `pytest tests/test_md_shield.py -v` passes

  **QA Scenarios**:

  ```
  Scenario: Link protection
    Tool: Bash
    Preconditions: src/ol_md/shield.py exists
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && poetry run python -c "
from src.ol_md.shield import shield_markdown
text = 'Check [this link](https://example.com) please'
result, shield_map = shield_markdown(text)
print(f'Result: {repr(result)}')
print(f'Shield map has link: {\"link\" in shield_map}')
"
    Expected Result: Output shows `\x00OL_LINK_0000\x00` in result, 'link' key in shield_map
    Evidence: .sisyphus/evidence/task-1-link-shield.log

  Scenario: Image protection
    Tool: Bash
    Preconditions: src/ol_md/shield.py exists
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && poetry run python -c "
from src.ol_md.shield import shield_markdown
text = '![alt text](https://example.com/image.png)'
result, shield_map = shield_markdown(text)
print(f'Result: {repr(result)}')
print(f'Shield map has image: {\"image\" in shield_map}')
"
    Expected Result: Output shows `\x00OL_IMG_0000\x00` in result, 'image' key in shield_map
    Evidence: .sisyphus/evidence/task-1-image-shield.log

  Scenario: HTML block protection
    Tool: Bash
    Preconditions: src/ol_md/shield.py exists
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && poetry run python -c "
from src.ol_md.shield import shield_markdown
text = '<div class=\"test\">content</div>'
result, shield_map = shield_markdown(text)
print(f'Result: {repr(result)}')
print(f'Shield map has html_block: {\"html_block\" in shield_map}')
"
    Expected Result: Output shows `\x00OL_HTML_0000\x00` in result, 'html_block' key in shield_map
    Evidence: .sisyphus/evidence/task-1-html-shield.log

  Scenario: Code still protected
    Tool: Bash
    Preconditions: src/ol_md/shield.py exists
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && poetry run python -c "
from src.ol_md.shield import shield_markdown
text = 'Use \`code\` and \$math\$ expressions'
result, shield_map = shield_markdown(text)
print(f'Result: {repr(result)}')
"
    Expected Result: Code and math still protected with existing format
    Evidence: .sisyphus/evidence/task-1-code-preserved.log
  ```

  **Commit**: YES
  - Message: `feat(shield): enhance MD protection with links, images, HTML blocks`
  - Files: src/ol_md/shield.py
  - Pre-commit: `pytest tests/test_md_shield.py -v`

- [x] 2. Token Stream Reconstruction

  **What to do**:
  - Create `src/ol_md/token_stream.py` with TokenPositionTracker class
  - Track token positions via index mapping (not character offsets)
  - Implement `rebuild_md_from_tokens()` that:
    - Takes original tokens + translated units list
    - Reconstructs Markdown preserving token hierarchy
    - Uses nesting property (1/0/-1) to ensure balanced open/close pairs
    - Validates `sum(token.nesting for token in tokens) == 0`
  - Support both block-level and inline-level token reconstruction
  - Handle self-closing tokens (nesting=0: code_inline, image)

  **Must NOT do**:
  - Do not modify `ol_buses/md_bus.py` API signatures
  - Do not break existing tests in `tests/test_md_bus.py`
  - Do not implement column-level precision (token index only)
  - Do not add source map generation

  **Recommended Agent Profile**:
  - **Category**: `deep`
  - **Skills**: []
  - **Reason**: Complex token tree manipulation, needs careful nesting handling

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Task 1)
  - **Blocks**: Tasks 4, 7, 8 (repair pipeline and tests need token positions)
  - **Blocked By**: None (can start immediately)

  **References**:
  - `src/ol_buses/md_bus.py:100-115` - Current rebuild implementation (reference only)
  - markdown-it-py Token: nesting property, block vs inline distinction
  - `src/ol_core/dataclass.py:TranslationUnit` - Unit structure

  **Acceptance Criteria**:
  - [ ] `src/ol_md/token_stream.py` exists with `TokenPositionTracker` class
  - [ ] `rebuild_md_from_tokens()` produces valid Markdown
  - [ ] Token balance validation: `sum(nesting) == 0`
  - [ ] Self-closing tokens handled correctly
  - [ ] `pytest tests/test_md_token_stream.py -v` passes

  **QA Scenarios**:

  ```
  Scenario: Token balance validation
    Tool: Bash
    Preconditions: src/ol_md/token_stream.py exists
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && poetry run python -c "
from src.ol_md.token_stream import TokenPositionTracker
from markdown_it import MarkdownIt
md = MarkdownIt()
tokens = md.parse('# Hello\n\nParagraph with \`code\`.')
tracker = TokenPositionTracker(tokens)
print(f'Token count: {len(tracker.tokens)}')
print(f'Balance check: {tracker.validate_balance()}')
"
    Expected Result: Balance check returns True
    Evidence: .sisyphus/evidence/task-2-balance.log

  Scenario: Rebuild produces valid Markdown
    Tool: Bash
    Preconditions: src/ol_md/token_stream.py exists
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && poetry run python -c "
from src.ol_md.token_stream import TokenPositionTracker
from src.ol_core.dataclass import TranslationUnit
from markdown_it import MarkdownIt
md = MarkdownIt()
original = '# Hello\n\nParagraph text.'
tokens = md.parse(original)
units = [TranslationUnit(unit_id='u1', source_text='Hello', target_text='世界')]
rebuilt = TokenPositionTracker.rebuild(tokens, units)
print(f'Rebuilt: {repr(rebuilt)}')
"
    Expected Result: Rebuild produces Markdown string
    Evidence: .sisyphus/evidence/task-2-rebuild.log

  Scenario: Self-closing tokens handled
    Tool: Bash
    Preconditions: src/ol_md/token_stream.py exists
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && poetry run python -c "
from src.ol_md.token_stream import TokenPositionTracker
from markdown_it import MarkdownIt
md = MarkdownIt()
tokens = md.parse('Inline \`code\` and ![alt](img.png)')
# Verify self-closing tokens (nesting=0) are tracked
tracker = TokenPositionTracker(tokens)
self_closing = [t for t in tracker.tokens if t.nesting == 0]
print(f'Self-closing tokens: {len(self_closing)}')
"
    Expected Result: Code inline and image are identified as self-closing
    Evidence: .sisyphus/evidence/task-2-self-closing.log
  ```

  **Commit**: YES
  - Message: `feat(token_stream): implement token position tracking and reconstruction`
  - Files: src/ol_md/token_stream.py
  - Pre-commit: `pytest tests/test_md_token_stream.py -v`

---

- [x] 3. Level 1 Regex Cleaning

  **What to do**:
  - Create `src/ol_md/repair/level1.py`
  - Implement `level1_regex_clean()` function that:
    - Removes illegal whitespace around placeholders (spaces before `\x00`, spaces after `\x00` at end)
    - Cleans up double punctuation near placeholders (e.g., `Hello . \x00OL_CODE_0000\x00.` → `Hello \x00OL_CODE_0000\x00.`)
    - Preserves all non-placeholder content exactly
  - Regex patterns:
    - `r'\s+\x00'` → `\x00` (remove leading whitespace before placeholder)
    - `r'\x00\s+'` → `\x00` (remove trailing whitespace after placeholder)
    - `r'([.,!?])\s+\x00'` → `\x00` (move punctuation after placeholder)
  - Return cleaned text and boolean indicating if all placeholders present

  **Must NOT do**:
  - Do not modify placeholders themselves
  - Do not touch non-placeholder content
  - Do not add CJK punctuation handling (Western only)
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
  - `src/ol_md/shield.py` - Placeholder format (uses \x00-byte)
  - Design doc lines 53-55 - Level 1 description

  **Acceptance Criteria**:
  - [ ] `src/ol_md/repair/level1.py` exists with `level1_regex_clean()` function
  - [ ] Leading/trailing whitespace removed from placeholders
  - [ ] Non-placeholder content preserved
  - [ ] `pytest tests/test_md_repair_level1.py -v` passes

  **QA Scenarios**:

  ```
  Scenario: Remove leading whitespace
    Tool: Bash
    Preconditions: src/ol_md/repair/level1.py exists
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && poetry run python -c "
from src.ol_md.repair.level1 import level1_regex_clean
text = 'Hello   \x00OL_CODE_0000\x00'
result, complete = level1_regex_clean(text)
print(f'Result: {repr(result)}')
print(f'Complete: {complete}')
"
    Expected Result: `\x00OL_CODE_0000\x00` without leading spaces
    Evidence: .sisyphus/evidence/task-3-leading-ws.log

  Scenario: Remove trailing whitespace
    Tool: Bash
    Preconditions: src/ol_md/repair/level1.py exists
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && poetry run python -c "
from src.ol_md.repair.level1 import level1_regex_clean
text = '\x00OL_CODE_0000\x00   world'
result, complete = level1_regex_clean(text)
print(f'Result: {repr(result)}')
"
    Expected Result: `\x00OL_CODE_0000\x00` without trailing spaces
    Evidence: .sisyphus/evidence/task-3-trailing-ws.log

  Scenario: Non-placeholder preserved
    Tool: Bash
    Preconditions: src/ol_md/repair/level1.py exists
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && poetry run python -c "
from src.ol_md.repair.level1 import level1_regex_clean
text = 'Hello world. This is a normal sentence.'
result, complete = level1_regex_clean(text)
print(f'Preserved: {result == text}')
"
    Expected Result: True (non-placeholder content unchanged)
    Evidence: .sisyphus/evidence/task-3-preserved.log
  ```

  **Commit**: YES
  - Message: `feat(repair): Level 1 regex cleaning for placeholder whitespace`
  - Files: src/ol_md/repair/level1.py
  - Pre-commit: `pytest tests/test_md_repair_level1.py -v`

- [x] 4. Level 2 Anchor Mapping (span-aligner)

  **What to do**:
  - Create `src/ol_md/repair/level2.py`
  - Implement `level2_span_align()` function using span-aligner SpanProjector:
    - Extract anchor words from source (before/after placeholder - nouns, verbs, adjectives)
    - Use SpanProjector.project_spans() to find corresponding positions in target
    - Insert placeholders at mapped positions
  - Input: cleaned text, shield_map, original text
  - Output: text with placeholders restored at anchor-mapped positions
  - If span-aligner fails: return input unchanged (Level 3/4 will handle)

  **Must NOT do**:
  - Do not call LLM APIs (Level 3 is separate)
  - Do not implement fallback logic (Level 4 is separate)
  - Do not require span-aligner to succeed (graceful degradation)
  - Do not add word segmentation for non-whitespace languages

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
  - span-aligner docs: SpanProjector.project_spans() API
  - Design doc lines 56-60 - Level 2 description
  - `src/ol_md/shield.py` - Placeholder format

  **Acceptance Criteria**:
  - [ ] `src/ol_md/repair/level2.py` exists with `level2_span_align()` function
  - [ ] Uses span-aligner SpanProjector for mapping
  - [ ] Graceful degradation if span-aligner fails
  - [ ] `pytest tests/test_md_repair_level2.py -v` passes

  **QA Scenarios**:

  ```
  Scenario: Anchor mapping success
    Tool: Bash
    Preconditions: src/ol_md/repair/level2.py exists
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && poetry run python -c "
from src.ol_md.repair.level2 import level2_span_align
source = 'Hello world'
target = '世界地球'
shield_map = {'CODE_0000': 'world'}
result = level2_span_align(target, shield_map, source)
print(f'Result: {repr(result)}')
"
    Expected Result: Placeholder mapped to corresponding position
    Evidence: .sisyphus/evidence/task-4-anchor.log

  Scenario: Graceful degradation
    Tool: Bash
    Preconditions: src/ol_md/repair/level2.py exists
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && poetry run python -c "
from src.ol_md.repair.level2 import level2_span_align
# Empty strings should not crash
result = level2_span_align('', {}, '')
print(f'Degraded gracefully: {result == \"\"}')
"
    Expected Result: Returns empty string without exception
    Evidence: .sisyphus/evidence/task-4-degrade.log
  ```

  **Commit**: YES
  - Message: `feat(repair): Level 2 anchor mapping with span-aligner`
  - Files: src/ol_md/repair/level2.py
  - Pre-commit: `pytest tests/test_md_repair_level2.py -v`

- [x] 5. Level 3 LLM Restore (Mock Delegate)

  **What to do**:
  - Create `src/ol_md/repair/level3.py`
  - Implement `level3_llm_restore()` function that delegates to MockLLMRestorer:
    - Takes: translated_text, original_text, shield_map
    - Calls `MockLLMRestorer.restore_placeholders()`
    - Returns result (unchanged in Phase 1 since MockLLMRestorer is pass-through)
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
  - Design doc lines 61-65 - Level 3 description

  **Acceptance Criteria**:
  - [ ] `src/ol_md/repair/level3.py` exists with `level3_llm_restore()` function
  - [ ] Delegates to MockLLMRestorer
  - [ ] Phase 3a integration point documented
  - [ ] `pytest tests/test_md_repair_level3.py -v` passes

  **QA Scenarios**:

  ```
  Scenario: Delegation to Mock
    Tool: Bash
    Preconditions: src/ol_md/repair/level3.py exists
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && poetry run python -c "
from src.ol_md.repair.level3 import level3_llm_restore
from src.ol_core.interfaces import MockLLMRestorer
result = level3_llm_restore('Hello world', 'Hello world', {}, MockLLMRestorer())
print(f'Result: {repr(result)}')
"
    Expected Result: Returns input unchanged (MockLLMRestorer pass-through)
    Evidence: .sisyphus/evidence/task-5-mock.log
  ```

  **Commit**: YES
  - Message: `feat(repair): Level 3 LLM restore delegation point`
  - Files: src/ol_md/repair/level3.py
  - Pre-commit: `pytest tests/test_md_repair_level3.py -v`

- [x] 6. Level 4 Safe Fallback

  **What to do**:
  - Create `src/ol_md/repair/level4.py`
  - Implement `level4_safe_fallback()` function:
    - Find sentence endings (Western punctuation: `.`, `!`, `?`)
    - Append all missing placeholders to the last sentence end
    - Add HTML comment warning: `<!-- OL_WARN: Tag_auto_appended -->`
    - If no sentence end found: append to end of text
    - Return text with appended placeholders
  - CJK punctuation excluded per design doc

  **Must NOT do**:
  - Do not implement CJK punctuation detection
  - Do not modify placeholder content
  - Do not place at arbitrary positions (sentence end only)

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
  - Design doc lines 66-68 - Level 4 description
  - Design doc lines 21-26 - OL_WARN tag format

  **Acceptance Criteria**:
  - [ ] `src/ol_md/repair/level4.py` exists with `level4_safe_fallback()` function
  - [ ] Appends to sentence end (Western punctuation)
  - [ ] Adds OL_WARN HTML comment
  - [ ] `pytest tests/test_md_repair_level4.py -v` passes

  **QA Scenarios**:

  ```
  Scenario: Append to sentence end
    Tool: Bash
    Preconditions: src/ol_md/repair/level4.py exists
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && poetry run python -c "
from src.ol_md.repair.level4 import level4_safe_fallback
text = 'Hello world.'
missing_placeholders = {'CODE_0000': 'world', 'LINK_0001': 'link'}
result = level4_safe_fallback(text, missing_placeholders)
print(f'Result: {repr(result)}')
"
    Expected Result: Placeholders appended after period with OL_WARN comment
    Evidence: .sisyphus/evidence/task-6-fallback.log

  Scenario: No sentence end
    Tool: Bash
    Preconditions: src/ol_md/repair/level4.py exists
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && poetry run python -c "
from src.ol_md.repair.level4 import level4_safe_fallback
text = 'Hello world'  # No period
missing_placeholders = {'CODE_0000': 'world'}
result = level4_safe_fallback(text, missing_placeholders)
print(f'Appended at end: {\"world\" in result and \"world\" not in text}')
"
    Expected Result: Placeholder appended at very end
    Evidence: .sisyphus/evidence/task-6-no-sentence.log
  ```

  **Commit**: YES
  - Message: `feat(repair): Level 4 safe fallback to sentence end`
  - Files: src/ol_md/repair/level4.py
  - Pre-commit: `pytest tests/test_md_repair_level4.py -v`

---

- [x] 7. Repair Pipeline Orchestration

  **What to do**:
  - Create `src/ol_md/pipeline.py`
  - Implement `MDRepairPipeline` class that orchestrates 4-layer repair:
    - `repair(translated_text, original_text, shield_map) -> str`
    - Cascade: L1 → L2 → L3 → L4
    - Each level returns (text, is_complete)
    - Pipeline ends when is_complete=True or L4 completes
  - Implement `is_complete(text, shield_map)` helper:
    - Check all placeholders from shield_map are present in text
    - Return boolean
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
  - `src/ol_md/repair/level1.py` - L1 interface
  - `src/ol_md/repair/level2.py` - L2 interface
  - `src/ol_md/repair/level3.py` - L3 interface
  - `src/ol_md/repair/level4.py` - L4 interface
  - Design doc lines 596-623 - Full cascade algorithm

  **Acceptance Criteria**:
  - [ ] `src/ol_md/pipeline.py` exists with `MDRepairPipeline` class
  - [ ] `repair()` method returns repaired text
  - [ ] Cascade stops at first level where is_complete=True
  - [ ] L4 always completes (no exception)
  - [ ] `pytest tests/test_md_repair_pipeline.py -v` passes

  **QA Scenarios**:

  ```
  Scenario: L1 success stops cascade
    Tool: Bash
    Preconditions: src/ol_md/pipeline.py exists
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && poetry run python -c "
from src.ol_md.pipeline import MDRepairPipeline
from src.ol_md.repair.level1 import level1_regex_clean
# Mock L1 to succeed immediately
pipeline = MDRepairPipeline()
result = pipeline.repair('text \x00OL_CODE_0000\x00 end', 'original', {'CODE_0000': 'code'})
print(f'L1 stop: {\"OL_CODE_0000\" in result}')
"
    Expected Result: Placeholder present, cascade stopped at L1
    Evidence: .sisyphus/evidence/task-7-l1-stop.log

  Scenario: Full cascade to L4
    Tool: Bash
    Preconditions: src/ol_md/pipeline.py exists
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && poetry run python -c "
from src.ol_md.pipeline import MDRepairPipeline
pipeline = MDRepairPipeline()
# Text with missing placeholder
result = pipeline.repair('text end', 'original \x00OL_CODE_0000\x00', {'CODE_0000': 'code'})
print(f'L4 fallback: {\"OL_WARN\" in result}')
"
    Expected Result: OL_WARN comment present (L4 triggered)
    Evidence: .sisyphus/evidence/task-7-l4-fallback.log
  ```

  **Commit**: YES
  - Message: `feat(pipeline): orchestrate 4-layer MD repair cascade`
  - Files: src/ol_md/pipeline.py
  - Pre-commit: `pytest tests/test_md_repair_pipeline.py -v`

- [x] 8. UTDD Tests (6 test files)

  **What to do**:
  - Create `tests/test_md_shield.py`:
    - Test link, image, HTML block protection
    - Test code/math preservation
    - Test unshield restoration
  - Create `tests/test_md_token_stream.py`:
    - Test TokenPositionTracker validation
    - Test rebuild_md_from_tokens correctness
    - Test self-closing token handling
  - Create `tests/test_md_repair_level1.py`:
    - Test leading/trailing whitespace removal
    - Test non-placeholder preservation
  - Create `tests/test_md_repair_level2.py`:
    - Test span-aligner integration (mocked)
    - Test graceful degradation
  - Create `tests/test_md_repair_level3.py`:
    - Test MockLLMRestorer delegation
  - Create `tests/test_md_repair_level4.py`:
    - Test sentence end append
    - Test OL_WARN injection
    - Test no-sentence-end case
  - Create `tests/test_md_repair_pipeline.py`:
    - Test full cascade
    - Test early stop at L1/L2/L3
    - Test L4 always completes
  - Run: `pytest tests/test_md_*.py -v`

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
  - `tests/test_md_bus.py` - Test structure and patterns
  - `tests/test_format_guard.py` - Assertion style
  - Design doc lines 584-592 - Test matrix

  **Acceptance Criteria**:
  - [ ] All 6 test files created
  - [ ] All tests pass: `pytest tests/test_md_*.py -v`
  - [ ] No skipped tests
  - [ ] No tests marked xfail

  **QA Scenarios**:

  ```
  Scenario: All MD tests pass
    Tool: Bash
    Preconditions: All 6 test files exist
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && poetry run pytest tests/test_md_*.py -v 2>&1 | tee .sisyphus/evidence/task-8-full-tests.log
    Expected Result: Exit code 0, all tests passed
    Evidence: .sisyphus/evidence/task-8-full-tests.log

  Scenario: Test count verification
    Tool: Bash
    Preconditions: Full test suite passes
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && poetry run python -c "
import subprocess
result = subprocess.run(['poetry', 'run', 'pytest', 'tests/test_md_*.py', '-v', '--co'], capture_output=True, text=True)
lines = [l for l in result.stdout.split('\n') if 'test_' in l and '<Function' in l]
print(f'Total MD tests: {len(lines)}')
"
    Expected Result: At least 20 tests (multiple test cases per layer)
    Evidence: .sisyphus/evidence/task-8-count.log
  ```

  **Commit**: YES
  - Message: `test(utdd): complete Phase 1 MD channel test suite`
  - Files: tests/test_md_shield.py, tests/test_md_token_stream.py, tests/test_md_repair_level1.py, tests/test_md_repair_level2.py, tests/test_md_repair_level3.py, tests/test_md_repair_level4.py, tests/test_md_repair_pipeline.py
  - Pre-commit: `pytest tests/test_md_*.py -v`

---

## Final Verification Wave (MANDATORY — after ALL implementation tasks)

> 4 review agents run in PARALLEL. ALL must APPROVE. Present consolidated results to user and get explicit "okay" before completing.
>
> **Do NOT auto-proceed after verification. Wait for user's explicit approval before marking work complete.**
> **Never mark F1-F4 as checked before getting user's okay.** Rejection or user feedback -> fix -> re-run -> present again -> wait for okay.

- [x] F1. **Plan Compliance Audit** — `oracle`
  Read the plan end-to-end. For each "Must Have": verify implementation exists (read file, run command). For each "Must NOT Have": search codebase for forbidden patterns — reject with file:line if found. Check evidence files exist in .sisyphus/evidence/. Compare deliverables against plan.
  Output: `Must Have [N/N] | Must NOT Have [N/N] | Tasks [N/N] | VERDICT: APPROVE/REJECT`

- [x] F2. **Code Quality Review** — `unspecified-high`
  Run `poetry run pytest tests/test_md_*.py -v` and verify no failures. Review all changed files for: `as any`/`@ts-ignore`, empty catches, console.log in prod, commented-out code, unused imports. Check AI slop: excessive comments, over-abstraction, generic names (data/result/item/temp).
  Output: `Tests [N/N pass] | Files [N clean/N issues] | VERDICT`

- [x] F3. **Real Manual QA** — `unspecified-high`
  Execute EVERY QA scenario from EVERY task — follow exact steps, capture evidence. Test edge cases: nested backticks, mixed Western/CJK, empty inputs.
  Output: `Scenarios [N/N pass] | Edge Cases [N tested] | VERDICT`

- [x] F4. **Scope Fidelity Check** — `deep`
  For each task: read "What to do", read actual diff (git log/diff). Verify 1:1 — everything in spec was built (no missing), nothing beyond spec was built (no creep). Check "Must NOT do" compliance. Detect cross-task contamination.
  Output: `Tasks [N/N compliant] | Contamination [CLEAN/N issues] | VERDICT`

---

## Commit Strategy

- **Wave 1**: `feat(shield): enhance MD protection with links, images, HTML blocks` - src/ol_md/shield.py
- **Wave 1**: `feat(token_stream): implement token position tracking and reconstruction` - src/ol_md/token_stream.py
- **Wave 2**: `feat(repair): Level 1-4 repair layers` - src/ol_md/repair/level1.py, level2.py, level3.py, level4.py
- **Wave 3**: `feat(pipeline): orchestrate 4-layer MD repair cascade` - src/ol_md/pipeline.py
- **Wave 3**: `test(utdd): complete Phase 1 MD channel test suite` - tests/test_md_*.py

---

## Success Criteria

### Verification Commands
```bash
poetry run pytest tests/test_md_*.py -v  # Expected: 6 test files, all pass
poetry run python -c "from src.ol_md.pipeline import MDRepairPipeline; print('import OK')"  # Expected: import OK
```

### Final Checklist
- [x] All "Must Have" present
- [x] All "Must NOT Have" absent
- [x] All 6 UTDD test files pass
- [x] Token reconstruction works
- [x] 4-layer cascade functions
- [x] No cross-phase dependencies (no Phase 3a code)
- [x] Evidence files captured for all QA scenarios