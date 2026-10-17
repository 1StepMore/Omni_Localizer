"""Tests for Issue #130 — field-level JSON tolerance + one-shot repair.

Covers the pure helpers in ``ol_pool.json_tolerance`` and both real call
sites (``ModelPool.judge`` / ``ModelPool.profile``).  Fully deterministic:
the LLM is stubbed, no network access.
"""
from __future__ import annotations

import asyncio
import json
import os
from unittest.mock import MagicMock, patch

import pytest

from ol_pool.json_tolerance import (
    repair_json_once,
    repair_json_text,
    salvage_fields,
)
from ol_pool.router import ModelPool


@pytest.fixture(autouse=True)
def _force_real_path():
    """conftest sets OMNI_TEST_FAKE_LLM=1; these tests need the real code path."""
    old = os.environ.get("OMNI_TEST_FAKE_LLM")
    os.environ["OMNI_TEST_FAKE_LLM"] = "0"
    yield
    if old is None:
        os.environ.pop("OMNI_TEST_FAKE_LLM", None)
    else:
        os.environ["OMNI_TEST_FAKE_LLM"] = old


# ---------------------------------------------------------------------------
# repair_json_text — pure syntactic repair
# ---------------------------------------------------------------------------

class TestRepairJsonText:
    def test_bare_identifier_becomes_null(self):
        repaired = repair_json_text(
            '{"score": wiggle, "accuracy": 90, "fluency": 90, "adequacy": 90}'
        )
        assert json.loads(repaired) == {
            "score": None, "accuracy": 90, "fluency": 90, "adequacy": 90,
        }

    def test_trailing_comma(self):
        assert json.loads(repair_json_text('{"a": 1,}')) == {"a": 1}
        assert json.loads(repair_json_text('{"a": [1, 2,],}')) == {"a": [1, 2]}

    def test_single_quotes(self):
        assert json.loads(repair_json_text("{'a': 1, 'b': 'x'}")) == {"a": 1, "b": "x"}

    def test_code_fences(self):
        fenced = '```json\n{"a": 1}\n```'
        assert json.loads(repair_json_text(fenced)) == {"a": 1}

    def test_nan_and_infinity(self):
        assert json.loads(repair_json_text('{"a": NaN, "b": -Infinity}')) == {
            "a": None, "b": None,
        }

    def test_leading_plus_normalized(self):
        assert json.loads(repair_json_text('{"a": +5}')) == {"a": 5}

    def test_braces_inside_strings_survive(self):
        text = '{"a": "b: }], { ignore", "c": 1}'
        assert json.loads(repair_json_text(text)) == {"a": "b: }], { ignore", "c": 1}

    def test_apostrophe_inside_double_quoted_string_survives(self):
        text = '{"note": "it\'s fine, really"}'
        assert json.loads(repair_json_text(text)) == {"note": "it's fine, really"}

    def test_valid_json_is_unchanged_in_value(self):
        assert json.loads(repair_json_text('{"a": 1, "b": "x"}')) == {"a": 1, "b": "x"}


# ---------------------------------------------------------------------------
# salvage_fields — field-level tolerance
# ---------------------------------------------------------------------------

class TestSalvageFields:
    def test_percent_string_losslessly_converted_to_float(self):
        result, invalid = salvage_fields({"score": "90%"}, {"score": float})
        assert result == {"score": 90.0}
        assert invalid == []
        assert isinstance(result["score"], float)

    def test_numeric_int_is_preserved_not_widened(self):
        result, invalid = salvage_fields({"score": 90}, {"score": float})
        assert result == {"score": 90}
        assert isinstance(result["score"], int)
        assert invalid == []

    def test_unconvertible_value_nulled_and_reported(self):
        result, invalid = salvage_fields(
            {"score": "wiggle", "accuracy": 90},
            {"score": float, "accuracy": float},
        )
        assert result == {"score": None, "accuracy": 90}
        assert invalid == ["score"]

    def test_explicit_none_is_reported(self):
        result, invalid = salvage_fields({"score": None}, {"score": float})
        assert result["score"] is None
        assert invalid == ["score"]

    def test_bool_is_not_a_valid_number(self):
        _, invalid = salvage_fields({"score": True}, {"score": float})
        assert invalid == ["score"]

    def test_missing_field_is_left_absent(self):
        result, invalid = salvage_fields({"accuracy": 90}, {"score": float})
        assert "score" not in result
        assert invalid == []

    def test_does_not_mutate_input(self):
        payload = {"score": "wiggle"}
        salvage_fields(payload, {"score": float})
        assert payload == {"score": "wiggle"}


# ---------------------------------------------------------------------------
# repair_json_once — injected llm_call, exactly once
# ---------------------------------------------------------------------------

