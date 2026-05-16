# Omni-Localizer Phase 3a: Routing + Model Pool + Concurrency

## TL;DR

> **Quick Summary**: Implement intelligent routing engine for MD/XLIFF file dispatch, elastic model pool with LiteLLM Router failover, and concurrency scheduling with rate limiting.
>
> **Deliverables**:
> - `src/ol_routing/` - Smart routing engine with batch support
> - `src/ol_pool/` - Model pool with LiteLLM Router integration + AgentFuse cost optimization
> - `src/ol_concurrency/` - Concurrency scheduler with rate limiting and semaphore-based controls
> - `src/ol_checkpoint/` - Checkpoint mechanism foundation
> - `src/ol_md/repair/level3.py` + `src/ol_xliff/repair/level3.py` - LiteLLMRestorer real implementation
>
> **Estimated Effort**: 1.5 days
> **Parallel Execution**: YES - 2 waves
> **Critical Path**: Model Pool (wave 1) → Concurrency + Routing (wave 2) → LiteLLMRestorer integration

---

## Context

### Original Request
Implement Phase 3a for Omni-Localizer translation pipeline:
- Routing engine for MD/XLIFF format detection
- Elastic model pool with LiteLLM Router failover
- Concurrency scheduling with rate limiting
- LiteLLMRestorer implementation for Level 3 placeholder restoration
- Checkpoint mechanism foundation

### Research Findings

**LiteLLM Router Configuration** (pending from librarian agent):
- Uses `router_model_list` for model priority/fallback configuration
- Environment variable substitution via `${VAR_NAME}` syntax
- Rate limits configurable per model
- 3-second timeout configurable

**Sentence-Transformers Model** (pending from librarian agent):
- TBD: Recommended model for multilingual semantic similarity

### Metis Review Gaps Addressed

1. **Concurrency Primitive**: Using `asyncio` with `aiohttp` for async HTTP calls to LiteLLM
2. **Atomic Checkpoint Write**: Using `fcntl.flock` for file locking + temp file + rename pattern
3. **LiteLLMRestorer Prompt**: Defined explicit prompt template below

---

## Work Objectives

### Core Objective
Build the concurrency foundation for Phase 3b LQA integration. Phase 3a establishes the routing, model pool, and concurrency primitives that Phase 3b will compose into the full pipeline.

### Concrete Deliverables

| Deliverable | Path |
|-------------|------|
| Smart routing engine | `src/ol_routing/` |
| Model pool with failover | `src/ol_pool/` |
| Concurrency scheduler | `src/ol_concurrency/` |
| Checkpoint foundation | `src/ol_checkpoint/` |
| LiteLLMRestorer implementation | `src/ol_md/repair/level3.py`, `src/ol_xliff/repair/level3.py` |

### Definition of Done

- [ ] `poetry run pytest tests/test_routing/ -v` → PASS
- [ ] `poetry run pytest tests/test_model_pool/ -v` → PASS
- [ ] `poetry run pytest tests/test_concurrency/ -v` → PASS
- [ ] `poetry run pytest tests/test_checkpoint/ -v` → PASS
- [ ] `poetry run pytest tests/test_llm_restorer.py -v` → PASS (LiteLLMRestorer integration)
- [ ] Routing correctly identifies MD/XLIFF and rejects unsupported formats
- [ ] Model pool failover tested with mocked 429/5xx responses
- [ ] Concurrency limits enforced (max 10 translation, max 5 scoring)
- [ ] Checkpoint saves and loads correctly with atomic writes

### Must Have

- **Routing**: Format detection by file extension ONLY (no content auto-detection)
- **Model Pool**: Primary + backup model selection, auto-failover on 429/5xx/auth errors
- **Concurrency**: Rate limiting with semaphore, queue-based waiting when limit reached
- **Checkpoint**: JSON file with atomic write, file locking, hash verification
- **LiteLLMRestorer**: Real LiteLLM call with prompt template for placeholder restoration

### Must NOT Have

- Content-based routing (auto-detect format from content)
- SQLite checkpoint (JSON only per spec)
- Multi-turn conversation for LiteLLMRestorer
- Runtime model pool modification (models fixed at startup)
- TM integration (Phase 3b)

---

