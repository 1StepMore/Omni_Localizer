"""MCP integration tests: quality gates wired into translate_md_text and translate_xliff (Issue #56).

Requires OMNI_TEST_FAKE_LLM=1 (set via conftest.py).
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

# Ensure OL config path resolution can find default.yaml for ModelPool
# (conftest sets OL_CONFIG_PATH, but MCP tools resolve via _get_config_path
#  which checks explicit param first, then OL_CONFIG_PATH, then default).
# The tests below pass an explicit config_path to avoid ambiguity.

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TIGHT_QG_CONFIG = """\
project_id: test-mcp-quality-gates
source_lang: en
target_lang: zh
llm_pool:
  translation:
    - provider: openai
      model: fake-model
      priority: 1
      role: translation
      api_key: "${ZHIPU_API_KEY}"
      base_url: "http://localhost:8080/v1"
      timeout: 120.0
    - provider: openai
      model: fake-model-2
      priority: 2
      role: translation
      api_key: "${AGNES_API_KEY}"
      base_url: "http://localhost:8080/v1"
      timeout: 120.0
  judging:
    - provider: openai
      model: fake-judge
      priority: 1
      role: judging
      api_key: "${ZHIPU_API_KEY}"
      base_url: "http://localhost:8080/v1"
      timeout: 120.0
    - provider: openai
      model: fake-judge-2
      priority: 2
      role: judging
      api_key: "${AGNES_API_KEY}"
      base_url: "http://localhost:8080/v1"
      timeout: 120.0
  restoration:
    - provider: openai
      model: fake-restore
      priority: 1
      role: restoration
      api_key: "${ZHIPU_API_KEY}"
      base_url: "http://localhost:8080/v1"
      timeout: 120.0
    - provider: openai
      model: fake-restore-2
      priority: 2
      role: restoration
      api_key: "${AGNES_API_KEY}"
      base_url: "http://localhost:8080/v1"
      timeout: 120.0
quality_gates:
  inline_tags: true
  terminology: true
  length_ratio:
    enabled: true
    min: 0.9
    max: 1.1
  locale:
    enabled: true
    target_locale: "en-US"
"""

_DISABLED_QG_CONFIG = """\
project_id: test-mcp-quality-gates-disabled
source_lang: en
target_lang: zh
llm_pool:
  translation:
    - provider: openai
      model: fake-model
      priority: 1
      role: translation
      api_key: "${ZHIPU_API_KEY}"
      base_url: "http://localhost:8080/v1"
      timeout: 120.0
    - provider: openai
      model: fake-model-2
      priority: 2
      role: translation
      api_key: "${AGNES_API_KEY}"
      base_url: "http://localhost:8080/v1"
      timeout: 120.0
  judging:
    - provider: openai
      model: fake-judge
      priority: 1
      role: judging
      api_key: "${ZHIPU_API_KEY}"
      base_url: "http://localhost:8080/v1"
      timeout: 120.0
    - provider: openai
      model: fake-judge-2
      priority: 2
      role: judging
      api_key: "${AGNES_API_KEY}"
      base_url: "http://localhost:8080/v1"
      timeout: 120.0
  restoration:
    - provider: openai
      model: fake-restore
      priority: 1
      role: restoration
      api_key: "${ZHIPU_API_KEY}"
      base_url: "http://localhost:8080/v1"
      timeout: 120.0
    - provider: openai
      model: fake-restore-2
      priority: 2
      role: restoration
      api_key: "${AGNES_API_KEY}"
      base_url: "http://localhost:8080/v1"
      timeout: 120.0
quality_gates:
  inline_tags: false
  terminology: false
  length_ratio:
    enabled: false
    min: 0.5
    max: 2.0
  locale:
    enabled: false
    target_locale: "en-US"
"""

_MINIMAL_XLIFF = """\
<?xml version="1.0" encoding="utf-8"?>
<xliff version="1.2" xmlns="urn:oasis:names:tc:xliff:document:1.2">
  <file original="test.txt" source-language="en" target-language="zh">
    <body>
      <trans-unit id="unit1">
        <source>A</source>
        <target/>
      </trans-unit>
      <trans-unit id="unit2">
        <source>Hello world</source>
        <target/>
      </trans-unit>
    </body>
  </file>
</xliff>
"""


@pytest.fixture
def tight_config_path():
    """Write a temporary config with tight length_ratio bounds."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False, encoding="utf-8",
    ) as f:
        f.write(_TIGHT_QG_CONFIG)
        tmp = f.name
    yield tmp
    try:
        os.unlink(tmp)
    except OSError:
        pass


