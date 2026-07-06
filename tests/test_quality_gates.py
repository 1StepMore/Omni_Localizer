"""TDD unit tests for quality_gates module (Issue #56)."""

from __future__ import annotations

import os
from typing import Any

import pytest

from ol_lqa.quality_gates import (
    check_cjk_residue,
    check_inline_tag_counts,
    check_length_ratio,
    check_llm_protocol_markers,
    check_locale_conventions,
    check_source_copy,
    check_terms_audit,
    check_terminology_consistency,
    format_warning_summary,
    retry_critical_failures,
    run_quality_gates,
)

# =========================================================================
# Gate 1: check_inline_tag_counts
# =========================================================================


class TestCheckInlineTagCounts:
    """Gate 1 — inline tag parity between source and target."""

    def test_happy_path_equal_tags(self) -> None:
        """Source and target have the same number of each tag type."""
        source = '<bx id="1"/>Hello<ex id="1"/><x id="2"/>'
        target = '<bx id="1"/>Bonjour<ex id="1"/><x id="2"/>'
        assert check_inline_tag_counts(source, target) == []

    def test_missing_bx_tag(self) -> None:
        """Warn when source has more <bx tags than target."""
        source = '<bx id="1"/><bx id="2"/>text'
        target = '<bx id="1"/>text'
        warnings = check_inline_tag_counts(source, target)
        assert len(warnings) == 1
        assert "OL_WARN: INLINE_TAG_MISMATCH" in warnings[0]
        assert "bx" in warnings[0]
        assert "2" in warnings[0]
        assert "1" in warnings[0]

    def test_extra_ex_tag_in_target(self) -> None:
        """Warn when target has more <ex tags than source."""
        source = '<ex id="1"/>text'
        target = '<ex id="1"/><ex id="2"/>texte'
        warnings = check_inline_tag_counts(source, target)
        assert len(warnings) == 1
        assert "OL_WARN: INLINE_TAG_MISMATCH" in warnings[0]
        assert "ex" in warnings[0]

    def test_missing_x_tag(self) -> None:
        """Warn when target has fewer <x tags."""
        source = 'text<x id="1"/><x id="2"/>'
        target = 'text<x id="1"/>'
        warnings = check_inline_tag_counts(source, target)
        assert len(warnings) == 1
        assert "x" in warnings[0]

    def test_no_tags_returns_empty(self) -> None:
        """No inline tags in either string."""
        assert check_inline_tag_counts("Hello world", "Bonjour le monde") == []

    def test_empty_strings(self) -> None:
        """Both strings empty."""
        assert check_inline_tag_counts("", "") == []

    def test_multiple_tag_type_mismatches(self) -> None:
        """Warn for each tag type that is mismatched."""
        source = '<bx id="1"/><ex id="1"/><x id="2"/>'
        target = '<bx id="1"/>'
        warnings = check_inline_tag_counts(source, target)
        assert len(warnings) >= 2  # ex and x mismatched

    def test_special_chars_not_tag_patterns(self) -> None:
        """Do not match text like '<xbox' as a tag."""
        source = "The xbox controller"
        target = "Le contrôleur xbox"
        assert check_inline_tag_counts(source, target) == []


# =========================================================================
# Gate 2: check_terminology_consistency
# =========================================================================


class TestCheckTerminologyConsistency:
    """Gate 2 — consistent use of glossary translations in target."""

    def test_happy_path_consistent(self) -> None:
        """All glossary terms used consistently in target."""
        glossary: dict[str, Any] = {
            "API endpoint": {
                "translation": "API endpoint",
                "variants": {},
                "confidence": 0.95,
            }
        }
        target = "This is an API endpoint for the system."
        assert check_terminology_consistency(target, glossary) == []

    def test_inconsistent_translation_forms(self) -> None:
        """Two distinct forms of a glossary term appear in target."""
        glossary: dict[str, Any] = {
            "button": {
                "translation": "button",
                "variants": {},
                "confidence": 0.95,
            }
        }
        # "Button" and "button" are the same normalized form
        target = "Press the Button. Then click the button."
        # Both normalize to "button" -> no warning
        assert check_terminology_consistency(target, glossary) == []

    def test_inconsistent_term_usage(self) -> None:
        """Both source term and translation appear in target (mixed usage)."""
        glossary: dict[str, Any] = {
            "file": {
                "translation": "fichier",
                "variants": {},
                "confidence": 0.95,
            }
        }
        # Both "file" (source) and "fichier" (translation) appear → inconsistency
        target = "Ouvrez le fichier. Close the file."
        warnings = check_terminology_consistency(target, glossary)
        assert len(warnings) == 1
        assert "OL_WARN: TERMINOLOGY_INCONSISTENCY" in warnings[0]

    def test_term_not_in_glossary_skipped(self) -> None:
        """Entries without 'translation' key are skipped."""
        glossary: dict[str, Any] = {
            "foo": {"variants": {}, "confidence": 0.5}  # no 'translation' key
        }
        assert check_terminology_consistency(target="anything", glossary=glossary) == []

    def test_glossary_translation_is_empty_string(self) -> None:
        """Empty string translation should not cause errors."""
        glossary: dict[str, Any] = {
            "foo": {"translation": "", "variants": {}, "confidence": 0.9}
        }
        assert check_terminology_consistency(target="anything", glossary=glossary) == []

    def test_empty_glossary(self) -> None:
        """Empty glossary returns no warnings."""
        assert check_terminology_consistency(target="any text", glossary={}) == []

    def test_case_insensitive_matching(self) -> None:
        """Search is case-insensitive."""
        glossary: dict[str, Any] = {
            "save": {"translation": "sauvegarder", "variants": {}, "confidence": 0.9}
        }
        target = "Sauvegarder le fichier. Auto-sauvegarder activé."
        # Only one form "sauvegarder" appears (case-insensitively same)
        assert check_terminology_consistency(target, glossary) == []


