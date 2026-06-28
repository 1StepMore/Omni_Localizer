# Real-LLM Test Runbook

**Owner**: Omni-Localizer maintainers (`@1StepMore`).
**Audience**: on-call engineer, monthly cost reviewer, anyone rotating the API key.
**Last reviewed**: 2026-06-07 (PR14 merge — A11 of slim-pipeline-hardening).

This runbook covers the **real-LLM CI infrastructure** that lives in
`tests/real_llm/` and `.github/workflows/real-llm-nightly.yml`. The
harness is defensive: in normal CI it is a no-op (all 4 real-LLM tests
skip), and in nightly CI it is cost-gated at ~$5/month. Real LLM calls
require explicit user authorization for ongoing spend.

## What runs where

| Environment | Trigger | What happens |
|---|---|---|
| Normal CI (`.github/workflows/test.yml`) | every PR, every push to main | `OMNI_RUN_REAL_LLM` is unset → all 4 real-LLM tests SKIP. The 2 cost-estimator unit tests RUN (pure stdlib, no LLM). |
| Nightly workflow (`.github/workflows/real-llm-nightly.yml`) | weekly cron `0 2 * * 0` (Sundays 02:00 UTC) + manual dispatch | `OMNI_RUN_REAL_LLM=1` + `OPENCODE_GO_KEY` set → 4 real-LLM tests RUN against the real model pool. |
| Local dev (you) | `OMNI_RUN_REAL_LLM=1 OPENCODE_GO_KEY=… pytest tests/real_llm/ -v` | Same as nightly. Useful for reproducing a nightly failure. |

**Promote weekly → nightly** after 1 month of stable green runs (per
plan A11 risk register). The cadence change is a one-line edit in
`.github/workflows/real-llm-nightly.yml` (`cron: "0 2 * * 0"` →
`"0 2 * *"`). Do not promote on speculation; wait for evidence.

## Cost discipline

The harness has a **two-layer cost gate**:

1. **Per-test pre-call check** (`CostEstimator.would_exceed_budget`):
   each test estimates the next call's cost before issuing it; if the
   call would push the test's cumulative spend over the $5 budget, the
   test short-circuits with `pytest.skip`. The budget is per-test, not
   per-night — a single misbehaving test cannot starve the others.
2. **Hardcoded rates** in `cost_estimator._RATES_PER_1M_TOKENS`: the
   estimator does NOT read rates from the YAML config (a stale config
   must not silently mis-bill real LLM calls). Rates are recalibrated
   **quarterly** — see "Recalibration cadence" below.

Expected spend at 4 tests × ~$0.005/test ≈ **$0.02/night** (weekly
cadence) → **$0.08/month** for 4 weekly runs. The plan's $5-15/month
estimate is conservative and assumes the corpus grows; current spend
is well below the budget.

## API key rotation

**Cadence**: quarterly. The OpenCode Go API key (`OPENCODE_GO_KEY` GitHub
secret) must be rotated every 90 days. See the provider dashboard for
additional keys (Zhipu, Agnes, NVIDIA NIM) that may need rotation. Set a
calendar reminder when you rotate.

**Owner**: whoever has GitHub repo write access. As of 2026-06-07, the
sole owner is `@1StepMore`. When that changes, update this section
and the calendar reminder.

### How to rotate

1. Generate a new key in the provider's console:
   - OpenCode Go: provider dashboard → API keys → "Create new"
   - Repeat for any other providers in use (Zhipu, Agnes, NVIDIA NIM)
2. Update the GitHub secret:
   - Repo → Settings → Secrets and variables → Actions
   - `OPENCODE_GO_KEY` → "Update secret" → paste the new value
3. Trigger a manual nightly run to verify the new key works:
   ```bash
   gh workflow run "Real-LLM Nightly" --repo <org>/Omni_Localizer
   ```
4. Revoke the OLD key in the provider console (do this LAST — if you
   revoke first, a test run with a bad key costs nothing but creates
   noise on the dashboard).
5. Note the rotation date in the team's shared log so the next person
   knows when the keys were last rotated.

### Quarterly cron reminder

Set a recurring calendar event for the first Monday of each quarter
(Jan / Apr / Jul / Oct) at 10:00 local time. Title: **"Rotate
Omni-Localizer real-LLM API keys"**. Description: link to this
runbook.

If you skip a quarter, the worst case is the keys expire (MiniMax
keys are valid for 90 days; Baidu varies). A nightly failure is the
signal — see "When the nightly job fails" below.

