"""Integration tests for Phase 3a components: routing, model pool, concurrency, checkpoint."""
import asyncio
import os
import sys
import tempfile
from unittest.mock import AsyncMock, MagicMock

import pytest

from ol_core.dataclass import ChannelType
from ol_core.exceptions import FormatNotSupportedError
from ol_pool.router import ModelPool
from ol_routing.router import route_batch, route_by_extension

# Mock fcntl for Windows compatibility in tests
if sys.platform == 'win32':
    import unittest.mock
    sys.modules['fcntl'] = unittest.mock.MagicMock()


class TestRoutingIntegration:
    """Integration tests for routing engine."""

    def test_routing_to_md_channel(self):
        channel = route_by_extension("document.md")
        assert channel == ChannelType.MD

    def test_routing_to_xliff_channel(self):
        channel = route_by_extension("translation.xliff")
        assert channel == ChannelType.XLIFF

    def test_routing_uppercase_extension_normalized(self):
        assert route_by_extension("FILE.MD") == ChannelType.MD
        assert route_by_extension("FILE.XLIFF") == ChannelType.XLIFF

    def test_routing_unsupported_format_raises(self):
        with pytest.raises(FormatNotSupportedError):
            route_by_extension("document.docx")

    def test_batch_routing_multiple_files(self):
        paths = ["file1.md", "file2.xliff", "file3.MD"]
        result = route_batch(paths)
        assert len(result) == 3
        assert result["file1.md"] == ChannelType.MD
        assert result["file2.xliff"] == ChannelType.XLIFF
        assert result["file3.MD"] == ChannelType.MD


class TestModelPoolIntegration:
    """Integration tests for ModelPool with mocked LiteLLM."""

    @pytest.fixture
    def mock_model_pool(self):
        pool = MagicMock(spec=ModelPool)
        pool.translate = AsyncMock(return_value="translated text")
        pool.judge = AsyncMock(return_value={"score": 8.5, "reason": "good quality"})
        return pool

    @pytest.mark.anyio
    async def test_translate_calls_pool(self, mock_model_pool):
        result = await mock_model_pool.translate("hello", "en", "zh")
        assert result == "translated text"
        mock_model_pool.translate.assert_called_once_with("hello", "en", "zh")

    @pytest.mark.anyio
    async def test_judge_calls_pool(self, mock_model_pool):
        result = await mock_model_pool.judge("hello", "你好", "en", "zh")
        assert result["score"] == 8.5
        mock_model_pool.judge.assert_called_once_with("hello", "你好", "en", "zh")

    @pytest.mark.anyio
    async def test_mock_pool_handles_calls(self, mock_model_pool):
        result = await mock_model_pool.translate("test input", "en", "zh")
        assert result == "translated text"
        mock_model_pool.translate.assert_called_once_with("test input", "en", "zh")


class TestConcurrencyIntegration:
    """Integration tests for ConcurrencyLimiter."""

    @pytest.fixture
    def limiter(self):
        return ConcurrencyLimiter(max_translation=1, max_scoring=1)

    @pytest.mark.anyio
    async def test_translation_slots_enforced(self, limiter):
        results = []

        async def task(i):
            async with limiter.translation():
                results.append(i)
                await asyncio.sleep(0.05)

        await asyncio.gather(*[task(i) for i in range(5)])
        assert len(results) == 5

    @pytest.mark.anyio
    async def test_scoring_slots_enforced(self, limiter):
        results = []

        async def task(i):
            async with limiter.scoring():
                results.append(i)
                await asyncio.sleep(0.05)

        await asyncio.gather(*[task(i) for i in range(4)])
        assert len(results) == 4

    @pytest.mark.anyio
    async def test_concurrent_translation_and_scoring(self, limiter):
        results = {"translation": [], "scoring": []}

        async def translate_task(i):
            async with limiter.translation():
                results["translation"].append(i)
                await asyncio.sleep(0.02)

        async def scoring_task(i):
            async with limiter.scoring():
                results["scoring"].append(i)
                await asyncio.sleep(0.02)

        await asyncio.gather(
            *[translate_task(i) for i in range(3)],
            *[scoring_task(i) for i in range(2)],
        )
        assert len(results["translation"]) == 3
        assert len(results["scoring"]) == 2

    @pytest.mark.anyio
    async def test_timeout_raises_queue_timeout_error(self, limiter):
        async with limiter.translation():
            with pytest.raises(QueueTimeoutError):
                async with limiter.translation(timeout=0.01):
                    pass