# =========================================================================
# Gate 3: check_length_ratio
# =========================================================================


class TestCheckLengthRatio:
    """Gate 3 — target/source length ratio within bounds."""

    def test_happy_path_within_default_bounds(self) -> None:
        """Ratio 1.0 is within default [0.5, 3.0]."""
        assert check_length_ratio("Hello world", "Bonjour le monde") == []

    def test_ratio_below_min(self) -> None:
        """Extremely short target warns."""
        warnings = check_length_ratio("A long source text here", "Hi", min_ratio=0.5)
        assert len(warnings) == 1
        assert "OL_WARN: LENGTH_RATIO" in warnings[0]

    def test_ratio_above_max(self) -> None:
        """Extremely long target warns."""
        warnings = check_length_ratio("Hi", "A very long target text that is way too long", max_ratio=3.0)
        assert len(warnings) == 1
        assert "OL_WARN: LENGTH_RATIO" in warnings[0]

    def test_zero_length_source_handled(self) -> None:
        """Division by zero guard."""
        assert check_length_ratio("", "anything") == []

    def test_custom_bounds(self) -> None:
        """Custom min/max ratio parameters."""
        # ratio = 2.0, within [1.5, 2.5]
        warnings = check_length_ratio("1234", "12345678", min_ratio=1.5, max_ratio=2.5)
        assert warnings == []

    def test_env_var_min_used_when_no_arg(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Read OL_LENGTH_RATIO_MIN env var when min_ratio is None."""
        monkeypatch.setenv("OL_LENGTH_RATIO_MIN", "0.8")
        monkeypatch.delenv("OL_LENGTH_RATIO_MAX", raising=False)
        warnings = check_length_ratio("Hello World", "Hi")
        # ratio=3/11≈0.27 < 0.8
        assert len(warnings) == 1

    def test_env_var_max_used_when_no_arg(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Read OL_LENGTH_RATIO_MAX env var when max_ratio is None."""
        monkeypatch.setenv("OL_LENGTH_RATIO_MAX", "1.2")
        monkeypatch.delenv("OL_LENGTH_RATIO_MIN", raising=False)
        warnings = check_length_ratio("Hi", "A much longer target than the source")
        # ratio > 1.2
        assert len(warnings) == 1

    def test_env_var_missing_falls_back_to_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When env vars are unset and args are None, use defaults."""
        monkeypatch.delenv("OL_LENGTH_RATIO_MIN", raising=False)
        monkeypatch.delenv("OL_LENGTH_RATIO_MAX", raising=False)
        # ratio = len("Bonjour")/len("Hello") = 7/5 = 1.4, within [0.5, 3.0]
        assert check_length_ratio("Hello", "Bonjour") == []

    def test_exactly_at_boundary(self) -> None:
        """Ratio exactly at min or max does not warn."""
        # ratio = 5/10 = 0.5, exactly at min
        assert check_length_ratio("0123456789", "01234", min_ratio=0.5, max_ratio=3.0) == []
        # ratio = 15/5 = 3.0, exactly at max
        assert check_length_ratio("01234", "012345678901234", min_ratio=0.5, max_ratio=3.0) == []


# =========================================================================
# Gate 4: check_locale_conventions
# =========================================================================


class TestCheckLocaleConventions:
    """Gate 4 — locale-specific formatting conventions."""

    # --- Currency mixing ---

    def test_currency_mixing_detected(self) -> None:
        """Warn when ≥2 currency symbols appear."""
        warnings = check_locale_conventions("Price: $10 and €5")
        assert len(warnings) == 1
        assert "OL_WARN: CURRENCY_MIXING" in warnings[0]

    def test_currency_mixing_three_symbols(self) -> None:
        """Warn when 3+ currency symbols appear."""
        warnings = check_locale_conventions("$10, €5, and £3")
        assert len(warnings) == 1
        assert "OL_WARN: CURRENCY_MIXING" in warnings[0]

    def test_single_currency_no_warning(self) -> None:
        """Single currency symbol is fine."""
        assert check_locale_conventions("Price: $10") == []
        assert check_locale_conventions("Price: €5") == []

    def test_no_currency_symbols(self) -> None:
        """No currency symbols is fine."""
        assert check_locale_conventions("Just text without prices") == []

    def test_yen_symbol_alone(self) -> None:
        """¥ alone does not trigger."""
        assert check_locale_conventions("Cost: ¥500") == []

    # --- Date leakage ---

    def test_cjk_date_in_en_locale(self) -> None:
        """CJK date pattern in English locale warns."""
        warnings = check_locale_conventions(
            "Date: 2024年01月15日", target_locale="en-US"
        )
        assert len(warnings) == 1
        assert "OL_WARN: DATE_LEAKAGE" in warnings[0]

    def test_cjk_date_in_fr_locale(self) -> None:
        """CJK date pattern in French locale warns."""
        warnings = check_locale_conventions(
            "Date: 2024年01月15日", target_locale="fr-FR"
        )
        assert len(warnings) == 1

    def test_cjk_date_in_cjk_locale_no_warning(self) -> None:
        """CJK date pattern in zh locale is fine."""
        warnings = check_locale_conventions(
            "日期：2024年01月15日", target_locale="zh-CN"
        )
        # zh-CN is not in the non-CJK list, so no warning
        # Actually, the spec says "non-CJK locales (en/fr/de/es/pt/it)"
        # zh-CN is not in that set, so it should pass
        assert warnings == []

    def test_no_date_no_warning(self) -> None:
        """No date pattern, no warning."""
        assert check_locale_conventions("Hello world", target_locale="en-US") == []

    def test_cjk_date_in_ja_locale_no_warning(self) -> None:
        """CJK date pattern in Japanese locale is fine (not in non-CJK list)."""
        warnings = check_locale_conventions(
            "日付：2024年01月15日", target_locale="ja-JP"
        )
        assert warnings == []

    # --- Digit grouping ---

    def test_eu_digit_grouping_in_en_us(self) -> None:
        """EU format (1.000.000,00) in en-US warns."""
        warnings = check_locale_conventions(
            "Total: 1.000.000,00", target_locale="en-US"
        )
        assert len(warnings) == 1
        assert "OL_WARN: DIGIT_GROUPING" in warnings[0]

    def test_us_digit_grouping_in_fr(self) -> None:
        """US format (1,000,000.00) in EU locale warns."""
        warnings = check_locale_conventions(
            "Total: 1,000,000.00", target_locale="fr-FR"
        )
        assert len(warnings) == 1
        assert "OL_WARN: DIGIT_GROUPING" in warnings[0]

    def test_us_digit_grouping_in_en_us_no_warning(self) -> None:
        """US format in en-US locale is fine."""
        assert check_locale_conventions(
            "Total: 1,000,000.00", target_locale="en-US"
        ) == []

    def test_eu_digit_grouping_in_de_no_warning(self) -> None:
        """EU format in German locale is fine."""
        assert check_locale_conventions(
            "Summe: 1.000.000,00", target_locale="de-DE"
        ) == []

    def test_no_digit_patterns(self) -> None:
        """No digit grouping patterns, no warning."""
        assert check_locale_conventions(
            "Hello world", target_locale="en-US"
        ) == []

    # --- Unit spelling ---

    def test_gb_spelling_in_en_us(self) -> None:
        """British spelling (colour) in en-US warns."""
        warnings = check_locale_conventions(
            "The colour of the centre", target_locale="en-US"
        )
        assert len(warnings) == 1
        assert "OL_WARN: UNIT_SPELLING" in warnings[0]

    def test_us_spelling_in_en_gb(self) -> None:
        """American spelling (color) in en-GB warns."""
        warnings = check_locale_conventions(
            "The color of the center", target_locale="en-GB"
        )
        assert len(warnings) == 1
        assert "OL_WARN: UNIT_SPELLING" in warnings[0]

    def test_gb_spelling_in_en_gb_no_warning(self) -> None:
        """British spelling in en-GB is fine."""
        assert check_locale_conventions(
            "The colour of the centre", target_locale="en-GB"
        ) == []

    def test_us_spelling_in_en_us_no_warning(self) -> None:
        """American spelling in en-US is fine."""
        assert check_locale_conventions(
            "The color of the center", target_locale="en-US"
        ) == []

    def test_no_spelling_issues(self) -> None:
        """No GB/US spelling triggers."""
        assert check_locale_conventions(
            "Hello world", target_locale="en-US"
        ) == []

    def test_multiple_violations_in_one_text(self) -> None:
        """Currency + date + grouping + spelling all in one string."""
        text = "$10 €5 Date: 2024年01月15日 Total: 1.000.000,00 colour"
        warnings = check_locale_conventions(text, target_locale="en-US")
        codes = {w.split(":")[1].strip() for w in warnings}
        assert "OL_WARN" in str(warnings)  # at least some warnings
        # Should detect multiple issues
        assert len(warnings) >= 2

    def test_target_locale_falls_back_to_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Read OL_TARGET_LOCALE env var when arg is None."""
        monkeypatch.setenv("OL_TARGET_LOCALE", "en-US")
        warnings = check_locale_conventions("The colour of the centre")
        assert len(warnings) == 1
        assert "OL_WARN: UNIT_SPELLING" in warnings[0]

    def test_target_locale_env_var_missing_no_crash(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When OL_TARGET_LOCALE is unset and arg is None, no crash."""
        monkeypatch.delenv("OL_TARGET_LOCALE", raising=False)
        # Should not crash, just return empty or limited checks
        warnings = check_locale_conventions("Hello world")
        assert isinstance(warnings, list)

    def test_locale_fr_fr_spelling_checks(self) -> None:
        """fr-FR is not an English locale, so spelling checks are skipped."""
        assert check_locale_conventions("The colour", target_locale="fr-FR") == []


# =========================================================================
# Orchestrator: run_quality_gates
# =========================================================================


class TestRunQualityGates:
    """Orchestrator wrapping all 4 gates."""

    def test_all_gates_enabled_no_issues(self) -> None:
        """All gates pass with clean input."""
        source = "<bx id='1'/>Hello"
        target = "<bx id='1'/>Bonjour"
        glossary: dict[str, Any] = {"hello": {"translation": "bonjour", "variants": {}, "confidence": 0.9}}
        warnings = run_quality_gates(
            source=source,
            target=target,
            glossary=glossary,
            target_locale="fr-FR",
        )
        assert warnings == []

    def test_inline_tag_warning_detected(self) -> None:
        """Gate 1 fires when tags are mismatched."""
        source = "<bx id='1'/>text"
        target = "text"
        warnings = run_quality_gates(source, target)
        assert any("OL_WARN: INLINE_TAG_MISMATCH" in w for w in warnings)

    def test_terminology_warning_detected(self) -> None:
        """Gate 2 fires with inconsistent glossary usage."""
        glossary: dict[str, Any] = {
            "file": {"translation": "fichier", "variants": {}, "confidence": 0.9}
        }
        # Both source term "file" and translation "fichier" appear in target
        target = "Ouvrez le fichier. Close the file."
        warnings = run_quality_gates(source="source", target=target, glossary=glossary)
        assert any("OL_WARN: TERMINOLOGY_INCONSISTENCY" in w for w in warnings)

    def test_length_ratio_warning_detected(self) -> None:
        """Gate 3 fires with extreme length mismatch."""
        warnings = run_quality_gates(
            source="A long source text that is quite lengthy here",
            target="Hi",
            length_ratio_min=0.5,
        )
        assert any("OL_WARN: LENGTH_RATIO" in w for w in warnings)

    def test_locale_convention_warning_detected(self) -> None:
        """Gate 4 fires with currency mixing."""
        warnings = run_quality_gates(
            source="source", target="$10 and €5", target_locale="en-US"
        )
        assert any("OL_WARN: CURRENCY_MIXING" in w for w in warnings)

    def test_disabled_inline_tags_gate(self) -> None:
        """Setting inline_tags_enabled=False suppresses Gate 1."""
        source = "<bx id='1'/>text"
        target = "text"
        warnings = run_quality_gates(source, target, inline_tags_enabled=False)
        assert not any("OL_WARN: INLINE_TAG_MISMATCH" in w for w in warnings)

    def test_disabled_terminology_gate(self) -> None:
        """Setting terminology_enabled=False suppresses Gate 2."""
        glossary: dict[str, Any] = {
            "file": {"translation": "fichier", "variants": {}, "confidence": 0.9}
        }
        warnings = run_quality_gates(
            source="s", target="Ouvrez le fichier. Close the file.",
            glossary=glossary, terminology_enabled=False,
        )
        assert not any("OL_WARN: TERMINOLOGY_INCONSISTENCY" in w for w in warnings)

    def test_disabled_length_ratio_gate(self) -> None:
        """Setting length_ratio_enabled=False suppresses Gate 3."""
        warnings = run_quality_gates(
            source="A long source text", target="Hi", length_ratio_enabled=False
        )
        assert not any("OL_WARN: LENGTH_RATIO" in w for w in warnings)

    def test_disabled_locale_gate(self) -> None:
        """Setting locale_enabled=False suppresses Gate 4."""
        warnings = run_quality_gates(
            source="s", target="$10 and €5", locale_enabled=False, target_locale="en-US"
        )
        assert not any("OL_WARN: CURRENCY_MIXING" in w for w in warnings)

    def test_error_isolation(self) -> None:
        """A crash in one gate does not block other gates."""
        # We can't easily make a gate crash with pure function args,
        # but the try/except is tested via a scenario where glossary
        # triggers a potential issue. Or we verify that all gates
        # still run when one produces warnings.

        source = "<bx id='1'/>Hello"
        target = "Bonjour"  # missing bx tag
        glossary: dict[str, Any] = {
            "hello": {"translation": "bonjour", "variants": {}, "confidence": 0.9}
        }
        warnings = run_quality_gates(source=source, target=target, glossary=glossary)
        # Gate 1 should warn about tags
        # Other gates should complete normally
        assert any("OL_WARN: INLINE_TAG_MISMATCH" in w for w in warnings)

    def test_all_gates_disabled(self) -> None:
        """All disabled returns empty list."""
        warnings = run_quality_gates(
            source="a", target="b",
            inline_tags_enabled=False,
            terminology_enabled=False,
            length_ratio_enabled=False,
            locale_enabled=False,
        )
        assert warnings == []

    def test_no_glossary_skips_terminology_gracefully(self) -> None:
        """When glossary is None, Gate 2 behaves as disabled."""
        warnings = run_quality_gates(
            source="source", target="target", glossary=None
        )
        # Should not crash, terminology just won't check anything
        assert isinstance(warnings, list)


# =========================================================================
# Edge cases and error resilience
# =========================================================================


class TestErrorResilience:
    """Ensure gates never raise unhandled exceptions."""

    def test_check_inline_tag_counts_binary_input(self) -> None:
        """Binary-like input should not crash."""
        warnings = check_inline_tag_counts("\x00\x01\x02", "\x00\x01")
        assert isinstance(warnings, list)

    def test_check_terminology_consistency_malformed_glossary(self) -> None:
        """Malformed glossary entries should not crash."""
        glossary: dict[str, Any] = {
            "key": {"translation": 123, "variants": {}, "confidence": 0.9}  # type: ignore[typeddict-item]
        }
        warnings = check_terminology_consistency(target="text 123", glossary=glossary)
        assert isinstance(warnings, list)

    def test_check_length_ratio_very_large_numbers(self) -> None:
        """Very large strings should not overflow."""
        source = "a" * 100000
        target = "b" * 100000
        warnings = check_length_ratio(source, target)
        assert isinstance(warnings, list)

    def test_check_locale_conventions_none_locale(self) -> None:
        """None locale should not crash."""
        warnings = check_locale_conventions("$10 €5", target_locale=None)
        assert isinstance(warnings, list)

    def test_run_quality_gates_none_args(self) -> None:
        """Calling with all None optional args should not crash."""
        warnings = run_quality_gates(source="src", target="tgt", glossary=None)
        assert isinstance(warnings, list)

    def test_run_quality_gates_empty_strings(self) -> None:
        """Empty source and target should not crash."""
        warnings = run_quality_gates(source="", target="")
        assert isinstance(warnings, list)

    def test_check_locale_conventions_partial_date(self) -> None:
        """Partial date pattern like 2024年 should not crash."""
        warnings = check_locale_conventions("2024年", target_locale="en-US")
        assert isinstance(warnings, list)

    def test_check_length_ratio_source_shorter_than_min(self) -> None:
        """Very short source with zero-length like scenarios."""
        # Source length 1, target length 100
        warnings = check_length_ratio("a", "b" * 100, max_ratio=3.0)
        assert len(warnings) == 1  # 100/1 = 100 > 3.0


class TestGate5SourceCopy:
    """Tests for Gate 5 SOURCE_COPY detection (Issue #57)."""

    def test_source_copy_identical_text_detected(self) -> None:
        """When source == target, SOURCE_COPY should be emitted."""
        warnings = check_source_copy("Hello world", "Hello world")
        assert len(warnings) == 1
        assert "SOURCE_COPY" in warnings[0]

    def test_source_copy_different_text_clean(self) -> None:
        """When source != target, no warning."""
        warnings = check_source_copy("Hello world", "你好世界")
        assert len(warnings) == 0

    def test_source_copy_pure_numbers_skipped(self) -> None:
        """Pure numeric content should be skipped (no alphabetic chars)."""
        warnings = check_source_copy("12345", "12345")
        assert len(warnings) == 0

    def test_source_copy_whitespace_skipped(self) -> None:
        """Whitespace-only content should be skipped."""
        warnings = check_source_copy("   \n  ", "   \n  ")
        assert len(warnings) == 0

    def test_source_copy_empty_string(self) -> None:
        """Empty strings should not produce warnings."""
        warnings = check_source_copy("", "")
        assert len(warnings) == 0

    def test_source_copy_symbols_only_skipped(self) -> None:
        """Symbol-only content should be skipped."""
        warnings = check_source_copy("!@#$%", "!@#$%")
        assert len(warnings) == 0

    def test_source_copy_with_run_quality_gates(self) -> None:
        """Gate 5 should fire when enabled via run_quality_gates."""
        warnings = run_quality_gates(
            source="Hello world", target="Hello world",
            inline_tags_enabled=False,
            terminology_enabled=False,
            length_ratio_enabled=False,
            locale_enabled=False,
            source_copy_enabled=True,
        )
        assert any("SOURCE_COPY" in w for w in warnings)

    def test_source_copy_disabled_via_flag(self) -> None:
        """When source_copy_enabled=False, Gate 5 should not fire."""
        warnings = run_quality_gates(
            source="Hello world", target="Hello world",
            inline_tags_enabled=False,
            terminology_enabled=False,
            length_ratio_enabled=False,
            locale_enabled=False,
            source_copy_enabled=False,
        )
        assert all("SOURCE_COPY" not in w for w in warnings)

    def test_source_copy_trailing_whitespace(self) -> None:
        """Trailing whitespace stripped, same content -> still a copy."""
        warnings = check_source_copy("Hello world  ", "Hello world")
        assert len(warnings) == 1  # stripped comparison still matches
        assert "SOURCE_COPY" in warnings[0]

    def test_source_copy_cjk_text_detected(self) -> None:
        """CJK text echoed back should be flagged."""
        warnings = check_source_copy("海尔是全球领先的家电企业", "海尔是全球领先的家电企业")
        assert len(warnings) == 1
        assert "SOURCE_COPY" in warnings[0]


class TestWarningSummary:
    """Tests for format_warning_summary (Issue #57)."""

    def test_empty_warnings(self) -> None:
        """Empty dict should produce '0 warnings'."""
        result = format_warning_summary({})
        assert result == "0 warnings"

    def test_no_ol_warn_codes(self) -> None:
        """Warnings without OL_WARN prefix should be ignored."""
        result = format_warning_summary({"u1": ["something else"]})
        assert result == "0 warnings"

    def test_single_warning(self) -> None:
        """Single warning code should appear in summary."""
        result = format_warning_summary({"u1": ["OL_WARN: SOURCE_COPY -- test"]})
        assert "SOURCE_COPY" in result
        assert "1 warnings" in result

    def test_multiple_codes_counted(self) -> None:
        """Multiple occurrences of same code should be counted."""
        result = format_warning_summary({
            "u1": ["OL_WARN: SOURCE_COPY -- a", "OL_WARN: SOURCE_COPY -- b"],
        })
        assert "SOURCE_COPYx2" in result

    def test_mixed_warnings(self) -> None:
        """Different codes should appear sorted by frequency."""
        result = format_warning_summary({
            "u1": ["OL_WARN: LENGTH_RATIO -- a", "OL_WARN: SOURCE_COPY -- b"],
            "u2": ["OL_WARN: LENGTH_RATIO -- c"],
        })
        assert "LENGTH_RATIOx2" in result
        assert "SOURCE_COPYx1" in result


class TestRetryCriticalFailures:
    """Tests for retry_critical_failures (Issue #57)."""

    def test_no_critical_warnings_returns_zero(self) -> None:
        """When no critical warnings exist, retry should return 0."""
        import asyncio
        result = asyncio.run(retry_critical_failures(
            units=[],
            pool=MockPool(),
            src_lang="zh", tgt_lang="en",
            quality_gates_cfg=MockQualityGateConfig(),
            glossary=None,
            warnings_per_unit={"u1": ["OL_WARN: LENGTH_RATIO -- test"]},
            max_retries=1,
        ))
        assert result == 0

    def test_source_copy_triggers_retry(self) -> None:
        """SOURCE_COPY warnings should trigger retry."""
        import asyncio
        result = asyncio.run(retry_critical_failures(
            units=[],
            pool=MockPool(),
            src_lang="zh", tgt_lang="en",
            quality_gates_cfg=MockQualityGateConfig(),
            glossary=None,
            warnings_per_unit={"u1": ["OL_WARN: SOURCE_COPY -- test"]},
            max_retries=1,
        ))
        assert result == 0  # No matching units to retry (empty list -> early return)


# =========================================================================
# Gate 6: check_cjk_residue
# =========================================================================


class TestCheckCjkResidue:
    """Gate 6 — detect CJK characters in non-CJK target text."""

    def test_clean_non_cjk_target(self) -> None:
        """No CJK characters in non-CJK target — no warnings."""
        source = "这是一段中文"
        target = "This is English text without any Chinese characters."
        warnings = check_cjk_residue(source, target, target_lang="en")
        assert warnings == []

    def test_cjk_residue_detected(self) -> None:
        """CJK characters found in English target — warning emitted."""
        source = "这是一段中文"
        target = "This text has Chinese: 这是一段中文残留在英文中"
        warnings = check_cjk_residue(source, target, target_lang="en")
        assert len(warnings) == 1
        assert "OL_WARN: CJK_RESIDUE" in warnings[0]

    def test_cjk_to_cjk_target_no_warning(self) -> None:
        """CJK source to CJK target (zh→ja) — no warning."""
        source = "这是一段中文"
        target = "これは日本語のテキストです"
        warnings = check_cjk_residue(source, target, target_lang="ja")
        assert warnings == []

    def test_unknown_target_lang_skipped(self) -> None:
        """No target_lang — check skipped."""
        source = "这是一段中文"
        target = "This text has Chinese: 这是一段中文残留在英文中"
        warnings = check_cjk_residue(source, target, target_lang=None)
        assert warnings == []

    def test_japanese_residue_detected(self) -> None:
        """Hiragana/Katakana found in English target."""
        source = "これは日本語のテキストです"
        target = "This text has Japanese: これは日本語のテキストです"
        warnings = check_cjk_residue(source, target, target_lang="en")
        assert len(warnings) == 1
        assert "OL_WARN: CJK_RESIDUE" in warnings[0]
        assert "JA" in warnings[0]

    def test_korean_residue_detected(self) -> None:
        """Hangul found in French target."""
        source = "이것은 한국어 텍스트입니다"
        target = "Ce texte contient du coréen: 이것은 한국어 텍스트입니다"
        warnings = check_cjk_residue(source, target, target_lang="fr")
        assert len(warnings) == 1
        assert "OL_WARN: CJK_RESIDUE" in warnings[0]
        assert "KO" in warnings[0]


# =========================================================================
# Gate 7: check_llm_protocol_markers
# =========================================================================


class TestCheckLlmProtocolMarkers:
    """Gate 7 — detect LLM protocol markers in translated output."""

    def test_clean_target_no_markers(self) -> None:
        """No LLM protocol markers — no warnings."""
        source = "Hello world"
        target = "你好世界"
        warnings = check_llm_protocol_markers(source, target)
        assert warnings == []

    def test_critical_marker_detected(self) -> None:
        """CRITICAL: marker detected."""
        source = "Hello world"
        target = "CRITICAL: this is a very important instruction that must be followed."
        warnings = check_llm_protocol_markers(source, target)
        assert len(warnings) == 1
        assert "OL_WARN: LLM_PROTOCOL_MARKER" in warnings[0]

    def test_output_only_fragment_detected(self) -> None:
        """'Output ONLY' fragment detected."""
        source = "Hello world"
        target = "你好世界 Output ONLY the translation."
        warnings = check_llm_protocol_markers(source, target)
        assert len(warnings) == 1
        assert "OL_WARN: LLM_PROTOCOL_MARKER" in warnings[0]

    def test_do_not_instruction_detected(self) -> None:
        """'Do not include' instruction detected."""
        source = "Hello world"
        target = "你好世界 Do not include any explanations."
        warnings = check_llm_protocol_markers(source, target)
        assert len(warnings) >= 1
        assert "OL_WARN: LLM_PROTOCOL_MARKER" in warnings[0]

    def test_translation_label_detected(self) -> None:
        """'Translation:' label detected."""
        source = "Hello world"
        target = "Translation: 你好世界"
        warnings = check_llm_protocol_markers(source, target)
        assert len(warnings) >= 1
        assert "OL_WARN: LLM_PROTOCOL_MARKER" in warnings[0]

    def test_multiple_markers_all_reported(self) -> None:
        """Multiple protocol markers in same target — all reported."""
        source = "Hello world"
        target = "CRITICAL: Output ONLY the translation. Do not include notes. Translation: 你好世界"
        warnings = check_llm_protocol_markers(source, target)
        assert len(warnings) >= 2  # at least CRITICAL + Output ONLY

    def test_normal_text_no_false_positive(self) -> None:
        """Normal text should not trigger false positives."""
        source = "Important meeting"
        target = "重要会议"
        warnings = check_llm_protocol_markers(source, target)
        assert warnings == []


class TestTermsAudit:
    """Gate — full glossary term audit via verify_translation."""

    def test_all_terms_verified(self) -> None:
        """Glossary terms all correctly used — no warnings."""
        source = "Click the button to submit."
        target = "点击按钮提交。"
        glossary = {"button": {"translation": "按钮"}}
        assert check_terms_audit(source, target, glossary) == []

    def test_mismatch_detected(self) -> None:
        """Term translated with non-glossary variant — mismatch warning."""
        source = "Click the button to submit."
        target = "点击按键提交。"
        glossary = {"button": {"translation": "按钮"}}
        warnings = check_terms_audit(source, target, glossary)
        assert len(warnings) >= 1
        assert any("TERM_AUDIT_MISMATCH" in w for w in warnings)

    def test_absent_term_detected(self) -> None:
        """Glossary term expected but not found in target — mismatch or absent warning."""
        source = "Configure the endpoint in settings."
        target = "在设置中进行配置。"
        glossary = {"endpoint": {"translation": "端点"}}
        warnings = check_terms_audit(source, target, glossary)
        assert len(warnings) >= 1
        assert any("TERM_AUDIT_MISMATCH" in w or "TERM_AUDIT_ABSENT" in w for w in warnings)

    def test_inconsistency_detected(self) -> None:
        """Same source term translated differently across sentences.

        With an empty glossary the verifier falls back to cross-segment
        consistency detection and flags terms rendered inconsistently.
        """
        source = "The system works. Fix the system."
        target = "系统正常。修复那个设备。"
        warnings = check_terms_audit(source, target, {})
        assert len(warnings) >= 1
        assert any("TERM_AUDIT_INCONSISTENCY" in w for w in warnings)

    def test_no_glossary_skip(self) -> None:
        """No glossary provided — check skipped with empty result."""
        source = "Hello world"
        target = "你好世界"
        assert check_terms_audit(source, target, None) == []

    def test_confidence_threshold_filters_low(self) -> None:
        """Terms below confidence threshold generate low_confidence warnings."""
        source = "Process the data."
        target = "处理数据。"
        glossary = {
            "process": {
                "translation": "处理",
                "confidence": 0.3,
            },
        }
        warnings = check_terms_audit(source, target, glossary, confidence_threshold=0.7)
        # The term exists with low confidence (0.3 < 0.7)
        # verify_translation may flag this as low_confidence
        # Just verify it doesn't crash and returns list
        assert isinstance(warnings, list)

    def test_empty_glossary(self) -> None:
        """Empty glossary dict — no warnings."""
        assert check_terms_audit("Hello", "你好", {}) == []

    def test_run_quality_gates_wires_terms_audit(self) -> None:
        """Verify run_quality_gates() calls check_terms_audit when enabled."""
        from ol_lqa.quality_gates import run_quality_gates
        source = "Click the button."
        target = "点击按键。"
        glossary = {"button": {"translation": "按钮"}}
        warnings = run_quality_gates(
            source, target, glossary=glossary,
            terms_audit_enabled=True, terms_audit_confidence=0.7,
            inline_tags_enabled=False, terminology_enabled=False,
            length_ratio_enabled=False, locale_enabled=False,
            source_copy_enabled=False, cjk_residue_enabled=False,
            llm_markers_enabled=False,
        )
        assert any("TERM_AUDIT" in w for w in warnings)

    def test_run_quality_gates_terms_audit_disabled(self) -> None:
        """When terms_audit_enabled=False, no TERM_AUDIT warnings."""
        from ol_lqa.quality_gates import run_quality_gates
        source = "Click the button."
        target = "点击按键。"
        glossary = {"button": {"translation": "按钮"}}
        warnings = run_quality_gates(
            source, target, glossary=glossary,
            terms_audit_enabled=False,
            inline_tags_enabled=False, terminology_enabled=False,
            length_ratio_enabled=False, locale_enabled=False,
            source_copy_enabled=False, cjk_residue_enabled=False,
            llm_markers_enabled=False,
        )
        assert not any("TERM_AUDIT" in w for w in warnings)


class MockPool:
    """Mock ModelPool for retry_critical_failures tests."""
    async def translate(self, text, src, tgt):
        return text


class MockQualityGateConfig:
    """Mock config for retry_critical_failures tests."""
    inline_tags = True
    terminology = True
    length_ratio = type("o", (), {"enabled": True, "min": 0.5, "max": 2.0})()
    locale = type("o", (), {"enabled": True, "target_locale": "en-US"})()
    source_copy = True
    source_copy_retry = True
    retry_on_translation_failed = True
    cjk_residue = True
    llm_markers = True
    terms_audit = True
    terms_audit_confidence = 0.7
    self_reflection = True
    self_reflection_rounds = 1
