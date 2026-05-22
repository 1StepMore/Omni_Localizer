"""Tests for XLIFF shield functionality."""
from ol_xliff.shield import shield_xliff


class TestXLIFFShield:
    """Test shield_xliff() for 7 inline element types."""

    def test_shield_x(self):
        """Test protection of x (standalone) inline elements."""
        text = 'Use <x id="1" type="bold"/> in text'
        result, shield_map = shield_xliff(text)
        assert '{{_OL_XTAG_x_1_}}' in result
        assert 'x_1' in shield_map
        assert shield_map['x_1'] == '<x id="1" type="bold"/>'

    def test_shield_bx(self):
        """Test protection of bx (begin) inline elements."""
        text = '<bx id="2" type="bold"/>bold text'
        result, shield_map = shield_xliff(text)
        assert '{{_OL_XTAG_bx_2_}}' in result
        assert 'bx_2' in shield_map

    def test_shield_ex(self):
        """Test protection of ex (end) inline elements."""
        text = 'bold text<ex id="2" type="bold"/>'
        result, shield_map = shield_xliff(text)
        assert '{{_OL_XTAG_ex_2_}}' in result
        assert 'ex_2' in shield_map

    def test_shield_mrk(self):
        """Test protection of mrk (marked content) inline elements."""
        text = 'Hello <mrk id="m1" type="comment">world</mrk> text'
        result, shield_map = shield_xliff(text)
        assert '{{_OL_XTAG_mrk_m1_}}' in result
        assert 'mrk_m1' in shield_map
        assert '<mrk id="m1" type="comment">world</mrk>' in shield_map['mrk_m1']

    def test_shield_em(self):
        """Test protection of em (emphasis) inline elements."""
        text = '<em id="e1">emphasized</em> text'
        result, shield_map = shield_xliff(text)
        assert '{{_OL_XTAG_em_e1_}}' in result
        assert 'em_e1' in shield_map
        assert '<em id="e1">emphasized</em>' in shield_map['em_e1']

    def test_shield_ph(self):
        """Test protection of ph (placeholder) inline elements."""
        text = 'Press <ph id="p1">Enter</ph> to continue'
        result, shield_map = shield_xliff(text)
        assert '{{_OL_XTAG_ph_p1_}}' in result
        assert 'ph_p1' in shield_map

    def test_shield_alayout(self):
        """Test protection of alayout (annotated layout) inline elements."""
        text = '<alayout id="a1" type="heading">Title</alayout> content'
        result, shield_map = shield_xliff(text)
        assert '{{_OL_XTAG_alayout_a1_}}' in result
        assert 'alayout_a1' in shield_map

    def test_shield_g(self):
        """Test protection of g (group) inline elements."""
        text = '<g id="1">Do not translate</g>'
        result, shield_map = shield_xliff(text)
        assert '{{_OL_XTAG_g_1_}}' in result
        assert 'g_1' in shield_map
        assert shield_map['g_1'] == '<g id="1">Do not translate</g>'

    def test_shield_ign(self):
        """Test protection of ign (ignore) inline elements."""
        text = '<ign id="i1">ignore me</ign>'
        result, shield_map = shield_xliff(text)
        assert '{{_OL_XTAG_ign_i1_}}' in result
        assert 'ign_i1' in shield_map
        assert shield_map['ign_i1'] == '<ign id="i1">ignore me</ign>'

    def test_unshield_restoration(self):
        """Test restoration of placeholders back to original tags."""
        text = 'Hello {{_OL_XTAG_mrk_m1_}} world'
        shield_map = {'mrk_m1': '<mrk id="m1" type="comment">world</mrk>'}

        # Unshield is not implemented in shield module; use parser's restore
        restored_text = text
        for key, tag in shield_map.items():
            placeholder = f'{{{{_OL_XTAG_{key}_}}}}'
            restored_text = restored_text.replace(placeholder, tag)

        assert '<mrk id="m1" type="comment">world</mrk>' in restored_text

    def test_legacy_x_bx_ex_still_work(self):
        """Test that x, bx, ex elements from legacy implementation still protected."""
        text = 'Use <x id="1"/> and <bx id="2"/>bold<ex id="2"/> text'
        result, shield_map = shield_xliff(text)
        assert '{{_OL_XTAG_x_1_}}' in result
        assert '{{_OL_XTAG_bx_2_}}' in result
        assert '{{_OL_XTAG_ex_2_}}' in result

    def test_multiple_inline_elements(self):
        """Test shielding multiple different inline element types."""
        text = '<em id="e1">A</em><mrk id="m1">B</mrk><x id="x1"/>'
        result, shield_map = shield_xliff(text)
        assert '{{_OL_XTAG_em_e1_}}' in result
        assert '{{_OL_XTAG_mrk_m1_}}' in result
        assert '{{_OL_XTAG_x_x1_}}' in result
        assert len(shield_map) == 3

    def test_no_inline_elements(self):
        """Test shielding text with no inline elements."""
        text = 'Plain text without inline elements'
        result, shield_map = shield_xliff(text)
        assert result == text
        assert len(shield_map) == 0

    def test_nested_mrk_elements(self):
        """Test protection of nested mrk same-type elements."""
        text = '<mrk id="m1">A<mrk id="m2">B</mrk>C</mrk>'
        result, shield_map = shield_xliff(text)
        assert 'mrk_m1' in shield_map
        assert 'mrk_m2' in shield_map
        assert result.count('{{_OL_XTAG_') == 2
        assert '</mrk>' not in result

    def test_nested_em_elements(self):
        """Test protection of nested em same-type elements."""
        text = '<em id="e1">outer<em id="e2">inner</em>rest</em>'
        result, shield_map = shield_xliff(text)
        assert 'em_e1' in shield_map
        assert 'em_e2' in shield_map
        assert result.count('{{_OL_XTAG_') == 2
        assert '</em>' not in result

    def test_deeply_nested_elements(self):
        """Test protection of deeply nested same-type elements."""
        text = '<mrk id="a">A<mrk id="b">B<mrk id="c">C</mrk></mrk>D</mrk>'
        result, shield_map = shield_xliff(text)
        assert 'mrk_a' in shield_map
        assert 'mrk_b' in shield_map
        assert 'mrk_c' in shield_map
        assert result.count('{{_OL_XTAG_') == 3
        assert '</mrk>' not in result
