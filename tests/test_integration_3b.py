"""Integration tests for Phase 3b components: LQA, Retry, TM, Checkpoint flow."""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# Mock fcntl for Windows compatibility in tests
if sys.platform == 'win32':
    import unittest.mock
    sys.modules['fcntl'] = unittest.mock.MagicMock()

from ol_checkpoint import CheckpointManager
from ol_checkpoint.exceptions import HashMismatchError
from ol_tm.service import TMService, TMMatch


class TestLQARetryIntegration:
    """Integration tests for LQA scoring triggering retry."""

    @pytest.fixture
    def mock_judge_low_score(self):
        async def judge(source, target, unit_id):
            return MagicMock(
                judge_overall_score=5.0,
                judge_scores={"adequacy": 5.0, "fluency": 5.0},
            )
        return judge

    @pytest.fixture
    def mock_judge_high_score(self):
        async def judge(source, target, unit_id):
            return MagicMock(
                judge_overall_score=8.0,
                judge_scores={"adequacy": 8.0, "fluency": 8.0},
            )
        return judge

    @pytest.mark.asyncio
    async def test_low_score_triggers_retry(self, mock_judge_low_score):

        mgr = RetryManager(max_retries=2, pass_threshold=7.0)
        call_count = 0

        async def translate():
            nonlocal call_count
            call_count += 1
            return f"translation_attempt_{call_count}"

        result = await mgr.execute_with_retry("u1", "hello", translate, mock_judge_low_score)

        assert result.attempts == 3
        assert result.final_score == 5.0
        assert "OL_WARN" in result.warning
        assert len(result.attempt_history) == 3

    @pytest.mark.asyncio
    async def test_high_score_no_retry(self, mock_judge_high_score):

        mgr = RetryManager(max_retries=2, pass_threshold=7.0)

        async def translate():
            return "good_translation"

        result = await mgr.execute_with_retry("u1", "hello", translate, mock_judge_high_score)

        assert result.attempts == 1
        assert result.final_score == 8.0
        assert result.warning is None

    @pytest.mark.asyncio
    async def test_retry_then_pass(self):

        mgr = RetryManager(max_retries=2, pass_threshold=7.0)
        call_count = 0

        async def translate():
            nonlocal call_count
            call_count += 1
            return f"attempt_{call_count}"

        async def judge(source, target, unit_id):
            if "attempt_1" in target:
                return MagicMock(judge_overall_score=5.0, judge_scores={})
            return MagicMock(judge_overall_score=8.0, judge_scores={})

        result = await mgr.execute_with_retry("u1", "hello", translate, judge)

        assert result.attempts == 2
        assert result.final_score == 8.0


class TestTMServiceIntegration:
    """Integration tests for TM service with fuzzy matching."""

    @pytest.fixture
    def temp_dir(self):
        tmpdir = tempfile.mkdtemp()
        yield tmpdir
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_tm_search_finds_match_above_threshold(self, temp_dir):

        tmx_path = os.path.join(temp_dir, "test.tmx")
        svc = TMService(tmx_path)

        svc._entries = [
            TMMatch(source="hello world", target="hola mundo", similarity=0.92, language_pair="en-es"),
            TMMatch(source="good morning", target="buenos dias", similarity=0.88, language_pair="en-es"),
            TMMatch(source="thank you", target="gracias", similarity=0.75, language_pair="en-es"),
        ]

        results = svc.search("hello world", threshold=0.85)

        assert len(results) == 2
        assert results[0].source == "hello world"
        assert results[1].source == "good morning"

    def test_tm_add_and_search(self, temp_dir):

        tmx_path = os.path.join(temp_dir, "test_add.tmx")
        svc = TMService(tmx_path)

        svc.add("welcome", "bienvenido", "en", "es")
        assert len(svc._entries) == 1
        assert svc._entries[0].source == "welcome"
        assert svc._entries[0].target == "bienvenido"


class TestCheckpointResumeIntegration:
    """Integration tests for CheckpointManager resume modes."""

    @pytest.fixture
    def temp_dir(self):
        tmpdir = tempfile.mkdtemp()
        yield tmpdir
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_resume_force_clears_and_fresh_start(self, temp_dir):

        ckpt_path = os.path.join(temp_dir, "checkpoint.json")
        ckpt_path_obj = Path(ckpt_path)
        ckpt_path_obj.write_text(json.dumps({"processed_units": ["u1", "u2", "u3"]}))

        mgr = CheckpointManager(ckpt_path)
        result = mgr.resume('force')

        assert result.fresh_start is True
        assert result.mode == 'force'
        assert not ckpt_path_obj.exists()

    def test_resume_merge_recovers_units(self, temp_dir):

        ckpt_path = os.path.join(temp_dir, "checkpoint.json")
        ckpt_path_obj = Path(ckpt_path)
        ckpt_path_obj.write_text(json.dumps({"processed_units": ["u1", "u2"]}))

        mgr = CheckpointManager(ckpt_path)
        result = mgr.resume('merge')

        assert result.fresh_start is False
        assert result.recovered_units == 2
        assert result.mode == 'merge'

    def test_checkpoint_gc_keeps_only_latest(self, temp_dir):

        ckpt_base = os.path.join(temp_dir, "checkpoint")
        for i in range(5):
            p = Path(f"{ckpt_base}.v{i}.json")
            p.write_text(json.dumps({"version": i}))

        mgr = CheckpointManager(ckpt_base)
        mgr.gc(keep_latest=2)

        remaining = list(Path(temp_dir).glob("checkpoint*.json"))
        assert len(remaining) == 2