## When the nightly job fails

1. **Open the failed run on GitHub Actions** → check the pytest log
   artifact (`real-llm-pytest-log`, retained 14 days).
2. **Classify the failure**:
   - **Test bug / corpus drift**: the assertion is too strict for the
     current model output. Fix the test or the corpus reference, push
     a patch, re-run.
   - **Provider degradation**: judge scores dropped, brand names
     mistranslated, output language leaked. This is exactly what the
     nightly is FOR. Open an issue, decide whether to roll back the
     provider or wait for the issue to clear.
   - **API key expired / auth error**: rotate the key (see above).
      If rotation doesn't fix it, check `secrets.OPENCODE_GO_KEY` is
      still set in repo settings.
   - **Cost overrun**: the pre-call gate should have prevented this.
     If it didn't, recalibrate the rates in `cost_estimator.py` (see
     "Recalibration cadence" below).
3. **If the failure is flaky** (passes on re-run without code change):
   the plan allows a 2-retry tolerance but we don't yet implement
   auto-retry in the suite. Re-run manually:
   ```bash
   gh workflow run "Real-LLM Nightly" --repo <org>/Omni_Localizer
   ```
   Track flaky runs in the team's issue tracker. After 3 flakies in
   30 days, treat as a real failure.

## Recalibration cadence

**Quarterly** (with the API key rotation). Update
`tests/real_llm/cost_estimator._RATES_PER_1M_TOKENS` to match the
provider's current list price:

- **glm-4-flash**: input $0.5/M, output $2/M tokens (as of 2026-06)
- **agnes-2.0-flash**: input $0.5/M, output $2/M tokens (as of 2026-06)
- **deepseek-v4-flash**: input $0.5/M, output $2/M tokens (as of 2026-06)

To recalibrate:

1. Check the provider's published rate card (MiniMax dashboard, Baidu
   Qianfan pricing page).
2. Update the tuple `(input_rate, output_rate)` in
   `_RATES_PER_1M_TOKENS`.
3. Re-run the cost-estimator unit tests to confirm the contract is
   pinned:
   ```bash
   pytest tests/real_llm/test_cost_estimator.py -v
   ```
4. Update the rates in the comment above if the providers changed.
5. Commit with message `chore(cost): recalibrate real-LLM rates for
   <quarter>`.

If a rate change is material (>20%), update the budget expectations
in this runbook too.

## Manual reproduction (debugging a nightly failure locally)

```bash
cd Omni_Localizer
export OMNI_RUN_REAL_LLM=1
export ZHIPU_API_KEY=…     # your own key
export AGNES_API_KEY=…     # your own key
export OPENCODE_GO_KEY=…   # your own key
export OPENCODE_GO_BASE_URL=…
export PYTHONPATH=src
pytest tests/real_llm/ -v --tb=long --durations=10
```

Expected output: 2 cost-estimator tests PASSED + 4 real-LLM tests
PASSED. If a real-LLM test fails, the pytest log will include the
LLM's actual response — useful for diagnosing provider degradation.

**Do not commit your real API key** to the repo. The `.env` file (if
you use one) is gitignored at the repo root, and GitHub secrets
(`${{ secrets.OPENCODE_GO_KEY }}`) are the only path the workflow
uses. See `.gitignore` for the full list.

## Adding a new real-LLM test

1. Add the test to `tests/real_llm/test_real_llm_e2e.py` (or a new
   file under `tests/real_llm/` if it's a different concern).
2. Decorate with `@pytest.mark.real_llm_required`. The conftest's
   `pytest_collection_modifyitems` hook applies the skipif — no
   per-test `@pytest.mark.skipif` needed.
3. Add the corpus input to `tests/fixtures/real_llm_corpus/` and
   register it in `reference_outputs.json` with `min_quality_score`
   and any `expected_keywords`.
4. Update the cost expectation in the runbook ("Expected spend").
5. Open a PR — the normal CI will verify the test correctly skips
   (2 cost tests pass, your new test skips).

## Reference

- **Plan**: `.omo/plans/slim-pipeline-hardening.md` section A11
  (lines 543-583 of the plan as of PR14).
- **Cost estimator code**: `tests/real_llm/cost_estimator.py`.
- **Conftest**: `tests/real_llm/conftest.py` — fixtures and marker
  → skipif wiring.
- **Workflow**: `.github/workflows/real-llm-nightly.yml`.
- **Provider pricing**: MiniMax dashboard, Baidu Qianfan pricing page
  (re-verify quarterly).
