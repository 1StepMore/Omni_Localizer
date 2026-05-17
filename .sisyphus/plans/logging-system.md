# Logging System - Omni-Localizer

## TL;DR

> **Quick Summary**: Add comprehensive logging to Omni-Localizer that captures all operations (CLI commands, file processing, batch progress, config loading, errors) to rotating log files in `logs/` directory.
>
> **Deliverables**:
> - `src/ol_logging/__init__.py` - Logger initialization and setup
> - `src/ol_logging/core.py` - Core logger configuration
> - `src/ol_logging/handlers.py` - File and console handlers
> - `src/ol_logging/formatters.py` - Structured log formatters
> - `src/ol_logging/context.py` - Async-safe context variables
> - `src/ol_logging/constants.py` - Log levels, paths, rotation settings
> - Logging calls added to all CLI commands and core modules
>
> **Estimated Effort**: Medium (~350 lines across 5 modules + integration)
> **Dependencies**: Python stdlib `logging` only (no new deps)
> **Parallel Execution**: YES - 4 waves

---

## Context

### Original Request
User asked: "create a logging system that creates logs automatically when the project runs, and have everything on the logs"

### Research Findings

**Existing Logging**: None. Grep found 0 matches for `logging`, `logger`, `log.` across all source files.

**Project Stack**:
- Python 3.13+ (as of pyproject.toml update)
- `typer` for CLI, `rich` for output, `pydantic` for config
- Already has `asyncio` for async operations
- Has structured error handling via `ol_core/exceptions.py`

**Architecture Layers to Log**:
| Layer | Module | Events to Log |
|-------|--------|----------------|
| CLI | `ol_cli.py` | Command start/end, args, errors |
| Batch | `ol_batch/processor.py` | Batch start/end, file start/complete/fail, summary |
| Config | `ol_config/loader.py` | Config load success/failure, env vars |
| Pool | `ol_pool/router.py` | Translation request, model selection, response |
| Discovery | `ol_batch/discovery.py` | Files found, scan start/end |
| Progress | `ol_batch/progress.py` | Progress updates, completions |

### Log Location
- Directory: `logs/` (in project root)
- Filename pattern: `ol-{YYYY-MM-DD}.log`
- Rotation: `RotatingFileHandler` with 10MB max, 5 backup files
- Default level: INFO (DEBUG available via env var)

### Format
```
2026-05-17 08:30:15.123 [INFO] [ol.cli.translate_md] Processing file.md (en→zh) - Start
2026-05-17 08:30:15.456 [DEBUG] [ol.pool] Model selected: MiniMax-M2.7 (priority=1)
2026-05-17 08:30:16.789 [ERROR] [ol.batch.processor] File failed: file.xlf - Error: timeout
```

---

## Work Objectives

### Core Objective
Add automatic logging that captures all operations with structured, searchable output.

### Definition of Done
- [ ] `logs/` directory created automatically on first log event
- [ ] All CLI commands log start/end with arguments
- [ ] All file processing operations logged (start, complete, fail per file)
- [ ] Batch processing logs per-file and summary
- [ ] Config loading logged (which config, env vars)
- [ ] Error logging with full exception traceback
- [ ] Log rotation working (10MB max, 5 backups)
- [ ] Log level configurable via environment variable

### Must Have
- Automatic log directory creation
- Log file naming with date stamp
- Structured log format (timestamp, level, logger, message)
- Per-module loggers (hierarchical: `ol.cli`, `ol.batch`, `ol.pool`, etc.)
- Async-safe context (file path, session id in logs)
- Error traceback logging

### Must NOT Have
- No external log libraries (stdlib only)
- No blocking writes (use buffered handler)
- No logging to stdout by default (file only, optional console)

---

## Execution Strategy

### Wave 1: Core Logging Infrastructure

| Task | What | Files |
|------|------|-------|
| 1 | Constants: log levels, paths, rotation settings | `src/ol_logging/constants.py` |
| 2 | Formatters: structured format strings | `src/ol_logging/formatters.py` |
| 3 | Context: async-safe context variables | `src/ol_logging/context.py` |
| 4 | Handlers: file + console handlers with rotation | `src/ol_logging/handlers.py` |
| 5 | Core: init_logger(), get_logger() functions | `src/ol_logging/core.py` |

