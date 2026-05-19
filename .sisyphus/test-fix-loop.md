# Omni-Localizer Skill Test-Fix Loop

## Purpose
Agent-facing verification loop for Omni-Localizer skill integration.

---

## PHASE 1: Discovery Verification

### 1.1 Verify OpenCode Skill
```
Bash: ls -la src/.opencode/skills/ol-localizer/SKILL.md
```
**Expected**: File exists
**If fail**: Create `src/.opencode/skills/ol-localizer/SKILL.md` with valid YAML frontmatter

### 1.2 Verify Hermes Skill
```
Bash: ls -la src/.hermes/skills/ol-localizer/SKILL.md
```
**Expected**: File exists
**If fail**: Create `src/.hermes/skills/ol-localizer/SKILL.md` with valid YAML frontmatter

---

## PHASE 2: Content Verification

### 2.1 Check OpenCode SKILL.md Sections
```
Grep: Procedure, Pitfalls, Verification in src/.opencode/skills/ol-localizer/SKILL.md
```
**Expected**: All three sections present
**If fail**: Add missing section to SKILL.md

### 2.2 Check Hermes SKILL.md Sections
```
Grep: Procedure, Pitfalls, Verification in src/.hermes/skills/ol-localizer/SKILL.md
```
**Expected**: All three sections present
**If fail**: Add missing section to SKILL.md

### 2.3 Validate YAML Frontmatter
```
Bash: python -c "import yaml; yaml.safe_load(open('src/.opencode/skills/ol-localizer/SKILL.md').read().split('---')[1])"
```
**Expected**: Parses without error, has `name` and `description`
**If fail**: Fix YAML frontmatter

---

## PHASE 3: CLI Verification

### 3.1 Test --json Flag Exists
```
Bash: python -m ol_cli translate-md --help 2>&1 | grep -i json
```
**Expected**: `--json` appears in help output
**If fail**: Add `--json` flag to `src/ol_cli.py`

### 3.2 Test JSON Error Output
```
Bash: python -m ol_cli translate-md nonexistent.md -o /tmp/out --json 2>/dev/null
```
**Expected**: Valid JSON with `success: false` and `error` field
**If fail**: Fix error handling in CLI to output JSON on error

### 3.3 Test JSON Success Output Structure
```
Bash: python -m ol_cli translate-md input.md -c config/default.yaml -s en -t zh -o /tmp/ --json 2>/dev/null | python -c "import sys,json; d=json.load(sys.stdin); print('OK' if 'success' in d and 'input_file' in d else 'FAIL')"
```
**Expected**: "OK"
**If fail**: Fix `output_json()` function

---

## PHASE 4: Test Suite Verification

### 4.1 Run OpenCode Skill Tests
```
Bash: pytest tests/test_opencode_skill.py -v --tb=short
```
**Expected**: All tests pass
**If fail**: Fix test or implementation per failure output

### 4.2 Run Hermes Skill Tests
```
Bash: pytest tests/test_hermes_skill.py -v --tb=short
```
**Expected**: All tests pass
**If fail**: Fix test or implementation per failure output

### 4.3 Run Invocation Tests
```
Bash: pytest tests/test_skill_invocation.py -v --tb=short
```
**Expected**: All tests pass
**If fail**: Fix test or implementation per failure output

---

## PHASE 5: Integration Verification

### 5.1 Full Translation Flow (if API keys available)
```
Bash: echo "# Test" > /tmp/test.md && python -m ol_cli translate-md /tmp/test.md -c config/default.yaml -s en -t zh -o /tmp/ --json
```
**Expected**: JSON success + translated file exists
**If fail**: Debug translation pipeline

### 5.2 Non-JSON Mode Unchanged
```
Bash: python -m ol_cli translate-md /tmp/test.md -c config/default.yaml -s en -t zh -o /tmp/ 2>&1 | head -1
```
**Expected**: Human-readable output (not JSON)
**If fail**: Ensure non-JSON mode outputs normally

---

## Agent Fix Protocol

When any test fails:

1. **Read the failing code**
   ```
   Read: <file_with_failure>
   ```

2. **Understand the error**
   - Syntax error? → Fix syntax
   - Logic error? → Trace through logic
   - Missing feature? → Implement missing part

3. **Fix the specific issue**
   ```
   Edit: <file_with_failure>
   OldString: <broken_code>
   NewString: <fixed_code>
   ```

4. **Verify fix**
   ```
   Bash: pytest tests/test_<failing_test>.py::test_<name> -v
   ```

5. **Re-run full test suite**
   ```
   Bash: pytest tests/test_opencode_skill.py tests/test_hermes_skill.py tests/test_skill_invocation.py -v
   ```

6. **Commit if all pass**
   ```
   Bash: git add -A && git commit -m "fix: <description>"
   ```

---

## Success Criteria

All phases pass = skill is agent-ready

| Phase | Checks | Must Pass |
|-------|---------|-----------|
| 1 | Skill files exist | ✅ |
| 2 | SKILL.md content valid | ✅ |
| 3 | CLI --json works | ✅ |
| 4 | All tests pass | ✅ |
| 5 | Integration works | ✅ (if keys available) |
