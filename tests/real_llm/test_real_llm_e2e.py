"""A11.4 — Real-LLM end-to-end tests (gated).

All tests in this file are gated by ``@pytest.mark.real_llm_required``,
which the ``conftest.py`` ``pytest_collection_modifyitems`` hook maps to
``pytest.mark.skipif(not os.environ.get("OMNI_RUN_REAL_LLM"))`` plus
``MINIMAX_API_KEY`` must be set (the conftest's ``real_model_pool``
fixture raises a clearer skip if the key is missing).

In normal CI (no env vars set), every test in this file SKIPS without
touching the LLM or spending any money. The nightly workflow
(``.github/workflows/real-llm-nightly.yml``) sets both env vars and runs
these tests against real MiniMax/M2.7.

Cost discipline:
- Each test uses the ``cost_estimator`` fixture (a fresh $5-budget
  CostEstimator) to estimate the call cost *before* issuing it. If the
  call would push cumulative spend over the budget, the test short-
  circuits with a clear skip rather than charging real money.
- The nightly runbook (docs/real_llm_runbook.md) documents the
  expected per-night spend (~$5/month = ~$0.15/night at 4 tests).

Sour: ol_pool.router.ModelPool.translate / judge.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# CJK Unified Ideographs (basic) + Extension A. Any character in these
# ranges means "this string is at least partially Chinese".
_CJK_RE = re.compile(
    r"[\u4e00-\u9fff"          # CJK Unified Ideographs
    r"\u3400-\u4dbf"           # CJK Unified Ideographs Extension A
    r"]"
)


def _has_chinese(text: str) -> bool:
    return bool(_CJK_RE.search(text or ""))


def _load_corpus_entry(corpus_dir: Path, name: str) -> dict:
    """Load a single entry from ``reference_outputs.json`` by corpus basename."""
    ref = corpus_dir / "reference_outputs.json"
    with ref.open(encoding="utf-8") as f:
        data = json.load(f)
    if name not in data:
        raise KeyError(
            f"Corpus entry {name!r} not found in {ref}. "
            f"Available: {sorted(k for k in data if not k.startswith('_'))}"
        )
    return data[name]


def _load_corpus_text(corpus_dir: Path, name: str) -> str:
    """Load a corpus .txt file (e.g. ``01_intro`` → ``01_intro.txt``)."""
    path = corpus_dir / f"{name}.txt"
    if not path.exists():
        raise FileNotFoundError(f"Corpus file missing: {path}")
    return path.read_text(encoding="utf-8").strip()


def _estimate_input_tokens(text: str) -> int:
    """Rough token count: 1 token per ~4 chars of source. Good enough for the gate.

    The real token count is whatever the LLM API reports; this is a
    conservative pre-call estimate so the budget gate has a margin.
    """
    return max(1, len(text) // 4)


def _estimate_output_tokens(source_text: str) -> int:
    """Rough output budget: assume translation is 1.2x the source length
    in tokens (CJK often expands, English contracts). Conservative.
    """
    return max(1, int(len(source_text) * 1.2) // 4)


# Pick the same model the nightly workflow resolves first: MiniMax-M2.7
# (priority 1 in config/local.yaml translation role).
_PRIMARY_MODEL = "MiniMax-M2.7"


# ===========================================================================
# A11.4 — 4 real-LLM E2E tests (all gated)
# ===========================================================================

@pytest.mark.real_llm_required
@pytest.mark.asyncio
async def test_real_translation_produces_chinese_for_english_input(
    real_model_pool, corpus_dir, cost_estimator,
) -> None:
    """Pin that the real LLM produces Chinese output for English input.

    Loads ``01_intro.txt`` from the corpus, calls ``pool.translate``
    en→zh, and asserts:
      1. The result contains at least one CJK Unified Ideograph
         (``U+4E00``–``U+9FFF``). An English-only or empty result is a
         regression — the LLM either refused, leaked source language,
         or returned an error string.
      2. The result is non-empty and not byte-identical to the source.
      3. The cost estimator's pre-call gate kept the run inside the $5
         budget — this is the cost discipline the runbook mandates.
    """
    source = _load_corpus_text(corpus_dir, "01_intro")
    assert source, "01_intro.txt is empty — corpus is broken"

    # Pre-call cost gate (cost_estimator from conftest, $5 budget)
    est = cost_estimator.estimate_call(
        _PRIMARY_MODEL,
        _estimate_input_tokens(source),
        _estimate_output_tokens(source),
    )
    if cost_estimator.would_exceed_budget(est):
        pytest.skip(
            f"Pre-call cost gate: cumulative ${cost_estimator.total_cost_usd:.4f} "
            f"+ candidate ${est:.4f} > budget ${cost_estimator.budget_usd}. "
            f"Aborting to prevent overrun. See docs/real_llm_runbook.md."
        )

    # Real LLM call
    translated = await real_model_pool.translate(
        source, source_lang="en", target_lang="zh",
    )
    cost_estimator.record_call(
        _PRIMARY_MODEL,
        _estimate_input_tokens(source),
        _estimate_output_tokens(source),
    )

    # 1. Result must be Chinese
    assert translated, "Translation returned empty string"
    assert translated != source, (
        f"Translation returned the source verbatim: {translated[:200]!r}"
    )
    assert _has_chinese(translated), (
        f"Translation result contains no CJK characters — the LLM likely "
        f"returned English or a placeholder. Got: {translated[:200]!r}"
    )

    # 2. Cost discipline: pre-call estimate + post-call record round-trip
    summary = cost_estimator.summary()
    assert summary["call_count"] == 1
    assert summary["total_cost"] > 0
    assert _PRIMARY_MODEL in summary["by_model"]


@pytest.mark.real_llm_required
@pytest.mark.asyncio
async def test_real_translation_preserves_brand_names(
    real_model_pool, corpus_dir, cost_estimator,
) -> None:
    """Pin that brand names survive translation verbatim.

    The corpus paragraph ``03_product.txt`` includes four brand-name
    tokens: "Microsoft Azure", "Apple" (within "Apple Push Notification
    service"), "Google Cloud", and "AS/400". Real LLMs occasionally
    translate brand names (a known failure mode). This test asserts
    that all four appear, verbatim, in the translated output.

    The corpus entry's ``min_quality_score`` (0.75) is elevated above
    the default 0.7 because this test asserts structural preservation
    in addition to fluency — a regression in brand handling should
    fail loud, not pass on a 0.71 quality score.
    """
    source = _load_corpus_text(corpus_dir, "03_product")
    ref = _load_corpus_entry(corpus_dir, "03_product")
    brand_names = ref.get("expected_keywords", [])
    assert brand_names, (
        "03_product reference_outputs.json must list expected brand names "
        "in expected_keywords; corpus drift?"
    )

    # Pre-call cost gate
    est = cost_estimator.estimate_call(
        _PRIMARY_MODEL,
        _estimate_input_tokens(source),
        _estimate_output_tokens(source),
    )
    if cost_estimator.would_exceed_budget(est):
        pytest.skip(
            f"Pre-call cost gate: cumulative ${cost_estimator.total_cost_usd:.4f} "
            f"+ candidate ${est:.4f} > budget ${cost_estimator.budget_usd}."
        )

    translated = await real_model_pool.translate(
        source, source_lang="en", target_lang="zh",
    )
    cost_estimator.record_call(
        _PRIMARY_MODEL,
        _estimate_input_tokens(source),
        _estimate_output_tokens(source),
    )

    # All brand names must appear in the translated output, case-sensitive.
    # A failure here usually means the LLM translated a brand name into
    # Chinese (e.g. "微软 Azure" instead of "Microsoft Azure"), which
    # breaks trademark and downstream TM matching.
    for brand in brand_names:
        assert brand in translated, (
            f"Brand name {brand!r} not preserved in translation. "
            f"Source: {source[:200]!r}\n"
            f"Translated: {translated[:300]!r}"
        )

    # Sanity: the translation must still be Chinese
    assert _has_chinese(translated), (
        f"Translation result has no CJK characters; brand test is meaningless. "
        f"Got: {translated[:200]!r}"
    )


@pytest.mark.real_llm_required
@pytest.mark.asyncio
async def test_real_lqa_score_above_threshold(
    real_model_pool, corpus_dir, cost_estimator,
) -> None:
    """Pin that the LLM judge's score meets the corpus's quality floor.

    Loads ``02_market.txt``, translates it, then calls
    ``pool.judge(source, target, "en", "zh")``. The corpus entry's
    ``min_quality_score`` is on a 0-1 scale; ``judge`` returns the
    ``score`` field on a 0-100 scale. The test scales the floor to
    match: ``score >= min_quality_score * 100``.

    A regression — LLM provider update, prompt-template change, model
    swap — typically surfaces as judge_score dropping below the floor.
    The 5% tolerance from the plan is intentionally NOT added here:
    the corpus is short and stable, and a hard threshold catches drift
    faster than a tolerance band.
    """
    source = _load_corpus_text(corpus_dir, "02_market")
    ref = _load_corpus_entry(corpus_dir, "02_market")
    min_quality_score = float(ref["min_quality_score"])
    score_floor_0_100 = min_quality_score * 100

    # Pre-call cost gate — covers both the translate() and judge() calls
    # (judge uses the same M2.7 priority chain in local.yaml).
    est_translate = cost_estimator.estimate_call(
        _PRIMARY_MODEL,
        _estimate_input_tokens(source),
        _estimate_output_tokens(source),
    )
    est_judge = cost_estimator.estimate_call(
        _PRIMARY_MODEL,
        _estimate_input_tokens(source) + 100,  # judge sees source + target
        200,  # judge returns a small JSON blob
    )
    if cost_estimator.would_exceed_budget(est_translate + est_judge):
        pytest.skip(
            f"Pre-call cost gate: cumulative ${cost_estimator.total_cost_usd:.4f} "
            f"+ estimated ${est_translate + est_judge:.4f} > budget ${cost_estimator.budget_usd}."
        )

    translated = await real_model_pool.translate(
        source, source_lang="en", target_lang="zh",
    )
    cost_estimator.record_call(
        _PRIMARY_MODEL,
        _estimate_input_tokens(source),
        _estimate_output_tokens(source),
    )

    # Translation must be Chinese — meaningless to judge an English result
    assert _has_chinese(translated), (
        f"Translation result has no CJK characters; judge would score 0. "
        f"Got: {translated[:200]!r}"
    )

    judge_result = await real_model_pool.judge(
        source=source, target=translated,
        source_lang="en", target_lang="zh",
    )
    cost_estimator.record_call(
        _PRIMARY_MODEL,
        _estimate_input_tokens(source) + 100,
        200,
    )

    # judge() shape: {"score": int 0-100, "accuracy", "fluency", "adequacy", ...}
    assert isinstance(judge_result, dict), (
        f"Judge returned non-dict: {type(judge_result).__name__}: {judge_result!r}"
    )
    assert "score" in judge_result, (
        f"Judge response missing 'score' field: {judge_result!r}"
    )
    score = judge_result["score"]
    assert isinstance(score, (int, float)), (
        f"Judge score is not numeric: {type(score).__name__}: {score!r}"
    )
    assert score >= score_floor_0_100, (
        f"Judge score {score} below floor {score_floor_0_100} "
        f"(corpus min_quality_score={min_quality_score}). "
        f"Full judge response: {judge_result!r}"
    )


@pytest.mark.real_llm_required
@pytest.mark.asyncio
async def test_real_e2e_translate_xliff_full_pipeline(
    real_model_pool, corpus_dir, cost_estimator,
) -> None:
    """Pin the full XLIFF pipeline end-to-end with a real LLM.

    Loads ``06_mini.xlf`` (a 2-trans-unit XLIFF), parses it, translates
    each trans-unit's source via the real ``ModelPool``, and writes
    the translations back into the XLIFF structure. Asserts:
      1. Both trans-units parse (2 units, with non-empty sources).
      2. Both translations are non-empty and contain CJK characters.
      3. The re-written XLIFF has the right structure: same number of
         ``<target>`` elements, no orphan or missing units.
      4. The cost gate kept the run inside budget.

    The test exercises: parse → translate (real LLM) → write. It does
    NOT exercise: restoration, judging, glossary injection, or TM
    lookup — those are covered by other A11.4 tests and by the
    non-real-LLM E2E suite in tests/test_e2e_xliff_pipeline.py.
    """
    # 1. Parse the corpus XLIFF
    from ol_xliff.parser import XliffParser  # noqa: PLC0415  (heavy import; gated test)

    xliff_path = corpus_dir / "06_mini.xlf"
    assert xliff_path.exists(), f"Corpus XLIFF missing: {xliff_path}"
    content = xliff_path.read_text(encoding="utf-8")

    parser = XliffParser()
    units = parser.parse_string(content)
    assert len(units) == 2, (
        f"06_mini.xlf should parse as 2 trans-units, got {len(units)}: {units!r}"
    )
    for u in units:
        assert u.source_text and u.source_text.strip(), (
            f"Trans-unit {u.unit_id!r} has empty source"
        )

    # Pre-call cost gate: 2 translation calls
    est_per_call = cost_estimator.estimate_call(
        _PRIMARY_MODEL,
        _estimate_input_tokens(units[0].source_text),
        _estimate_output_tokens(units[0].source_text),
    )
    if cost_estimator.would_exceed_budget(est_per_call * 2):
        pytest.skip(
            f"Pre-call cost gate: 2-call estimate ${est_per_call * 2:.4f} "
            f"would exceed budget ${cost_estimator.budget_usd}."
        )

    # 2. Translate each unit (real LLM)
    translated_units: list[tuple[str, str]] = []  # (unit_id, target)
    for unit in units:
        target = await real_model_pool.translate(
            unit.source_text, source_lang="en", target_lang="zh",
        )
        cost_estimator.record_call(
            _PRIMARY_MODEL,
            _estimate_input_tokens(unit.source_text),
            _estimate_output_tokens(unit.source_text),
        )
        translated_units.append((unit.unit_id, target))

    # 3. Assertions on translations
    assert len(translated_units) == 2
    for unit_id, target in translated_units:
        assert target, f"Trans-unit {unit_id!r}: translation is empty"
        assert _has_chinese(target), (
            f"Trans-unit {unit_id!r}: translation has no CJK. Got: {target[:200]!r}"
        )

    # 4. Write back into the XLIFF structure: simple string replace
    # (the test fixture has exactly 2 trans-units, so this is safe).
    out = content
    for unit_id, target in translated_units:
        # Find the <trans-unit id="...">...<source>...</source><target></target>...</trans-unit>
        # and inject the target text. We use a regex that tolerates either
        # an empty <target></target> or absent <target> (we add it).
        tu_pattern = re.compile(
            rf'(<trans-unit[^>]*id="{re.escape(unit_id)}"[^>]*>.*?<source[^>]*>.*?</source>)(.*?)(</trans-unit>)',
            re.DOTALL,
        )
        # Escape XML special chars in the target so the re-written XLIFF parses
        safe_target = (
            target
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
        replacement = (
            rf'\1<target>{safe_target}</target>\3'
        )
        new_out, n_replaced = tu_pattern.subn(replacement, out, count=1)
        assert n_replaced == 1, (
            f"Failed to inject target for trans-unit {unit_id!r} into XLIFF. "
            f"Source XLIFF: {content!r}"
        )
        out = new_out

    # 5. Final structural assertions on the rewritten XLIFF
    target_count = len(re.findall(r"<target[^>]*>[^<]+</target>", out))
    assert target_count == 2, (
        f"Rewritten XLIFF must have exactly 2 non-empty <target> elements, "
        f"got {target_count}. Output:\n{out}"
    )
    # XLIFF 1.2 root tag must still be present (structural integrity)
    assert "<xliff" in out and "</xliff>" in out, (
        f"Rewritten XLIFF lost its root <xliff> tag. Output:\n{out}"
    )