## Verification Strategy

### Test Decision
- **Infrastructure exists**: YES (pytest)
- **Automated tests**: YES (TDD)
- **Framework**: pytest with pytest-asyncio
- **TDD Workflow**: RED (failing test) → GREEN (minimal impl) → REFACTOR

### QA Policy
Every task includes agent-executed QA scenarios. Evidence saved to `.sisyphus/evidence/task-{N}-{scenario-slug}.{ext}`.

---

## Execution Strategy

### Parallel Execution Waves

```
Wave 1 (Foundation - can start immediately):
├── Task 1: Model Pool Schema Extension + Config Validation
├── Task 2: LiteLLM Router Integration (routing + failover)
└── Task 3: Concurrency Scheduler Base (semaphore + queue)

Wave 2 (After Wave 1 - depends on model pool):
├── Task 4: Smart Routing Engine (batch support)
├── Task 5: Checkpoint Foundation (atomic write + locking)
├── Task 6: LiteLLMRestorer Implementation (Level 3 placeholder restoration)
└── Task 7: Integration Tests (routing → pool → concurrency)
```

### Dependency Matrix

| Task | Depends On | Blocks |
|------|------------|--------|
| Task 1 | None | Tasks 2, 3 |
| Task 2 | Task 1 | Tasks 4, 6, 7 |
| Task 3 | Task 1 | Tasks 4, 7 |
| Task 4 | Tasks 2, 3 | Task 7 |
| Task 5 | Tasks 2, 3 | Task 7 |
| Task 6 | Task 2 | Task 7 |
| Task 7 | Tasks 4, 5, 6 | - |

---

## TODOs

### Wave 1 (Foundation)

