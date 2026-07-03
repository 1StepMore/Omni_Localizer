"""Tests for Phase 4 OL repair pipeline fixes (P4-T3, T4, T5, T6)."""
from pathlib import Path


_SRC = Path(__file__).resolve().parent.parent / "src"


def test_p4_t3_old_shield_module_deleted():
    """P4-T3: ol_buses/md_shield.py must be deleted (was the old currency-eating shield)."""
    p = _SRC / "ol_buses" / "md_shield.py"
    assert not p.exists(), (
        f"Old shield module still exists at {p}. It has the currency-eating regex "
        f"(no LaTeX guard) and conflicts with the new shield at src/ol_md/shield.py."
    )


def test_p4_t3_md_bus_uses_new_shield():
    """P4-T3: ol_buses/md_bus.py must import from the NEW shield (ol_md.shield), not the old one."""
    p = _SRC / "ol_buses" / "md_bus.py"
    if not p.exists():
        return  # If md_bus was also deleted, nothing to check
    content = p.read_text(encoding="utf-8")
    # Should NOT import from old shield
    assert "ol_buses.md_shield" not in content, (
        "md_bus.py still imports from the old ol_buses.md_shield module"
    )
    # Should import from new shield
    assert "ol_md.shield" in content or "ol_md import shield" in content, (
        "md_bus.py should import from ol_md.shield (the new one)"
    )


def test_p4_t3_init_does_not_export_old_shield():
    """P4-T3: ol_buses/__init__.py must not re-export from ol_buses.md_shield."""
    p = _SRC / "ol_buses" / "__init__.py"
    content = p.read_text(encoding="utf-8")
    assert "ol_buses.md_shield" not in content, (
        "ol_buses/__init__.py still imports from the old ol_buses.md_shield module"
    )


def test_p4_t4_level3_prompt_uses_correct_placeholder_format():
    """P4-T4: Level 3 LLM prompt must reference [OL:TYPE:NNNN] format, not UUID placeholders."""
    p = _SRC / "ol_md" / "repair" / "level3.py"
    content = p.read_text(encoding="utf-8")
    # The actual format is [OL:TYPE:NNNN]
    assert "[OL:" in content or "OL:TYPE" in content, (
        "Level 3 prompt should reference the [OL:TYPE:NNNN] placeholder format "
        "used by the actual shield"
    )
    # The wrong UUID format should not be the primary reference
    if "OLCODE" in content or "OLICODE" in content:
        assert False, (
            "Level 3 prompt still references UUID placeholders (OLCODE/OLICODE) "
            "which don't match the actual shield format"
        )


def test_p4_t5_level1_strips_prompt_injection():
    """P4-T5: Level 1 MD repair must strip CRITICAL/IMPORTANT/NOTE prompt-injection echoes."""
    p = _SRC / "ol_md" / "repair" / "level1.py"
    content = p.read_text(encoding="utf-8")
    # Check for the prompt-injection strip pattern (same as XLIFF level1)
    has_strip = (
        "CRITICAL" in content
        and "Output ONLY" in content
        and ("re.sub" in content or "subn" in content or "re.subn" in content)
    )
    assert has_strip, (
        "Level 1 MD repair must strip CRITICAL/IMPORTANT/NOTE prompt-injection echoes "
        "(XLIFF Level 1 has this at line 33-39; MD is missing it per AGENTS.md E2E-65 claim)"
    )


def test_p4_t5_level1_strips_injection_functionally():
    """P4-T5: Verify the strip actually works on sample prompt-injection text."""
    import sys
    sys.path.insert(0, str(_SRC))
    from ol_md.repair.level1 import level1_regex_clean
    # Simulate LLM echoing back the system prompt
    injected = "CRITICAL: Output ONLY the en translation. This is a test."
    cleaned, modified = level1_regex_clean(injected)
    assert "CRITICAL" not in cleaned, (
        f"level1_regex_clean failed to strip prompt injection. Output: {cleaned!r}"
    )
    assert "This is a test." in cleaned, (
        f"level1_regex_clean lost the actual translation content. Output: {cleaned!r}"
    )


def test_p4_t6_level4_no_false_warning():
    """P4-T6: Level 4 must NOT append 'Tag_auto_appended' warning when no placeholders are missing."""
    p = _SRC / "ol_md" / "repair" / "level4.py"
    content = p.read_text(encoding="utf-8")
    # Check the early return for empty missing_placeholders
    # The bug: returns text + warning even when nothing is missing
    # Look at lines 10-12 specifically
    lines = content.splitlines()
    # Find the early return
    for i, line in enumerate(lines):
        if "if not missing_placeholders" in line:
            # The next line should return text WITHOUT warning
            next_line = lines[i + 1].strip() if i + 1 < len(lines) else ""
            assert "OL_WARN" not in next_line, (
                f"Line {i+2}: Level 4 still appends false 'Tag_auto_appended' warning "
                f"when missing_placeholders is empty: {next_line!r}"
            )
            break


def test_p4_t6_level4_still_warns_when_missing():
    """P4-T6: Level 4 SHOULD append warning when there ARE actually missing placeholders."""
    import sys
    sys.path.insert(0, str(_SRC))
    from ol_md.repair.level4 import level4_safe_fallback
    # With actual missing placeholders, warning should be appended
    result = level4_safe_fallback("Hello [OL:CODE:0000] world.", {"code_0000": "[OL:CODE:0000]"})
    assert "OL_WARN" in result, (
        "Level 4 should still append OL_WARN when there are actual missing placeholders"
    )