### Wave 2: CLI Integration

| Task | What | Files |
|------|------|-------|
| 6 | Import logging in `ol_cli.py`, add to all commands | `src/ol_cli.py` |
| 7 | Add logging to `_translate_md_async()` | `src/ol_cli.py` |
| 8 | Add logging to `translate_batch()` | `src/ol_cli.py` |

### Wave 3: Batch + Core Integration

| Task | What | Files |
|------|------|-------|
| 9 | Add logging to `BatchProcessor.process_batch()` | `src/ol_batch/processor.py` |
| 10 | Add logging to `discover_files()` and `validate_directory()` | `src/ol_batch/discovery.py` |
| 11 | Add logging to config loading | `src/ol_config/loader.py` |

### Wave 4: Testing + Polish

| Task | What | Files |
|------|------|-------|
| 12 | Add logging to `ModelPool.translate()` | `src/ol_pool/router.py` |
| 13 | Add unit tests for logging | `tests/test_logging.py` |

### Dependency Matrix

```
Wave 1 (Tasks 1-5) → independent → blocks Wave 2
Wave 2 (Tasks 6-8) → depends on Wave 1 → blocks Wave 3
Wave 3 (Tasks 9-11) → depends on Wave 2 → blocks Wave 4
Wave 4 (Tasks 12-13) → depends on Wave 3
```

---

## TODOs

### Wave 1: Core Logging Infrastructure

- [ ] T1. **Create constants.py**

  **What**: Log level constants, paths, rotation settings

  ```python
  # Log levels
  DEBUG = 10
  INFO = 20
  WARNING = 30
  ERROR = 40

  # Paths
  LOG_DIR = "logs"
  LOG_FILE_PATTERN = "ol-{date}.log"
  MAX_BYTES = 10 * 1024 * 1024  # 10MB
  BACKUP_COUNT = 5

  # Environment variable
  LOG_LEVEL_ENV = "OL_LOG_LEVEL"
  ```

- [ ] T2. **Create formatters.py**

  **What**: Structured log format strings

  ```python
  FORMATTER = "%(asctime)s.%(msecs)03d [%(levelname)s] [%(name)s] %(message)s"
  DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
  ```

- [ ] T3. **Create context.py**

  **What**: Async-safe context variables for file/session tracking

  ```python
  from contextvars import ContextVar

  current_file: ContextVar[str] = ContextVar('current_file', default='')
  session_id: ContextVar[str] = ContextVar('session_id', default='')
  ```

- [ ] T4. **Create handlers.py**

  **What**: File + console handlers with rotation

  ```python
  def get_file_handler(log_dir: Path, level: int) -> RotatingFileHandler:
      """Create rotating file handler."""
      log_dir.mkdir(exist_ok=True)
      handler = RotatingFileHandler(
          log_dir / LOG_FILE_PATTERN.format(date=date.today().isoformat()),
          maxBytes=MAX_BYTES,
          backupCount=BACKUP_COUNT,
      )
      handler.setLevel(level)
      return handler

  def get_console_handler(level: int) -> StreamHandler:
      """Create console handler (optional)."""
  ```

- [ ] T5. **Create core.py**

  **What**: init_logger() and get_logger() functions

  ```python
  def init_logger(level: int = INFO, log_dir: Path = Path(LOG_DIR)) -> None:
      """Initialize root logger with file + optional console handler."""
      root_logger = logging.getLogger("ol")
      root_logger.setLevel(level)
      root_logger.addHandler(get_file_handler(log_dir, level))
      # Console only if OL_LOG_CONSOLE=true
      if os.getenv("OL_LOG_CONSOLE"):
          root_logger.addHandler(get_console_handler(level))

  def get_logger(name: str) -> logging.Logger:
      """Get logger for module (e.g., 'ol.cli.translate_md')."""
      return logging.getLogger(f"ol.{name}")
  ```

### Wave 2: CLI Integration