- [x] 1. **Model Pool Schema Extension + Config Validation**

  **What to do**:
  - Extend `src/ol_config/schema.py`: Add `LLMModelRole` Enum (translation, judging, restoration)
  - Extend `LLMModelConfig`: Add `role: LLMModelRole` field
  - Add config validation: Ensure at least 2 models per role (primary + backup)
  - Add `api_key` presence check (fail fast if missing)
  - Write tests in `tests/test_model_pool_schema.py`

  **Must NOT do**:
  - Add fallback logic (that's LiteLLM Router's job)
  - Add retry logic (LiteLLM handles retries)

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: Schema extension is straightforward dataclass work
  - **Skills**: `["pytest"]`
    - `pytest`: For writing validation tests

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 2, 3)
  - **Blocks**: Tasks 2, 3
  - **Blocked By**: None

  **References**:
  - `src/ol_config/schema.py:1-50` - Current schema definitions
  - `config/default.yaml:1-20` - Current config structure

  **Acceptance Criteria**:
  - [ ] `poetry run pytest tests/test_model_pool_schema.py -v` → PASS
  - [ ] Config with 1 model per role → ValidationError raised
  - [ ] Config with valid api_key `${VAR}` where var exists → Passes

  **QA Scenarios**:

  \`\`\`
  Scenario: Valid config with 2 models per role passes validation
    Tool: Bash
    Preconditions: Valid YAML with OPENAI_API_KEY env var set
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && poetry run python -c "
import os
os.environ['OPENAI_API_KEY'] = 'test-key'
from src.ol_config.loader import load_config
config = load_config('config/default.yaml')
print(f'Roles: {[m.role for m in config.llm_pool.translation]}')
"
    Expected Result: Output shows 2 translation models, 2 judging models
    Failure Indicators: ValidationError, missing role field
    Evidence: .sisyphus/evidence/task-1-valid-config.{ext}

  Scenario: Config with only 1 model per role raises ValidationError
    Tool: Bash
    Preconditions: Invalid YAML with only 1 model
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && poetry run python -c "
import os
os.environ['OPENAI_API_KEY'] = 'test'
from src.ol_config.loader import load_config
try:
    config = load_config('config/invalid_one_model.yaml')
    print('ERROR: Should have raised ValidationError')
except Exception as e:
    print(f'Correctly raised: {type(e).__name__}')
"
    Expected Result: ValidationError with message about needing ≥2 models per role
    Failure Indicators: No error raised, or wrong error type
    Evidence: .sisyphus/evidence/task-1-invalid-config.{ext}
  \`\`\`

- [x] 2. **LiteLLM Router Integration**

  **What to do**:
  - Create `src/ol_pool/router.py`: LiteLLM Router wrapper class
  - Implement `ModelPool.translate()` using Router with model groups
  - Implement `ModelPool.judge()` using Router with model groups
  - Configure: `routing_strategy="simple-shuffle"`, `num_retries=1`, `timeout=3`
  - Write tests in `tests/test_model_pool_failover.py`

  **Must NOT do**:
  - Implement custom failover logic (use LiteLLM's built-in)
  - Use ThreadPoolExecutor (use asyncio)

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: LiteLLM Router API integration requires understanding of async patterns
  - **Skills**: `["pytest", "pytest-asyncio"]`
    - `pytest-asyncio`: For async test support

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1, 3)
  - **Blocks**: Tasks 4, 6, 7
  - **Blocked By**: Task 1

  **References**:
  - LiteLLM Router docs: `router_model_list` with `model_name` grouping
  - `src/ol_core/interfaces.py:40-80` - Current LLMRestorer interface
  - `.sisyphus/plans/phase-3a-routing-modelpool-concurrency.md` appendix - LiteLLM Router config example

  **Acceptance Criteria**:
  - [ ] `poetry run pytest tests/test_model_pool_failover.py -v` → PASS
  - [ ] Router routes to correct model group (translation/judging)
  - [ ] 429 error triggers automatic failover to backup model
  - [ ] Failover completes within 3 seconds

  **QA Scenarios**:

  \`\`\`
  Scenario: Router selects correct model group
    Tool: Bash
    Preconditions: LiteLLM API key in env, Router initialized
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && poetry run python -c "
from src.ol_pool.router import ModelPool
pool = ModelPool()
# Test routing
result = pool.route('translation')
print(f'Translation model: {result}')
"
    Expected Result: Output shows 'gpt-4-turbo' or 'claude-3-sonnet'
    Failure Indicators: Wrong model, exception
    Evidence: .sisyphus/evidence/task-2-route-group.{ext}

  Scenario: Failover on 429 error
    Tool: Bash (with mocked 429 response)
    Preconditions: Mock primary to return 429, backup to return success
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && poetry run python -c "
from unittest.mock import patch
from src.ol_pool.router import ModelPool

# Mock primary failure, backup success
def mock_primary(*args, **kwargs):
    raise Exception('429 Rate Limit')

with patch.object(ModelPool, '_call_litellm', side_effect=[mock_primary(), 'success']):
    pool = ModelPool()
    result = pool.translate('test text')
    print(f'Result: {result}, Fallback used: True')
"
    Expected Result: Result is 'success', fallback was used
    Failure Indicators: Exception not caught, no fallback
    Evidence: .sisyphus/evidence/task-2-failover.{ext}
  \`\`\`

- [x] 3. **Concurrency Scheduler Base**

  **What to do**:
  - Create `src/ol_concurrency/scheduler.py`: Semaphore-based concurrency
  - Implement `ConcurrencyLimiter` with max 10 translation, max 5 scoring slots
  - Implement queue-based waiting when limit reached
  - Implement `with_timeout()` context manager
  - Write tests in `tests/test_concurrent_engine.py`

  **Must NOT do**:
  - Use ThreadPoolExecutor (use asyncio.Semaphore)
  - Implement blocking queue (use asyncio.Queue)

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: asyncio concurrency patterns require careful handling
  - **Skills**: `["pytest", "pytest-asyncio"]`
    - `pytest-asyncio`: For async concurrency tests

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 1 (with Tasks 1, 2)
  - **Blocks**: Tasks 4, 7
  - **Blocked By**: Task 1

  **References**:
  - Python asyncio docs: Semaphore, Queue
  - `src/ol_core/exceptions.py` - Existing exception patterns

  **Acceptance Criteria**:
  - [ ] `poetry run pytest tests/test_concurrent_engine.py -v` → PASS
  - [ ] 11th translation request queues when 10 slots occupied
  - [ ] Queued request proceeds when slot frees
  - [ ] Timeout triggers after specified duration

  **QA Scenarios**:

  \`\`\`
  Scenario: 11th request queues when 10 slots occupied
    Tool: Bash
    Preconditions: ConcurrencyLimiter with max 10
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && poetry run python -c "
import asyncio
from src.ol_concurrency.scheduler import ConcurrencyLimiter

async def test():
    limiter = ConcurrencyLimiter(max_translation=2)  # Small for testing
    results = []
    
    async def task(i):
        async with limiter.translation():
            results.append(f'task-{i}')
            await asyncio.sleep(0.1)
    
    # Start 4 tasks (2 will run, 2 will queue)
    await asyncio.gather(*[task(i) for i in range(4)])
    return results

results = asyncio.run(test())
print(f'Completed: {results}')
"
    Expected Result: All 4 tasks complete (2 run, 2 queue)
    Failure Indicators: Tasks don't complete, deadlock
    Evidence: .sisyphus/evidence/task-3-concurrency.{ext}

  Scenario: Queue timeout
    Tool: Bash
    Preconditions: ConcurrencyLimiter with very low timeout
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && poetry run python -c "
import asyncio
from src.ol_concurrency.scheduler import ConcurrencyLimiter, QueueTimeoutError

async def test():
    limiter = ConcurrencyLimiter(max_translation=1)
    async with limiter.translation():
        # Inner task holds slot
        await asyncio.sleep(0.1)
    
    # Try to acquire with timeout=0
    try:
        async with limiter.translation(timeout=0):
            print('Should not reach here')
    except QueueTimeoutError:
        print('Correctly got QueueTimeoutError')

asyncio.run(test())
"
    Expected Result: QueueTimeoutError raised
    Failure Indicators: No error, or different error
    Evidence: .sisyphus/evidence/task-3-timeout.{ext}
  \`\`\`

### Wave 2 (After Wave 1)

- [x] 4. **Smart Routing Engine**

  **What to do**:
  - Extend `src/ol_buses/format_guard.py` to `src/ol_routing/router.py`
  - Implement `route_by_extension(path) -> ChannelType`
  - Handle edge cases: uppercase `.MD`, double extension `.md.txt`
  - Implement batch routing for multiple files
  - Write tests in `tests/test_routing.py`

  **Must NOT do**:
  - Implement content-based detection (extension only)
  - Return non-MD/XLIFF channel types

  **Recommended Agent Profile**:
  - **Category**: `quick`
    - Reason: Simple extension parsing logic
  - **Skills**: `["pytest"]`
    - `pytest`: For routing tests

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 5, 6, 7)
  - **Blocks**: Task 7
  - **Blocked By**: Tasks 2, 3

  **References**:
  - `src/ol_buses/format_guard.py` - Current format guard
  - `src/ol_core/dataclass.py:10-30` - ChannelType enum

  **Acceptance Criteria**:
  - [ ] `poetry run pytest tests/test_routing.py -v` → PASS
  - [ ] `.md` → MD, `.MD` (uppercase) → MD (normalized)
  - [ ] `.xliff` → XLIFF, `.xlf` → XLIFF
  - [ ] `.docx` → raises UnsupportedFormatError
  - [ ] `.md.txt` → raises UnsupportedFormatError (double ext)

  **QA Scenarios**:

  \`\`\`
  Scenario: Uppercase extension normalized to lowercase
    Tool: Bash
    Preconditions: None
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && poetry run python -c "
from src.ol_routing.router import route_by_extension
result = route_by_extension('/path/to/file.MD')
print(f'Result: {result.value}')
"
    Expected Result: 'md' output
    Failure Indicators: Error, wrong value
    Evidence: .sisyphus/evidence/task-4-uppercase.{ext}

  Scenario: Double extension rejected
    Tool: Bash
    Preconditions: None
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && poetry run python -c "
from src.ol_routing.router import route_by_extension
try:
    result = route_by_extension('/path/to/file.md.txt')
    print('ERROR: Should have raised')
except Exception as e:
    print(f'Correctly raised: {type(e).__name__}')
"
    Expected Result: UnsupportedFormatError
    Failure Indicators: No error or wrong error
    Evidence: .sisyphus/evidence/task-4-double-ext.{ext}
  \`\`\`

- [x] 5. **Checkpoint Foundation**

  **What to do**:
  - Create `src/ol_checkpoint/checkpoint.py`: CheckpointManager class
  - Implement atomic write: temp file + rename pattern
  - Implement file locking with `fcntl.flock`
  - Store: version, file_hash, processed_units, timestamp, tmx_path, config_snapshot
  - Implement hash verification on load
  - Write tests in `tests/test_checkpoint.py`

  **Must NOT do**:
  - Use SQLite (JSON only per spec)
  - Implement per-unit checkpoint (batch only)
  - Allow concurrent checkpoint writes (file lock)

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: Atomic file operations and locking require careful implementation
  - **Skills**: `["pytest"]`
    - `pytest`: For checkpoint tests

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 4, 6, 7)
  - **Blocks**: Task 7
  - **Blocked By**: Tasks 2, 3

  **References**:
  - `.sisyphus/plans/phase-3a-routing-modelpool-concurrency.md` appendix - Checkpoint structure

  **Acceptance Criteria**:
  - [ ] `poetry run pytest tests/test_checkpoint.py -v` → PASS
  - [ ] Checkpoint saves to JSON file atomically
  - [ ] Concurrent write attempt is serialized via lock
  - [ ] Hash mismatch on load raises error
  - [ ] Resume loads correct state

  **QA Scenarios**:

  \`\`\`
  Scenario: Atomic checkpoint save
    Tool: Bash
    Preconditions: Clean temp directory
    Steps:
      1. cd /tmp && mkdir -p ol_test && cd ol_test && poetry run python -c "
from src.ol_checkpoint.checkpoint import CheckpointManager
import json

cp = CheckpointManager('/tmp/ol_test/file.md.ol_checkpoint.json')
cp.save({
    'version': '1.0',
    'file_hash': 'abc123',
    'processed_units': ['u1', 'u2'],
    'total_units': 10,
    'completed_units': 2,
})
print('Checkpoint saved')
with open('/tmp/ol_test/file.md.ol_checkpoint.json') as f:
    print(f.read()[:100])
"
    Expected Result: Valid JSON with all fields
    Failure Indicators: Partial JSON, corruption
    Evidence: .sisyphus/evidence/task-5-atomic-save.{ext}

  Scenario: Concurrent write serialized
    Tool: Bash
    Preconditions: Checkpoint file exists
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && poetry run python -c "
import subprocess
result = subprocess.run([
    'poetry', 'run', 'python', '-c',
    '''
import time
from src.ol_checkpoint.checkpoint import CheckpointManager
cp = CheckpointManager(\"/tmp/test_concurrent.ol_checkpoint.json\")
cp.save({\"units\": list(range(100))})
print(\"Saved\")
'''
], capture_output=True, text=True)
print(result.stdout)
print(result.stderr if result.stderr else 'No error')
"
    Expected Result: Success output, no lock error
    Failure Indicators: Lock error, corruption
    Evidence: .sisyphus/evidence/task-5-concurrent.{ext}
  \`\`\`

- [x] 6. **LiteLLMRestorer Implementation**

  **What to do**:
  - Implement `src/ol_md/repair/level3.py`: LiteLLMRestorer real implementation
  - Implement `src/ol_xliff/repair/level3.py`: LiteLLMRestorer for XLIFF
  - Use prompt template from appendix
  - Call LiteLLM Router for restoration
  - Write tests in `tests/test_llm_restorer.py`

  **Must NOT do**:
  - Use multi-turn conversation
  - Implement custom fallback (use pool failover)
  - Call LLM without routing through ModelPool

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: LLM prompt engineering and integration
  - **Skills**: `["pytest", "pytest-asyncio"]`
    - `pytest-asyncio`: For async LLM calls

  **Parallelization**:
  - **Can Run In Parallel**: YES
  - **Parallel Group**: Wave 2 (with Tasks 4, 5, 7)
  - **Blocks**: Task 7
  - **Blocked By**: Task 2

  **References**:
  - `src/ol_core/interfaces.py:40-80` - LLMRestorer interface
  - `.sisyphus/plans/phase-3a-routing-modelpool-concurrency.md` appendix - Prompt template

  **Acceptance Criteria**:
  - [ ] `poetry run pytest tests/test_llm_restorer.py -v` → PASS
  - [ ] LiteLLMRestorer calls real LiteLLM API
  - [ ] Placeholders restored to correct positions
  - [ ] Timeout handled gracefully

  **QA Scenarios**:

  \`\`\`
  Scenario: Placeholder restoration with real LLM
    Tool: Bash (requires API key)
    Preconditions: OPENAI_API_KEY in env
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && poetry run python -c "
from src.ol_md.repair.level3 import LiteLLMRestorer

restorer = LiteLLMRestorer()
original = 'Hello {{_OL_TAG_abc_}} World'
translated = 'Hola Mundo'
shield_map = {'abc': '{{_OL_TAG_abc_}}'}

result = restorer.restore_placeholders(translated, original, shield_map)
print(f'Result: {result}')
"
    Expected Result: Text with placeholder in correct position
    Failure Indicators: Exception, placeholder not restored
    Evidence: .sisyphus/evidence/task-6-restorer.{ext}

  Scenario: Restore failure falls back to safe output
    Tool: Bash
    Preconditions: Mock LLM to fail
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && poetry run python -c "
from unittest.mock import patch
from src.ol_md.repair.level3 import LiteLLMRestorer

restorer = LiteLLMRestorer()

with patch.object(restorer, '_call_llm', side_effect=Exception('LLM Error')):
    result = restorer.restore_placeholders('translated', 'original', {})
    print(f'Fallback result: {result}')
"
    Expected Result: Returns original translated text (fallback)
    Failure Indicators: Exception propagates
    Evidence: .sisyphus/evidence/task-6-fallback.{ext}
  \`\`\`

- [x] 7. **Integration Tests**

  **What to do**:
  - Create `tests/test_integration_3a.py`: End-to-end integration tests
  - Test: routing → model pool → concurrency → checkpoint
  - Test: Full pipeline with mocked LLM calls
  - Write tests for error handling and recovery

  **Recommended Agent Profile**:
  - **Category**: `deep`
    - Reason: Integration testing across multiple components
  - **Skills**: `["pytest", "pytest-asyncio"]`
    - `pytest-asyncio`: For async integration tests

  **Parallelization**:
  - **Can Run In Parallel**: NO (depends on all other tasks)
  - **Blocked By**: Tasks 4, 5, 6

  **References**:
  - `tests/test_md_pipeline.py` - Phase 1 integration pattern
  - `tests/test_xliff_pipeline.py` - Phase 2 integration pattern

  **Acceptance Criteria**:
  - [ ] `poetry run pytest tests/test_integration_3a.py -v` → PASS
  - [ ] Full routing → pool → concurrency flow works
  - [ ] Checkpoint saves and loads correctly in pipeline
  - [ ] Error recovery works across components

  **QA Scenarios**:

  \`\`\`
  Scenario: Full pipeline with routing and model pool
    Tool: Bash
    Preconditions: Config with valid API keys
    Steps:
      1. cd /mnt/d/贯维/Omni_Localizer && poetry run python -c "
from src.ol_routing.router import route_by_extension
from src.ol_pool.router import ModelPool
from src.ol_concurrency.scheduler import ConcurrencyLimiter

channel = route_by_extension('/path/to/doc.md')
print(f'Channel: {channel}')

pool = ModelPool()
limiter = ConcurrencyLimiter(max_translation=10)

print(f'Pool initialized, limiter ready')
"
    Expected Result: All components initialize without error
    Failure Indicators: Import error, config error
    Evidence: .sisyphus/evidence/task-7-integration.{ext}
  \`\`\`

---

## Final Verification Wave

- [x] F1. **Plan Compliance Audit** — `oracle`
  Read the plan end-to-end. For each "Must Have": verify implementation exists. For each "Must NOT Have": search codebase for forbidden patterns — reject with file:line if found. Check evidence files exist.
  Output: `Must Have [5/5] | Must NOT Have [5/5] | Tasks [7/7] | VERDICT: APPROVE`

- [x] F2. **Code Quality Review** — `general`
  Run `poetry check` + linter + `poetry run pytest`. Review all changed files for: type errors, empty catches, console.log in prod.
  Output: `Syntax PASS | Empty Catches [0] | Console.log [0] | TODOs [0] | VERDICT: CLEAN`

- [x] F3. **Real Manual QA** — `general`
  Execute EVERY QA scenario from EVERY task — follow exact steps, capture evidence.
  Output: `Syntax PASS | Import Errors [0] | VERDICT: CLEAN`

- [x] F4. **Scope Fidelity Check** — `plan`
  For each task: read "What to do", read actual diff. Verify 1:1 — everything in spec was built, nothing beyond spec.
  Output: `Tasks [7/7 compliant] | Contamination [CLEAN] | VERDICT: APPROVE`

---

## Commit Strategy

**Wave 1**: `feat(pool): add model pool schema and liteLLM router integration`
- Files: `src/ol_pool/`, `src/ol_config/schema.py`

**Wave 2**: `feat(concurrency): add concurrency scheduler and routing engine`
- Files: `src/ol_concurrency/`, `src/ol_routing/`, `src/ol_checkpoint/`

**Final**: `feat(integration): add liteLLMRestorer and integration tests`
- Files: `src/ol_md/repair/level3.py`, `src/ol_xliff/repair/level3.py`, `tests/`

---

## Success Criteria

### Verification Commands
```bash
poetry run pytest tests/test_routing/ tests/test_model_pool/ tests/test_concurrency/ tests/test_checkpoint/ -v
```

### Final Checklist
- [ ] All "Must Have" present
- [ ] All "Must NOT Have" absent
- [ ] All tests pass
- [ ] LiteLLMRestorer calls real LiteLLM API (not mock)
- [ ] Model pool failover tested with mocked 429/5xx
- [ ] Concurrency limits enforced via semaphore
- [ ] Checkpoint atomic write with file locking

---

## Appendix: LiteLLMRestorer Prompt Template

```prompt
Restore these placeholders to their exact positions in the translation.

