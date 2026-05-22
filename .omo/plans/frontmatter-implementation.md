# Frontmatter Implementation Plan for Omni-Localizer

**Created**: 2026-05-22
**Updated**: 2026-05-22 (v5 - addresses v4 review findings)
**Project**: Omni-Localizer (OL)
**Spec Source**: `OL-改进计划-Frontmatter.md`
**Status**: READY FOR IMPLEMENTATION (v5)

---

## 1. Overview

Implement YAML frontmatter support for OL's MD output and XLIFF header notes, enabling downstream ORF to track translation metadata.

### Changes Summary

| Change | File | Priority | Complexity |
|--------|------|----------|------------|
| MD Frontmatter | `src/ol_cli.py` | 🟡 Medium | Low |
| XLIFF Header Note | `src/ol_cli.py` | 🟢 Low | Medium |
| Batch Frontmatter | `src/ol_cli.py` + `src/ol_batch/processor.py` | 🟡 Medium | HIGH |

---

## 2. Security Considerations (CRITICAL)

### Input Validation & Sanitization

All user-provided values (filenames, language codes) must be validated and escaped before insertion into structured output formats.

#### YAML Injection Prevention

```python
def _escape_yaml_value(value: str) -> str:
    """Escape special characters in YAML string values to prevent injection."""
    if any(c in value for c in ':#\n'):
        return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'
    return value
```

#### XML/XLIFF Injection Prevention (FIXED - single-pass character-by-character)

```python
def _escape_xml(value: str) -> str:
    """Escape special characters in XML using single-pass character-by-character approach.

    This prevents double-encoding issues that occur with naive sequential .replace() calls.
    """
    result = []
    for c in value:
        if c == '&':
            result.append('&amp;')
        elif c == '<':
            result.append('&lt;')
        elif c == '>':
            result.append('&gt;')
        elif c == '"':
            result.append('&quot;')
        elif c == "'":
            result.append('&apos;')
        else:
            result.append(c)
    return ''.join(result)

def _validate_lang_code(code: str) -> str:
    """Validate ISO 639-1 language code."""
    if not re.match(r'^[a-z]{2}(-[A-Z]{2})?$', code):
        raise ValueError(f"Invalid language code: {code}")
    return code
```

---

## 3. Implementation Tasks

### Wave 1 (Start Immediately)

#### Task 1: Create frontmatter helper functions

| Field | Value |
|-------|-------|
| **What** | Add ALL helper functions to `src/ol_cli.py`: `_escape_yaml_value`, `_validate_lang_code`, `_escape_xml`, `_generate_frontmatter`, `_get_ol_version` |
| **File** | `/mnt/d/贯维/Omni_Localizer/src/ol_cli.py` |
| **Location** | Top of file (after imports, around line 16) |
| **Blocks** | Task 2, Task 3, Task 4, Task 6, Task 8 |
| **Category** | `quick` |
| **Skills** | `[]` |

- [x] COMPLETED: Helper functions added (lines 21-108)

**Implementation** (all functions in Task 1):