class TestCheckpointIntegration:
    """Integration tests for CheckpointManager."""

    @pytest.fixture
    def temp_dir(self):
        tmpdir = tempfile.mkdtemp()
        yield tmpdir
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

    @pytest.fixture
    def checkpoint_manager(self, temp_dir):
        checkpoint_path = os.path.join(temp_dir, "test_checkpoint.json")
        source_path = os.path.join(temp_dir, "source.txt")
        with open(source_path, 'w') as f:
            f.write("test content for checkpoint")
        return CheckpointManager(checkpoint_path, source_path)

    def test_save_and_load_checkpoint(self, checkpoint_manager):
        data = {
            "version": "1.0",
            "processed_units": ["unit1", "unit2", "unit3"],
            "total_units": 10,
            "completed_units": 3,
        }
        checkpoint_manager.save(data)
        loaded = checkpoint_manager.load()
        assert loaded["version"] == "1.0"
        assert loaded["processed_units"] == ["unit1", "unit2", "unit3"]
        assert loaded["total_units"] == 10
        assert loaded["completed_units"] == 3

    def test_checkpoint_atomic_write(self, checkpoint_manager):
        data = {"version": "1.0", "processed_units": list(range(50))}
        checkpoint_manager.save(data)
        assert os.path.exists(checkpoint_manager._path)
        loaded = checkpoint_manager.load()
        assert len(loaded["processed_units"]) == 50

    def test_resume_force_mode(self, checkpoint_manager):
        data = {"processed_units": ["unit1", "unit2"]}
        result = checkpoint_manager.resume("force", data)
        assert result == data

    def test_resume_merge_mode(self, checkpoint_manager):
        existing_data = {
            "version": "1.0",
            "processed_units": ["unit1", "unit2"],
        }
        checkpoint_manager.save(existing_data)
        new_data = {"processed_units": ["unit2", "unit3"]}
        result = checkpoint_manager.resume("merge", new_data)
        assert "unit1" in result["processed_units"]
        assert "unit2" in result["processed_units"]
        assert "unit3" in result["processed_units"]

    def test_hash_verification_on_load(self, temp_dir):
        checkpoint_path = os.path.join(temp_dir, "checkpoint.json")
        source_path = os.path.join(temp_dir, "source.txt")
        with open(source_path, 'w') as f:
            f.write("original content")

        manager = CheckpointManager(checkpoint_path, source_path)
        data = {
            "version": "1.0",
            "file_hash": "wrong_hash_value",
            "processed_units": [],
        }
        manager.save(data)
        with pytest.raises(HashMismatchError):
            manager.load()


class TestPipelineIntegration:
    """End-to-end integration tests for the full pipeline."""

    @pytest.fixture
    def mock_components(self, temp_dir):
        pool = MagicMock(spec=ModelPool)
        pool.translate = AsyncMock(return_value="translated content")
        pool.judge = AsyncMock(return_value={"score": 9.0, "reason": "excellent"})

        limiter = ConcurrencyLimiter(max_translation=5, max_scoring=3)

        checkpoint_path = os.path.join(temp_dir, "pipeline_checkpoint.json")
        source_path = os.path.join(temp_dir, "pipeline_source.md")
        with open(source_path, 'w') as f:
            f.write("# Test Document\n\nContent here.")
        checkpoint = CheckpointManager(checkpoint_path, source_path)

        return {
            "pool": pool,
            "limiter": limiter,
            "checkpoint": checkpoint,
            "source_path": source_path,
        }

    @pytest.fixture
    def temp_dir(self):
        tmpdir = tempfile.mkdtemp()
        yield tmpdir
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

    @pytest.mark.anyio
    async def test_routing_to_translation_pipeline(self, mock_components):
        channel = route_by_extension("document.md")
        assert channel == ChannelType.MD

        async with mock_components["limiter"].translation():
            result = await mock_components["pool"].translate(
                "hello world", "en", "zh",
            )
        assert result == "translated content"

    @pytest.mark.anyio
    async def test_routing_to_judging_pipeline(self, mock_components):
        channel = route_by_extension("translation.xliff")
        assert channel == ChannelType.XLIFF

        async with mock_components["limiter"].scoring():
            result = await mock_components["pool"].judge(
                "hello", "你好", "en", "zh",
            )
        assert result["score"] == 9.0

    @pytest.mark.anyio
    async def test_checkpoint_in_pipeline_flow(self, mock_components):
        units_processed = ["unit_1", "unit_2", "unit_3", "unit_4", "unit_5"]

        data = {
            "version": "1.0",
            "processed_units": units_processed,
            "total_units": 10,
            "completed_units": 5,
        }
        mock_components["checkpoint"].save(data)

        loaded = mock_components["checkpoint"].load()
        assert loaded["completed_units"] == 5
        assert len(loaded["processed_units"]) == 5

    @pytest.mark.anyio
    async def test_pipeline_error_propagates(self, mock_components):
        mock_components["pool"].translate = AsyncMock(
            side_effect=Exception("API Error"),
        )

        with pytest.raises(Exception) as exc_info:
            async with mock_components["limiter"].translation():
                await mock_components["pool"].translate("test", "en", "zh")

        assert "API Error" in str(exc_info.value)

    @pytest.mark.anyio
    async def test_concurrent_pipeline_operations(self, mock_components):
        results = []

        async def process_file(file_idx):
            channel = route_by_extension(f"file{file_idx}.md")
            async with mock_components["limiter"].translation():
                result = await mock_components["pool"].translate(
                    f"text {file_idx}", "en", "zh",
                )
            results.append((file_idx, result, channel))

        await asyncio.gather(*[process_file(i) for i in range(5)])

        assert len(results) == 5
        for i, result, channel in results:
            assert channel == ChannelType.MD
            assert result == "translated content"


