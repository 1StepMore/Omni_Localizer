"""Tests for async translation polling (Wave 0.5, OL#12).

Tests the task_tracker module, the get_translation_status MCP tool,
and the async_mode parameter on translate_md_text / translate_xliff.

Requires OMNI_TEST_FAKE_LLM=1 to avoid real LLM calls.
"""
from __future__ import annotations

import asyncio
import json
import os
import time

import pytest

# Ensure FAKE_LLM is set before any OL imports
os.environ.setdefault("OMNI_TEST_FAKE_LLM", "1")

from ol_mcp.task_tracker import (
    ActiveTask,
    InMemoryTaskTracker,
    TaskStatus,
    TaskTracker,
)
from ol_mcp.status import get_translation_status


# ── TaskTracker unit tests ──────────────────────────────────────────


class TestTaskStatus:
    """Test TaskStatus enum values."""

    def test_enum_values(self):
        assert TaskStatus.PENDING == "pending"
        assert TaskStatus.RUNNING == "running"
        assert TaskStatus.COMPLETED == "completed"
        assert TaskStatus.FAILED == "failed"

    def test_enum_is_str(self):
        assert isinstance(TaskStatus.PENDING, str)


class TestActiveTask:
    """Test ActiveTask data class."""

    def test_defaults(self):
        task = ActiveTask(request_id="test-123")
        assert task.request_id == "test-123"
        assert task.status == TaskStatus.PENDING
        assert task.progress == 0.0
        assert task.total_steps == 1
        assert task.current_step == 0
        assert task.result is None
        assert task.error is None
        assert task.created_at is not None
        assert task.updated_at is not None

    def test_custom_total_steps(self):
        task = ActiveTask(request_id="abc", total_steps=5)
        assert task.total_steps == 5


class TestInMemoryTaskTracker:
    """Test InMemoryTaskTracker implementation."""

    def test_create_task_generates_uuid(self):
        tracker = InMemoryTaskTracker()
        rid = tracker.create_task()
        assert isinstance(rid, str)
        assert len(rid) == 36  # UUID format

    def test_create_task_with_explicit_id(self):
        tracker = InMemoryTaskTracker()
        rid = tracker.create_task(request_id="my-id")
        assert rid == "my-id"
        task = tracker.get_task("my-id")
        assert task is not None
        assert task.request_id == "my-id"

    def test_get_task_not_found(self):
        tracker = InMemoryTaskTracker()
        assert tracker.get_task("nonexistent") is None

    def test_update_progress(self):
        tracker = InMemoryTaskTracker()
        rid = tracker.create_task()
        tracker.update_progress(rid, TaskStatus.RUNNING, progress=0.5)
        task = tracker.get_task(rid)
        assert task is not None
        assert task.status == TaskStatus.RUNNING
        assert task.progress == 0.5

    def test_update_progress_with_result(self):
        tracker = InMemoryTaskTracker()
        rid = tracker.create_task()
        result = {"translated": "hello world"}
        tracker.update_progress(rid, TaskStatus.COMPLETED, progress=1.0, result=result)
        task = tracker.get_task(rid)
        assert task is not None
        assert task.status == TaskStatus.COMPLETED
        assert task.result == result

    def test_update_progress_with_error(self):
        tracker = InMemoryTaskTracker()
        rid = tracker.create_task()
        error = {"code": "FAILED", "message": "something broke"}
        tracker.update_progress(rid, TaskStatus.FAILED, error=error)
        task = tracker.get_task(rid)
        assert task is not None
        assert task.status == TaskStatus.FAILED
        assert task.error == error

    def test_update_progress_nonexistent_id(self):
        """Updating a nonexistent task should be a no-op (no crash)."""
        tracker = InMemoryTaskTracker()
        tracker.update_progress("nonexistent", TaskStatus.RUNNING)  # should not raise

    def test_list_tasks(self):
        tracker = InMemoryTaskTracker()
        tracker.create_task(request_id="a")
        tracker.create_task(request_id="b")
        tasks = tracker.list_tasks()
        assert len(tasks) == 2
        ids = {t.request_id for t in tasks}
        assert ids == {"a", "b"}

    def test_list_tasks_empty(self):
        tracker = InMemoryTaskTracker()
        assert tracker.list_tasks() == []

    def test_thread_safety(self):
        """Multiple threads creating/updating tasks concurrently."""
        tracker = InMemoryTaskTracker()
        errors = []

        def _worker(n: int):
            try:
                for i in range(50):
                    rid = tracker.create_task(request_id=f"t-{n}-{i}")
                    tracker.update_progress(rid, TaskStatus.RUNNING, progress=0.5)
                    tracker.update_progress(rid, TaskStatus.COMPLETED, progress=1.0, result={"done": True})
                    task = tracker.get_task(rid)
                    assert task is not None
                    assert task.status == TaskStatus.COMPLETED
            except Exception as e:
                errors.append(e)

        threads = []
        import threading
        for n in range(4):
            t = threading.Thread(target=_worker, args=(n,))
            threads.append(t)
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert errors == [], f"Thread errors: {errors}"
        assert len(tracker.list_tasks()) == 200  # 4 threads * 50 tasks


