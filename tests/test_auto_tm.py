"""Tests for Phase D4: auto-gen translation memory."""

import pytest

from ol_tm.auto_gen import (
    TMEntry,
    build_in_context_examples,
    find_similar,
    jaccard_similarity,
    load_tmx,
    save_tmx,
)


CORPUS = [
    TMEntry(source="Hello world", target="你好世界", lang_pair="en-zh"),
    TMEntry(source="Click the button to continue", target="点击按钮继续", lang_pair="en-zh"),
    TMEntry(source="The API endpoint is unavailable", target="API 端点不可用", lang_pair="en-zh"),
    TMEntry(source="Reset your password", target="重置您的密码", lang_pair="en-zh"),
    TMEntry(source="The application crashed", target="应用程序崩溃了", lang_pair="en-zh"),
]


class TestJaccard:
    def test_identical(self):
        assert jaccard_similarity("hello world", "hello world") == 1.0

    def test_no_overlap(self):
        assert jaccard_similarity("hello world", "foo bar") == 0.0

    def test_partial_overlap(self):
        sim = jaccard_similarity("hello world", "hello there")
        assert 0.0 < sim < 1.0

    def test_case_insensitive(self):
        assert jaccard_similarity("Hello World", "hello world") == 1.0

    def test_empty_returns_zero(self):
        assert jaccard_similarity("", "hello") == 0.0
        assert jaccard_similarity("hello", "") == 0.0


class TestFindSimilar:
    def test_top_k_returns_3(self):
        results = find_similar("Click the button", CORPUS, top_k=3, min_similarity=0.1)
        assert len(results) == 3
        assert results[0].source == "Click the button to continue"
        assert results[0].score > 0

    def test_min_similarity_filters(self):
        results = find_similar("xyz qrs", CORPUS, min_similarity=0.5)
        assert len(results) == 0

    def test_sorted_by_score(self):
        results = find_similar("button", CORPUS, top_k=5)
        scores = [r.score for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_empty_corpus(self):
        results = find_similar("anything", [], top_k=3)
        assert results == []

    def test_scores_populated(self):
        results = find_similar("hello", CORPUS, top_k=1)
        assert results[0].score > 0


class TestBuildExamples:
    def test_no_matches(self):
        assert build_in_context_examples([]) == ""

    def test_single_match(self):
        matches = [TMEntry(source="hi", target="你好", score=0.5)]
        result = build_in_context_examples(matches)
        assert "hi" in result
        assert "你好" in result
        assert "Translation Memory" in result

    def test_multiple_matches(self):
        matches = [
            TMEntry(source="a", target="A", score=0.9),
            TMEntry(source="b", target="B", score=0.8),
        ]
        result = build_in_context_examples(matches)
        assert "1. a -> A" in result
        assert "2. b -> B" in result


class TestSaveLoad:
    def test_round_trip(self, tmp_path):
        path = tmp_path / "tm.tsv"
        save_tmx(CORPUS, path)
        loaded = load_tmx(path)
        assert len(loaded) == len(CORPUS)
        assert loaded[0].source == CORPUS[0].source
        assert loaded[0].target == CORPUS[0].target
        assert loaded[0].lang_pair == CORPUS[0].lang_pair

    def test_load_missing_file(self, tmp_path):
        path = tmp_path / "nonexistent.tsv"
        assert load_tmx(path) == []

    def test_save_creates_parent_dirs(self, tmp_path):
        path = tmp_path / "subdir" / "tm.tsv"
        save_tmx(CORPUS[:1], path)
        assert path.exists()
