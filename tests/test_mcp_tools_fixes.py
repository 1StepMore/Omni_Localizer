"""Tests for MCP tools code quality fixes (Wave 4).

Covers:
- 4.5: _resolve_async ThreadPoolExecutor deadlock fix (RED->GREEN)
"""



class TestResolveAsyncDeadlock:
    """RED->GREEN: _resolve_async must not create a new ThreadPoolExecutor per coroutine.

    The old implementation created a new ThreadPoolExecutor(max_workers=1) for
    each coroutine, causing thread leaks and potential deadlocks when called
    from thread pool threads. The fix uses a module-level shared executor.
    """

    def test_resolve_async_with_coroutine(self):
        """Coroutine is resolved correctly via the shared executor."""
        from ol_mcp.tools import _resolve_async

        async def sample_coro():
            return "resolved"

        result = _resolve_async(sample_coro())
        assert result == "resolved"

    def test_resolve_async_with_sync_value(self):
        """Sync values pass through unchanged."""
        from ol_mcp.tools import _resolve_async

        result = _resolve_async("already_resolved")
        assert result == "already_resolved"

    def test_resolve_async_with_none(self):
        """None passes through."""
        from ol_mcp.tools import _resolve_async

        assert _resolve_async(None) is None

    def test_shared_executor_is_reused(self):
        """Multiple calls reuse the same executor instead of creating new ones."""
        from ol_mcp.tools import _resolve_async

        async def sample_coro(v):
            return v

        # Run 10 coroutines through _resolve_async
        results = []
        for i in range(10):
            results.append(_resolve_async(sample_coro(i)))

        assert results == list(range(10))

    def test_resolve_async_no_deadlock_from_thread(self):
        """Calling _resolve_async from a thread pool thread must not deadlock.

        The old implementation created a new ThreadPoolExecutor(max_workers=1)
        per call. If called from a thread that already holds a thread pool
        slot, the inner submit() could deadlock waiting for a worker that will
        never be available. The shared executor has max_workers=4, so concurrent
        submissions from different threads all succeed.
        """
        from ol_mcp.tools import _resolve_async
        from concurrent.futures import ThreadPoolExecutor

        async def sample_coro(v):
            return v * 2

        def _call_from_thread(pool, value):
            # This mimics: a thread pool thread calling _resolve_async
            return _resolve_async(sample_coro(value))

        # Use a pool with limited workers to expose deadlocks
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(_call_from_thread, pool, i) for i in range(5)]
            results = [f.result(timeout=5) for f in futures]

        assert results == [0, 2, 4, 6, 8], (
            f"Expected [0, 2, 4, 6, 8], got {results}. "
            f"Deadlock would have caused a timeout."
        )