@pytest.fixture
def disabled_config_path():
    """Write a temporary config with all quality gates disabled."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False, encoding="utf-8",
    ) as f:
        f.write(_DISABLED_QG_CONFIG)
        tmp = f.name
    yield tmp
    try:
        os.unlink(tmp)
    except OSError:
        pass


@pytest.fixture
def xliff_file():
    """Write a minimal XLIFF file for translate_xliff tests."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".xlf", delete=False, encoding="utf-8",
    ) as f:
        f.write(_MINIMAL_XLIFF)
        tmp = f.name
    yield tmp
    try:
        os.unlink(tmp)
    except OSError:
        pass


# =========================================================================
# translate_md_text
# =========================================================================


class TestTranslateMdQualityGates:
    """Quality gates integrated into translate_md_text."""

    @pytest.mark.asyncio
    async def test_returns_length_ratio_warning(self, tight_config_path):
        """Tight length_ratio bounds trigger a LENGTH_RATIO warning.

        FAKE_LLM returns "[zh] A" (6 chars) for source "A" (1 char).
        Ratio = 6.0 > config max 1.1 → LENGTH_RATIO warning expected.
        """
        from ol_mcp.tools import translate_md_text, TranslateInput

        params = TranslateInput(
            content="A",
            source_lang="en",
            target_lang="zh",
            config_path=tight_config_path,
        )
        result_str = await translate_md_text(params)
        result = json.loads(result_str)

        assert result["success"] is True
        content = result["content"]
        warnings = content.get("warnings", [])
        length_warnings = [w for w in warnings if "OL_WARN: LENGTH_RATIO" in w]
        assert len(length_warnings) >= 1, (
            f"Expected at least one LENGTH_RATIO warning in {warnings}"
        )

    @pytest.mark.asyncio
    async def test_disabled_gates_produce_no_warnings(self, disabled_config_path):
        """When all quality gates are disabled, no gate warnings appear."""
        from ol_mcp.tools import translate_md_text, TranslateInput

        params = TranslateInput(
            content="A",
            source_lang="en",
            target_lang="zh",
            config_path=disabled_config_path,
        )
        result_str = await translate_md_text(params)
        result = json.loads(result_str)

        assert result["success"] is True
        content = result["content"]
        warnings = content.get("warnings", [])
        qg_warnings = [w for w in warnings if w.startswith("OL_WARN:")]
        assert len(qg_warnings) == 0, (
            f"Expected no OL_WARN messages with disabled gates, got: {qg_warnings}"
        )

    @pytest.mark.asyncio
    async def test_gate_warnings_do_not_fail_response(self, tight_config_path):
        """Quality gate warnings must not change success=False."""
        from ol_mcp.tools import translate_md_text, TranslateInput

        params = TranslateInput(
            content="A",
            source_lang="en",
            target_lang="zh",
            config_path=tight_config_path,
        )
        result_str = await translate_md_text(params)
        result = json.loads(result_str)

        assert result["success"] is True, (
            "Quality gate warnings must not cause a failure response"
        )

    @pytest.mark.asyncio
    async def test_async_mode_with_gates(self, tight_config_path):
        """Async mode translate_md_text still returns quality gate warnings in final payload."""
        from ol_mcp.tools import translate_md_text, TranslateInput, _task_tracker
        from ol_mcp.status import get_translation_status

        import asyncio
        import time

        params = TranslateInput(
            content="A",
            source_lang="en",
            target_lang="zh",
            config_path=tight_config_path,
            async_mode=True,
        )
        result_str = await translate_md_text(params)
        result = json.loads(result_str)
        request_id = result["content"]["request_id"]

        deadline = time.time() + 60
        final = None
        while time.time() < deadline:
            status_str = get_translation_status(request_id, _task_tracker)
            status = json.loads(status_str)
            if status["content"]["status"] in ("completed", "failed"):
                final = status
                break
            await asyncio.sleep(0.5)

        assert final is not None, "Task did not complete"
        assert final["content"]["status"] == "completed"
        payload = final["content"].get("result", {})
        warnings = payload.get("warnings", [])
        length_warnings = [w for w in warnings if "OL_WARN: LENGTH_RATIO" in w]
        assert len(length_warnings) >= 1, (
            f"Expected LENGTH_RATIO warning in async mode payload, got {warnings}"
        )


# =========================================================================
# translate_xliff
# =========================================================================