class TestTaskTrackerABC:
    """Verify InMemoryTaskTracker satisfies the TaskTracker interface."""

    def test_is_subclass(self):
        assert issubclass(InMemoryTaskTracker, TaskTracker)

    def test_instance(self):
        tracker = InMemoryTaskTracker()
        assert isinstance(tracker, TaskTracker)


# ── get_translation_status MCP tool tests ───────────────────────────


class TestGetTranslationStatus:
    """Test the get_translation_status MCP tool function."""

    def test_not_found(self):
        tracker = InMemoryTaskTracker()
        result = json.loads(get_translation_status("nonexistent", tracker))
        assert result["success"] is False
        assert result["error"]["code"] == "NOT_FOUND"
        assert "nonexistent" in result["error"]["message"]

    def test_pending_task(self):
        tracker = InMemoryTaskTracker()
        rid = tracker.create_task()
        result = json.loads(get_translation_status(rid, tracker))
        assert result["success"] is True
        content = result["content"]
        assert content["request_id"] == rid
        assert content["status"] == "pending"
        assert content["progress"] == 0.0
        assert "created_at" in content
        assert "updated_at" in content

    def test_completed_task(self):
        tracker = InMemoryTaskTracker()
        rid = tracker.create_task()
        tracker.update_progress(rid, TaskStatus.COMPLETED, progress=1.0, result={"translated": "done"})
        result = json.loads(get_translation_status(rid, tracker))
        assert result["success"] is True
        content = result["content"]
        assert content["status"] == "completed"
        assert content["progress"] == 1.0
        assert content["result"] == {"translated": "done"}

    def test_failed_task(self):
        tracker = InMemoryTaskTracker()
        rid = tracker.create_task()
        tracker.update_progress(rid, TaskStatus.FAILED, error={"code": "BOOM", "message": "kaboom"})
        result = json.loads(get_translation_status(rid, tracker))
        assert result["success"] is True
        content = result["content"]
        assert content["status"] == "failed"
        assert content["error_details"] == {"code": "BOOM", "message": "kaboom"}

    def test_running_task_no_result_yet(self):
        tracker = InMemoryTaskTracker()
        rid = tracker.create_task()
        tracker.update_progress(rid, TaskStatus.RUNNING, progress=0.5)
        result = json.loads(get_translation_status(rid, tracker))
        assert result["success"] is True
        content = result["content"]
        assert content["status"] == "running"
        assert content["progress"] == 0.5
        assert "result" not in content
        assert "error_details" not in content


# ── Integration: translate_md_text with async_mode ──────────────────