class TestFullPipeline3B:
    """End-to-end integration tests for Phase 3b pipeline."""

    @pytest.fixture
    def temp_dir(self):
        tmpdir = tempfile.mkdtemp()
        yield tmpdir
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

    @pytest.fixture
    def mock_pool(self):
        pool = MagicMock()
        pool.translate = AsyncMock(return_value="translated")
        pool.judge = AsyncMock(return_value=MagicMock(
            judge_overall_score=8.0,
            judge_scores={"adequacy": 8.0, "fluency": 8.0},
        ))
        return pool

    @pytest.mark.asyncio
    async def test_retry_flow_with_checkpoint_save(self, temp_dir, mock_pool):
        from ol_checkpoint import CheckpointManager

        ckpt_path = os.path.join(temp_dir, "pipeline_ckpt.json")
        source_path = os.path.join(temp_dir, "source.txt")
        Path(source_path).write_text("source content")

        checkpoint_mgr = CheckpointManager(ckpt_path, source_path)
        retry_mgr = RetryManager(max_retries=1, pass_threshold=7.0)

        units_to_process = ["u1", "u2", "u3"]
        processed = []

        for unit_id in units_to_process:
            result = await retry_mgr.execute_with_retry(
                unit_id,
                f"source_{unit_id}",
                lambda u=unit_id: mock_pool.translate(f"text_{u}", "en", "es"),
                lambda s, t, u: mock_pool.judge(s, t, "en", "es"),
            )
            processed.append(unit_id)
            checkpoint_mgr.save({
                "processed_units": processed,
                "file_hash": checkpoint_mgr._compute_hash(Path(source_path)),
            })

        loaded = checkpoint_mgr.load()
        assert len(loaded["processed_units"]) == 3

    @pytest.mark.asyncio
    async def test_tm_in_pipeline_flow(self, temp_dir):

        tmx_path = os.path.join(temp_dir, "pipeline.tmx")
        svc = TMService(tmx_path)

        svc._entries = [
            TMMatch(source="hello", target="hola", similarity=0.95, language_pair="en-es"),
            TMMatch(source="world", target="mundo", similarity=0.90, language_pair="en-es"),
        ]

        matches = svc.search("hello", threshold=0.85)
        assert len(matches) == 1
        assert matches[0].target == "hola"

        svc.add("test", "prueba", "en", "es")
        assert len(svc._entries) == 3

    @pytest.mark.asyncio
    async def test_low_score_retry_with_mock_pool(self, temp_dir):
        from ol_checkpoint import CheckpointManager

        call_count = 0

        async def translate_fn():
            nonlocal call_count
            call_count += 1
            return f"attempt_{call_count}"

        async def judge_fn(source, target, unit_id):
            if "attempt_1" in target:
                return MagicMock(judge_overall_score=5.0, judge_scores={})
            return MagicMock(judge_overall_score=8.0, judge_scores={})

        retry_mgr = RetryManager(max_retries=2, pass_threshold=7.0)
        result = await retry_mgr.execute_with_retry("u1", "source_text", translate_fn, judge_fn)

        assert result.attempts == 2
        assert result.final_score == 8.0

        ckpt_path = os.path.join(temp_dir, "retry_ckpt.json")
        checkpoint_mgr = CheckpointManager(ckpt_path)
        checkpoint_mgr.save({
            "unit_id": "u1",
            "attempts": result.attempts,
            "final_score": result.final_score,
            "attempt_history": result.attempt_history,
        })

        loaded = checkpoint_mgr.load()
        assert loaded["attempts"] == 2
        assert loaded["final_score"] == 8.0


class TestErrorRecoveryIntegration:
    """Integration tests for error handling across components."""

    @pytest.fixture
    def temp_dir(self):
        tmpdir = tempfile.mkdtemp()
        yield tmpdir
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_checkpoint_hash_mismatch_requires_explicit_action(self, temp_dir):

        source_path = os.path.join(temp_dir, "source.txt")
        Path(source_path).write_text("original content")

        ckpt_path = os.path.join(temp_dir, "checkpoint.json")
        Path(ckpt_path).write_text(json.dumps({
            "processed_units": ["u1"],
            "file_hash": "wrong_hash",
        }))

        mgr = CheckpointManager(ckpt_path, source_path)

        with pytest.raises(HashMismatchError):
            mgr.load()

        result = mgr.resume('force')
        assert result.fresh_start is True

    def test_checkpoint_resume_invalid_mode_raises(self, temp_dir):

        ckpt_path = os.path.join(temp_dir, "checkpoint.json")
        mgr = CheckpointManager(ckpt_path)

        with pytest.raises(ValueError, match="Invalid resume mode"):
            mgr.resume('invalid_mode')

    @pytest.mark.asyncio
    async def test_retry_exhausted_all_attempts(self, temp_dir):

        mgr = RetryManager(max_retries=2, pass_threshold=7.0)

        async def translate():
            return "bad_translation"

        async def judge(source, target, unit_id):
            return MagicMock(judge_overall_score=4.0, judge_scores={})

        result = await mgr.execute_with_retry("u1", "hello", translate, judge)

        assert result.attempts == 3
        assert result.final_score == 4.0
        assert result.warning == "OL_WARN: Low_Score"
        assert len(result.attempt_history) == 3

    def test_tm_search_empty_entries(self, temp_dir):

        tmx_path = os.path.join(temp_dir, "empty.tmx")
        svc = TMService(tmx_path)

        results = svc.search("hello", threshold=0.85)
        assert results == []


# Import at bottom to avoid import issues
from ol_retry.retry import RetryManager