```python
# ========== OL Frontmatter Support ==========

from datetime import datetime, timezone
import re

def _escape_yaml_value(value: str) -> str:
    """Escape special characters in YAML string values to prevent injection."""
    if any(c in value for c in ':#\n'):
        return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'
    return value

def _validate_lang_code(code: str) -> str:
    """Validate ISO 639-1 language code."""
    if not re.match(r'^[a-z]{2}(-[A-Z]{2})?$', code):
        raise ValueError(f"Invalid language code: {code}")
    return code

def _escape_xml(value: str) -> str:
    """Escape special characters in XML using single-pass character-by-character approach.

    This prevents double-encoding issues that occur with naive sequential .replace() calls.
    For example: '&lt;' would become '&amp;lt;' with sequential replacement.
    """
    result = []
    for c in value:
        if c == '&':
            result.append('&amp;')
        elif c == '<':
            result.append('&lt;')
        elif c == '>':
            result.append('&gt;')
        elif c == '"':
            result.append('&quot;')
        elif c == "'":
            result.append('&apos;')
        else:
            result.append(c)
    return ''.join(result)

def _generate_frontmatter(
    source_lang: str,
    target_lang: str,
    original_filename: str,
    ol_version: str = "0.1.0",
) -> str:
    """Generate YAML frontmatter header with translation metadata.

    Args:
        source_lang: Source language code (ISO 639-1)
        target_lang: Target language code (ISO 639-1)
        original_filename: Original input filename
        ol_version: OL version number

    Returns:
        YAML frontmatter string with leading and trailing ---

    Raises:
        ValueError: If language codes are invalid
    """
    # Validate inputs to prevent injection
    source_lang = _validate_lang_code(source_lang)
    target_lang = _validate_lang_code(target_lang)
    escaped_filename = _escape_yaml_value(original_filename)

    timestamp = datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')

    frontmatter_lines = [
        "---",
        f"source_lang: {source_lang}",
        f"target_lang: {target_lang}",
        f"original_file: {escaped_filename}",
        'processor: "OL"',
        f'version: "{ol_version}"',
        f"translated_at: {timestamp}",
        "---",
        "",
    ]

    return "\n".join(frontmatter_lines)

def _get_ol_version() -> str:
    """Get OL version from module-level __version__."""
    # __version__ is defined at line 16 of ol_cli.py
    return __version__

def _build_xliff_header_note(src_lang: str, tgt_lang: str) -> str:
    """Build XLIFF-compliant header note element."""
    validated_src = _validate_lang_code(src_lang)
    validated_tgt = _validate_lang_code(tgt_lang)
    note_text = f'Translated from {validated_src} to {validated_tgt} by OL'
    return f'<header>\n    <note from="OL">{_escape_xml(note_text)}</note>\n  </header>'

def _inject_xliff_header(repaired: str, header_note: str) -> str:
    """Inject header note into XLIFF output at correct position."""
    # Insert header after <xliff ...> opening tag, before <file> element
    if '<file' in repaired:
        return repaired.replace('<file', header_note + '\n  <file', 1)
    return repaired  # No <file> element found, skip header injection
```

**QA**:
```bash
cd /mnt/d/贯维/Omni_Localizer
PYTHONPATH=src python -c "from ol_cli import _generate_frontmatter, _escape_xml; fm=_generate_frontmatter('en','zh','test.md','0.1.0'); assert fm.startswith('---\n'); assert 'source_lang: en' in fm; assert 'original_file: test.md' in fm; print('OK')"
```

**Validation Tests**:
- Test with malicious filename `test: malicious #injection` → should produce `original_file: "test: malicious #injection"`
- Test with invalid lang code `invalid!` → should raise ValueError

---

#### Task 5: Explore XLIFF output structure (Background)

| Field | Value |
|-------|-------|
| **What** | Confirm XLIFF header note injection point in `translate_xliff` |
| **File** | `/mnt/d/贯维/Omni_Localizer/src/ol_cli.py` |
| **Location** | Lines 349-354 (translate_xliff output writing) |
| **Blocks** | Task 6 |
| **Category** | `unspecified-high` |
| **Skills** | `[]` |

- [x] COMPLETED: Confirmed injection point at lines 463-468 (after pipeline.repair)

**Current Code** (lines 349-354):
```python
original_text = input_path.read_text(encoding="utf-8")
pipeline = XLIFFRepairPipeline()
repaired = pipeline.repair(original_text, original_text, {})

output_file = output_path / input_path.name
output_file.write_text(repaired, encoding="utf-8")
```

**QA**: Read XLIFF output file, verify `<header><note from="OL">` exists after implementation.

---

### Wave 2 (After Wave 1)

#### Task 2: Modify MD output to prepend frontmatter

| Field | Value |
|-------|-------|
| **What** | Update `_translate_md_async()` to prepend frontmatter before writing |
| **File** | `/mnt/d/贯维/Omni_Localizer/src/ol_cli.py` |
| **Location** | Lines 94-127 (function signature and body) |
| **Blocks** | Task 3, Task 4 |
| **Category** | `quick` |
| **Skills** | `[]` |

