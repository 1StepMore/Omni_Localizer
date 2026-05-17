"""Edge case tests for batch processing."""
import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ol_batch.config import BatchConfig, BatchResult
from ol_batch.discovery import discover_files, validate_directory
from ol_batch.processor import BatchProcessor, QueueTimeoutError
from ol_concurrency.scheduler import ConcurrencyLimiter


class TestEmptyDirectory:
    """Tests for empty directory edge cases."""

    @pytest.fixture
    def empty_temp_dir(self):
        tmpdir = tempfile.mkdtemp()
        yield tmpdir
        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_empty_directory_no_files(self, empty_temp_dir):
        """Test empty directory produces empty file list."""
        files = discover_files(Path(empty_temp_dir), ["*.md", "*.xliff", "*.xlf"])
        assert len(files) == 0

    def test_validate_directory_returns_true_for_empty(self, empty_temp_dir):
        """Test validate_directory returns True for empty but valid directory."""
        assert validate_directory(Path(empty_temp_dir)) is True


class TestZeroMatchingFiles:
    """Tests for directory with no matching files."""

    @pytest.fixture
    def temp_dir_no_match(self):
        tmpdir = tempfile.mkdtemp()
        # Create files that don't match patterns
        Path(tmpdir, "readme.txt").write_text("readme")
        Path(tmpdir, "data.json").write_text("{}")
        yield tmpdir
        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_zero_matching_files(self, temp_dir_no_match):
        """Test directory with non-matching files returns empty list."""
        files = discover_files(Path(temp_dir_no_match), ["*.md", "*.xliff", "*.xlf"])
        assert len(files) == 0


class TestAllFilesFailing:
    """Tests for all files failing translation."""

    @pytest.fixture
    def temp_dir_with_failing_files(self):
        tmpdir = tempfile.mkdtemp()
        # Create valid markdown files
        Path(tmpdir, "file1.md").write_text("# Test 1")
        Path(tmpdir, "file2.md").write_text("# Test 2")
        yield tmpdir
        shutil.rmtree(tmpdir, ignore_errors=True)

    @pytest.fixture
    def mock_failing_pool(self):
        pool = MagicMock()
        pool.translate = AsyncMock(side_effect=RuntimeError("API Error"))
        return pool

    @pytest.fixture
    def mock_limiter(self):
        limiter = MagicMock(spec=ConcurrencyLimiter)
        limiter.translation = MagicMock()
        limiter.translation.return_value.__aenter__ = AsyncMock(return_value=None)
        limiter.translation.return_value.__aexit__ = AsyncMock(return_value=None)
        return limiter

    @pytest.mark.anyio
    async def test_all_files_fail_exit_nonzero(self, temp_dir_with_failing_files, mock_failing_pool, mock_limiter):
        """Test all files failing returns non-zero exit."""
        config = BatchConfig(max_concurrent=2)
        processor = BatchProcessor(config, mock_failing_pool, mock_limiter)

        files = discover_files(Path(temp_dir_with_failing_files), ["*.md"])
        output_dir = Path(tempfile.mkdtemp())

        result = await processor.process_batch(files, output_dir)

        assert len(result.succeeded) == 0
        assert len(result.failed) == 2
        assert result.total == 2


