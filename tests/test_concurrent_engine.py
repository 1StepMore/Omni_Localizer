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
        """Test queue tracks waiting tasks after acquiring slot."""
        limiter = ConcurrencyLimiter(max_translation=1, max_scoring=1)
        async with limiter.translation():
            assert limiter._translation_queue.qsize() == 1
        assert limiter._translation_queue.qsize() == 0
