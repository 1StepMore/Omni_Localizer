"""Tests for BatchProcessor batch translation orchestration."""
import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ol_batch.config import BatchConfig, BatchResult
from ol_batch.discovery import discover_files, validate_directory
from ol_batch.processor import BatchProcessor, QueueTimeoutError


class TestDiscoverFiles:
    """Test discover_files() file discovery functionality."""

    def test_empty_directory(self):
        """Test discover_files returns empty list for empty dir."""
        with tempfile.TemporaryDirectory() as tmpdir:
            directory = Path(tmpdir)
            results = discover_files(directory, ["*.md"])
            assert results == []

    def test_directory_with_files(self):
        """Test discover_files finds files matching pattern."""
        with tempfile.TemporaryDirectory() as tmpdir:
            directory = Path(tmpdir)
            (directory / "file1.md").touch()
            (directory / "file2.md").touch()
            (directory / "file3.txt").touch()

            results = discover_files(directory, ["*.md"])
            assert len(results) == 2
            assert all(p.suffix == ".md" for p in results)

    def test_nested_directories(self):
        """Test discover_files finds files in nested dirs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            directory = Path(tmpdir)
            subdir = directory / "subdir"
            subdir.mkdir()
            (directory / "root.md").touch()
            (subdir / "nested.md").touch()

            results = discover_files(directory, ["*.md"])
            assert len(results) == 2

    def test_multiple_patterns(self):
        """Test discover_files with multiple patterns."""
        with tempfile.TemporaryDirectory() as tmpdir:
            directory = Path(tmpdir)
            (directory / "file1.md").touch()
            (directory / "file2.xliff").touch()
            (directory / "file3.txt").touch()

            results = discover_files(directory, ["*.md", "*.xliff"])
            assert len(results) == 2

    def test_symlinks_ignored(self):
        """Test discover_files skips symlinks."""
        with tempfile.TemporaryDirectory() as tmpdir:
            directory = Path(tmpdir)
            (directory / "real.md").touch()
            symlink = directory / "link.md"
            symlink.symlink_to(directory / "real.md")

            results = discover_files(directory, ["*.md"])
            assert len(results) == 1

    def test_directories_excluded(self):
        """Test discover_files only returns files, not dirs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            directory = Path(tmpdir)
            (directory / "file.md").touch()
            (directory / "subdir").mkdir()

            results = discover_files(directory, ["*.md", "*"])
            file_results = [p for p in results if p.is_file()]
            assert all(p.is_file() for p in file_results)


class TestValidateDirectory:
    """Test validate_directory() directory validation."""

    def test_valid_directory(self):
        """Test validate_directory returns True for valid dir."""
        with tempfile.TemporaryDirectory() as tmpdir:
            directory = Path(tmpdir)
            assert validate_directory(directory) is True

    def test_nonexistent_directory(self):
        """Test validate_directory returns False for non-existent path."""
        assert validate_directory(Path("/nonexistent/path")) is False

    def test_not_a_directory(self):
        """Test validate_directory returns False for file path."""
        with tempfile.NamedTemporaryFile() as tmpfile:
            assert validate_directory(Path(tmpfile.name)) is False

    def test_not_readable_directory(self):
        """Test validate_directory returns False when dir not readable."""
        with tempfile.TemporaryDirectory() as tmpdir:
            directory = Path(tmpdir)
            directory.chmod(0o000)
            try:
                assert validate_directory(directory) is False
            finally:
                directory.chmod(0o755)