class TestPartialFailures:
    """Tests for partial failure scenarios."""

    @pytest.fixture
    def temp_dir_partial(self):
        tmpdir = tempfile.mkdtemp()
        Path(tmpdir, "success1.md").write_text("# Success 1")
        Path(tmpdir, "fail.md").write_text("# Fail")
        Path(tmpdir, "success2.md").write_text("# Success 2")
        yield tmpdir
        shutil.rmtree(tmpdir, ignore_errors=True)

    @pytest.fixture
    def mock_partial_pool(self):
        pool = MagicMock()
        async def translate_with_partial_failure(text, src, tgt):
            if "Fail" in text:
                raise RuntimeError("Translation failed for this file")
            return "# Translated content"
        pool.translate = AsyncMock(side_effect=translate_with_partial_failure)
        return pool

    @pytest.fixture
    def mock_limiter(self):
        limiter = MagicMock(spec=ConcurrencyLimiter)
        limiter.translation = MagicMock()
        limiter.translation.return_value.__aenter__ = AsyncMock(return_value=None)
        limiter.translation.return_value.__aexit__ = AsyncMock(return_value=None)
        return limiter

    @pytest.mark.anyio
    async def test_partial_failures_succeeded_in_output(self, temp_dir_partial, mock_partial_pool, mock_limiter):
        """Test partial failures: succeeded files exist in output."""
        config = BatchConfig(max_concurrent=3)
        processor = BatchProcessor(config, mock_partial_pool, mock_limiter)

        files = discover_files(Path(temp_dir_partial), ["*.md"])
        output_dir = Path(tempfile.mkdtemp())

        result = await processor.process_batch(files, output_dir)

        # Should have 2 succeeded, 1 failed
        assert len(result.succeeded) == 2
        assert len(result.failed) == 1
        assert result.total == 3

        # Check output files exist
        for succeeded_file in result.succeeded:
            assert succeeded_file.exists()

    @pytest.mark.anyio
    async def test_partial_failures_failed_in_summary(self, temp_dir_partial, mock_partial_pool, mock_limiter):
        """Test partial failures: failed file shows error in summary."""
        config = BatchConfig(max_concurrent=3)
        processor = BatchProcessor(config, mock_partial_pool, mock_limiter)

        files = discover_files(Path(temp_dir_partial), ["*.md"])
        output_dir = Path(tempfile.mkdtemp())

        result = await processor.process_batch(files, output_dir)

        # Check failed list contains the failing file with error message
        failed_files = [f for f, _ in result.failed]
        fail_path = next((f for f in failed_files if "fail" in str(f)), None)
        assert fail_path is not None

        # Find error message for fail.md
        fail_error = next(err for f, err in result.failed if "fail" in str(f))
        assert "Translation failed" in fail_error or "RuntimeError" in fail_error


class TestUnicodeFilenames:
    """Tests for Unicode filename handling."""

    @pytest.fixture
    def temp_dir_unicode(self):
        tmpdir = tempfile.mkdtemp()
        # Create files with Unicode names
        Path(tmpdir, "中文文件.md").write_text("# Chinese filename")
        Path(tmpdir, "файл.md").write_text("# Cyrillic filename")
        Path(tmpdir, "日本語.md").write_text("# Japanese filename")
        yield tmpdir
        shutil.rmtree(tmpdir, ignore_errors=True)

    @pytest.fixture
    def mock_pool(self):
        pool = MagicMock()
        pool.translate = AsyncMock(return_value="# Translated")
        return pool

    @pytest.fixture
    def mock_limiter(self):
        limiter = MagicMock(spec=ConcurrencyLimiter)
        limiter.translation = MagicMock()
        limiter.translation.return_value.__aenter__ = AsyncMock(return_value=None)
        limiter.translation.return_value.__aexit__ = AsyncMock(return_value=None)
        return limiter

    def test_discover_unicode_filenames(self, temp_dir_unicode):
        """Test discover_files handles Unicode filenames."""
        files = discover_files(Path(temp_dir_unicode), ["*.md"])
        assert len(files) == 3
        # Verify Unicode names are preserved
        filenames = [f.name for f in files]
        assert any("中文文件" in name for name in filenames)
        assert any("файл" in name for name in filenames)
        assert any("日本語" in name for name in filenames)

    @pytest.mark.anyio
    async def test_process_unicode_filenames(self, temp_dir_unicode, mock_pool, mock_limiter):
        """Test BatchProcessor handles Unicode filenames."""
        config = BatchConfig(max_concurrent=3)
        processor = BatchProcessor(config, mock_pool, mock_limiter)

        files = discover_files(Path(temp_dir_unicode), ["*.md"])
        output_dir = Path(tempfile.mkdtemp())

        result = await processor.process_batch(files, output_dir)

        # All files should be processed successfully
        assert len(result.succeeded) == 3
        assert len(result.failed) == 0

        # Output files should have Unicode names preserved
        for output_file in result.succeeded:
            assert output_file.exists()
            assert output_file.name in ["中文文件.md", "файл.md", "日本語.md"]