Original text with placeholders:
{original_text}

Current translation (placeholders may be missing or moved):
{translated_text}

Placeholders to restore:
{list(shield_map.values())}

Return the translation with all placeholders restored to their correct positions.
Only return the restored translation, nothing else.
```

## Appendix: Checkpoint File Structure

```json
{
  "version": "1.0",
  "file_hash": "sha256_of_source_file",
  "processed_units": ["unit_id_1", "unit_id_2", ...],
  "timestamp": "2026-05-15T10:30:00Z",
  "tmx_path": "./backup/tmx/",
  "config_snapshot": {...},
  "total_units": 10000,
  "completed_units": 5000
}
```

## Appendix: LiteLLM Router Configuration

**Model Group Pattern** (from research):
```python
from litellm import Router

router = Router(
    model_list=[
        # Translation models (primary + backup via same model_name)
        {
            "model_name": "translation",
            "litellm_params": {"model": "openai/gpt-4-turbo", "api_key": os.environ["OPENAI_API_KEY"]},
            "rpm": 500,
        },
        {
            "model_name": "translation",
            "litellm_params": {"model": "anthropic/claude-3-sonnet-20240229", "api_key": os.environ["ANTHROPIC_API_KEY"]},
            "rpm": 500,
        },
        # Judging models
        {
            "model_name": "judging",
            "litellm_params": {"model": "openai/gpt-4o-mini", "api_key": os.environ["OPENAI_API_KEY"]},
            "rpm": 1000,
        },
        {
            "model_name": "judging",
            "litellm_params": {"model": "deepseek/deepseek-chat", "api_key": os.environ["DEEPSEEK_API_KEY"]},
            "rpm": 1000,
        },
    ],
    routing_strategy="simple-shuffle",
    num_retries=1,        # Quick failover to backup
    timeout=3,             # 3-second failover
    retry_after=0,         # No wait on 429 - try next immediately
    allowed_fails=3,
    cooldown_time=60,
)
```

## Appendix: Sentence-Transformers Model for TM

**Recommended Model**: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`
- 384 dim, ~420MB, 7500 sentences/sec
- Supports 50+ languages
- 85% threshold is achievable with cosine similarity

```python
from sentence_transformers import SentenceTransformer

model = SentenceTransformer("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
embeddings = model.encode(["source text", "TM source text"])
similarities = model.similarity(embeddings, embeddings)
# similarities[0, 1] = cosine similarity score
```