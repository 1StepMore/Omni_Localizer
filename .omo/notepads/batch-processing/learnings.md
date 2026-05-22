# Batch Processing Learnings

## Created: processor.py (BatchProcessor + BatchResult)

### Key patterns implemented:
1. `asyncio.gather(*tasks, return_exceptions=True)` for parallel execution (per scorer.py:53-57)
2. Per-file error handling via try/except, aggregate succeeded/failed
3. `limiter.translation()` context manager wraps per-file processing
4. `ModelPool.translate()` called per file (per ol_cli.py:58)

### Architecture notes:
- BatchProcessor is orchestrator only - actual translation via ModelPool
- ConcurrencyLimiter handles semaphore via `translation()` async context manager
- Per-file error handling: track both succeeded (Path) and failed (tuple[Path, str])
- BatchResult includes success_rate property

### Imports verified:
- `ol_md.shield`: shield_markdown, unshield_markdown
- `ol_md.pipeline`: MDRepairPipeline
- `ol_config.loader`: load_config
- `ol_pool.router`: ModelPool (external)

### Gotchas:
- asyncio.TimeoutError must be caught separately from general Exception
- QueueTimeoutError custom exception for translation timeout
- Must call output_dir.mkdir(parents=True, exist_ok=True) before writing