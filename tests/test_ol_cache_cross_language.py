"""OL#8: Cross-language cache collision regression tests.

Verifies that translating the same input to two different target languages
produces different cache keys (and thus different cached outputs) across
all three caching layers:
  1. CLI file cache (_cache_key in ol_cli.py)
  2. LLM prompt cache (_make_cache_key in ol_pool/router.py)
  3. TM search language filter (TMService.search in ol_tm/service.py)
"""
from pathlib import Path

import pytest

from ol_tm.service import TMMatch, TMService


class TestCLICacheKeyLanguageAwareness:
    """_cache_key must include src_lang/tgt_lang so same-input
    different-language translations get different cache keys."""

    def test_cache_key_differs_by_tgt_lang(self, tmp_path):
        """Same input + same flags + different tgt_lang => different keys."""
        from ol_cli import _cache_key

        input_file = tmp_path / "test.md"
        input_file.write_text("# Hello\n\nWorld.\n")

        key_zh = _cache_key(input_file, None, src_lang="en", tgt_lang="zh")
        key_fr = _cache_key(input_file, None, src_lang="en", tgt_lang="fr")
        key_de = _cache_key(input_file, None, src_lang="en", tgt_lang="de")

        assert key_zh != key_fr, "en→zh and en→fr must produce different cache keys"
        assert key_zh != key_de, "en→zh and en→de must produce different cache keys"
        assert key_fr != key_de, "en→fr and en→de must produce different cache keys"

    def test_cache_key_differs_by_src_lang(self, tmp_path):
        """Same input + different src_lang => different keys."""
        from ol_cli import _cache_key

        input_file = tmp_path / "test.md"
        input_file.write_text("# Hello\n\nWorld.\n")

        key_en_zh = _cache_key(input_file, None, src_lang="en", tgt_lang="zh")
        key_fr_zh = _cache_key(input_file, None, src_lang="fr", tgt_lang="zh")

        assert key_en_zh != key_fr_zh

    def test_cache_key_same_when_langs_match(self, tmp_path):
        """Same input + same langs => same key (deterministic)."""
        from ol_cli import _cache_key

        input_file = tmp_path / "test.md"
        input_file.write_text("# Hello\n\nWorld.\n")

        key1 = _cache_key(input_file, None, src_lang="en", tgt_lang="zh")
        key2 = _cache_key(input_file, None, src_lang="en", tgt_lang="zh")

        assert key1 == key2


class TestPromptCacheKeyLanguageAwareness:
    """_make_cache_key must include source_lang/target_lang as explicit
    key dimensions so prompt cache does not cross language boundaries."""

    def test_cache_key_includes_language_pair(self):
        """Same messages + different language pairs => different cache keys."""
        from ol_pool.router import ModelPool

        pool = ModelPool.__new__(ModelPool)
        messages = [
            {"role": "system", "content": "Translate."},
            {"role": "user", "content": "Hello"},
        ]

        key_zh = pool._make_cache_key("translation", messages, 0.0, source_lang="en", target_lang="zh")
        key_fr = pool._make_cache_key("translation", messages, 0.0, source_lang="en", target_lang="fr")

        assert key_zh != key_fr, (
            "Same prompt with different target languages must produce different cache keys"
        )

    def test_cache_key_same_when_languages_match(self):
        """Same messages + same language pair => same key (deterministic)."""
        from ol_pool.router import ModelPool

        pool = ModelPool.__new__(ModelPool)
        messages = [
            {"role": "system", "content": "Translate."},
            {"role": "user", "content": "Hello"},
        ]

        key1 = pool._make_cache_key("translation", messages, 0.0, source_lang="en", target_lang="zh")
        key2 = pool._make_cache_key("translation", messages, 0.0, source_lang="en", target_lang="zh")

        assert key1 == key2

    def test_judge_cache_key_includes_language_pair(self):
        """Judge path also includes language pair in cache key."""
        from ol_pool.router import ModelPool

        pool = ModelPool.__new__(ModelPool)
        messages = [
            {"role": "system", "content": "Evaluate."},
            {"role": "user", "content": "Score this."},
        ]

        key_zh = pool._make_cache_key("judging", messages, 0.0, source_lang="en", target_lang="zh")
        key_fr = pool._make_cache_key("judging", messages, 0.0, source_lang="en", target_lang="fr")

        assert key_zh != key_fr


class TestTMSearchLanguageFilter:
    """TMService.search must filter by language pair so entries from
    one language pair don't leak into another pair's results."""

    def test_search_returns_only_matching_pair(self):
        """en→zh entries must NOT appear in en→fr search results."""
        svc = TMService("/tmp/test_cross_lang.tmx")
        svc._entries = [
            TMMatch(source="hello", target="你好", similarity=0.95, language_pair="en-zh"),
            TMMatch(source="hello", target="bonjour", similarity=0.93, language_pair="en-fr"),
        ]

        results_zh = svc.search("hello", threshold=0.85, src_lang="en", tgt_lang="zh")
        results_fr = svc.search("hello", threshold=0.85, src_lang="en", tgt_lang="fr")

        assert len(results_zh) == 1
        assert results_zh[0].language_pair == "en-zh"
        assert results_zh[0].target == "你好"

        assert len(results_fr) == 1
        assert results_fr[0].language_pair == "en-fr"
        assert results_fr[0].target == "bonjour"

    def test_search_unknown_pair_returns_empty(self):
        svc = TMService("/tmp/test_cross_lang_unknown.tmx")
        svc._entries = [
            TMMatch(source="hello", target="你好", similarity=0.95, language_pair="en-zh"),
        ]

        results = svc.search("hello", threshold=0.85, src_lang="en", tgt_lang="de")
        assert results == []
