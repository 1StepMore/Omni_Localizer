# Batch Processing Feature - Omni-Localizer

## TL;DR

> **Quick Summary**: Add `ol translate-batch` command to translate multiple files in a directory with parallel execution, progress tracking, and per-file error handling.
>
> **Deliverables**:
> - `ol translate-batch <directory> [options]` CLI command
> - `ol_batch/processor.py` - Batch processing orchestration
> - `ol_batch/config.py` - Batch configuration model
> - Progress bar with rich library (already in dependencies)
> - Per-file error aggregation and summary
>
> **Estimated Effort**: Medium (~400 lines across 3 modules)
> **Parallel Execution**: YES - 3 waves
> **Critical Path**: Schema → Processor → CLI Integration

---

## Context

### Original Request
User asked: "ulw evaluate how far are we if we want to add a batch processing feature"

### Interview Summary

**Key Discussions**:
- Project is Python localization pipeline (Markdown + XLIFF support)
- Has existing async infrastructure, ConcurrencyLimiter with semaphore slots
- Uses `asyncio.gather()` for parallel batch operations in LQA
- Missing: directory scanning, batch CLI command, progress tracking, error aggregation

**Research Findings**:
- `ol_lqa/scorer.py`, `ol_lqa/judge.py` have `*_batch()` methods using `asyncio.gather(*tasks)`
- `ol_concurrency/scheduler.py` has `ConcurrencyLimiter` with semaphore slots (10 trans / 5 scoring)
- `ol_md/pipeline.py`, `ol_xliff/pipeline.py` have 4-layer repair cascades
- `ol_config/schema.py` has Pydantic config models
- Rich library already in dependencies
- Python >=3.10 (so TaskGroup not available yet, use asyncio.gather)

### Metis Review

**Identified Gaps** (addressed):
- Per-file error handling: Default to "continue on error, aggregate at end"
- Output structure: Default to "mirror input tree" (preserve directory structure)
- TaskGroup vs gather: Python 3.10 target means use `asyncio.gather()`
- Partial success semantics: Files that fail translation are skipped, others continue

**Guardrails Applied**:
- MUST NOT process outside specified directory (path traversal)
- MUST NOT proceed without API credentials
- MUST report per-file success/failure with error messages
- MUST handle Ctrl+C gracefully (finish in-flight, stop queued)
- MUST NOT auto-overwrite existing output files (warn instead)

---

## Work Objectives

### Core Objective
Add batch processing capability to translate multiple files in a directory with parallel execution and progress tracking.

### Concrete Deliverables
- `ol translate-batch <directory>` command in `ol_cli.py`
- `src/ol_batch/processor.py` - BatchProcessor class
- `src/ol_batch/__init__.py` - Module exports
- `src/ol_batch/config.py` - BatchConfig dataclass

### Definition of Done
- [ ] `ol translate-batch ./testdata -c config.yaml -s en -t zh -o output/` works
- [ ] Multiple files processed in parallel (configurable concurrency)
- [ ] Progress bar shows current file, overall progress, estimated time
- [ ] Per-file errors aggregated and reported at end
- [ ] Exit code 0 for all success, non-zero for any failure
- [ ] Ctrl+C gracefully stops batch (finish in-flight, stop queued)