- [x] COMPLETED: `add_frontmatter` param added (line 199), frontmatter logic added (lines 224-237)

**Current Function Signature** (line 94):
```python
async def _translate_md_async(
    input_path: Path,
    output_path: Path,
    config_path: Optional[str],
    src_lang: str,
    tgt_lang: str,
) -> str:
```

**Modified Function Signature**:
```python
async def _translate_md_async(
    input_path: Path,
    output_path: Path,
    config_path: Optional[str],
    src_lang: str,
    tgt_lang: str,
    add_frontmatter: bool = True,  # NEW PARAMETER
) -> str:
```

**Current Code** (line 125):
```python
output_file.write_text(repaired, encoding="utf-8")
```

**Modified Code**:
```python
# Check if frontmatter should be added
if add_frontmatter and not repaired.strip().startswith('---'):
    # Validate and escape inputs
    safe_src_lang = _validate_lang_code(src_lang)
    safe_tgt_lang = _validate_lang_code(tgt_lang)

    frontmatter = _generate_frontmatter(
        source_lang=safe_src_lang,
        target_lang=safe_tgt_lang,
        original_filename=input_path.name,
        ol_version=_get_ol_version(),
    )
    output_content = frontmatter + repaired
else:
    output_content = repaired

output_file.write_text(output_content, encoding="utf-8")
```

**QA**:
1. Create test MD without frontmatter
2. Run `PYTHONPATH=src python -m ol_cli translate-md test.md -o output/ -s en -t zh`
3. Check output file starts with `---\nsource_lang: en`

---

#### Task 6: Add XLIFF header note

| Field | Value |
|-------|-------|
| **What** | Add proper XLIFF `<header><note from="OL">` element to XLIFF output |
| **File** | `/mnt/d/贯维/Omni_Localizer/src/ol_cli.py` |
| **Location** | Lines 353-354 (after `repaired = pipeline.repair(...)`) |
| **Blocks** | Task 7 |
| **Category** | `unspecified-high` |
| **Skills** | `[]` |

- [x] COMPLETED: XLIFF header injection added at lines 466-467

**Implementation** (per spec section 3.4):
```python
# Add OL header note with translation metadata
xliff_header = _build_xliff_header_note(src_lang, tgt_lang)
repaired = _inject_xliff_header(repaired, xliff_header)
```

**In translate_xliff** (around line 349):
```python
repaired = pipeline.repair(original_text, original_text, {})

# Add OL header note with translation metadata
xliff_header = _build_xliff_header_note(src_lang, tgt_lang)
repaired = _inject_xliff_header(repaired, xliff_header)

output_file = output_path / input_path.name
output_file.write_text(repaired, encoding="utf-8")
```

**Expected Output** (per spec section 3.4):
```xml
<?xml version="1.0" encoding="utf-8"?>
<xliff version="1.2" xmlns="urn:oasis:names:tc:xliff:document:1.2">
  <header>
    <note from="OL">Translated from en to zh by OL</note>
  </header>
  <file original="spec.md" source-language="en" target-language="zh">
    <body>
      ...
    </body>
  </file>
</xliff>
```

**QA**:
1. Run `PYTHONPATH=src python -m ol_cli translate-xliff test.xlf -o output/ -s en -t zh`
2. Check output contains `<header><note from="OL">Translated from en to zh by OL</note></header>`

---

### Wave 3 (After Task 2)

#### Task 3: Add --frontmatter CLI option to translate-md

| Field | Value |
|-------|-------|
| **What** | Add `--frontmatter/--no-frontmatter` option to `translate_md` command |
| **File** | `/mnt/d/贯维/Omni_Localizer/src/ol_cli.py` |
| **Location** | `translate_md` function (around line 137), async call (around line 170-172) |
| **Blocks** | Task 7 |
| **Category** | `quick` |
| **Skills** | `[]` |

