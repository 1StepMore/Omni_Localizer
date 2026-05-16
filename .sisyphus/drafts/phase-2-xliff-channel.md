# Draft: Phase 2 XLIFF Channel

## Requirements (confirmed)
- Full XLIFF 2.0 with inline elements
- Protectable types: mrk (marked segments), em (emphasis), bx (bold-explicit), ex (explicit), ph (placeholder), alayout (annotations)
- 4-layer repair cascade (similar to MD channel approach): Regex → Anchor Mapping → LLM Restore → Safe Fallback
- Uses \x00-byte placeholder format (consistent with MD channel)

## Technical Decisions
- TBD: translate-toolkit XLIFF 2.0 support level
- TBD: How inline elements are represented in translate-toolkit
- TBD: XLIFF 2.0 schema vs 1.2

## Research Findings

### Existing Implementation (Phase 0)
- `src/ol_buses/xliff_bus.py`: Basic load_xliff(), iterate_trans_units(), write_target_back() - REGEX-BASED
- `src/ol_buses/xliff_shield.py`: Basic tag extraction for x, bx, ex only - MISSING: mrk, ph, it, sm, alayout
- Uses `{{_OL_XTAG_{type}_{id}_}}` placeholder format (from design doc line 172)

### translate-toolkit XLIFF 2.0 Support
- **XLIFF 1.x**: `translate.storage.xliff` (legacy)
- **XLIFF 2.0**: `translate.storage.xliff2` (added v3.17.0)
- **Class hierarchy**: `Xliff2Unit → XliffUnit` (shared base)
- **CRITICAL BUG**: `<ph>` placeholder tag handling is broken (issue #4762)
- **mrk element**: Partially supported - need XML access via `xmlelement.iterdescendants()`

### Gaps vs Phase 1 MD Channel
| Feature | MD Channel (Phase 1) | XLIFF Channel (Phase 0) |
|---------|---------------------|------------------------|
| Shield | shield.py (5 types) | xliff_shield.py (3 types only: x,bx,ex) |
| Parser | token_stream.py | regex-based (no proper parsing) |
| Repair | 4-layer repair/ | NONE |
| Pipeline | pipeline.py | NONE |

### XLIFF 2.0 Inline Elements (from design doc)
- mrk (marked segments) - PARTIALLY SUPPORTED
- em (emphasis) - NOT HANDLED
- bx (bold-explicit) - HANDLED
- ex (explicit) - HANDLED
- ph (placeholder) - **BUGGY IN translate-toolkit**
- alayout (annotations) - NOT HANDLED
- x (generic inline) - HANDLED

### Placeholder Format
- MD: `\x00OL_TYPE_xxxx\x00` (byte-delimited)
- XLIFF: `{{_OL_XTAG_{type}_{id}_}}` (curly brace delimited)

## Open Questions
- How does translate-toolkit handle XLIFF 2.0 inline elements (mrk, em, bx)?
- What's the equivalent "token stream" approach for XLIFF?
- Should we use span-aligner for XLIFF as well?

## Scope Boundaries
- IN: XLIFF 2.0 inline element protection, 4-layer repair for XLIFF, xliff_shield.py, xliff_pipeline.py, xliff_repair/ layers
- OUT: LiteLLMRestorer (Phase 3a), LQA scoring (Phase 3b), CLI/GUI (Phase 4), TM integration (Phase 3b)

## Reference from Phase 1
- MD channel structure: shield.py → token_stream.py → repair/level1-4 → pipeline.py
- XLIFF channel should follow similar pattern: xliff_shield.py → xliff_parser.py → xliff_repair/level1-4 → xliff_pipeline.py

## Test Strategy
- UTDD with pytest (consistent with Phase 0 and Phase 1)
- Tests-first approach
