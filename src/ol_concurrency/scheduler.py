"""Concurrency management for Omni-Localizer."""

import asyncio
from contextlib import asynccontextmanager

from ol_core.exceptions import OLBaseError


class QueueTimeoutError(OLBaseError):
    """Raised when queued request times out waiting for available slot."""

    pass


class ConcurrencyLimiter:
    """Controls concurrent translation and scoring operations with semaphore-based limiting."""

    def __init__(self, max_translation: int = 10, max_scoring: int = 5):
        self._translation_sem = asyncio.Semaphore(max_translation)
        self._scoring_sem = asyncio.Semaphore(max_scoring)
        self._translation_queue: asyncio.Queue = asyncio.Queue()
        self._scoring_queue: asyncio.Queue = asyncio.Queue()

    @asynccontextmanager
    async def translation(self, timeout: float | None = None):
        """Acquire translation slot. Queues if full, times out if wait exceeds timeout."""
        await self._translation_queue.put(None)
        try:
            if timeout is not None:
                async with asyncio.timeout(timeout):
                    await self._translation_sem.acquire()
            else:
                await self._translation_sem.acquire()
            yield
        except TimeoutError:
            raise QueueTimeoutError(f"Translation slot wait timed out after {timeout}s")
        finally:
            self._translation_sem.release()
            try:
                self._translation_queue.get_nowait()
            except asyncio.QueueEmpty:
                pass

    @asynccontextmanager
    async def scoring(self, timeout: float | None = None):
        """Acquire scoring slot. Queues if full, times out if wait exceeds timeout."""
        await self._scoring_queue.put(None)
        try:
            if timeout is not None:
                async with asyncio.timeout(timeout):
                    await self._scoring_sem.acquire()
            else:
                await self._scoring_sem.acquire()
            yield
        except TimeoutError:
            raise QueueTimeoutError(f"Scoring slot wait timed out after {timeout}s")
        finally:
            self._scoring_sem.release()
            try:
                self._scoring_queue.get_nowait()
            except asyncio.QueueEmpty:
                pass

    @asynccontextmanager
    async def with_timeout(self, timeout: float):
        """Context manager that applies timeout to any operation within."""
        async with asyncio.timeout(timeout):
            yield