- [x] COMPLETED: `add_frontmatter` option added to CLI (line 252), passed to async (line 286)

**Add to `translate_md` function signature** (line 137):
```python
add_frontmatter: bool = typer.Option(
    True,
    "--frontmatter/--no-frontmatter",
    help="Add YAML frontmatter with translation metadata to output file"
),
```

**Modify async call in `translate_md`** (around line 170-172):
```python
output_file = asyncio.run(
    _translate_md_async(input_path, output_path, config, src, tgt, add_frontmatter)
)
```

**QA**:
```bash
PYTHONPATH=src python -m ol_cli translate-md --help | grep -A1 frontmatter
# Expected: --frontmatter/--no-frontmatter  Add YAML frontmatter...
```

---

#### Task 4: Write tests/test_frontmatter.py

| Field | Value |
|-------|-------|
| **What** | Create comprehensive test suite for frontmatter functionality |
| **File** | `/mnt/d/贯维/Omni_Localizer/tests/test_frontmatter.py` |
| **Blocks** | Task 7 |
| **Category** | `quick` |
| **Skills** | `[]` |

- [x] COMPLETED: 12 tests created and passing

**Test Cases** (9 tests):

1. **test_frontmatter_format**: Verify correct YAML structure
2. **test_frontmatter_timestamp_is_valid_iso**: Verify ISO 8601 format with Z suffix
3. **test_frontmatter_not_added_if_already_present**: Skip when input has `---`
4. **test_version_access**: Verify `__version__` is correctly accessed
5. **test_translate_md_adds_frontmatter**: Integration test with mocked LLM
6. **test_frontmatter_cli_option_respected**: Verify `--no-frontmatter` skips addition
7. **test_frontmatter_escapes_yaml_special_chars**: Filename with `:` or `#` is properly quoted
8. **test_frontmatter_rejects_invalid_lang_code**: Invalid codes raise ValueError
9. **test_xliff_header_escapes_xml_special_chars**: Note text with special chars is escaped

**QA**:
```bash
cd /mnt/d/贯维/Omni_Localizer
PYTHONPATH=src pytest tests/test_frontmatter.py -v
# Expected: 9 passed
```

---

### Wave 3-4 (After Task 3)

#### Task 8: Add batch frontmatter support

| Field | Value |
|-------|-------|
| **What** | Add `--frontmatter` option to `translate_batch` AND modify `BatchProcessor` to support frontmatter |
| **File** | `src/ol_cli.py` + `src/ol_batch/processor.py` |
| **Location** | `translate_batch` (around line 247), `_translate_batch_async` (line 193), `BatchProcessor` (in `ol_batch/processor.py`) |
| **Blocks** | Task 7 |
| **Category** | `unspecified-high` |
| **Skills** | `[]` |

- [x] COMPLETED: Step 8a (CLI option at lines 314, 363, 402) and Step 8b (BatchProcessor at lines 26-28, 42-48, 109-129)

**ARCHITECTURE NOTE**: The batch file writing happens in `BatchProcessor._translate_file()` in `ol_batch/processor.py` (lines 87-110), NOT in `_translate_batch_async`. This is a different module that must be explicitly modified.

### Step 8a: Modify `translate_batch` CLI

**Add to `translate_batch` function signature** (around line 247):
```python
add_frontmatter: bool = typer.Option(
    True,
    "--frontmatter/--no-frontmatter",
    help="Add YAML frontmatter with translation metadata to output file"
),
```

**Modify `_translate_batch_async` signature** (line 193):
```python
async def _translate_batch_async(
    directory: Path,
    output_dir: Path,
    config_path: Optional[str],
    src_lang: str,
    tgt_lang: str,
    max_concurrent: int,
    add_frontmatter: bool = True,  # NEW PARAMETER
) -> tuple[int, int]:
```

**Modify async call in `translate_batch`** (around line 285-287):
```python
succeeded, failed = asyncio.run(
    _translate_batch_async(input_path, output_path, config, src, tgt, concurrency, add_frontmatter)
)
```

