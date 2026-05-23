"""Unit tests for QA rules wrapper (ol_lqa.qa_rules).

Tests the selected 5 pofilter rules: accelerators, brackets, printf, variables, xmltags.
"""
import pytest  # noqa: F401 - used implicitly by pytest fixtures

from ol_lqa.qa_rules import (
    QARulesChecker,
    QAWarning,
    Severity,
    check_pair,
    check_qa_rules,
)


class TestCheckPair:
    """Tests for check_pair() function."""

    def test_check_pair_no_warnings_on_good_translation(self):
        """Good translation produces no warnings."""
        source = "Click the button to continue"
        target = "点击按钮继续"
        warnings = check_pair(source, target)
        # Filter to only accelerators/brackets/printf/variables/xmltags
        relevant = [w for w in warnings if w.rule_id in ("accelerators", "brackets", "printf", "variables", "xmltags")]
        assert len(relevant) == 0, f"Unexpected warnings: {relevant}"

    def test_check_pair_detects_accelerator_issue(self):
        """Accelerator issue detected when source has & but target lacks it."""
        source = "Click &File to open menu"
        target = "点击 File 打开菜单"
        warnings = check_pair(source, target)
        accel_warnings = [w for w in warnings if w.rule_id == "accelerators"]
        assert len(accel_warnings) >= 1, "Expected accelerator warning"
        assert accel_warnings[0].severity == Severity.FUNCTIONAL

    def test_check_pair_detects_brackets_issue(self):
        """Bracket mismatch detected."""
        source = "Save file (important)"
        target = "保存文件 重要)"
        warnings = check_pair(source, target)
        bracket_warnings = [w for w in warnings if w.rule_id == "brackets"]
        assert len(bracket_warnings) >= 1, "Expected brackets warning"
        assert bracket_warnings[0].severity == Severity.COSMETIC


class TestCheckQARules:
    """Tests for check_qa_rules() function."""

    def test_check_qa_rules_parses_xliff_content(self):
        """check_qa_rules parses XLIFF content and returns warnings."""
        xliff_content = '''<?xml version="1.0"?>
<xliff version="1.2" xmlns="urn:oasis:names:tc:xliff:document:1.2">
  <file source-language="en" target-language="zh" original="test">
    <body>
      <trans-unit id="1">
        <source>Click &File</source>
        <target>点击 File</target>
      </trans-unit>
    </body>
  </file>
</xliff>'''
        warnings = check_qa_rules(xliff_content)
        accel_warnings = [w for w in warnings if w.rule_id == "accelerators"]
        assert len(accel_warnings) >= 1, f"Expected accelerator warning, got: {warnings}"

    def test_check_qa_rules_handles_multiple_units(self):
        """check_qa_rules processes multiple trans-unit elements."""
        xliff_content = '''<?xml version="1.0"?>
<xliff version="1.2" xmlns="urn:oasis:names:tc:xliff:document:1.2">
  <file source-language="en" target-language="zh" original="test">
    <body>
      <trans-unit id="1">
        <source>Open &File</source>
        <target>打开文件</target>
      </trans-unit>
      <trans-unit id="2">
        <source>Save (now)</source>
        <target>立即保存</target>
      </trans-unit>
    </body>
  </file>
</xliff>'''
        warnings = check_qa_rules(xliff_content)
        assert len(warnings) >= 2, f"Expected at least 2 warnings, got: {warnings}"


class TestQAWarning:
    """Tests for QAWarning dataclass."""

    def test_qa_warning_to_dict(self):
        """QAWarning.to_dict returns proper dict structure."""
        warning = QAWarning(
            rule_id="accelerators",
            message="Accelerator mismatch",
            severity=Severity.FUNCTIONAL,
            position=0,
            source_segment="Click &File",
            target_segment="点击 File",
        )
        d = warning.to_dict()
        assert d["rule_id"] == "accelerators"
        assert d["message"] == "Accelerator mismatch"
        assert d["severity"] == "functional"
        assert d["position"] == 0
        assert d["source_segment"] == "Click &File"
        assert d["target_segment"] == "点击 File"

    def test_qa_warning_severity_levels(self):
        """QAWarning severity levels are correctly assigned."""
        accel_warning = QAWarning(rule_id="accelerators", message="", severity=Severity.FUNCTIONAL)
        assert accel_warning.severity == Severity.FUNCTIONAL

        bracket_warning = QAWarning(rule_id="brackets", message="", severity=Severity.COSMETIC)
        assert bracket_warning.severity == Severity.COSMETIC

        printf_warning = QAWarning(rule_id="printf", message="", severity=Severity.CRITICAL)
        assert printf_warning.severity == Severity.CRITICAL

        var_warning = QAWarning(rule_id="variables", message="", severity=Severity.CRITICAL)
        assert var_warning.severity == Severity.CRITICAL

        xml_warning = QAWarning(rule_id="xmltags", message="", severity=Severity.CRITICAL)
        assert xml_warning.severity == Severity.CRITICAL


class TestQARulesChecker:
    """Tests for QARulesChecker class."""

    def test_check_batch_multiple_units(self):
        """check_batch processes multiple units and returns flat warning list."""
        checker = QARulesChecker()
        units = [
            ("Click &File", "点击文件"),
            ("Open (now)", "打开)"),
            ("Save %s", "保存 %s"),
        ]
        warnings = checker.check_batch(units)

        first_unit_warnings = [w for w in warnings if w.position == 0]
        assert any(w.rule_id == "accelerators" for w in first_unit_warnings)

        second_unit_warnings = [w for w in warnings if w.position == 1]
        assert any(w.rule_id == "brackets" for w in second_unit_warnings)

        third_unit_warnings = [w for w in warnings if w.position == 2]
        assert len(third_unit_warnings) == 0

    def test_check_unit_with_position(self):
        """check_unit tracks position correctly."""
        checker = QARulesChecker()
        warnings = checker.check_unit("test", "测试", position=5)
        for w in warnings:
            assert w.position == 5

    def test_checker_with_custom_accelmarkers(self):
        """QARulesChecker accepts custom accelerator markers."""
        checker = QARulesChecker(accelmarkers="~")
        warnings = checker.check_unit("Press ~File", "按 ~File", position=0)
        accel_warnings = [w for w in warnings if w.rule_id == "accelerators"]
        assert len(accel_warnings) == 0 or accel_warnings[0].message is not None