class TestErrorHandlingIntegration:
    """Integration tests for error handling and recovery."""

    @pytest.fixture
    def limiter(self):
        return ConcurrencyLimiter(max_translation=1, max_scoring=1)

    @pytest.fixture
    def temp_dir(self):
        tmpdir = tempfile.mkdtemp()
        yield tmpdir
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_checkpoint_load_nonexistent_raises(self, temp_dir):
        manager = CheckpointManager("/nonexistent/path.json")
        with pytest.raises(FileNotFoundError):
            manager.load()

    def test_checkpoint_resume_invalid_mode_raises(self, temp_dir):
        checkpoint_path = os.path.join(temp_dir, "checkpoint.json")
        manager = CheckpointManager(checkpoint_path)
        with pytest.raises(ValueError):
            manager.resume("invalid_mode")

    @pytest.mark.anyio
    async def test_timeout_error_contains_timing_info(self, limiter):
        async with limiter.translation():
            with pytest.raises(QueueTimeoutError) as exc_info:
                async with limiter.translation(timeout=0.1):
                    pass
            assert "0.1" in str(exc_info.value)

    def test_format_not_supported_error_contains_path(self):
        with pytest.raises(FormatNotSupportedError) as exc_info:
            route_by_extension("file.unsupported")
        assert "file.unsupported" in str(exc_info.value)


class TestComponentInitialization:
    """Integration tests for component initialization."""

    @pytest.fixture
    def temp_dir(self):
        tmpdir = tempfile.mkdtemp()
        yield tmpdir
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_checkpoint_manager_initializes_with_paths(self, temp_dir):
        checkpoint_path = os.path.join(temp_dir, "checkpoint.json")
        source_path = os.path.join(temp_dir, "source.txt")
        with open(source_path, 'w') as f:
            f.write("content")

        manager = CheckpointManager(checkpoint_path, source_path)
        assert manager._path.name == "checkpoint.json"
        assert manager._source_path.name == "source.txt"

    def test_concurrency_limiter_default_values(self):
        limiter = ConcurrencyLimiter()
        assert limiter._translation_sem._value == 10
        assert limiter._scoring_sem._value == 5

    def test_concurrency_limiter_custom_values(self):
        limiter = ConcurrencyLimiter(max_translation=20, max_scoring=15)
        assert limiter._translation_sem._value == 20
        assert limiter._scoring_sem._value == 15

    def test_route_batch_returns_dict(self):
        paths = ["file1.md", "file2.xliff"]
        result = route_batch(paths)
        assert isinstance(result, dict)
        assert len(result) == 2


# Import at bottom to avoid fcntl import issues on Windows
from ol_checkpoint import CheckpointManager, HashMismatchError
from ol_concurrency.scheduler import ConcurrencyLimiter, QueueTimeoutError