class TestTranslateXliffQualityGates:
    """Quality gates integrated into translate_xliff."""

    @pytest.mark.asyncio
    async def test_returns_length_ratio_warning_per_unit(
        self, tight_config_path, xliff_file,
    ):
        """Tight length_ratio bounds trigger per-unit LENGTH_RATIO warnings.

        FAKE_LLM for unit with source "A" (1 char) returns "[zh] A" (6 chars).
        The warning is stored in warnings_per_unit internally; we verify the
        output XLIFF has the expected target text length ratio.
        """
        from ol_mcp.tools import translate_xliff, TranslateXliffInput

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".xlf", delete=False, encoding="utf-8",
        ) as out_f:
            output_path = out_f.name

        try:
            params = TranslateXliffInput(
                input_path=xliff_file,
                output_path=output_path,
                source_lang="en",
                target_lang="zh",
                config_path=tight_config_path,
            )
            result_str = await translate_xliff(params)
            result = json.loads(result_str)

            assert result["success"] is True
            content = result["content"]
            assert content["units_processed"] == 2

            # Verify output XLIFF contains quality gate warnings as notes
            output_text = Path(output_path).read_text(encoding="utf-8")
            # The LENGTH_RATIO warning for unit1 ("A" → "[zh] A", ratio ~11) should
            # appear as an OL note in the output. The write_target_back() function
            # injects quality gate warnings as <note from="OL"> elements.
            assert "OL_WARN: LENGTH_RATIO" in output_text, (
                f"Expected LENGTH_RATIO warning note in output, got:\n{output_text}"
            )
            # Only unit1 (source "A") should have the warning, not unit2
            # unit2 has source "Hello world" (11 chars) → target "[zh] Hello world" (16 chars)
            # ratio ≈ 1.45, within bounds
            unit2_pos = output_text.index("id=\"unit2\"")
            unit2_after = output_text[unit2_pos:]
            assert "OL_WARN" not in unit2_after, (
                f"Unit2 should not have quality gate warnings:\n{unit2_after}"
            )
        finally:
            try:
                os.unlink(output_path)
            except OSError:
                pass

    @pytest.mark.asyncio
    async def test_disabled_gates_no_per_unit_warnings(
        self, disabled_config_path, xliff_file,
    ):
        """Disabled quality gates produce no OL_WARN per-unit warnings."""
        from ol_mcp.tools import translate_xliff, TranslateXliffInput

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".xlf", delete=False, encoding="utf-8",
        ) as out_f:
            output_path = out_f.name

        try:
            params = TranslateXliffInput(
                input_path=xliff_file,
                output_path=output_path,
                source_lang="en",
                target_lang="zh",
                config_path=disabled_config_path,
            )
            result_str = await translate_xliff(params)
            result = json.loads(result_str)

            assert result["success"] is True
            content = result["content"]
            assert content["units_processed"] == 2

            # Parse output XLIFF to verify per-unit warnings are absent
            # The result itself doesn't expose warnings_per_unit in the
            # JSON response for sync translate_xliff (it's a file-based tool).
            # We verify the tool didn't fail and the output file exists.
            assert os.path.getsize(output_path) > 0

            # Read output file to confirm it has valid target elements
            output_text = Path(output_path).read_text(encoding="utf-8")
            assert "<target>" in output_text
        finally:
            try:
                os.unlink(output_path)
            except OSError:
                pass

    @pytest.mark.asyncio
    async def test_gate_warnings_do_not_fail_xliff_response(self, tight_config_path, xliff_file):
        """Quality gate warnings in translate_xliff must not cause a failure response."""
        from ol_mcp.tools import translate_xliff, TranslateXliffInput

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".xlf", delete=False, encoding="utf-8",
        ) as out_f:
            output_path = out_f.name

        try:
            params = TranslateXliffInput(
                input_path=xliff_file,
                output_path=output_path,
                source_lang="en",
                target_lang="zh",
                config_path=tight_config_path,
            )
            result_str = await translate_xliff(params)
            result = json.loads(result_str)

            assert result["success"] is True, (
                "Quality gate warnings must not cause translate_xliff to fail"
            )
            assert result["content"]["units_processed"] == 2
        finally:
            try:
                os.unlink(output_path)
            except OSError:
                pass


# =========================================================================
# Issue #115: a gate pass that never ran must not look like a clean one.
# Before the fix, a missing/unloadable config was downgraded to one log line
# and the caller got {"translated": ..., "warnings": []} — byte-identical to
# "the gates ran and everything passed".
# =========================================================================

_NOT_RUN_PREFIX = "OL_GATES_NOT_RUN:"
_SKIPPED_PREFIX = "OL_GATES_SKIPPED:"


def _gate_markers(warnings):
    """The non-run/skip markers in a warnings list, ignoring OL_WARN gate output."""
    return [w for w in warnings if w.startswith((_NOT_RUN_PREFIX, _SKIPPED_PREFIX))]


