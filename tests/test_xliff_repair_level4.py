"""Tests for XLIFF repair level 4 (safe fallback)."""
from ol_xliff.repair.level4 import level4_safe_fallback


class TestRepairLevel4:
    """Test level4_safe_fallback() function.

    Contract: returns (text, warnings) tuple. Text no longer contains
    <note> XML — warnings are emitted separately so write_target_back
    can inject them as siblings of <target>, not nested inside.
    """

    def test_actual_tag_content_appended(self):
        text = '<unit id="1"><source>Hello world</source></unit>'
        missing_placeholders = {'x_1': '<x id="1"/>', 'mrk_m2': '<mrk id="m2">marked</mrk>'}
        text_out, warnings = level4_safe_fallback(text, missing_placeholders)

        assert '<x id="1"/>' in text_out
        assert '<mrk id="m2">marked</mrk>' in text_out
        assert '{{_OL_XTAG_' not in text_out
        assert '<note' not in text_out
        assert len(warnings) >= 1

    def test_ol_note_in_warnings(self):
        text = '<unit id="1"><source>Test</source></unit>'
        missing_placeholders = {'x_1': '<x id="1"/>'}
        text_out, warnings = level4_safe_fallback(text, missing_placeholders)

        assert '<note' not in text_out
        joined = ' '.join(warnings)
        assert 'Tag auto-appended' in joined or 'Warning' in joined

    def test_no_unit_boundary_fallback(self):
        text = 'Plain text without unit tags'
        missing_placeholders = {'x_1': '<x id="1"/>'}
        text_out, warnings = level4_safe_fallback(text, missing_placeholders)

        assert '<x id="1"/>' in text_out
        assert '{{_OL_XTAG_' not in text_out
        assert '<note' not in text_out
        assert len(warnings) >= 1

    def test_empty_text(self):
        text_out, warnings = level4_safe_fallback('', {'x_1': '<x id="1"/>'})
        assert '<x id="1"/>' in text_out
        assert len(warnings) >= 1

    def test_empty_missing_placeholders(self):
        text = '<unit id="1">Hello</unit>'
        result = level4_safe_fallback(text, {})
        assert result == (text, [])

    def test_multiple_missing_placeholders(self):
        text = '<trans-unit id="1"><source>Test</source></trans-unit>'
        missing_placeholders = {
            'x_1': '<x id="1"/>',
            'ph_2': '<ph id="2"/>',
            'mrk_m3': '<mrk id="m3">text</mrk>',
        }
        text_out, warnings = level4_safe_fallback(text, missing_placeholders)

        assert '<x id="1"/>' in text_out
        assert '<ph id="2"/>' in text_out
        assert '<mrk id="m3">text</mrk>' in text_out
        assert len(warnings) >= 1

    def test_trans_unit_boundary(self):
        text = '<trans-unit id="1"><source>Hello</source></trans-unit>'
        missing = {'bx_1': '<bx id="1"/>'}
        text_out, warnings = level4_safe_fallback(text, missing)

        assert '<bx id="1"/>' in text_out
        assert len(warnings) >= 1

    # POST_MORTEM ORF-5: insert at best-effort position, not at end-of-unit.

    def test_insert_after_inline_tag(self):
        text = '<unit id="1"><source>Hello <x id="1"/> world</source></unit>'
        missing = {'mrk_2': '<mrk id="2">new</mrk>'}
        text_out, warnings = level4_safe_fallback(text, missing)

        # New placeholder should be inserted right after the existing <x>
        # inline tag, not at end-of-unit.
        assert text_out.index('<mrk id="2">new</mrk>') < text_out.index('</source>')
        assert 'after-inline-tag' in warnings[0]

    def test_insert_after_ol_placeholder(self):
        text = '<unit id="1"><source>Hello {{_OL_XTAG_1}} world</source></unit>'
        missing = {'x_2': '<x id="2"/>'}
        text_out, warnings = level4_safe_fallback(text, missing)

        # New placeholder should be inserted right after the surviving
        # {{_OL_XTAG_*}} placeholder, not at end-of-unit.
        x_2_pos = text_out.index('<x id="2"/>')
        ol_pos = text_out.index('{{_OL_XTAG_1}}')
        assert x_2_pos > ol_pos
        assert x_2_pos < text_out.index('</source>')
        assert 'after-placeholder' in warnings[0]

    def test_insert_before_unit_end_when_no_inline(self):
        text = '<unit id="1"><source>Hello world</source></unit>'
        missing = {'x_1': '<x id="1"/>'}
        text_out, warnings = level4_safe_fallback(text, missing)

        # No inline tags or OL placeholders in text → fall back to
        # before </unit> (preserves unit structure).
        x_1_pos = text_out.index('<x id="1"/>')
        assert x_1_pos < text_out.index('</unit>')
        assert 'before-unit-end' in warnings[0]

    # ── bx/ex half-aware tests ─────────────────────────────────────────

    def test_bx_ex_both_missing_insert_both(self):
        text = '<unit id="1"><source>Hello world</source></unit>'
        missing = {'bx_1': '<bx id="1"/>', 'ex_1': '<ex id="1"/>'}
        text_out, warnings = level4_safe_fallback(text, missing)

        assert '<bx id="1"/>' in text_out
        assert '<ex id="1"/>' in text_out
        assert len(warnings) == 2

    def test_bx_in_text_ex_missing_only_ex_inserted(self):
        """bx already in text (L3 restored), ex missing → only ex inserted,
        bx not duplicated."""
        text = '<unit id="1"><source>Hello <bx id="1"/> world</source></unit>'
        missing = {'bx_1': '<bx id="1"/>', 'ex_1': '<ex id="1"/>'}
        text_out, warnings = level4_safe_fallback(text, missing)

        assert text_out.count('<bx id="1"/>') == 1, \
            "bx should not be duplicated"
        assert text_out.count('<ex id="1"/>') == 1, \
            "ex should be inserted once"
        assert len(warnings) == 1, \
            "only ex should be in warnings"

    def test_ex_in_text_bx_missing_only_bx_inserted(self):
        """ex already in text (L3 restored), bx missing → only bx inserted,
        ex not duplicated."""
        text = '<unit id="1"><source>Hello <ex id="1"/> world</source></unit>'
        missing = {'bx_1': '<bx id="1"/>', 'ex_1': '<ex id="1"/>'}
        text_out, warnings = level4_safe_fallback(text, missing)

        assert text_out.count('<ex id="1"/>') == 1, \
            "ex should not be duplicated"
        assert text_out.count('<bx id="1"/>') == 1, \
            "bx should be inserted once"
        assert len(warnings) == 1, \
            "only bx should be in warnings"

    def test_bx_ex_both_in_text_skipped(self):
        """Both halves already restored by L3 → nothing inserted."""
        text = '<unit id="1"><source><bx id="1"/>text<ex id="1"/></source></unit>'
        missing = {'bx_1': '<bx id="1"/>', 'ex_1': '<ex id="1"/>'}
        text_out, warnings = level4_safe_fallback(text, missing)

        assert text_out == text, "text should be unchanged"
        assert warnings == [], "no warnings for skipped tags"

    def test_bx_missing_ex_placeholder_present(self):
        """Only bx missing, ex placeholder still in text → bx inserted once."""
        text = '<unit id="1"><source>Hello {{_OL_XTAG_ex_1_}} world</source></unit>'
        missing = {'bx_1': '<bx id="1"/>'}
        text_out, warnings = level4_safe_fallback(text, missing)

        assert text_out.count('<bx id="1"/>') == 1
        assert '<ex id="1"/>' not in text_out
        assert len(warnings) == 1

    def test_mixed_bx_ex_with_non_paired(self):
        """Mix of bx/ex and non-paired tags: bx/ex half-aware, others unaffected."""
        text = '<unit id="1"><source>Hello <bx id="1"/> world</source></unit>'
        missing = {
            'bx_1': '<bx id="1"/>',
            'ex_1': '<ex id="1"/>',
            'x_2': '<x id="2"/>',
            'ph_3': '<ph id="3"/>',
        }
        text_out, warnings = level4_safe_fallback(text, missing)

        assert text_out.count('<bx id="1"/>') == 1
        assert '<ex id="1"/>' in text_out
        assert '<x id="2"/>' in text_out
        assert '<ph id="3"/>' in text_out
        assert len(warnings) == 3
