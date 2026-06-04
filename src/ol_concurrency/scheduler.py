"""Concurrency management for Omni-Localizer."""

import asyncio
from contextlib import asynccontextmanager

from ol_core.exceptions import OLBaseError


class QueueTimeoutError(OLBaseError):
    """Raised when queued request times out waiting for available slot."""

    pass


class ConcurrencyLimiter:
    """Controls concurrent translation and scoring operations with semaphore-based limiting.

    Concurrency is enforced exclusively by :class:`asyncio.Semaphore`. The
    semaphores are the source of truth for slot accounting; no auxiliary
    tracking structure is needed.
    """

    def __init__(self, max_translation: int = 10, max_scoring: int = 5):
        # C14 fix: the previous implementation also created an unbounded
        # ``asyncio.Queue`` per role and pushed ``None`` on every acquisition
        # (with a racy ``get_nowait()`` in ``finally``). That queue was
        # dead — it was never drained anywhere — and grew without bound
        # (O(N) per batch). The semaphores alone do the limiting, so the
        # queue has been removed entirely.
        self._translation_sem = asyncio.Semaphore(max_translation)
        self._scoring_sem = asyncio.Semaphore(max_scoring)

    @asynccontextmanager
    async def translation(self, timeout: float | None = None):
        """Acquire translation slot. Blocks if full, times out if wait exceeds timeout."""
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

    @asynccontextmanager
    async def scoring(self, timeout: float | None = None):
        """Acquire scoring slot. Blocks if full, times out if wait exceeds timeout."""
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

    @asynccontextmanager
    async def with_timeout(self, timeout: float):
        """Context manager that applies timeout to any operation within."""
        async with asyncio.timeout(timeout):
            yield