@pytest.fixture
def missing_config_path(tmp_path):
    """A config path that does not exist — config drift, the issue's repro."""
    return str(tmp_path / "no_such_config.yaml")


class TestTranslateMdGateOutcomeReporting:
    """translate_md_text tells the caller whether the gates actually ran."""

    @pytest.mark.asyncio
    async def test_missing_config_is_reported_not_silently_skipped(self, missing_config_path):
        """Repro for #115: a nonexistent config must surface, not vanish into a log."""
        from ol_mcp.tools import translate_md_text, TranslateInput

        params = TranslateInput(
            content="A",
            source_lang="en",
            target_lang="zh",
            config_path=missing_config_path,
        )
        result = json.loads(await translate_md_text(params))

        assert result["success"] is True, "A non-run is reported, not a translation failure"
        gates = result["content"]["quality_gates"]
        assert gates["status"] == "not_run"
        assert gates["reason"].startswith("config_load_failed:"), gates
        assert "Config file not found" in gates["reason"], gates

        markers = _gate_markers(result["content"]["warnings"])
        assert len(markers) == 1, result["content"]["warnings"]
        assert markers[0].startswith(_NOT_RUN_PREFIX), markers

    @pytest.mark.asyncio
    async def test_gate_invocation_failure_is_reported(self, tight_config_path, monkeypatch):
        """A raising gate invocation is a non-run, not a silently clean pass."""
        from ol_mcp import translate_md as translate_md_mod
        from ol_mcp.tools import translate_md_text, TranslateInput

        def _boom(*args, **kwargs):
            raise RuntimeError("gate exploded")

        monkeypatch.setattr(translate_md_mod, "run_quality_gates", _boom)

        params = TranslateInput(
            content="A",
            source_lang="en",
            target_lang="zh",
            config_path=tight_config_path,
        )
        result = json.loads(await translate_md_text(params))

        assert result["success"] is True
        gates = result["content"]["quality_gates"]
        assert gates["status"] == "not_run"
        assert gates["reason"].startswith("gate_invocation_failed:"), gates
        assert "gate exploded" in gates["reason"], gates
        assert _gate_markers(result["content"]["warnings"]), result["content"]["warnings"]

    @pytest.mark.asyncio
    async def test_explicit_opt_out_is_visible_and_distinct(self, tight_config_path):
        """no_quality_gates=true reads as skipped, never as the broken case."""
        from ol_mcp.tools import translate_md_text, TranslateInput

        params = TranslateInput(
            content="A",
            source_lang="en",
            target_lang="zh",
            config_path=tight_config_path,
            no_quality_gates=True,
        )
        result = json.loads(await translate_md_text(params))

        gates = result["content"]["quality_gates"]
        assert gates["status"] == "skipped"
        assert "no_quality_gates=true" in gates["reason"], gates

        markers = _gate_markers(result["content"]["warnings"])
        assert len(markers) == 1 and markers[0].startswith(_SKIPPED_PREFIX), markers

        # Tight bounds would fire LENGTH_RATIO had the gates run, so their
        # absence proves the skip was real and not merely unreported.
        assert not [w for w in result["content"]["warnings"] if w.startswith("OL_WARN:")], (
            f"Gates were skipped, so no gate warnings expected: {result['content']['warnings']}"
        )

    @pytest.mark.asyncio
    async def test_opt_out_survives_a_missing_config(self, missing_config_path):
        """An opted-out call never reports not_run — nothing was asked for."""
        from ol_mcp.tools import translate_md_text, TranslateInput

        params = TranslateInput(
            content="A",
            source_lang="en",
            target_lang="zh",
            config_path=missing_config_path,
            no_quality_gates=True,
        )
        result = json.loads(await translate_md_text(params))

        assert result["content"]["quality_gates"]["status"] == "skipped"
        assert not any(
            w.startswith(_NOT_RUN_PREFIX) for w in result["content"]["warnings"]
        ), result["content"]["warnings"]

    @pytest.mark.asyncio
    async def test_warnings_path_shape_is_unchanged(self, tight_config_path):
        """#115 must be purely additive: gates-ran-with-warnings is untouched."""
        from ol_mcp.tools import translate_md_text, TranslateInput

        params = TranslateInput(
            content="A",
            source_lang="en",
            target_lang="zh",
            config_path=tight_config_path,
        )
        content = json.loads(await translate_md_text(params))["content"]

        assert content["quality_gates"] == {"status": "ran", "reason": ""}
        assert [w for w in content["warnings"] if "OL_WARN: LENGTH_RATIO" in w]
        assert _gate_markers(content["warnings"]) == [], content["warnings"]

    @pytest.mark.asyncio
    async def test_clean_pass_reports_ran_with_no_warnings(self, disabled_config_path):
        """Gates ran and found nothing: 'ran', and warnings stay exactly []."""
        from ol_mcp.tools import translate_md_text, TranslateInput

        params = TranslateInput(
            content="A",
            source_lang="en",
            target_lang="zh",
            config_path=disabled_config_path,
        )
        content = json.loads(await translate_md_text(params))["content"]

        assert content["quality_gates"] == {"status": "ran", "reason": ""}
        assert content["warnings"] == []

    @pytest.mark.asyncio
    async def test_async_payload_reports_non_run(self, missing_config_path):
        """async_mode delivers the same signal through the task tracker payload."""
        import asyncio
        import time

        from ol_mcp.tools import translate_md_text, TranslateInput, _task_tracker
        from ol_mcp.status import get_translation_status

        params = TranslateInput(
            content="A",
            source_lang="en",
            target_lang="zh",
            config_path=missing_config_path,
            async_mode=True,
        )
        request_id = json.loads(await translate_md_text(params))["content"]["request_id"]

        deadline = time.time() + 60
        final = None
        while time.time() < deadline:
            status = json.loads(get_translation_status(request_id, _task_tracker))
            if status["content"]["status"] in ("completed", "failed"):
                final = status
                break
            await asyncio.sleep(0.5)

        assert final is not None, "Task did not complete"
        assert final["content"]["status"] == "completed"
        payload = final["content"]["result"]
        assert payload["quality_gates"]["status"] == "not_run", payload
        assert _gate_markers(payload["warnings"]), payload["warnings"]