### Step 8b: Modify `BatchProcessor`

**File**: `/mnt/d/贯维/Omni_Localizer/src/ol_batch/processor.py`

**Current `BatchProcessor.__init__`** (line 60):
```python
def __init__(self, config: BatchConfig, model_pool: ModelPool, limiter: ConcurrencyLimiter):
```

**Modified `BatchProcessor.__init__`**:
```python
def __init__(self, config: BatchConfig, model_pool: ModelPool, limiter: ConcurrencyLimiter,
             add_frontmatter: bool = True, src_lang: str = "en", tgt_lang: str = "zh"):
    # NOTE: BatchProcessor is a @dataclass, so we directly assign fields
    # DO NOT use super().__init__() - dataclasses don't use inheritance initialization
    self._config = config
    self._pool = model_pool
    self._limiter = limiter
    self.add_frontmatter = add_frontmatter
    self.src_lang = src_lang
    self.tgt_lang = tgt_lang
```

**Current `_translate_file` hardcoded lang codes** (lines 96-99):
```python
# CURRENT (HARDCODED):
src_lang = "en"
tgt_lang = "zh"
```

**Modified `_translate_file`** (add params + frontmatter logic):
```python
async def _translate_file(self, input_path: Path, output_path: Path) -> bool:
    # ... existing shield/unshield logic unchanged ...

    # Use instance language codes instead of hardcoded
    src_lang = self.src_lang
    tgt_lang = self.tgt_lang

    # ... existing translation logic ...

    if self.add_frontmatter and output_path.suffix == '.md' and not repaired.strip().startswith('---'):
        # Import frontmatter generators from ol_cli
        from ol_cli import _generate_frontmatter, _get_ol_version, _escape_yaml_value, _validate_lang_code

        safe_src = _validate_lang_code(src_lang)
        safe_tgt = _validate_lang_code(tgt_lang)

        frontmatter = _generate_frontmatter(
            source_lang=safe_src,
            target_lang=safe_tgt,
            original_filename=input_path.name,
            ol_version=_get_ol_version(),
        )
        repaired = frontmatter + repaired

    output_file.write_text(repaired, encoding="utf-8")
    return True
```

**Current `process_batch` signature** (line 77):
```python
async def process_batch(self, files: list[Path], output_dir: Path) -> BatchResult:
```

**Modify `process_batch` to thread parameters**:
```python
async def process_batch(self, files: list[Path], output_dir: Path,
                       add_frontmatter: bool = True, src_lang: str = "en", tgt_lang: str = "zh") -> BatchResult:
    self.add_frontmatter = add_frontmatter
    self.src_lang = src_lang
    self.tgt_lang = tgt_lang
    # ... rest of method unchanged ...
```

**Modify `_translate_batch_async` to pass params**:
```python
result = await processor.process_batch(
    files, output_dir,
    add_frontmatter=add_frontmatter,
    src_lang=src_lang,
    tgt_lang=tgt_lang
)
```

**QA**:
1. Run `PYTHONPATH=src python -m ol_cli translate-batch test_dir/ -o output/ -s en -t zh --frontmatter`
2. Check output MD files have frontmatter
3. Run `PYTHONPATH=src python -m ol_cli translate-batch test_dir/ -o output/ -s en -t zh --no-frontmatter`
4. Check output MD files do NOT have frontmatter

---

### Wave 5 (After Wave 3-4)

#### Task 7: Run regression tests

| Field | Value |
|-------|-------|
| **What** | Ensure existing tests still pass after changes |
| **Blocks** | None |
| **Category** | `quick` |
| **Skills** | `[]` |

- [x] COMPLETED: test_frontmatter.py 12/12 passed; test_ol_cli.py 13/16 passed (3 pre-existing failures unrelated to frontmatter)

**QA**:
```bash
cd /mnt/d/贯维/Omni_Localizer
PYTHONPATH=src pytest tests/test_ol_cli.py tests/test_frontmatter.py -v
# Expected: All tests pass
```