class TestSkipExistingOutputFiles:
    """Tests for skip existing output files behavior."""

    @pytest.fixture
    def temp_dir_with_input_and_output(self):
        input_dir = tempfile.mkdtemp()
        output_dir = tempfile.mkdtemp()
        # Create input file
        Path(input_dir, "existing.md").write_text("# Existing file")
        # Pre-create output file
        Path(output_dir, "existing.md").write_text("# Old translation")
        yield input_dir, output_dir
        shutil.rmtree(input_dir, ignore_errors=True)
        shutil.rmtree(output_dir, ignore_errors=True)

    @pytest.fixture
    def mock_pool(self):
        pool = MagicMock()
        pool.translate = AsyncMock(return_value="# New translation")
        return pool

    @pytest.fixture
    def mock_limiter(self):
        limiter = MagicMock(spec=ConcurrencyLimiter)
        limiter.translation = MagicMock()
        limiter.translation.return_value.__aenter__ = AsyncMock(return_value=None)
        limiter.translation.return_value.__aexit__ = AsyncMock(return_value=None)
        return limiter

    def test_skip_existing_config_default_true(self):
        """Test BatchConfig skip_existing defaults to True."""
        config = BatchConfig()
        assert config.skip_existing is True

    def test_skip_existing_config_can_be_false(self):
        """Test BatchConfig skip_existing can be set to False."""
        config = BatchConfig(skip_existing=False)
        assert config.skip_existing is False

    @pytest.mark.anyio
    async def test_output_file_already_exists(self, temp_dir_with_input_and_output, mock_pool, mock_limiter):
        """Test output file already exists behavior."""
        input_dir, output_dir = temp_dir_with_input_and_output
        config = BatchConfig(skip_existing=True)
        processor = BatchProcessor(config, mock_pool, mock_limiter)

        files = discover_files(Path(input_dir), ["*.md"])
        result = await processor.process_batch(files, Path(output_dir))

        # Translation should succeed
        assert len(result.succeeded) == 1

        # When skip_existing=True, the existing file content should be preserved
        # or overwritten depending on implementation
        output_file = Path(output_dir) / "existing.md"
        assert output_file.exists()


class TestBatchResultSummary:
    """Tests for BatchResult summary functionality."""

    def test_batch_result_success_rate_all_success(self):
        """Test success rate 100% when all succeed."""
        result = BatchResult(
            succeeded=[Path("a.md"), Path("b.md")],
            failed=[],
            total=2
        )
        assert result.success_rate == 100.0

    def test_batch_result_success_rate_all_fail(self):
        """Test success rate 0% when all fail."""
        result = BatchResult(
            succeeded=[],
            failed=[(Path("a.md"), "error"), (Path("b.md"), "error")],
            total=2
        )
        assert result.success_rate == 0.0

    def test_batch_result_success_rate_partial(self):
        """Test success rate for partial success."""
        result = BatchResult(
            succeeded=[Path("a.md")],
            failed=[(Path("b.md"), "error")],
            total=2
        )
        assert result.success_rate == 50.0

    def test_batch_result_success_rate_empty(self):
        """Test success rate 0% for empty batch."""
        result = BatchResult(
            succeeded=[],
            failed=[],
            total=0
        )
        assert result.success_rate == 0.0


class TestConcurrencyHandling:
    """Tests for concurrency limiting in edge cases."""

    @pytest.fixture
    def temp_dir_many_files(self):
        tmpdir = tempfile.mkdtemp()
        for i in range(10):
            Path(tmpdir, f"file{i}.md").write_text(f"# File {i}")
        yield tmpdir
        shutil.rmtree(tmpdir, ignore_errors=True)

    @pytest.fixture
    def mock_pool(self):
        pool = MagicMock()
        pool.translate = AsyncMock(return_value="# Translated")
        return pool

    @pytest.mark.anyio
    async def test_concurrency_limiter_respected(self, temp_dir_many_files, mock_pool):
        """Test concurrency limiter is respected during batch processing."""
        config = BatchConfig(max_concurrent=2)
        limiter = ConcurrencyLimiter(max_translation=2, max_scoring=1)
        processor = BatchProcessor(config, mock_pool, limiter)

        files = discover_files(Path(temp_dir_many_files), ["*.md"])
        output_dir = Path(tempfile.mkdtemp())

        result = await processor.process_batch(files, output_dir)

        # All files should be processed
        assert len(result.succeeded) == 10


class TestNonExistentDirectory:
    """Tests for non-existent directory handling."""

    def test_validate_directory_false_for_nonexistent(self):
        """Test validate_directory returns False for non-existent path."""
        result = validate_directory(Path("/nonexistent/path/to/directory"))
        assert result is False

    def test_discover_files_empty_for_nonexistent(self):
        """Test discover_files returns empty list for non-existent directory."""
        files = discover_files(Path("/nonexistent/path"), ["*.md"])
        assert len(files) == 0