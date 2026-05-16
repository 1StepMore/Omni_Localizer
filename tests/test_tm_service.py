import pytest
from ol_tm.service import TMService, TMMatch
from ol_core.dataclass import EvaluationResult


class TestTMMatch:
    def test_creation(self):
        m = TMMatch(source="hello", target="hola", similarity=0.95, language_pair="en-es")
        assert m.source == "hello"
        assert m.target == "hola"
        assert m.similarity == 0.95
        assert m.language_pair == "en-es"


class TestTMService:
    def test_init_default_model(self):
        svc = TMService("/tmp/test.tmx")
        assert svc._embedding_model == "paraphrase-multilingual-MiniLM-L12-v2"

    def test_init_custom_model(self):
        svc = TMService("/tmp/test.tmx", embedding_model="other-model")
        assert svc._embedding_model == "other-model"

    def test_add_entry(self):
        svc = TMService("/tmp/test_new.tmx")
        svc.add("hello", "hola", "en", "es")
        assert len(svc._entries) == 1
        assert svc._entries[0].source == "hello"
        assert svc._entries[0].target == "hola"

    def test_search_empty(self):
        svc = TMService("/tmp/test_empty.tmx")
        results = svc.search("hello", threshold=0.85)
        assert results == []

    def test_search_threshold(self):
        svc = TMService("/tmp/test_threshold.tmx")
        svc._entries = [
            TMMatch(source="hello", target="hola", similarity=0.90, language_pair="en-es"),
            TMMatch(source="world", target="mundo", similarity=0.80, language_pair="en-es"),
        ]
        results = svc.search("hello", threshold=0.85)
        assert len(results) == 1
        assert results[0].source == "hello"

    def test_search_sorted_by_similarity(self):
        svc = TMService("/tmp/test_sorted.tmx")
        svc._entries = [
            TMMatch(source="a", target="x", similarity=0.85, language_pair="en-es"),
            TMMatch(source="b", target="y", similarity=0.95, language_pair="en-es"),
            TMMatch(source="c", target="z", similarity=0.90, language_pair="en-es"),
        ]
        results = svc.search("test", threshold=0.80)
        assert len(results) == 3
        assert results[0].similarity == 0.95
        assert results[1].similarity == 0.90
        assert results[2].similarity == 0.85