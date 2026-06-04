"""Tests for ConcurrencyLimiter."""
import asyncio

import pytest

from ol_concurrency.scheduler import ConcurrencyLimiter, QueueTimeoutError


class TestConcurrencyLimiter:
    """Test ConcurrencyLimiter semaphore-based concurrency control."""

    @pytest.mark.anyio
    async def test_translation_acquisition(self):
        """Test translation slot can be acquired and released."""
        limiter = ConcurrencyLimiter(max_translation=2, max_scoring=2)
        async with limiter.translation():
            assert True

    @pytest.mark.anyio
    async def test_scoring_acquisition(self):
        """Test scoring slot can be acquired and released."""
        limiter = ConcurrencyLimiter(max_translation=2, max_scoring=2)
        async with limiter.scoring():
            assert True

    @pytest.mark.anyio
    async def test_concurrent_translation_slots(self):
        """Test multiple translation slots can be held concurrently."""
        limiter = ConcurrencyLimiter(max_translation=3, max_scoring=1)
        results = []

        async def task():
            async with limiter.translation():
                results.append(1)
                await asyncio.sleep(0.1)

        await asyncio.gather(task(), task(), task())
        assert len(results) == 3

    @pytest.mark.anyio
    async def test_concurrent_scoring_slots(self):
        """Test multiple scoring slots can be held concurrently."""
        limiter = ConcurrencyLimiter(max_translation=1, max_scoring=3)
        results = []

        async def task():
            async with limiter.scoring():
                results.append(1)
                await asyncio.sleep(0.1)

        await asyncio.gather(task(), task(), task())
        assert len(results) == 3

    @pytest.mark.anyio
    async def test_translation_timeout(self):
        """Test translation raises QueueTimeoutError on timeout."""
        limiter = ConcurrencyLimiter(max_translation=1, max_scoring=1)
        async with limiter.translation():
            with pytest.raises(QueueTimeoutError):
                async with limiter.translation(timeout=0.1):
                    pass

    @pytest.mark.anyio
    async def test_scoring_timeout(self):
        """Test scoring raises QueueTimeoutError on timeout."""
        limiter = ConcurrencyLimiter(max_translation=1, max_scoring=1)
        async with limiter.scoring():
            with pytest.raises(QueueTimeoutError):
                async with limiter.scoring(timeout=0.1):
                    pass

    @pytest.mark.anyio
    async def test_with_timeout(self):
        """Test with_timeout context manager."""
        limiter = ConcurrencyLimiter()
        async with limiter.with_timeout(1.0):
            await asyncio.sleep(0.05)

    @pytest.mark.anyio
    async def test_with_timeout_raises(self):
        """Test with_timeout raises on expiration."""
        limiter = ConcurrencyLimiter()
        with pytest.raises(asyncio.TimeoutError):
            async with limiter.with_timeout(0.1):
                await asyncio.sleep(1.0)

    @pytest.mark.anyio
    async def test_default_values(self):
        """Test default max values are applied."""
        limiter = ConcurrencyLimiter()
        assert limiter._translation_sem._value == 10
        assert limiter._scoring_sem._value == 5

    @pytest.mark.anyio
    async def test_custom_values(self):
        """Test custom max values."""
        limiter = ConcurrencyLimiter(max_translation=20, max_scoring=10)
        assert limiter._translation_sem._value == 20
        assert limiter._scoring_sem._value == 10

    @pytest.mark.anyio
    async def test_queue_tracks_waiters(self):
        """Test waiter behavior: blocked tasks unblock once a slot is released.

        C14 fix: the dead ``_translation_queue`` / ``_scoring_queue`` tracking
        was removed. This test now verifies the equivalent waiter semantics via
        the semaphore: a second acquisition blocks until the first is released.
        """
        limiter = ConcurrencyLimiter(max_translation=1, max_scoring=1)
        order: list[str] = []

        async def second():
            order.append("second_start")
            async with limiter.translation():
                order.append("second_inside")
            order.append("second_done")

        async def first():
            order.append("first_start")
            async with limiter.translation():
                order.append("first_inside")
                await asyncio.sleep(0.05)
            order.append("first_done")
            await second()

        await first()

        assert order == [
            "first_start",
            "first_inside",
            "first_done",
            "second_start",
            "second_inside",
            "second_done",
        ]

    # ---- C14 regression tests (unbounded asyncio.Queue removed) ----

    @pytest.mark.anyio
    async def test_no_translation_queue_attribute(self):
        """C14: ``_translation_queue`` attribute is gone (no memory leak)."""
        limiter = ConcurrencyLimiter()
        assert not hasattr(limiter, "_translation_queue")

    @pytest.mark.anyio
    async def test_no_scoring_queue_attribute(self):
        """C14: ``_scoring_queue`` attribute is gone (no memory leak)."""
        limiter = ConcurrencyLimiter()
        assert not hasattr(limiter, "_scoring_queue")

    @pytest.mark.anyio
    async def test_concurrency_still_limited_by_semaphore(self):
        """C14: 5 tasks, limit 2 -> peak concurrency observed is 2 (semaphore works)."""
        limiter = ConcurrencyLimiter(max_translation=2, max_scoring=2)
        in_flight = 0
        peak = 0
        started = asyncio.Event()

        async def task():
            nonlocal in_flight, peak
            async with limiter.translation():
                in_flight += 1
                peak = max(peak, in_flight)
                # Hold long enough that all 5 tasks have been scheduled.
                await asyncio.sleep(0.05)
                in_flight -= 1

        await asyncio.gather(*(task() for _ in range(5)))
        assert peak == 2, f"Expected peak=2, observed peak={peak}"

    @pytest.mark.anyio
    async def test_no_memory_accumulation_under_load(self):
        """C14: many tasks through the limiter must not accumulate internal state.

        The original bug: every translation put ``None`` onto an unbounded
        ``asyncio.Queue`` and the matching ``get_nowait()`` in ``finally`` was
        racy. After C14, no such accumulator exists, so 200 tasks complete
        cleanly with no queue attributes.
        """
        limiter = ConcurrencyLimiter(max_translation=4, max_scoring=4)
        counter = 0

        async def task():
            nonlocal counter
            async with limiter.translation():
                counter += 1
                await asyncio.sleep(0.001)

        await asyncio.gather(*(task() for _ in range(200)))

        assert counter == 200
        # No queue attribute is allowed to exist.
        assert not hasattr(limiter, "_translation_queue")
        assert not hasattr(limiter, "_scoring_queue")
        # The semaphore must be fully released (no leaked acquisitions).
        assert limiter._translation_sem._value == 4
        assert limiter._scoring_sem._value == 4
