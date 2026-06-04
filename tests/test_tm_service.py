from unittest.mock import MagicMock

import hypomnema

from ol_tm.service import TMMatch, TMService


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


class TestTMServiceFlush:
    """TDD RED phase: tests for the planned TMService dirty-flag + flush + context-manager API.

    These tests assert the new public API (flush, close, __enter__/__exit__) that
    will be implemented in T5. They MUST FAIL against the current TMService,
    which has no flush()/close()/context-manager support.
    """

    @staticmethod
    def _install_tmx_mock(monkeypatch) -> MagicMock:
        """Attach a MagicMock TMXFile class to the real `hypomnema` module.

        TMService._save() does `import hypomnema; tmx = hypomnema.TMXFile(path)`.
        Patching the module attribute (rather than the import site) is the
        correct "import boundary" mock per the task spec, and monkeypatch
        auto-reverts after the test.

        Returns the mock class. Each instantiation of `hypomnema.TMXFile(path)`
        returns `mock_class.return_value`, so call counts on
        `mock_class.return_value.write` reflect `_save()` invocations.
        """
        mock_class = MagicMock()
        # raising=False: the installed `hypomnema` package has no TMXFile attribute,
        # so we need to *create* it (not just replace an existing one).
        monkeypatch.setattr(hypomnema, "TMXFile", mock_class, raising=False)
        return mock_class

    def test_flush_method_exists(self, tmp_path):
        """TMService must expose a callable flush() method."""
        svc = TMService(str(tmp_path / "x.tmx"))
        assert hasattr(svc, "flush") and callable(svc.flush)

    def test_flush_persists_entries(self, tmp_path, monkeypatch):
        """flush() must persist pending entries via hypomnema.TMXFile.write()."""
        mock_tmx = self._install_tmx_mock(monkeypatch)

        svc = TMService(str(tmp_path / "x.tmx"))
        svc.add("a", "A", "en", "es")
        svc.flush()

        assert mock_tmx.return_value.write.call_count == 1

    def test_context_manager_flushes_on_exit(self, tmp_path, monkeypatch):
        """Exiting `with TMService(...) as svc:` must flush pending entries."""
        mock_tmx = self._install_tmx_mock(monkeypatch)

        with TMService(str(tmp_path / "x.tmx")) as svc:
            svc.add("a", "A", "en", "es")

        assert mock_tmx.return_value.write.call_count == 1

    def test_close_method_flushes(self, tmp_path, monkeypatch):
        """svc.close() must flush pending entries (errors logged, not raised)."""
        mock_tmx = self._install_tmx_mock(monkeypatch)

        svc = TMService(str(tmp_path / "x.tmx"))
        svc.add("a", "A", "en", "es")
        svc.close()

        assert mock_tmx.return_value.write.call_count == 1

    def test_backward_compat_existing_api(self, tmp_path, monkeypatch):
        """Public API (__init__, add, search) signatures and basic behavior are unchanged.

        Regression guard: this must PASS both now and after T5.
        """
        # Mock hypomnema so current code's add()-time _save() doesn't AttributeError
        # (the installed hypomnema package has no TMXFile attribute in this env).
        _ = self._install_tmx_mock(monkeypatch)

        # __init__ signature unchanged
        svc = TMService(str(tmp_path / "x.tmx"))
        assert svc._embedding_model == "paraphrase-multilingual-MiniLM-L12-v2"

        # search() on an empty service returns [] without loading the embedding model
        results = svc.search("test", threshold=0.85)
        assert results == []

        # add() signature unchanged: (source, target, src_lang, tgt_lang)
        svc.add("a", "A", "en", "es")
        assert len(svc._entries) == 1
        assert svc._entries[0].source == "a"
        assert svc._entries[0].target == "A"
        assert svc._entries[0].language_pair == "en-es"