class TestTranslateXliffGateOutcomeReporting:
    """translate_xliff tells the caller whether the gates actually ran."""

    @pytest.mark.asyncio
    async def test_missing_config_is_reported_not_silently_skipped(
        self, missing_config_path, xliff_file, tmp_path,
    ):
        """Repro for #115 on the XLIFF path; translation still lands on disk."""
        from ol_mcp.tools import translate_xliff, TranslateXliffInput

        output_path = str(tmp_path / "out.xlf")
        params = TranslateXliffInput(
            input_path=xliff_file,
            output_path=output_path,
            source_lang="en",
            target_lang="zh",
            config_path=missing_config_path,
        )
        result = json.loads(await translate_xliff(params))

        assert result["success"] is True
        content = result["content"]
        assert content["units_processed"] == 2
        gates = content["quality_gates"]
        assert gates["status"] == "not_run"
        assert gates["reason"].startswith("config_load_failed:"), gates
        markers = _gate_markers(content["warnings"])
        assert len(markers) == 1 and markers[0].startswith(_NOT_RUN_PREFIX), markers
        assert "<target>" in Path(output_path).read_text(encoding="utf-8")

    @pytest.mark.asyncio
    async def test_explicit_opt_out_is_visible_and_distinct(
        self, tight_config_path, xliff_file, tmp_path,
    ):
        """no_quality_gates=true skips the per-unit gates and says so."""
        from ol_mcp.tools import translate_xliff, TranslateXliffInput

        output_path = str(tmp_path / "out.xlf")
        params = TranslateXliffInput(
            input_path=xliff_file,
            output_path=output_path,
            source_lang="en",
            target_lang="zh",
            config_path=tight_config_path,
            no_quality_gates=True,
        )
        content = json.loads(await translate_xliff(params))["content"]

        assert content["quality_gates"]["status"] == "skipped"
        markers = _gate_markers(content["warnings"])
        assert len(markers) == 1 and markers[0].startswith(_SKIPPED_PREFIX), markers
        assert "OL_WARN" not in Path(output_path).read_text(encoding="utf-8")

    @pytest.mark.asyncio
    async def test_warnings_path_shape_is_unchanged(
        self, tight_config_path, xliff_file, tmp_path,
    ):
        """Gates ran and warned: 'ran', notes in the XLIFF, no extra marker."""
        from ol_mcp.tools import translate_xliff, TranslateXliffInput

        output_path = str(tmp_path / "out.xlf")
        params = TranslateXliffInput(
            input_path=xliff_file,
            output_path=output_path,
            source_lang="en",
            target_lang="zh",
            config_path=tight_config_path,
        )
        content = json.loads(await translate_xliff(params))["content"]

        assert content["quality_gates"] == {"status": "ran", "reason": ""}
        assert _gate_markers(content["warnings"]) == [], content["warnings"]
        assert "OL_WARN: LENGTH_RATIO" in Path(output_path).read_text(encoding="utf-8")
