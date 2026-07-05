"""Tests for BatchProcessor integration with quality gates (Issue #56)."""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from ol_batch.config import BatchConfig
from ol_batch.processor import BatchProcessor
from ol_config.schema import (
    LengthRatioGateConfig,
    LocaleGateConfig,
    QualityGateConfig,
)


class TestBatchQualityGates:
    """BatchProcessor must call run_quality_gates() when quality_gates is
    configured, and embed warnings as HTML comments in .md output files."""

    @pytest.fixture
    def mock_model_pool(self):
        pool = MagicMock()
        pool.translate = AsyncMock(return_value="translated content")
        return pool

    @pytest.fixture
    def mock_limiter(self):
        limiter = MagicMock()
        limiter.translation = MagicMock()
        limiter.translation.return_value.__aenter__ = AsyncMock(return_value=None)
        limiter.translation.return_value.__aexit__ = AsyncMock(return_value=None)
        return limiter

    @pytest.fixture
    def batch_config(self):
        return BatchConfig(timeout=30.0)

    @pytest.mark.anyio
    async def test_enabled_gates_append_length_ratio_warning(
        self, mock_model_pool, mock_limiter, batch_config,
    ):
        """Length ratio gate fires when target is much longer than source."""
        short_source = "Hello world."
        # The pool returns a very short translation, so to trigger
        # length_ratio we set min/max such that even this short target
        # exceeds the bound.  Actually, the default mock returns
        # "translated content" (17 chars) vs "Hello world." (12 chars)
        # — ratio ~1.42, which is above max=1.0.
        mock_model_pool.translate.return_value = (
            "This is a very long translated content that should trigger "
            "the length ratio quality gate warning because it is much "
            "longer than the original source text."
        )

        quality_gates = QualityGateConfig(
            inline_tags=False,
            terminology=False,
            length_ratio=LengthRatioGateConfig(enabled=True, min=0.5, max=1.0),
            locale=LocaleGateConfig(enabled=False),
        )

        processor = BatchProcessor(
            config=batch_config,
            model_pool=mock_model_pool,
            limiter=mock_limiter,
            quality_gates=quality_gates,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            input_dir = Path(tmpdir) / "input"
            output_dir = Path(tmpdir) / "output"
            input_dir.mkdir()
            output_dir.mkdir()

            test_file = input_dir / "test.md"
            test_file.write_text(short_source)

            result = await processor.process_batch([test_file], output_dir)

            assert result.total == 1
            assert len(result.succeeded) == 1

            output_content = (output_dir / "test.md").read_text()
            assert "<!-- Quality gate warnings -->" in output_content, (
                "Output should contain the quality gate warning header"
            )
            assert "OL_WARN: LENGTH_RATIO" in output_content, (
                "Output should contain the LENGTH_RATIO warning"
            )

    @pytest.mark.anyio
    async def test_disabled_gates_no_warning(
        self, mock_model_pool, mock_limiter, batch_config,
    ):
        """No warnings appended when all quality gates are disabled."""
        mock_model_pool.translate.return_value = (
            "This is a very long translated content that should trigger "
            "the length ratio quality gate warning because it is much "
            "longer than the original source text."
        )

        quality_gates = QualityGateConfig(
            inline_tags=False,
            terminology=False,
            length_ratio=LengthRatioGateConfig(enabled=False, min=0.5, max=1.0),
            locale=LocaleGateConfig(enabled=False),
        )

        processor = BatchProcessor(
            config=batch_config,
            model_pool=mock_model_pool,
            limiter=mock_limiter,
            quality_gates=quality_gates,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            input_dir = Path(tmpdir) / "input"
            output_dir = Path(tmpdir) / "output"
            input_dir.mkdir()
            output_dir.mkdir()

            test_file = input_dir / "test.md"
            test_file.write_text("Hello world.")

            result = await processor.process_batch([test_file], output_dir)

            assert result.total == 1
            assert len(result.succeeded) == 1

            output_content = (output_dir / "test.md").read_text()
            assert "<!-- Quality gate warnings -->" not in output_content, (
                "Output should NOT contain quality gate comments when all "
                "gates are disabled"
            )
            assert "OL_WARN:" not in output_content, (
                "Output should NOT contain any OL_WARN from quality gates"
            )

    @pytest.mark.anyio
    async def test_gates_with_no_warnings_pass_through(
        self, mock_model_pool, mock_limiter, batch_config,
    ):
        """No warnings emitted when the translated text passes all gates."""
        # Source and target have similar length → length ratio passes
        # (ratio ~1.0, within default 0.5-2.0).
        mock_model_pool.translate.return_value = "Hello beautiful world."

        quality_gates = QualityGateConfig(
            inline_tags=False,
            terminology=False,
            length_ratio=LengthRatioGateConfig(enabled=True, min=0.1, max=20.0),
            locale=LocaleGateConfig(enabled=False),
        )

        processor = BatchProcessor(
            config=batch_config,
            model_pool=mock_model_pool,
            limiter=mock_limiter,
            quality_gates=quality_gates,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            input_dir = Path(tmpdir) / "input"
            output_dir = Path(tmpdir) / "output"
            input_dir.mkdir()
            output_dir.mkdir()

            test_file = input_dir / "test.md"
            test_file.write_text("Hello world.")

            result = await processor.process_batch([test_file], output_dir)

            assert result.total == 1
            assert len(result.succeeded) == 1

            output_content = (output_dir / "test.md").read_text()
            assert "<!-- Quality gate warnings -->" not in output_content, (
                "Output should NOT contain quality gate comments when "
                "all gates pass"
            )

    @pytest.mark.anyio
    async def test_multiple_files_get_individual_warnings(
        self, mock_model_pool, mock_limiter, batch_config,
    ):
        """Each file gets its own quality gate assessment."""
        mock_model_pool.translate.return_value = (
            "This is a very long translated content that should trigger "
            "the length ratio gate because it is much longer than the "
            "original source text.  Adding more words to ensure the "
            "ratio is well above 1.0."
        )

        quality_gates = QualityGateConfig(
            inline_tags=False,
            terminology=False,
            length_ratio=LengthRatioGateConfig(enabled=True, min=0.5, max=1.0),
            locale=LocaleGateConfig(enabled=False),
        )

        processor = BatchProcessor(
            config=batch_config,
            model_pool=mock_model_pool,
            limiter=mock_limiter,
            quality_gates=quality_gates,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            input_dir = Path(tmpdir) / "input"
            output_dir = Path(tmpdir) / "output"
            input_dir.mkdir()
            output_dir.mkdir()

            for i in range(3):
                f = input_dir / f"file{i}.md"
                f.write_text(f"Short source {i}.")

            files = [
                input_dir / "file0.md",
                input_dir / "file1.md",
                input_dir / "file2.md",
            ]

            result = await processor.process_batch(files, output_dir)

            assert result.total == 3
            assert len(result.succeeded) == 3

            for i in range(3):
                content = (output_dir / f"file{i}.md").read_text()
                assert "<!-- Quality gate warnings -->" in content, (
                    f"file{i}.md should have quality gate warnings"
                )
                assert "OL_WARN: LENGTH_RATIO" in content, (
                    f"file{i}.md should have LENGTH_RATIO warning"
                )

    @pytest.mark.anyio
    async def test_gates_skip_when_quality_gates_is_none(
        self, mock_model_pool, mock_limiter, batch_config,
    ):
        """Default constructor (quality_gates=None) does not run gates."""
        mock_model_pool.translate.return_value = (
            "This is a very long translation that would trigger the "
            "length ratio gate if it were enabled."
        )

        processor = BatchProcessor(
            config=batch_config,
            model_pool=mock_model_pool,
            limiter=mock_limiter,
            # quality_gates defaults to None
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            input_dir = Path(tmpdir) / "input"
            output_dir = Path(tmpdir) / "output"
            input_dir.mkdir()
            output_dir.mkdir()

            test_file = input_dir / "test.md"
            test_file.write_text("Hello world.")

            result = await processor.process_batch([test_file], output_dir)

            assert result.total == 1
            assert len(result.succeeded) == 1

            output_content = (output_dir / "test.md").read_text()
            assert "<!-- Quality gate warnings -->" not in output_content
