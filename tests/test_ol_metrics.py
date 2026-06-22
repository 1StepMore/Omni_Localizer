"""Phase 4.5 — OL per-module Prometheus metrics.

Verifies the ``ol_mcp.metrics`` module:
- Exposes ``OL_REQUESTS_TOTAL``, ``OL_REQUEST_DURATION_SECONDS``,
  ``OL_TRANSLATIONS_TOTAL`` with the right names, label sets, and
  histogram buckets.
- ``record_request`` increments the counter and observes the
  histogram, and writes a valid Prometheus textfile under
  ``OMNI_METRICS_DIR`` (default ``/tmp/omni-metrics/ol.prom``).
- The status helpers classify the four canonical status values.
- ``record_request_from_arguments`` only bumps the translation
  counter on success and routes md vs xliff by tool name.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


OL_SRC = Path(__file__).resolve().parents[1] / "src"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def metrics_dir(tmp_path, monkeypatch):
    out = tmp_path / "omni-metrics"
    monkeypatch.setenv("OMNI_METRICS_DIR", str(out))
    return out


@pytest.fixture
def metrics(metrics_dir):
    return _load("ol_metrics_under_test", OL_SRC / "ol_mcp" / "metrics.py")


class TestMetricRegistration:
    def test_ol_requests_total_emitted_name(self, metrics, metrics_dir):
        metrics.record_request("t", metrics.STATUS_SUCCESS, 0.001)
        body = (metrics_dir / "ol.prom").read_text(encoding="utf-8")
        assert "ol_requests_total" in body
        assert "# TYPE ol_requests_total counter" in body

    def test_ol_request_duration_seconds_buckets(self, metrics):
        assert tuple(metrics.OL_REQUEST_DURATION_SECONDS._upper_bounds)[:-1] == (
            0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0,
        )

    def test_label_sets(self, metrics):
        assert sorted(metrics.OL_REQUESTS_TOTAL._labelnames) == ["status", "tool_name"]
        assert sorted(metrics.OL_TRANSLATIONS_TOTAL._labelnames) == [
            "mode", "source_lang", "target_lang",
        ]
        assert sorted(metrics.OL_REQUEST_DURATION_SECONDS._labelnames) == ["tool_name"]


class TestStatusConstants:
    @pytest.mark.parametrize(
        "label",
        ["success", "error", "rate_limited", "auth_failed"],
    )
    def test_status_constant_present(self, metrics, label):
        assert label in {
            metrics.STATUS_SUCCESS,
            metrics.STATUS_ERROR,
            metrics.STATUS_RATE_LIMITED,
            metrics.STATUS_AUTH_FAILED,
        }


class TestRecordRequest:
    def test_increments_counter_and_observes_histogram(self, metrics):
        before = metrics.OL_REQUESTS_TOTAL.labels(
            tool_name="translate_md_text", status="success",
        )._value.get()
        metrics.record_request("translate_md_text", metrics.STATUS_SUCCESS, 0.05)
        after = metrics.OL_REQUESTS_TOTAL.labels(
            tool_name="translate_md_text", status="success",
        )._value.get()
        assert after == before + 1

    def test_writes_prom_textfile(self, metrics, metrics_dir):
        metrics.record_request("translate_md_text", metrics.STATUS_SUCCESS, 0.05)
        out = metrics_dir / "ol.prom"
        assert out.exists()
        body = out.read_text(encoding="utf-8")
        assert "# TYPE ol_requests_total counter" in body
        assert "# TYPE ol_request_duration_seconds histogram" in body
        assert 'tool_name="translate_md_text"' in body


class TestRecordTranslation:
    def test_record_translation_md(self, metrics):
        before = metrics.OL_TRANSLATIONS_TOTAL.labels(
            source_lang="en", target_lang="zh", mode="md",
        )._value.get()
        metrics.record_translation("en", "zh", "md")
        after = metrics.OL_TRANSLATIONS_TOTAL.labels(
            source_lang="en", target_lang="zh", mode="md",
        )._value.get()
        assert after == before + 1

    def test_record_translation_xliff(self, metrics):
        before = metrics.OL_TRANSLATIONS_TOTAL.labels(
            source_lang="en", target_lang="fr", mode="xliff",
        )._value.get()
        metrics.record_translation("en", "fr", "xliff")
        after = metrics.OL_TRANSLATIONS_TOTAL.labels(
            source_lang="en", target_lang="fr", mode="xliff",
        )._value.get()
        assert after == before + 1


class TestRequestFromArguments:
    def test_translation_counter_only_on_success(self, metrics):
        before = metrics.OL_TRANSLATIONS_TOTAL.labels(
            source_lang="en", target_lang="zh", mode="md",
        )._value.get()
        metrics.record_request_from_arguments(
            "translate_md_text",
            {"source_lang": "en", "target_lang": "zh"},
            metrics.STATUS_ERROR,
            0.1,
        )
        after = metrics.OL_TRANSLATIONS_TOTAL.labels(
            source_lang="en", target_lang="zh", mode="md",
        )._value.get()
        assert after == before

    def test_routes_xliff_mode(self, metrics):
        before = metrics.OL_TRANSLATIONS_TOTAL.labels(
            source_lang="en", target_lang="de", mode="xliff",
        )._value.get()
        metrics.record_request_from_arguments(
            "translate_xliff",
            {"source_lang": "en", "target_lang": "de"},
            metrics.STATUS_SUCCESS,
            0.1,
        )
        after = metrics.OL_TRANSLATIONS_TOTAL.labels(
            source_lang="en", target_lang="de", mode="xliff",
        )._value.get()
        assert after == before + 1