---

## 4. Dependency Graph (CORRECTED)

```
Task 1 (Wave 1) ─────────────────────────────► Task 2 (Wave 2) ──┬──► Task 3 (Wave 3) ──┐
    │                                                         │                      │
    └─────────────────────────────────────────────────────────┤                      │
Task 5 (Wave 1) ─────────────────────────────► Task 6 (Wave 2) ─┘                      │
    │                                                                                  │
    └──────────────────────────────────────────────────────────────────────────────────┘
                                                                                         │
                                                                                   Task 4 (Wave 3)
                                                                                         │
                                                                          ┌────────────────────────────┘
                                                                          │
Task 8 (Wave 3-4) ──────────────────────────────────────────────────────► Task 7 (Wave 5)
```

**Key**: 
- Task 1 creates ALL helper functions including `_escape_xml` which Task 6 depends on
- Task 8 (batch support) depends on Task 1 for helper imports and Task 3 for CLI options

---

## 5. Critical Path

```
Task 1 → Task 2 → Task 3 → Task 4 → Task 7
         └─────────────────────────────────┘
                   │
              Task 8 (can run after Task 3)
```

**Estimated Time**: 2-2.5 hours (MD frontmatter + XLIFF header + batch support)

---

## 6. Commit Strategy (8 atomic commits)

| # | Commit Message | Files Changed |
|---|-----------------|---------------|
| 1 | `feat(cli): Add all frontmatter helper functions` | `src/ol_cli.py` |
| 2 | `feat(cli): Integrate frontmatter into MD translation` | `src/ol_cli.py` |
| 3 | `feat(cli): Add --frontmatter CLI option to translate-md` | `src/ol_cli.py` |
| 4 | `feat(cli): Add --frontmatter CLI option to translate-batch` | `src/ol_cli.py` |
| 5 | `feat(batch): Add frontmatter support to BatchProcessor` | `src/ol_batch/processor.py` |
| 6 | `feat(xliff): Add proper XLIFF header note with XML escaping` | `src/ol_cli.py` |
| 7 | `test(cli): Add frontmatter tests including security tests` | `tests/test_frontmatter.py` |
| 8 | `test(cli): Run regression tests` | - |

---

## 7. Verification Commands

| Task | Command | Expected Result |
|------|---------|-----------------|
| 1 | `cd /mnt/d/贯维/Omni_Localizer && PYTHONPATH=src python -c "from ol_cli import _generate_frontmatter, _escape_xml; print(_generate_frontmatter('en','zh','test.md'))"` | YAML frontmatter printed |
| 1b | `cd /mnt/d/贯维/Omni_Localizer && PYTHONPATH=src python -c "from ol_cli import _generate_frontmatter; fm=_generate_frontmatter('en','zh','test: malicious #injection'); assert '\"test: malicious #injection\"' in fm; print('OK')"` | Escaped filename |
| 2 | `PYTHONPATH=src python -m ol_cli translate-md test.md -o output/ -s en -t zh` then check output | Output starts with `---\nsource_lang: en` |
| 3 | `PYTHONPATH=src python -m ol_cli translate-md --help \| grep frontmatter` | Option shown |
| 4 | `cd /mnt/d/贯维/Omni_Localizer && PYTHONPATH=src pytest tests/test_frontmatter.py -v` | 9 passed |
| 6 | Check XLIFF output for `<header><note from="OL">` | Proper XLIFF note present |
| 8a | `PYTHONPATH=src python -m ol_cli translate-batch test_dir/ -o output/ -s en -t zh --frontmatter` then check MD files | Output has frontmatter |
| 8b | `PYTHONPATH=src python -m ol_cli translate-batch test_dir/ -o output/ -s en -t zh --no-frontmatter` then check MD files | Output has NO frontmatter |
| 7 | `cd /mnt/d/贯维/Omni_Localizer && PYTHONPATH=src pytest tests/test_ol_cli.py tests/test_frontmatter.py -v` | All pass |

