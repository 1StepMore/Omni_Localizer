"""QA rules wrapper for translate-toolkit pofilter subset.

Selects 5-10 domain-relevant rules for software localization:
accelerators, xmltags, variables, printf, brackets.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from translate.filters.checks import CheckerConfig, FilterFailure, SeriousFilterFailure, StandardChecker

_logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    pass


class Severity(str, Enum):
    """QA warning severity levels."""

    CRITICAL = "critical"  # Can break a program
    FUNCTIONAL = "functional"  # May confuse the user
    COSMETIC = "cosmetic"  # Make it look better


@dataclass
class QAWarning:
    """Quality assurance warning from rule checking."""

    rule_id: str
    message: str
    severity: Severity
    position: int = 0  # Unit index in XLIFF file
    source_segment: str = ""
    target_segment: str = ""

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "message": self.message,
            "severity": self.severity.value,
            "position": self.position,
            "source_segment": self.source_segment,
            "target_segment": self.target_segment,
        }


# Critical rules that can break programs
CRITICAL_RULES = {"escapes", "newlines", "nplurals", "printf", "pythonbraceformat", "tabs", "variables", "xmltags"}

# Functional rules that may confuse users
FUNCTIONAL_RULES = {
    "accelerators",
    "acronyms",
    "blank",
    "emails",
    "filepaths",
    "functions",
    "gconf",
    "kdecomments",
    "long",
    "musttranslatewords",
    "notranslatewords",
    "numbers",
    "options",
    "purepunc",
    "sentencecount",
    "short",
    "spellcheck",
    "urls",
    "unchanged",
}

# Cosmetic rules
COSMETIC_RULES = {
    "brackets",
    "doublequoting",
    "doublespacing",
    "doublewords",
    "endpunc",
    "endwhitespace",
    "puncspacing",
    "simplecaps",
    "simpleplurals",
    "singlequoting",
    "startcaps",
    "startpunc",
    "startwhitespace",
    "validchars",
}


def _get_severity(rule_id: str) -> Severity:
    """Determine severity from rule ID."""
    if rule_id in CRITICAL_RULES:
        return Severity.CRITICAL
    if rule_id in FUNCTIONAL_RULES:
        return Severity.FUNCTIONAL
    return Severity.COSMETIC


# Selected rules for software localization
SELECTED_RULES = {
    "accelerators",
    "brackets",
    "printf",
    "variables",
    "xmltags",
}


class QARulesChecker:
    """Wrapper for translate-toolkit StandardChecker with selected rules.

    Provides QA checks for XLIFF translation units using a subset of
    translate-toolkit pofilter rules relevant to software localization.
    """

    def __init__(
        self,
        accelmarkers: str | None = "&",
        target_language: str | None = None,
    ) -> None:
        self._accelmarkers = accelmarkers
        self._target_language = target_language
        self._checker = StandardChecker(
            excludefilters=None,
            limitfilters=list(SELECTED_RULES),
        )
        # Configure the checker with proper language settings for accelerator validation
        config = CheckerConfig()
        config.accelmarkers = [accelmarkers] if accelmarkers else []
        config.sourcelang = type("Sourcelang", (), {"validaccel": "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"})()
        config.lang = type("Targetlang", (), {"validaccel": "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"})()
        config.criticaltests = []
        self._checker.setconfig(config)

    def check_unit(self, source: str, target: str, position: int = 0) -> list[QAWarning]:
        """Check a single source-target pair.

        Args:
            source: Source segment text
            target: Target segment text
            position: Unit index for position tracking

        Returns:
            List of QAWarning instances for failed checks
        """
        warnings: list[QAWarning] = []

        # Set up str1 and str2 directly to avoid unit object requirements
        self._checker.str1 = source
        self._checker.str2 = target
        self._checker.hasplural = False

        # Run each selected filter individually for better error reporting
        for rule_id in SELECTED_RULES:
            try:
                filter_method = getattr(self._checker, rule_id, None)
                if filter_method is None:
                    continue
                result = filter_method(source, target)
                # filter_method returns True if pass, returns False on fail (no exception),
                # or raises FilterFailure/SeriousFilterFailure
                if result:
                    continue
                warnings.append(
                    QAWarning(
                        rule_id=rule_id,
                        message=f"QA rule {rule_id} did not pass",
                        severity=_get_severity(rule_id),
                        position=position,
                        source_segment=source,
                        target_segment=target,
                    )
                )
            except FilterFailure as e:
                warnings.append(
                    QAWarning(
                        rule_id=rule_id,
                        message=str(e),
                        severity=_get_severity(rule_id),
                        position=position,
                        source_segment=source,
                        target_segment=target,
                    )
                )
            except SeriousFilterFailure as e:
                warnings.append(
                    QAWarning(
                        rule_id=rule_id,
                        message=str(e),
                        severity=Severity.CRITICAL,
                        position=position,
                        source_segment=source,
                        target_segment=target,
                    )
                )
            except Exception as e:
                _logger.warning(
                    "QA rule %s raised on source=%r target=%r: %s",
                    rule_id, source[:80], target[:80], e,
                    exc_info=True,
                )
                continue

        return warnings

    def check_batch(self, units: list[tuple[str, str]]) -> list[QAWarning]:
        """Check multiple source-target pairs.

        Args:
            units: List of (source, target) tuples

        Returns:
            Flat list of QAWarning instances for all failed checks
        """
        all_warnings: list[QAWarning] = []
        for position, (source, target) in enumerate(units):
            unit_warnings = self.check_unit(source, target, position)
            all_warnings.extend(unit_warnings)
        return all_warnings


def check_qa_rules(xliff_content: str) -> list[QAWarning]:
    """Check XLIFF content against selected QA rules.

    Parses XLIFF content and runs pofilter subset checks on each unit.
    This is a simplified wrapper that extracts source/target from XLIFF
    and delegates to QARulesChecker.

    Args:
        xliff_content: XLIFF file content as string

    Returns:
        List of QAWarning instances for all failed checks across all units
    """
    import re

    warnings: list[QAWarning] = []
    checker = QARulesChecker()

    # Parse XLIFF to extract source-target pairs
    # Simple regex-based extraction for common XLIFF patterns
    # Example: <trans-unit id="1"><source>text</source><target>translated</target></trans-unit>
    unit_pattern = re.compile(
        r'<trans-unit[^>]*id="([^"]*)"[^>]*>.*?<source[^>]*>(.*?)</source>.*?<target[^>]*>(.*?)</target>.*?</trans-unit>',
        re.DOTALL,
    )

    units: list[tuple[str, str]] = []
    for match in unit_pattern.finditer(xliff_content):
        unit_id = match.group(1)
        source = _unescape_xml(match.group(2))
        target = _unescape_xml(match.group(3))
        units.append((source, target))

    # If simple pattern didn't match, try alternate XLIFF structure
    if not units:
        alt_pattern = re.compile(
            r'<trans-unit[^>]*id="([^"]*)"[^>]*>\s*<source>(.*?)</source>\s*<target>(.*?)</target>\s*</trans-unit>',
            re.DOTALL,
        )
        for match in alt_pattern.finditer(xliff_content):
            unit_id = match.group(1)
            source = _unescape_xml(match.group(2))
            target = _unescape_xml(match.group(3))
            units.append((source, target))

    # Check all units
    for position, (source, target) in enumerate(units):
        unit_warnings = checker.check_unit(source, target, position)
        warnings.extend(unit_warnings)

    return warnings


def _unescape_xml(text: str) -> str:
    """Unescape common XML entities."""
    return (
        text.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&apos;", "'")
    )


# Convenience function for direct rule checking
def check_pair(source: str, target: str, position: int = 0) -> list[QAWarning]:
    """Check a source-target pair directly without XLIFF parsing.

    Args:
        source: Source segment text
        target: Target segment text
        position: Unit index for position tracking

    Returns:
        List of QAWarning instances for failed checks
    """
    checker = QARulesChecker()
    return checker.check_unit(source, target, position)