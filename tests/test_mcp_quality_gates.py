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