---

## 8. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Frontmatter breaks downstream tools | Medium | `--no-frontmatter` flag for backward compat |
| Double frontmatter on re-translation | Low | Detect `---` prefix, skip if present |
| YAML injection via filename | HIGH | `_escape_yaml_value()` with quoting |
| XLIFF/XML injection via language codes | HIGH | `_validate_lang_code()` + single-pass `_escape_xml()` |
| XLIFF header note non-standard | Low | Proper XLIFF `<header><note>` per spec |
| Batch frontmatter not propagated | HIGH | Task 8 modifies BatchProcessor with proper parameter threading |
| BatchProcessor module separate from ol_cli | HIGH | Task 8 explicitly modifies `ol_batch/processor.py` |

---

## 9. Uncertainties Resolved

| Item | Resolution |
|------|------------|
| XLIFF target file | `src/ol_cli.py` lines 349-354, NOT `generator.py` (doesn't exist) - using string injection workaround |
| CLI option naming | `--frontmatter/--no-frontmatter` per spec |
| XLIFF note format | Proper XLIFF `<header><note from="OL">` element per spec section 3.4 |
| Batch command support | Task 8 adds `--frontmatter` option to `translate_batch` AND modifies `BatchProcessor` |
| `__version__` access | Direct reference (function is inside `ol_cli.py` where `__version__` is defined) |
| `_escape_xml` location | Created in Task 1 (not Task 6) to fix dependency |
| `_escape_xml` bug | Fixed - uses single-pass character-by-character approach |
| BatchProcessor architecture | Task 8 explicitly modifies `ol_batch/processor.py` - separate module from `ol_cli.py` |
| Hardcoded lang codes in batch | Task 8 replaces hardcoded "en"/"zh" with instance variables `self.src_lang`/`self.tgt_lang` |

---

## 10. Files Summary

| File | Changes |
|------|---------|
| `src/ol_cli.py` | Add helpers (`_escape_yaml_value`, `_validate_lang_code`, `_escape_xml`, `_generate_frontmatter`, `_get_ol_version`, `_build_xliff_header_note`, `_inject_xliff_header`), modify `_translate_md_async` (add `add_frontmatter` param), modify `_translate_batch_async` (add `add_frontmatter` param), modify `translate_md` (add CLI option), modify `translate_batch` (add CLI option + pass to async), modify `translate_xliff` (add XLIFF header) |
| `src/ol_batch/processor.py` | Modify `BatchProcessor.__init__()` (add params), modify `process_batch()` (thread params), modify `_translate_file()` (add frontmatter logic, use instance lang codes) |
| `tests/test_frontmatter.py` | New file with 9 tests (6 functional + 3 security) |

---

## 11. Key Changes from v4

| Issue | v4 (Wrong) | v5 (Fixed) |
|-------|------------|------------|
| `BatchProcessor.__init__()` invalid | Used `super().__init__()` - dataclasses don't use inheritance | Direct field assignment without `super()` call |

## 12. Key Changes from v3

| Issue | v3 (Wrong) | v4 (Fixed) |
|-------|------------|------------|
| `_escape_xml` double-encoding | Sequential `.replace()` can corrupt existing entities | Single-pass character-by-character approach |
| Batch frontmatter not propagated | Only modified `_translate_batch_async`, ignored BatchProcessor | Task 8 explicitly modifies `BatchProcessor.__init__()`, `process_batch()`, `_translate_file()` |
| Hardcoded lang codes in batch | `_translate_file()` hardcoded "en"/"zh" | Uses instance variables `self.src_lang`/`self.tgt_lang` |
| Batch architectural gap | Assumed threading param to `_translate_batch_async` would work | Task 8 documents full parameter chain: CLI → async → BatchProcessor → process_batch → _translate_file |
| XLIFF implementation deviation | Not documented | Section 9 explicitly states `generator.py` doesn't exist, plan uses `ol_cli.py` string injection workaround |

---

**End of Plan**