class TestTranslateMdTextAsyncMode:
    """Test translate_md_text with async_mode=True."""

    @pytest.mark.asyncio
    async def test_async_returns_immediately(self):
        """async_mode=True should return {request_id, status: 'pending'} instantly."""
        from ol_mcp.tools import translate_md_text, TranslateInput

        params = TranslateInput(
            content="# Hello\nTest content.",
            source_lang="en",
            target_lang="zh",
            async_mode=True,
        )
        result_str = await translate_md_text(params)
        result = json.loads(result_str)
        assert result["success"] is True
        content = result["content"]
        assert "request_id" in content
        assert content["status"] == "pending"

    @pytest.mark.asyncio
    async def test_sync_mode_unchanged(self):
        """async_mode=False (default) should behave exactly as before."""
        from ol_mcp.tools import translate_md_text, TranslateInput

        params = TranslateInput(
            content="# Hello\nTest content.",
            source_lang="en",
            target_lang="zh",
        )
        result_str = await translate_md_text(params)
        result = json.loads(result_str)
        # Sync mode returns the full translation result
        assert result["success"] is True
        assert "translated" in result.get("content", {})

    @pytest.mark.asyncio
    async def test_async_then_poll(self):
        """Start async translation, poll until completed."""
        from ol_mcp.tools import translate_md_text, TranslateInput, _task_tracker
        from ol_mcp.status import get_translation_status

        params = TranslateInput(
            content="# Hello\nShort text.",
            source_lang="en",
            target_lang="zh",
            async_mode=True,
        )
        result_str = await translate_md_text(params)
        result = json.loads(result_str)
        request_id = result["content"]["request_id"]

        # Poll until completed (max 60s for FAKE_LLM)
        deadline = time.time() + 60
        final = None
        while time.time() < deadline:
            status_str = get_translation_status(request_id, _task_tracker)
            status = json.loads(status_str)
            assert status["success"] is True
            if status["content"]["status"] in ("completed", "failed"):
                final = status
                break
            await asyncio.sleep(0.5)

        assert final is not None, "Task did not complete within timeout"
        assert final["content"]["status"] == "completed"
        assert "result" in final["content"]
        assert "translated" in final["content"]["result"]


# ── Integration: translate_xliff with async_mode ────────────────────


class TestTranslateXliffAsyncMode:
    """Test translate_xliff with async_mode=True (basic param test)."""

    def test_async_mode_in_input_model(self):
        """TranslateXliffInput should accept async_mode param."""
        from ol_mcp.tools import TranslateXliffInput

        params = TranslateXliffInput(
            input_path="/tmp/test.xlf",
            source_lang="en",
            target_lang="zh",
            async_mode=True,
        )
        assert params.async_mode is True

    def test_async_mode_default_false(self):
        """async_mode defaults to False for backward compat."""
        from ol_mcp.tools import TranslateXliffInput

        params = TranslateXliffInput(
            input_path="/tmp/test.xlf",
            source_lang="en",
            target_lang="zh",
        )
        assert params.async_mode is False


# ── Concurrent async tasks ─────────────────────────────────────────


class TestConcurrentAsyncTasks:
    """Multiple concurrent async tasks each get unique request_id."""

    @pytest.mark.asyncio
    async def test_unique_request_ids(self):
        from ol_mcp.tools import translate_md_text, TranslateInput

        tasks = []
        for i in range(3):
            params = TranslateInput(
                content=f"# Chapter {i}\nContent for chapter {i}.",
                source_lang="en",
                target_lang="zh",
                async_mode=True,
            )
            tasks.append(translate_md_text(params))

        results = await asyncio.gather(*tasks)
        request_ids = set()
        for r in results:
            parsed = json.loads(r)
            assert parsed["success"] is True
            rid = parsed["content"]["request_id"]
            request_ids.add(rid)

        # All request IDs must be unique
        assert len(request_ids) == 3