class TestRepairJsonOnce:
    def test_sync_stub_parses_repaired_json(self):
        calls: list[str] = []

        def _stub(prompt: str) -> str:
            calls.append(prompt)
            return '{"score": 88, "accuracy": 90}'

        result = asyncio.run(
            repair_json_once('{"score": wiggle}', ValueError("bad"), _stub)
        )
        assert result == {"score": 88, "accuracy": 90}
        assert len(calls) == 1
        assert "Broken output" in calls[0]

    def test_async_stub_is_awaited(self):
        calls: list[str] = []

        async def _stub(prompt: str) -> str:
            calls.append(prompt)
            return '```json\n{"score": 88}\n```'

        result = asyncio.run(
            repair_json_once('{"score": wiggle}', ValueError("bad"), _stub)
        )
        assert result == {"score": 88}
        assert len(calls) == 1

    def test_second_failure_raises(self):
        def _stub(prompt: str) -> str:
            return "still not json"

        with pytest.raises(json.JSONDecodeError):
            asyncio.run(
                repair_json_once('{"score": wiggle}', ValueError("bad"), _stub)
            )


# ---------------------------------------------------------------------------
# ModelPool.judge / profile integration (stubbed router)
# ---------------------------------------------------------------------------

def _make_pool(contents: list[str]):
    """Build a real-path ModelPool whose acompletion serves ``contents``.

    Each call pops the next content; the last one repeats.  ``calls`` records
    the messages passed to the router so callers can count LLM invocations.
    """
    calls: list[list[dict]] = []

    async def _mock_acompletion(*args, **kwargs):
        calls.append(kwargs.get("messages"))
        idx = min(len(calls) - 1, len(contents) - 1)
        content = contents[idx]
        return MagicMock(
            choices=[
                MagicMock(
                    message=MagicMock(content=content),
                    finish_reason="stop",
                )
            ]
        )

    with patch("ol_pool.router.load_config", return_value=(MagicMock(), None)), \
         patch("ol_pool.router.Router") as mock_router_cls:
        mock_router = MagicMock()
        mock_router.acompletion = _mock_acompletion
        mock_router_cls.return_value = mock_router
        pool = ModelPool(config_path="/nonexistent/config.yaml")

    pool._test_mode = False
    pool._cache_enabled = False
    return pool, calls


class TestJudgeJsonTolerance:
    def test_bad_field_triggers_exactly_one_repair(self):
        bad = '{"score": wiggle, "accuracy": 90, "fluency": 90, "adequacy": 90}'
        good = '{"score": 88, "accuracy": 90, "fluency": 90, "adequacy": 90}'
        pool, calls = _make_pool([bad, good])

        result = asyncio.run(pool.judge("src", "tgt", "en", "zh"))

        assert result["score"] == 88
        assert result["accuracy"] == 90
        assert result["fluency"] == 90
        assert result["adequacy"] == 90
        # 1 initial call + exactly 1 repair call
        assert len(calls) == 2

    def test_valid_json_fast_path_makes_no_repair(self):
        good = '{"accuracy": 85, "fluency": 90, "adequacy": 88, "score": 87}'
        pool, calls = _make_pool([good])

        result = asyncio.run(pool.judge("src", "tgt", "en", "zh"))

        assert result == {"accuracy": 85, "fluency": 90, "adequacy": 88, "score": 87}
        assert len(calls) == 1

    def test_two_bad_responses_fail_closed_with_invalid_fields(self):
        bad1 = '{"score": wiggle, "accuracy": 90, "fluency": 90, "adequacy": 90}'
        bad2 = '{"score": nope, "accuracy": 90, "fluency": 90, "adequacy": 90}'
        pool, calls = _make_pool([bad1, bad2])

        result = asyncio.run(pool.judge("src", "tgt", "en", "zh"))

        assert result["score"] == 0
        assert result["accuracy"] == 0
        assert result["fluency"] == 0
        assert result["adequacy"] == 0
        assert result["parse_failed"] is True
        assert "invalid_fields" in result
        assert "score" in result["invalid_fields"]
        # never more than one repair attempt
        assert len(calls) == 2

    def test_field_level_recovery_from_text_repair(self):
        # Text repair alone is enough here (no second LLM call required):
        # the only problem is a trailing comma / single quotes / fences.
        pool, calls = _make_pool(["```json\n{'accuracy': 80, 'fluency': 80, 'adequacy': 80, 'score': 80,}\n```"])

        result = asyncio.run(pool.judge("src", "tgt", "en", "zh"))

        assert result["score"] == 80
        assert len(calls) == 1


class TestProfileJsonTolerance:
    def test_profile_bad_then_repaired(self):
        pool, calls = _make_pool([
            "tone is formal, summary is x",
            '{"tone": "formal", "summary": "x"}',
        ])

        result = asyncio.run(pool.profile("some text", "en"))

        assert result["tone"] == "formal"
        assert len(calls) == 2

    def test_profile_text_repair_sufficient(self):
        # A single bare identifier is fixed by text repair alone — no second call.
        pool, calls = _make_pool(['{"tone": formal, "summary": "x"}'])

        result = asyncio.run(pool.profile("some text", "en"))

        assert result["tone"] is None
        assert result["summary"] == "x"
        assert len(calls) == 1

    def test_profile_total_failure_returns_raw_response(self):
        pool, calls = _make_pool(["this is not json at all", "still not json"])

        result = asyncio.run(pool.profile("some text", "en"))

        assert result == {"raw_response": "this is not json at all"}
        assert len(calls) == 2

    def test_profile_valid_fast_path(self):
        pool, calls = _make_pool(['{"tone": "formal", "register": "academic"}'])

        result = asyncio.run(pool.profile("some text", "en"))

        assert result == {"tone": "formal", "register": "academic"}
        assert len(calls) == 1
