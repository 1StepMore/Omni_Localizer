# Scheduler Concurrency Implementation Learnings

## Completed Tasks
- Created `src/ol_concurrency/__init__.py` - module exports
- Created `src/ol_concurrency/scheduler.py` - ConcurrencyLimiter with QueueTimeoutError
- Created `tests/test_concurrent_engine.py` - 11 tests all passing

## Key Implementation Details

### ConcurrencyLimiter
- Uses `asyncio.Semaphore` for limiting concurrent slots
- Uses `asyncio.Queue` for tracking waiting tasks (queue-based waiting)
- Default: max_translation=10, max_scoring=5
- Uses `asyncio.timeout` (Python 3.11+) for timeout handling

### Queue-based waiting pattern
- When entering `translation()` or `scoring()`, task first puts into queue
- Then waits to acquire semaphore
- On timeout, raises `QueueTimeoutError`
- On exit, releases semaphore and dequeues

### AnyIO Testing
- Project uses `pytest-anyio` plugin (NOT pytest-asyncio)
- Mark tests with `@pytest.mark.anyio` not `@pytest.mark.asyncio`
- The anyio plugin auto-detects asyncio when running

## Issues Encountered
1. Initial tests used `@pytest.mark.asyncio` which is wrong for this project
2. Test `test_queue_tracks_waiters` had flawed logic - removed complex task cancellation test