- [ ] T6. **Add logging to ol_cli.py imports and init**

  **What**: Import logging, call init_logger() on module load

  ```python
  from ol_logging import init_logger, get_logger

  # At module load (after imports)
  log_level = getattr(logging, os.getenv(LOG_LEVEL_ENV, "INFO"))
  init_logger(level=log_level)
  logger = get_logger("cli")
  ```

- [ ] T7. **Add logging to _translate_md_async()**

  **What**: Log file start, completion, errors

  ```python
  logger.info(f"Processing {input_path.name} ({src_lang}→{tgt_lang}) - Start")
  try:
      # ... processing
      logger.info(f"Processing {input_path.name} - Complete")
  except Exception as e:
      logger.error(f"Processing {input_path.name} - Failed: {e}")
      raise
  ```

- [ ] T8. **Add logging to translate_batch()**

  **What**: Log batch start, per-file progress, batch summary

  ```python
  logger.info(f"Batch started: {len(files)} files")
  for f in files:
      logger.debug(f"File queued: {f.name}")
  # ... after batch
  logger.info(f"Batch complete: {success_count}/{total} succeeded")
  ```

### Wave 3: Batch + Core Integration

- [ ] T9. **Add logging to BatchProcessor.process_batch()**

  ```python
  _logger = get_logger("batch.processor")
  _logger.info(f"Batch processing started: {len(files)} files")
  for file in files:
      _logger.debug(f"Processing file: {file.name}")
  # ... on complete
  _logger.info(f"Batch complete: {result.success_rate:.1f}% success rate")
  ```

- [ ] T10. **Add logging to discovery.py**

  ```python
  _logger = get_logger("batch.discovery")
  _logger.info(f"Scanning directory: {directory}")
  _logger.info(f"Found {len(files)} files matching {patterns}")
  ```

- [ ] T11. **Add logging to config/loader.py**

  ```python
  _logger = get_logger("config")
  _logger.info(f"Loading config: {config_path}")
  # ... on success
  _logger.info(f"Config loaded: {cfg.project_id}")
  ```

### Wave 4: Testing + Polish

- [ ] T12. **Add logging to ModelPool.translate()**

  ```python
  _logger = get_logger("pool")
  _logger.debug(f"Translation request: {len(text)} chars")
  # ... on response
  _logger.debug(f"Translation response: {len(translated)} chars")
  ```

- [ ] T13. **Add unit tests for logging**

  ```python
  def test_log_file_creation():
      """Test that log file is created on first log."""
      # ...

  def test_log_rotation():
      """Test that rotation happens at MAX_BYTES."""
      # ...

  def test_context_vars():
      """Test async-safe context is propagated."""
      # ...
  ```

---

## Commit Strategy

- **W1**: `feat(logging): add core logging infrastructure` - ol_logging/*.py (5 files)
- **W2**: `feat(logging): add CLI logging` - ol_cli.py changes
- **W3**: `feat(logging): add batch and config logging` - processor.py, discovery.py, loader.py
- **W4**: `feat(logging): add pool logging and tests` - router.py, test_logging.py

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OL_LOG_LEVEL` | `INFO` | Log level (DEBUG, INFO, WARNING, ERROR) |
| `OL_LOG_DIR` | `logs` | Log directory path |
| `OL_LOG_CONSOLE` | (not set) | Set to `1` to enable console output |

---

## Success Criteria

```bash
# Verify log directory created
ls -la logs/

# Verify log file created after running
ol translate-md test.md -o output/ -c config.yaml -s en -t zh
cat logs/ol-2026-05-17.log

# Verify structured format
grep "\[INFO\] \[ol.cli\]" logs/ol-*.log | head -10

# Verify batch logging
ol translate-batch ./testdata -o output/
grep "\[INFO\] \[ol.batch" logs/ol-*.log | head -10
```

### Final Checklist
- [ ] Log files created automatically in `logs/`
- [ ] Structured format with timestamp, level, logger, message
- [ ] All CLI commands logged
- [ ] All file processing logged
- [ ] All errors logged with traceback
- [ ] Log rotation working
- [ ] Tests pass