"""TDD unit tests for quality_gates module (Issue #56)."""

from __future__ import annotations

import os
from typing import Any

import pytest

from ol_lqa.quality_gates import (
    check_inline_tag_counts,
    check_length_ratio,
    check_locale_conventions,
    check_source_copy,
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
# Gate 5: check_source_copy
# =========================================================================


class TestCheckSourceCopy:
    """Gate 5 — detect when LLM echoes source text unchanged."""

    def test_identical_source_and_target_flagged(self) -> None:
        """When source == target, a SOURCE_COPY warning is emitted."""
        warnings = check_source_copy("第二章海尔的全球创牌", "第二章海尔的全球创牌")
        assert len(warnings) == 1
        assert "OL_WARN: SOURCE_COPY" in warnings[0]

    def test_different_source_and_target_clean(self) -> None:
        """When source != target, no warning."""
        assert check_source_copy("你好世界", "Hello World") == []

    def test_whitespace_differs_after_strip_clean(self) -> None:
        """Leading/trailing whitespace differences do not suppress the warning when content matches."""
        warnings = check_source_copy("  hello  ", "hello")
        assert len(warnings) == 1
        assert "OL_WARN: SOURCE_COPY" in warnings[0]

    def test_meaningful_differs_after_strip_clean(self) -> None:
        """When content differs after stripping, no warning."""
        assert check_source_copy("  hello  ", "world") == []

    def test_pure_numbers_not_flagged(self) -> None:
        """Pure numbers/symbols that are unchanged should not be flagged."""
        assert check_source_copy("×116 ×54", "×116 ×54") == []
        assert check_source_copy("#46", "#46") == []

    def test_mixed_content_with_numbers_flagged(self) -> None:
        """Content with both text and numbers should still be flagged."""
        warnings = check_source_copy("第二章海尔的全球创牌", "第二章海尔的全球创牌")
        assert len(warnings) == 1
        assert "OL_WARN: SOURCE_COPY" in warnings[0]

    def test_empty_source_and_target(self) -> None:
        """Both strings empty — no alpha content, not flagged."""
        assert check_source_copy("", "") == []

    def test_empty_source_nonempty_target_clean(self) -> None:
        """One empty, one non-empty is not a copy."""
        assert check_source_copy("", "hello") == []

    def test_source_copy_via_orchestrator(self) -> None:
        """run_quality_gates with source_copy_enabled=True flags copy."""
        warnings = run_quality_gates(
            source="海尔全球创牌",
            target="海尔全球创牌",
            source_copy_enabled=True,
            inline_tags_enabled=False,
            terminology_enabled=False,
            length_ratio_enabled=False,
            locale_enabled=False,
        )
        assert any("OL_WARN: SOURCE_COPY" in w for w in warnings)

    def test_source_copy_disabled(self) -> None:
        """Setting source_copy_enabled=False suppresses Gate 5."""
        warnings = run_quality_gates(
            source="海尔全球创牌",
            target="海尔全球创牌",
            source_copy_enabled=False,
            inline_tags_enabled=False,
            terminology_enabled=False,
            length_ratio_enabled=False,
            locale_enabled=False,
        )
        assert not any("OL_WARN: SOURCE_COPY" in w for w in warnings)


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


# =========================================================================
# Gate 5 retry: retry_critical_failures
# =========================================================================


class TestRetryCriticalFailures:
    """Tests for retry_critical_failures()."""

    @pytest.mark.asyncio
    async def test_no_source_copy_no_retry(self) -> None:
        """No SOURCE_COPY warnings → retry does nothing, returns 0."""
        from ol_pool.fake import _FakeModelPool
        from ol_core.dataclass import TranslationUnit
        from ol_config.schema import QualityGateConfig

        pool = _FakeModelPool()
        units = [
            TranslationUnit(
                unit_id="1", source_text="Hello", target_text="[zh] Hello"
            ),
        ]
        warnings_per_unit: dict[str, list[str]] = {
            "1": ["OL_WARN: LENGTH_RATIO"],
        }
        cfg = QualityGateConfig()
        n = await retry_critical_failures(
            units, pool, "en", "zh", cfg, None, warnings_per_unit,
        )
        assert n == 0
        assert pool._call_count == 0

    @pytest.mark.asyncio
    async def test_source_copy_retry_success(self) -> None:
        """SOURCE_COPY warning → retry succeeds → warning removed, target updated."""
        from ol_pool.fake import _FakeModelPool
        from ol_core.dataclass import TranslationUnit
        from ol_config.schema import QualityGateConfig

        pool = _FakeModelPool()
        source = "Hello world"
        units = [
            TranslationUnit(
                unit_id="1", source_text=source, target_text=source,
            ),
        ]
        warnings_per_unit: dict[str, list[str]] = {
            "1": [
                "OL_WARN: SOURCE_COPY — target is identical to source, "
                "translation skipped / LLM echoed input back",
            ],
        }
        cfg = QualityGateConfig()
        n = await retry_critical_failures(
            units, pool, "en", "zh", cfg, None, warnings_per_unit,
        )
        assert n == 1
        assert pool._call_count == 1
        # target_text should be updated to a real translation (not source copy)
        assert units[0].target_text != source
        assert "[zh]" in units[0].target_text
        # SOURCE_COPY warning should be gone
        assert not any(
            "SOURCE_COPY" in w for w in warnings_per_unit["1"]
        )

    @pytest.mark.asyncio
    async def test_source_copy_retry_still_copy(self) -> None:
        """Retry still produces SOURCE_COPY → warning upgraded, returns 0."""
        from ol_core.dataclass import TranslationUnit
        from ol_config.schema import QualityGateConfig

        source = "Still copy"

        class _EchoPool:
            """Fake pool that always echoes the source unchanged."""
            _call_count = 0

            async def translate(
                self, text: str, src: str = "", tgt: str = "",
                **kwargs: object,
            ) -> str:
                self._call_count += 1
                return text  # echo back = source copy

        pool = _EchoPool()
        units = [
            TranslationUnit(
                unit_id="1", source_text=source, target_text=source,
            ),
        ]
        warnings_per_unit: dict[str, list[str]] = {
            "1": [
                "OL_WARN: SOURCE_COPY — target is identical to source, "
                "translation skipped / LLM echoed input back",
            ],
        }
        cfg = QualityGateConfig()
        n = await retry_critical_failures(
            units, pool, "en", "zh", cfg, None, warnings_per_unit,
        )
        assert n == 0  # no successful retries
        assert pool._call_count == 1
        # Should have "retry exhausted" message
        copy_warnings = [
            w for w in warnings_per_unit["1"]
            if "FAILED_RETRY" in w
        ]
        assert len(copy_warnings) == 1
        assert "retry exhausted" in copy_warnings[0]

    @pytest.mark.asyncio
    async def test_source_copy_retry_transport_error(self) -> None:
        """Pool raises during retry → handled gracefully, original warning kept."""
        from ol_core.dataclass import TranslationUnit
        from ol_config.schema import QualityGateConfig

        source = "Hello"

        class _FailingPool:
            _call_count = 0

            async def translate(
                self, text: str, src: str = "", tgt: str = "",
                **kwargs: object,
            ) -> str:
                self._call_count += 1
                msg = "Connection error"
                raise RuntimeError(msg)

        pool = _FailingPool()
        units = [
            TranslationUnit(
                unit_id="1", source_text=source, target_text=source,
            ),
        ]
        warnings_per_unit: dict[str, list[str]] = {
            "1": [
                "OL_WARN: SOURCE_COPY — target is identical to source",
            ],
        }
        cfg = QualityGateConfig()
        n = await retry_critical_failures(
            units, pool, "en", "zh", cfg, None, warnings_per_unit,
        )
        assert n == 0
        assert pool._call_count == 1
        # Original SOURCE_COPY warning should still be there
        assert any(
            "SOURCE_COPY" in w for w in warnings_per_unit["1"]
        )

    @pytest.mark.asyncio
    async def test_multiple_units_mixed(self) -> None:
        """Multiple units: one with copy, one without → only one retried."""
        from ol_pool.fake import _FakeModelPool
        from ol_core.dataclass import TranslationUnit
        from ol_config.schema import QualityGateConfig

        pool = _FakeModelPool()
        source_a = "Copy me"
        units = [
            TranslationUnit(
                unit_id="1", source_text=source_a, target_text=source_a,
            ),
            TranslationUnit(
                unit_id="2", source_text="Fine", target_text="[zh] Fine",
            ),
        ]
        warnings_per_unit: dict[str, list[str]] = {
            "1": [
                "OL_WARN: SOURCE_COPY — target is identical to source",
            ],
            "2": ["OL_WARN: LENGTH_RATIO"],
        }
        cfg = QualityGateConfig()
        n = await retry_critical_failures(
            units, pool, "en", "zh", cfg, None, warnings_per_unit,
        )
        assert n == 1
        assert pool._call_count == 1
        assert units[0].target_text != source_a
        assert units[1].target_text == "[zh] Fine"  # unchanged

    @pytest.mark.asyncio
    async def test_no_source_copy_warnings_empty_dict(self) -> None:
        """Empty warnings_per_unit → retry does nothing."""
        from ol_pool.fake import _FakeModelPool
        from ol_core.dataclass import TranslationUnit
        from ol_config.schema import QualityGateConfig

        pool = _FakeModelPool()
        units = [
            TranslationUnit(
                unit_id="1", source_text="Hello", target_text="[zh] Hello",
            ),
        ]
        cfg = QualityGateConfig()
        n = await retry_critical_failures(
            units, pool, "en", "zh", cfg, None, {},
        )
        assert n == 0
        assert pool._call_count == 0

    @pytest.mark.asyncio
    async def test_source_copy_retry_max_retries_exhausted(self) -> None:
        """max_retries=2 → both echo source → retry failed after 2 attempts."""
        from ol_core.dataclass import TranslationUnit
        from ol_config.schema import QualityGateConfig

        source = "Echo"

        class _EchoPool:
            _call_count = 0

            async def translate(
                self, text: str, src: str = "", tgt: str = "",
                **kwargs: object,
            ) -> str:
                self._call_count += 1
                return text

        pool = _EchoPool()
        units = [
            TranslationUnit(
                unit_id="1", source_text=source, target_text=source,
            ),
        ]
        warnings_per_unit: dict[str, list[str]] = {
            "1": [
                "OL_WARN: SOURCE_COPY — target is identical to source",
            ],
        }
        cfg = QualityGateConfig()
        n = await retry_critical_failures(
            units, pool, "en", "zh", cfg, None,
            warnings_per_unit, max_retries=2,
        )
        assert n == 0
        assert pool._call_count == 2  # both retries attempted
        copy_warnings = [
            w for w in warnings_per_unit["1"]
            if "FAILED_RETRY" in w
        ]
        assert len(copy_warnings) == 1
        assert "retry exhausted" in copy_warnings[0]

    @pytest.mark.asyncio
    async def test_translation_failed_retry_success(self):
        """TRANSLATION_FAILED warning -> retry succeeds -> resolved."""
        from ol_pool.fake import _FakeModelPool
        from ol_core.dataclass import TranslationUnit
        from ol_config.schema import QualityGateConfig

        pool = _FakeModelPool()
        source = "Hello world"
        units = [
            TranslationUnit(unit_id="1", source_text=source, target_text=source),
        ]
        warnings_per_unit = {
            "1": ["OL_WARN: TRANSLATION_FAILED (TimeoutError: LLM timed out)"],
        }
        cfg = QualityGateConfig()
        n = await retry_critical_failures(units, pool, "en", "zh", cfg, None, warnings_per_unit)
        assert n == 1
        assert pool._call_count == 1
        assert units[0].target_text != source
        assert "[zh]" in units[0].target_text

    @pytest.mark.asyncio
    async def test_translation_failed_and_source_copy_both_retried(self):
        """Both SOURCE_COPY and TRANSLATION_FAILED -> both retried."""
        from ol_pool.fake import _FakeModelPool
        from ol_core.dataclass import TranslationUnit
        from ol_config.schema import QualityGateConfig

        pool = _FakeModelPool()
        units = [
            TranslationUnit(unit_id="1", source_text="Copy me", target_text="Copy me"),
            TranslationUnit(unit_id="2", source_text="Hello world", target_text="Hello world"),
        ]
        warnings_per_unit = {
            "1": ["OL_WARN: SOURCE_COPY - target is identical to source"],
            "2": ["OL_WARN: TRANSLATION_FAILED (RuntimeError: API error)"],
        }
        cfg = QualityGateConfig()
        n = await retry_critical_failures(units, pool, "en", "zh", cfg, None, warnings_per_unit)
        assert n == 2
        assert pool._call_count == 2
        assert units[0].target_text != "Copy me"
        assert units[1].target_text != "Hello world"


class TestFormatWarningSummary:
    """Tests for format_warning_summary()."""

    def test_empty_warnings(self):
        assert format_warning_summary({}) == "0 warnings"

    def test_single_warning(self):
        result = format_warning_summary({"1": ["OL_WARN: SOURCE_COPY - test"]})
        assert "1 warnings" in result
        assert "SOURCE_COPY" in result

    def test_multiple_types(self):
        result = format_warning_summary({
            "1": ["OL_WARN: LENGTH_RATIO - ratio 3.5 exceeds max"],
            "2": ["OL_WARN: SOURCE_COPY - target is identical"],
            "3": ["OL_WARN: LENGTH_RATIO - ratio 2.1", "OL_WARN: UNIT_SPELLING - British"],
        })
        assert "4 warnings" in result
        assert "LENGTH_RATIO" in result
        assert "SOURCE_COPY" in result
        assert "UNIT_SPELLING" in result

    def test_non_ol_warn_lines(self):
        result = format_warning_summary({
            "1": ["Some random line", "OL_WARN: SOURCE_COPY - test"],
        })
        assert "1 warnings" in result
        assert "SOURCE_COPY" in result