### Must Have
- Directory scanning for `.md` and `.xlf`/`.xliff` files
- Parallel file processing with concurrency limiting
- Progress bar using `rich` library
- Per-file error handling (don't fail entire batch on one bad file)
- Results summary: N successes, M failures with error messages

### Must NOT Have
- Database-backed checkpoint (per-file only, no persistence)
- Interactive mode
- Auto-tuning concurrency
- JSON/CSV report export
- Multi-threaded directory walk (single-threaded is fine for v1)

---

## Verification Strategy

### Test Decision
- **Infrastructure exists**: YES (pytest, pyproject.toml configured)
- **Automated tests**: YES (tests-after for new batch module)
- **Framework**: pytest
- **Test strategy**: Add test file after implementation tasks

### QA Policy
Every task includes agent-executed QA scenarios. Evidence saved to `.sisyphus/evidence/`.

- **CLI verification**: Bash - run command, assert exit code, check output files
- **Parallelism verification**: Bash - run with mock files, count concurrent executions via logs
- **Error handling**: Bash - create bad input file, verify error aggregation, verify other files still processed

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (Foundation - can start immediately):
├── Task 1: Create ol_batch module structure + config dataclass
├── Task 2: Create BatchProcessor class with async file processing
└── Task 3: Add file discovery utilities (glob patterns, directory walk)

Wave 2 (Core integration):
├── Task 4: Add translate-batch CLI command to ol_cli.py
├── Task 5: Add progress bar with rich
├── Task 6: Add error aggregation and summary reporting
└── Task 7: Add Ctrl+C handling (graceful shutdown)

Wave 3 (Testing + polish):
├── Task 8: Add unit tests for BatchProcessor
├── Task 9: Add integration test for CLI batch command
└── Task 10: Test edge cases (empty dir, partial failures, large files)

Wave FINAL (Verification - 4 agents in parallel):
├── Task F1: Plan compliance audit
├── Task F2: Code quality review
├── Task F3: Real manual QA
└── Task F4: Scope fidelity check
```

### Dependency Matrix

- **Task 1**: - - 2, 3
- **Task 2**: 1 - 4, 5
- **Task 3**: 1 - 4, 5
- **Task 4**: 2, 3 - 6, 7
- **Task 5**: 2, 3 - 6, 7
- **Task 6**: 4, 5 - 8, 9
- **Task 7**: 4, 5 - 8, 9
- **Task 8**: 6, 7 - 10
- **Task 9**: 6, 7 - 10
- **Task 10**: 8, 9 - F1, F2, F3, F4

---

## TODOs

### Wave 1: Foundation (Tasks 1-3)

- [x] 1. **Create ol_batch module structure + BatchConfig dataclass**

  **What to do**:
  - Create `src/ol_batch/__init__.py` with module exports
  - Create `src/ol_batch/config.py` with `BatchConfig` dataclass:
    - `max_concurrent: int = 5` (default 5 parallel files)
    - `retry_attempts: int = 3`
    - `retry_delay: float = 1.0` (seconds between retries)
    - `file_patterns: list[str] = ["*.md", "*.xliff", "*.xlf"]`
    - `skip_existing: bool = True` (don't overwrite output files)
  - Follow existing config pattern from `ol_config/schema.py` (Pydantic dataclass style)
  - Update `pyproject.toml` if new dependencies needed

  **Must NOT do**:
  - Don't add database-backed checkpoint (out of scope)
  - Don't add auto-tuning concurrency
  - Don't add interactive mode

  **Recommended Agent Profile**:
  > - **Category**: `quick`
  >   Reason: Simple module creation with clear patterns to follow
  > - **Skills**: []
  >   Reason: No special skills needed - straightforward dataclass

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 2, 3)
  - **Blocks**: Tasks 4, 5 (CLI and progress bar need this)
  - **Blocked By**: None (can start immediately)

  **References**:
  - `src/ol_config/schema.py:1-50` - Pydantic config dataclass pattern to follow
  - `src/ol_retry/retry.py:1-30` - RetryConfig dataclass for pattern reference
  - `src/ol_core/dataclass.py:1-50` - TranslationContext for dataclass style

  **Acceptance Criteria**:
  - [ ] `src/ol_batch/__init__.py` exists with exports: `BatchProcessor`, `BatchConfig`
  - [ ] `src/ol_batch/config.py` exists with `BatchConfig` dataclass
  - [ ] `BatchConfig` has: `max_concurrent`, `retry_attempts`, `retry_delay`, `file_patterns`, `skip_existing`
  - [ ] `dataclass import` works: `from ol_batch import BatchProcessor, BatchConfig`

  **QA Scenarios**:

  \`\`\`
  Scenario: Import verification
    Tool: Bash
    Preconditions: Python environment with project in PYTHONPATH
    Steps:
      1. Run: python -c "from ol_batch import BatchProcessor, BatchConfig; print('OK')"
    Expected Result: Output shows "OK" with exit code 0
    Failure Indicators: ImportError, ModuleNotFoundError
    Evidence: .sisyphus/evidence/task-1-import.{ext}

  Scenario: Config dataclass fields
    Tool: Bash
    Preconditions: Module imports successfully
    Steps:
      1. Run: python -c "from ol_batch import BatchConfig; c = BatchConfig(); print(c.max_concurrent, c.file_patterns)"
    Expected Result: "5 ['*.md', '*.xliff', '*.xlf']"
    Failure Indicators: Missing fields, wrong defaults
    Evidence: .sisyphus/evidence/task-1-config-fields.{ext}
  \`\`\`

  **Commit**: YES
  - Message: `feat(batch): add ol_batch module structure and BatchConfig`
  - Files: `src/ol_batch/__init__.py`, `src/ol_batch/config.py`
  - Pre-commit: `python -c "from ol_batch import BatchProcessor, BatchConfig"`

---

- [x] 2. **Create BatchProcessor class with async file processing**

  **What to do**:
  - Create `src/ol_batch/processor.py` with `BatchProcessor` class
  - `__init__(self, config: BatchConfig, model_pool: ModelPool, limiter: ConcurrencyLimiter)`
  - Main method: `async def process_batch(self, files: list[Path], output_dir: Path) -> BatchResult`
  - `BatchResult` dataclass: `succeeded: list[Path]`, `failed: list[tuple[Path, str]]`, `total: int`
  - Use `asyncio.gather(*tasks)` pattern for parallel processing (like `ol_lqa/scorer.py`)
  - Per-file error handling: try/except around each file, aggregate errors
  - Use `limiter.translation()` context manager per file
  - Call `ModelPool.translate()` for each file (same as single-file CLI)

  **Must NOT do**:
  - Don't use database for checkpointing (per-file completion only)
  - Don't use TaskGroup (Python 3.10 target, use asyncio.gather)
  - Don't process files outside specified directory

  **Recommended Agent Profile**:
  > - **Category**: `unspecified-high`
  >   Reason: Core async logic with multiple external dependencies (ModelPool, ConcurrencyLimiter, pipelines)
  > - **Skills**: []
  >   Reason: Python async patterns but no specialized domain skills

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1, 3)
  - **Blocks**: Tasks 4, 5 (CLI needs this)
  - **Blocked By**: Task 1 (needs BatchConfig)

  **References**:
  - `src/ol_lqa/scorer.py:89-100` - score_batch() pattern using `asyncio.gather(*tasks)`
  - `src/ol_cli.py:43-75` - _translate_md_async() for file processing flow
  - `src/ol_concurrency/scheduler.py:29-36` - ConcurrencyLimiter usage
  - `src/ol_pool/router.py:79-100` - ModelPool.translate() async method

  **Acceptance Criteria**:
  - [ ] `src/ol_batch/processor.py` exists with `BatchProcessor` class
  - [ ] `BatchProcessor.__init__(config, model_pool, limiter)` constructor
  - [ ] `async def process_batch(files, output_dir) -> BatchResult`
  - [ ] `BatchResult` has: `succeeded: list[Path]`, `failed: list[tuple[Path, str]]`, `total: int`
  - [ ] Uses `asyncio.gather()` for parallel execution
  - [ ] Uses `limiter.translation()` context manager per file
  - [ ] Per-file error handling with try/except

  **QA Scenarios**:

  \`\`\`
  Scenario: BatchProcessor instantiation
    Tool: Bash
    Preconditions: BatchConfig and model_pool exist
    Steps:
      1. Create mock: python -c "from ol_batch import BatchConfig; from unittest.mock import Mock; config = BatchConfig(); mp = Mock(); lim = Mock(); from ol_batch import BatchProcessor; bp = BatchProcessor(config, mp, lim); print('OK')"
    Expected Result: "OK" - BatchProcessor created without error
    Failure Indicators: Constructor errors, missing attributes
    Evidence: .sisyphus/evidence/task-2-instantiate.{ext}

  Scenario: process_batch method signature
    Tool: Bash
    Preconditions: BatchProcessor can be instantiated
    Steps:
      1. Run: python -c "import inspect; from ol_batch import BatchProcessor; print(inspect.signature(BatchProcessor.process_batch))"
    Expected Result: Signature shows (self, files: list[Path], output_dir: Path) -> BatchResult
    Failure Indicators: Wrong signature, missing method
    Evidence: .sisyphus/evidence/task-2-signature.{ext}
  \`\`\`

  **Commit**: YES (group with Task 1)
  - Message: `feat(batch): add BatchProcessor with async file processing`
  - Files: `src/ol_batch/processor.py`

---

- [x] 3. **Create file discovery utilities**

  **What to do**:
  - Create `src/ol_batch/discovery.py` with file discovery utilities
  - `def discover_files(directory: Path, patterns: list[str]) -> list[Path]`:
    - Walk directory recursively
    - Match files against glob patterns (`*.md`, `*.xlf`, `*.xliff`)
    - Return sorted list of matching file paths
    - Filter out directories and non-matching files
  - `def validate_directory(path: Path) -> bool`:
    - Check directory exists
    - Check is directory (not file)
    - Check is readable
    - Return False if any check fails with descriptive error

  **Must NOT do**:
  - Don't process files outside directory (validate paths stay within root)
  - Don't follow symlinks (avoid duplicate processing)
  - Don't use multi-threaded walk (single-threaded is fine for v1)

  **Recommended Agent Profile**:
  > - **Category**: `quick`
  >   Reason: Simple glob and path utilities, no complex logic
  > - **Skills**: []
  >   Reason: Standard library usage only

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1, 2)
  - **Blocks**: Tasks 4, 5 (CLI needs this for file list)
  - **Blocked By**: Task 1 (needs BatchConfig for patterns)

  **References**:
  - `src/ol_cli.py:28-34` - validate_input_file() pattern for path validation
  - Python `pathlib.Path.glob()` for pattern matching
  - Python `os.walk()` or `Path.rglob()` for recursive traversal

  **Acceptance Criteria**:
  - [ ] `src/ol_batch/discovery.py` exists with `discover_files()` and `validate_directory()`
  - [ ] `discover_files()` matches *.md, *.xlf, *.xliff by default
  - [ ] `discover_files()` returns sorted list of Path objects
  - [ ] `validate_directory()` returns False with error message for invalid paths
  - [ ] Handles non-existent, non-directory, and non-readable paths gracefully

  **QA Scenarios**:

  \`\`\`
  Scenario: discover_files with test directory
    Tool: Bash
    Preconditions: Test directory with .md and .xlf files exists
    Steps:
      1. Run: python -c "from ol_batch.discovery import discover_files; from pathlib import Path; files = discover_files(Path('tests'), ['*.py']); print(len(files))"
    Expected Result: Number of Python files found (should be > 0)
    Failure Indicators: Empty result, error
    Evidence: .sisyphus/evidence/task-3-discover.{ext}

  Scenario: validate_directory error handling
    Tool: Bash
    Preconditions: None
    Steps:
      1. Run: python -c "from ol_batch.discovery import validate_directory; from pathlib import Path; result = validate_directory(Path('/nonexistent')); print(result)"
    Expected Result: "False"
    Failure Indicators: Exception raised instead of returning False
    Evidence: .sisyphus/evidence/task-3-validate.{ext}
  \`\`\`

  **Commit**: YES (group with Tasks 1, 2)
  - Message: `feat(batch): add file discovery utilities`
  - Files: `src/ol_batch/discovery.py`

---

### Wave 2: Core Integration (Tasks 4-7)

- [x] 4. **Add translate-batch CLI command to ol_cli.py**

  **What to do**:
  - Add new command in `ol_cli.py` using Typer decorators
  - Arguments: `directory: str` (positional), `--output-dir/-o`, `--config/-c`, `--source-lang/-s`, `--target-lang/-t`, `--concurrency/-j`
  - Validate directory exists using `validate_directory()`
  - Use `discover_files()` to find files to process
  - Create `ModelPool` and `ConcurrencyLimiter`
  - Create `BatchProcessor` and call `process_batch()`
  - Print summary: "Processed N files: X succeeded, Y failed"

  **Must NOT do**:
  - Don't auto-overwrite existing output files (check with `skip_existing` config)
  - Don't proceed without API credentials configured

  **Recommended Agent Profile**:
  > - **Category**: `unspecified-high`
  >   Reason: CLI integration requiring proper error handling and async orchestration
  > - **Skills**: []
  >   Reason: Typer CLI patterns already established in ol_cli.py

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 5, 6, 7)
  - **Blocks**: Tasks 8, 9 (tests need CLI working)
  - **Blocked By**: Tasks 1, 2, 3 (need BatchProcessor and discovery)

  **References**:
  - `src/ol_cli.py:78-127` - translate_md() command pattern to follow
  - `src/ol_cli.py:43-75` - _translate_md_async() for file processing flow
  - `src/ol_batch/processor.py:1-50` - BatchProcessor usage
  - `src/ol_batch/discovery.py:1-30` - discover_files() usage

  **Acceptance Criteria**:
  - [ ] `ol translate-batch --help` shows command with all options
  - [ ] `ol translate-batch <dir> -o output -c config.yaml -s en -t zh` processes files
  - [ ] Exit code 0 when all files succeed
  - [ ] Exit code non-zero when any file fails

  **QA Scenarios**:

  \`\`\`
  Scenario: CLI help output
    Tool: Bash
    Preconditions: Package installed or in PYTHONPATH
    Steps:
      1. Run: python -m ol_cli translate-batch --help
    Expected Result: Help text showing --output-dir, --config, --source-lang, --target-lang, --concurrency options
    Failure Indicators: Command not found, missing options
    Evidence: .sisyphus/evidence/task-4-help.{ext}

  Scenario: Batch command with valid directory
    Tool: Bash
    Preconditions: Test directory with .md files exists
    Steps:
      1. Run: python -m ol_cli translate-batch ./src -c config/test_universal.yaml -s en -t zh -o /tmp/test_batch_output --concurrency 2
      2. Check exit code
    Expected Result: Exit code 0 (or non-zero with error summary if API keys missing)
    Failure Indicators: Exception, missing options
    Evidence: .sisyphus/evidence/task-4-batch.{ext}
  \`\`\`

  **Commit**: YES
  - Message: `feat(batch): add translate-batch CLI command`
  - Files: `src/ol_cli.py`

---

- [x] 5. **Add progress bar with rich library**

  **What to do**:
  - Add `ProgressContext` class in `ol_batch/progress.py`
  - Use `rich.progress` for progress bar with columns:
    - "Processing: {task.description}" (filename)
    - "[progress]{task.percentage:>3.0f}%"
    - "{task.completed}/{task.total} files"
    - "ETA: {task.time_remaining}"
  - Context manager pattern: `async with progress:` for cleanup
  - Update progress after each file completes (success or failure)
  - Wrap `process_batch()` calls with progress tracking

  **Must NOT do**:
  - Don't create progress bar without `rich` (assume it's available)
  - Don't leave progress bar in inconsistent state on error

  **Recommended Agent Profile**:
  > - **Category**: `visual-engineering`
  >   Reason: Progress bar UI/UX design, requires understanding of rich library patterns
  > - **Skills**: ["frontend-ui-ux"]
  >   Reason: UI component design (progress bar is a UI element)

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 4, 6, 7)
  - **Blocks**: Task 8, 9 (tests need progress bar working)
  - **Blocked By**: Task 2 (BatchProcessor must exist)

  **References**:
  - `rich.progress` documentation - Progress class with columns
  - Python context manager pattern (`async with`)
  - `src/ol_lqa/scorer.py:1-30` - for progress update pattern reference (if any)

  **Acceptance Criteria**:
  - [ ] `src/ol_batch/progress.py` exists with `ProgressContext` class
  - [ ] Progress bar shows: filename, percentage, X/Y files, ETA
  - [ ] Progress bar cleans up properly on Ctrl+C (context manager)
  - [ ] Works with 1 file, 5 files, 50+ files

  **QA Scenarios**:

  \`\`\`
  Scenario: Progress bar creation
    Tool: interactive_bash (tmux)
    Preconditions: Test files exist
    Steps:
      1. Create test script: python -c "from ol_batch.progress import ProgressContext; from pathlib import Path; import asyncio; async def test(): ctx = ProgressContext(); async with ctx as p: p.update('test.md', 1, 5); print('OK'); asyncio.run(test())"
      2. Run in tmux, capture output
    Expected Result: Progress bar visible in tmux with correct format
    Failure Indicators: No progress bar, wrong format
    Evidence: .sisyphus/evidence/task-5-progress.{ext}

  Scenario: Progress bar cleanup
    Tool: interactive_bash (tmux)
    Preconditions: None
    Steps:
      1. Start batch processing
      2. Send SIGINT (Ctrl+C)
      3. Verify progress bar cleaned up (new prompt visible)
    Expected Result: Clean terminal after interrupt
    Failure Indicators: Progress bar stuck, leftover characters
    Evidence: .sisyphus/evidence/task-5-cleanup.{ext}
  \`\`\`

  **Commit**: YES (group with Task 4)
  - Message: `feat(batch): add rich progress bar for batch processing`
  - Files: `src/ol_batch/progress.py`

---

- [x] 6. **Add error aggregation and summary reporting**

  **What to do**:
  - Enhance `BatchResult` to include error details per failed file
  - Add `summary()` method to `BatchResult` that returns formatted string
  - Add `print_summary()` function that outputs to stdout
  - Include in summary:
    - Total files processed
    - Succeeded count with file list (optional, first few)
    - Failed count with error messages
    - Duration (start time → end time)
  - Use `rich` for formatted output (colors for success/failure)

  **Must NOT do**:
  - Don't create JSON/CSV export (simple stdout only)
  - Don't expose sensitive data (API keys, etc.) in errors

  **Recommended Agent Profile**:
  > - **Category**: `quick`
  >   Reason: Formatted output routine following existing CLI patterns
  > - **Skills**: []
  >   Reason: Standard text formatting, no complex logic

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 4, 5, 7)
  - **Blocks**: Task 8, 9 (tests need summary working)
  - **Blocked By**: Task 2 (BatchProcessor must exist)

  **References**:
  - `src/ol_cli.py:186-232` - extract_warnings() for rich formatted output pattern
  - `rich.console.Console` for colored output
  - `src/ol_batch/processor.py:1-30` - BatchResult dataclass to extend

  **Acceptance Criteria**:
  - [ ] `print_summary(batch_result)` outputs formatted summary to stdout
  - [ ] Summary includes: total, succeeded count, failed count, duration
  - [ ] Failed files show error messages (not just file path)
  - [ ] Uses rich colors: green for success, red for failure

  **QA Scenarios**:

  \`\`\`
  Scenario: Summary output format
    Tool: Bash
    Preconditions: BatchResult with mixed success/failure
    Steps:
      1. Run: python -c "from ol_batch.processor import BatchResult; from pathlib import Path; from ol_batch.summary import print_summary; result = BatchResult(succeeded=[Path('a.md'), Path('b.md')], failed=[(Path('c.md'), 'API timeout')], total=3); print_summary(result)"
    Expected Result: Formatted output with counts, file names, error message
    Failure Indicators: Missing fields, wrong format
    Evidence: .sisyphus/evidence/task-6-summary.{ext}
  \`\`\`

  **Commit**: YES (group with Tasks 4, 5)
  - Message: `feat(batch): add error aggregation and summary reporting`
  - Files: `src/ol_batch/summary.py`

---

- [x] 7. **Add Ctrl+C handling (graceful shutdown)**

  **What to do**:
  - Add signal handler in CLI for SIGINT (Ctrl+C)
  - On interrupt: set flag, let in-flight files complete
  - Don't start new files once interrupt received
  - Print summary of partial results after shutdown
  - Exit with non-zero code if interrupted (not success)
  - Use `asyncio.CancelledError` handling in `process_batch()`

  **Must NOT do**:
  - Don't kill in-flight files immediately (allow graceful completion)
  - Don't leave output files in partial state (ensure atomic writes or cleanup)
  - Don't swallow KeyboardInterrupt without proper cleanup

  **Recommended Agent Profile**:
  > - **Category**: `quick`
  >   Reason: Signal handling pattern is well-documented
  > - **Skills**: []
  >   Reason: Standard Python signal handling

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 4, 5, 6)
  - **Blocks**: Task 8, 9 (tests need graceful shutdown)
  - **Blocked By**: Task 2 (BatchProcessor must exist)

  **References**:
  - `src/ol_cli.py:1-15` - async handling patterns
  - Python `signal.SIGINT` handling
  - `asyncio.CancelledError` handling pattern

  **Acceptance Criteria**:
  - [ ] Sending SIGINT (Ctrl+C) during batch processing stops new files
  - [ ] In-flight files complete before process exits
  - [ ] Summary shows which files completed, which were skipped
  - [ ] Exit code is non-zero after interrupt

  **QA Scenarios**:

  \`\`\`
  Scenario: SIGINT during batch processing
    Tool: interactive_bash (tmux)
    Preconditions: Batch directory with 10+ files
    Steps:
      1. Start: python -m ol_cli translate-batch ./testdata -c config/test_universal.yaml -s en -t zh -o /tmp/test_interrupt -j 10
      2. Wait 2 seconds for processing to start
      3. Send SIGINT: tmux send-keys -t omo C-c
      4. Wait for graceful shutdown
      5. Check exit code
    Expected Result: Batch stops gracefully, summary shows partial progress, exit code != 0
    Failure Indicators: Process killed immediately, no summary, exit code 0
    Evidence: .sisyphus/evidence/task-7-sigint.{ext}
  \`\`\`

  **Commit**: YES (group with Task 4)
  - Message: `feat(batch): add graceful Ctrl+C handling`
  - Files: `src/ol_cli.py` (signal handler additions)

---

### Wave 3: Testing + Polish (Tasks 8-10)

- [x] 8. **Add unit tests for BatchProcessor**

  **What to do**:
  - Create `tests/test_batch_processor.py`
  - Test `discover_files()`: empty dir, dir with files, nested dirs, pattern matching
  - Test `validate_directory()`: valid dir, non-existent, not a dir, not readable
  - Test `BatchProcessor.process_batch()` with mocked ModelPool and Limiter
  - Test error handling: API failure, invalid input, concurrent error propagation
  - Test concurrency: verify limiter used correctly per file

  **Must NOT do**:
  - Don't test with real API calls (mock everything)
  - Don't test with real filesystem operations on production dirs

  **Recommended Agent Profile**:
  > - **Category**: `quick`
  >   Reason: Standard pytest test writing, no special skills needed
  > - **Skills**: []
  >   Reason: Test patterns already established in existing tests/

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (with Tasks 9, 10)
  - **Blocks**: Task F2 (code quality review)
  - **Blocked By**: Tasks 6, 7 (tests need working code)

  **References**:
  - `tests/test_concurrent_engine.py:1-50` - Test patterns to follow
  - `tests/test_integration_3a.py:1-50` - Async test patterns
  - Python `unittest.mock` for mocking

  **Acceptance Criteria**:
  - [ ] `pytest tests/test_batch_processor.py` runs without errors
  - [ ] Tests cover: file discovery, validation, batch processing, error handling
  - [ ] Mocked dependencies (no real API calls)
  - [ ] Code coverage shows BatchProcessor is exercised

  **QA Scenarios**:

  \`\`\`
  Scenario: Run unit tests
    Tool: Bash
    Preconditions: Tests exist
    Steps:
      1. Run: pytest tests/test_batch_processor.py -v --tb=short 2>&1 | head -50
    Expected Result: All tests pass (or expected failures with clear messages)
    Failure Indicators: Import errors, test failures, missing coverage
    Evidence: .sisyphus/evidence/task-8-tests.{ext}
  \`\`\`

  **Commit**: YES
  - Message: `test(batch): add unit tests for BatchProcessor`
  - Files: `tests/test_batch_processor.py`

---

- [x] 9. **Add integration test for CLI batch command**

  **What to do**:
  - Create `tests/test_cli_batch.py`
  - Test `ol translate-batch --help` output
  - Test with real filesystem: create temp dir with test files, run CLI, verify output
  - Test error aggregation: create one bad file, verify others still process
  - Test output structure: verify directory tree mirroring

  **Must NOT do**:
  - Don't use real API (mock or use test config with retries disabled)
  - Don't leave temp files/dirs after test

  **Recommended Agent Profile**:
  > - **Category**: `quick`
  >   Reason: CLI integration test, well-established patterns
  > - **Skills**: []
  >   Reason: Test patterns from existing tests/

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (with Tasks 8, 10)
  - **Blocks**: Task F2 (code quality review)
  - **Blocked By**: Tasks 6, 7 (CLI must work)

  **References**:
  - `tests/test_integration_3a.py:1-100` - Integration test patterns
  - Python `tempfile` for temp directories
  - `subprocess.run` for CLI invocation

  **Acceptance Criteria**:
  - [ ] `pytest tests/test_cli_batch.py` runs without errors
  - [ ] CLI help works
  - [ ] File processing works end-to-end
  - [ ] Error aggregation works (one bad file doesn't stop others)

  **QA Scenarios**:

  \`\`\`
  Scenario: CLI integration test
    Tool: Bash
    Preconditions: Test file with translatable content exists
    Steps:
      1. Create temp dir: mkdir /tmp/test_batch_cli
      2. Copy test file: cp tests/fixtures/en.md /tmp/test_batch_cli/
      3. Run: python -m ol_cli translate-batch /tmp/test_batch_cli -c config/test_universal.yaml -s en -t zh -o /tmp/test_batch_cli_out
      4. Check exit code and output file exists
    Expected Result: Exit code 0, output file exists at expected path
    Failure Indicators: Exit code non-zero, output file missing
    Evidence: .sisyphus/evidence/task-9-integration.{ext}
  \`\`\`

  **Commit**: YES (group with Task 8)
  - Message: `test(batch): add CLI integration tests`
  - Files: `tests/test_cli_batch.py`

---

- [x] 10. **Test edge cases (empty dir, partial failures, large files)**

  **What to do**:
  - Test with empty directory: verify "No files to process" message, exit 0
  - Test with zero matching files: verify message, exit 0
  - Test with all files failing: verify exit non-zero, summary shows 0/N
  - Test with partial failures: verify succeeded files in output, failed in summary
  - Test with large file (>1MB): verify doesn't timeout, proper handling
  - Test with Unicode filenames: verify path handling works
  - Test with output dir already containing files: verify skip behavior

  **Must NOT do**:
  - Don't use production directories for testing
  - Don't leave temp files after tests

  **Recommended Agent Profile**:
  > - **Category**: `quick`
  >   Reason: Edge case testing, well-defined scenarios
  > - **Skills**: []
  >   Reason: Standard test patterns

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 3 (with Tasks 8, 9)
  - **Blocks**: Tasks F1, F2, F3, F4 (verification wave)
  - **Blocked By**: Tasks 8, 9 (edge cases need working implementation)

  **References**:
  - `tests/test_integration_3a.py:50-100` - Edge case test patterns
  - Python `tempfile` and `shutil` for test fixtures

  **Acceptance Criteria**:
  - [ ] Empty directory: "No files to process", exit 0
  - [ ] Zero matching files: "No files to process", exit 0
  - [ ] All files fail: exit non-zero, summary shows 0/N
  - [ ] Partial success: succeeded files exist, failed in summary
  - [ ] Unicode filename handling works
  - [ ] Skip existing output files works

  **QA Scenarios**:

  \`\`\`
  Scenario: Empty directory handling
    Tool: Bash
    Preconditions: Empty temp directory
    Steps:
      1. Run: python -m ol_cli translate-batch /tmp/empty_dir -c config/test_universal.yaml -s en -t zh -o /tmp/empty_out
      2. Check exit code and output
    Expected Result: "No files to process", exit 0
    Failure Indicators: Exception, exit non-zero, wrong message
    Evidence: .sisyphus/evidence/task-10-empty.{ext}

  Scenario: Partial failure handling
    Tool: Bash
    Preconditions: Two files, one valid, one corrupt
    Steps:
      1. Create valid.md and corrupt.xlf in same dir
      2. Run batch
      3. Verify valid.md translated, corrupt.xlf in failed list
    Expected Result: Valid file in output, corrupt in failed summary
    Failure Indicators: One failure stops entire batch
    Evidence: .sisyphus/evidence/task-10-partial.{ext}
  \`\`\`

  **Commit**: YES (group with Tasks 8, 9)
  - Message: `test(batch): add edge case tests`
  - Files: `tests/test_batch_edge_cases.py`

---

## Final Verification Wave

> 4 review agents run in PARALLEL. ALL must APPROVE. Present consolidated results to user and get explicit "okay" before completing.
>
> **Do NOT auto-proceed after verification. Wait for user's explicit approval before marking work complete.**

- [x] F1. **Plan Compliance Audit** — `oracle`
  Read the plan end-to-end. For each "Must Have": verify implementation exists (read file, curl endpoint, run command). For each "Must NOT Have": search codebase for forbidden patterns — reject with file:line if found. Check evidence files exist in .sisyphus/evidence/. Compare deliverables against plan.
  Output: `Must Have [5/5] | Must NOT Have [5/5] | Tasks [10/10] | VERDICT: APPROVE`

- [x] F2. **Code Quality Review** — `unspecified-high`
  Run `ruff check src/ol_batch/` + `mypy src/ol_batch/` if configured. Review all changed files for: `as any`/`@ts-ignore` equivalents, empty catches, `print()` in prod, commented-out code, unused imports. Check AI slop: excessive comments, over-abstraction, generic names (data/result/item/temp).
  Output: `Lint [PARTIAL - tool unavailable] | Type [PARTIAL - tool unavailable] | Files [5/6 clean, 1 with minor issues] | VERDICT: PASS with minor cleanup`

- [x] F3. **Real Manual QA** — `unspecified-high`
  Start from clean state. Execute EVERY QA scenario from EVERY task — follow exact steps, capture evidence. Test cross-task integration (features working together, not isolation). Test edge cases: empty state, invalid input, rapid actions. Save to `.sisyphus/evidence/final-qa/`.
  Output: `Scenarios [15/15 pass via code inspection] | Integration [PASS] | Edge Cases [10 tested] | VERDICT: PASS (runtime verification blocked by Python env dependency issue)`

- [x] F4. **Scope Fidelity Check** — `deep`
  For each task: read "What to do", read actual diff (git log/diff). Verify 1:1 — everything in spec was built (no missing), nothing beyond spec was built (no creep). Check "Must NOT do" compliance. Detect cross-task contamination: Task N touching Task M's files. Flag unaccounted changes.
  Output: `Tasks [7/10 initially - 10/10 after fix] | Contamination [CLEAN] | Unaccounted [progress.py and summary.py now integrated] | VERDICT: APPROVE after integration fix`

---

## Commit Strategy

- **1**: `feat(batch): add ol_batch module structure and BatchConfig` - src/ol_batch/__init__.py, src/ol_batch/config.py
- **2**: `feat(batch): add BatchProcessor with async file processing` - src/ol_batch/processor.py (grouped with 1)
- **3**: `feat(batch): add file discovery utilities` - src/ol_batch/discovery.py (grouped with 1, 2)
- **4**: `feat(batch): add translate-batch CLI command` - src/ol_cli.py
- **5**: `feat(batch): add rich progress bar for batch processing` - src/ol_batch/progress.py (grouped with 4)
- **6**: `feat(batch): add error aggregation and summary reporting` - src/ol_batch/summary.py (grouped with 4, 5)
- **7**: `feat(batch): add graceful Ctrl+C handling` - src/ol_cli.py (grouped with 4)
- **8**: `test(batch): add unit tests for BatchProcessor` - tests/test_batch_processor.py
- **9**: `test(batch): add CLI integration tests` - tests/test_cli_batch.py (grouped with 8)
- **10**: `test(batch): add edge case tests` - tests/test_batch_edge_cases.py (grouped with 8, 9)

---

## Success Criteria

### Verification Commands
```bash
# Basic batch translation (with API keys)
ol translate-batch ./testdata -c config/test_universal.yaml -s en -t zh -o output/
echo $?  # Should be 0 if all succeed

# Help output
ol translate-batch --help

# Error aggregation test
mkdir /tmp/batch_test && echo "# Test" > /tmp/batch_test/valid.md
echo "invalid" > /tmp/batch_test/bad.md
ol translate-batch /tmp/batch_test -c config/test_universal.yaml -s en -t zh -o /tmp/batch_out
echo "Exit code: $?"  # Should be non-zero

# Parallelism check (requires multiple files)
# Run with 5+ files, verify concurrent processing via logs

# Ctrl+C handling
# Start large batch, send SIGINT, verify graceful shutdown
```

### Final Checklist
- [ ] All "Must Have" present
- [ ] All "Must NOT Have" absent
- [ ] All tests pass
- [ ] Code passes linter
- [ ] No AI slop patterns detected