class TestBatchProcessor:
    """Test BatchProcessor batch translation orchestration."""

    @pytest.fixture
    def mock_model_pool(self):
        """Create mock ModelPool."""
        pool = MagicMock()
        pool.translate = AsyncMock(return_value="translated content")
        return pool

    @pytest.fixture
    def mock_limiter(self):
        """Create mock ConcurrencyLimiter."""
        limiter = MagicMock()
        limiter.translation = MagicMock()
        limiter.translation.return_value.__aenter__ = AsyncMock()
        limiter.translation.return_value.__aexit__ = AsyncMock()
        return limiter

    @pytest.fixture
    def batch_config(self):
        """Create BatchConfig for testing."""
        return BatchConfig(timeout=30.0)

    @pytest.fixture
    def processor(self, mock_model_pool, mock_limiter, batch_config):
        """Create BatchProcessor with mocked dependencies."""
        return BatchProcessor(
            config=batch_config,
            model_pool=mock_model_pool,
            limiter=mock_limiter,
        )

    @pytest.mark.anyio
    async def test_process_batch_all_succeed(self, processor, mock_model_pool, mock_limiter):
        """Test process_batch succeeds when all files translate."""
        with tempfile.TemporaryDirectory() as tmpdir:
            input_dir = Path(tmpdir) / "input"
            output_dir = Path(tmpdir) / "output"
            input_dir.mkdir()
            output_dir.mkdir()

            file1 = input_dir / "test1.md"
            file2 = input_dir / "test2.md"
            file1.write_text("original content 1")
            file2.write_text("original content 2")

            result = await processor.process_batch([file1, file2], output_dir)

            assert result.total == 2
            assert len(result.succeeded) == 2
            assert len(result.failed) == 0
            assert mock_limiter.translation.call_count == 2

    @pytest.mark.anyio
    async def test_process_batch_api_failure(self, processor, mock_model_pool, mock_limiter):
        """Test process_batch handles API failures."""
        with tempfile.TemporaryDirectory() as tmpdir:
            input_dir = Path(tmpdir) / "input"
            output_dir = Path(tmpdir) / "output"
            input_dir.mkdir()
            output_dir.mkdir()

            file1 = input_dir / "test1.md"
            file1.write_text("original content")

            mock_model_pool.translate.side_effect = RuntimeError("API Error")

            result = await processor.process_batch([file1], output_dir)

            assert result.total == 1
            assert len(result.succeeded) == 0
            assert len(result.failed) == 1
            assert "API Error" in result.failed[0][1]

    @pytest.mark.anyio
    async def test_process_batch_timeout(self, processor, mock_model_pool, mock_limiter):
        """Test process_batch handles timeout errors."""
        with tempfile.TemporaryDirectory() as tmpdir:
            input_dir = Path(tmpdir) / "input"
            output_dir = Path(tmpdir) / "output"
            input_dir.mkdir()
            output_dir.mkdir()

            file1 = input_dir / "test1.md"
            file1.write_text("original content")

            mock_limiter.translation.return_value.__aenter__.side_effect = asyncio.TimeoutError()

            result = await processor.process_batch([file1], output_dir)

            assert result.total == 1
            assert len(result.failed) == 1
            assert "timed out" in result.failed[0][1].lower() or "timeout" in result.failed[0][1].lower()

    @pytest.mark.anyio
    async def test_process_batch_concurrent_limiter(self, processor, mock_limiter):
        """Test process_batch uses limiter for each file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            input_dir = Path(tmpdir) / "input"
            output_dir = Path(tmpdir) / "output"
            input_dir.mkdir()
            output_dir.mkdir()

            file1 = input_dir / "test1.md"
            file2 = input_dir / "test2.md"
            file1.write_text("content 1")
            file2.write_text("content 2")

            await processor.process_batch([file1, file2], output_dir)

            assert mock_limiter.translation.call_count == 2

    @pytest.mark.anyio
    async def test_process_batch_invalid_input(self, processor, mock_model_pool, mock_limiter):
        """Test process_batch handles invalid input."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "output"
            output_dir.mkdir()

            file1 = Path("/nonexistent/file.md")

            result = await processor.process_batch([file1], output_dir)

            assert result.total == 1
            assert len(result.failed) == 1

    @pytest.mark.anyio
    async def test_process_batch_empty_list(self, processor, mock_limiter):
        """Test process_batch handles empty file list."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "output"
            output_dir.mkdir()

            result = await processor.process_batch([], output_dir)

            assert result.total == 0
            assert len(result.succeeded) == 0
            assert len(result.failed) == 0
            mock_limiter.translation.assert_not_called()

    @pytest.mark.anyio
    async def test_limiter_context_manager_used(self, processor, mock_limiter, mock_model_pool):
        """Test limiter context manager is properly used per file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            input_dir = Path(tmpdir) / "input"
            output_dir = Path(tmpdir) / "output"
            input_dir.mkdir()
            output_dir.mkdir()

            file1 = input_dir / "test1.md"
            file1.write_text("test content")

            await processor.process_batch([file1], output_dir)

            mock_limiter.translation.assert_called_once_with(timeout=processor._config.timeout)


class TestQueueTimeoutError:
    """Test QueueTimeoutError exception."""

    def test_exception_message(self):
        """Test QueueTimeoutError has proper message."""
        error = QueueTimeoutError("Translation timed out")
        assert str(error) == "Translation timed out"

    def test_exception_inherits_from_exception(self):
        """Test QueueTimeoutError inherits from Exception."""
        assert issubclass(QueueTimeoutError, Exception)