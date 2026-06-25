from contextlib import contextmanager
from pathlib import Path

import logging
import sys
import threading
import weakref
from dataclasses import dataclass

_logger = logging.getLogger("tm")


def _ensure_hypomnema_tmxfile() -> None:
    """Install ``ol_tm._py_tmx.TMXFile`` as ``hypomnema.TMXFile`` if missing.

    ``hypomnema`` 0.8 is a typed domain-model library with no ``TMXFile``
    class. :class:`TMService` was written against the legacy
    ``TMXFile(path)`` / ``unit_iterator()`` / ``add_unit()`` / ``write()``
    API, so we register a pure-Python stub at import time to keep those
    call sites unchanged. Idempotent; safe under ``monkeypatch``.
    """
    import hypomnema
    if not hasattr(hypomnema, "TMXFile"):
        from ol_tm import _py_tmx
        hypomnema.TMXFile = _py_tmx.TMXFile


_ensure_hypomnema_tmxfile()


def _safe_flush_on_gc(svc: "TMService") -> None:
    """GC-time finalizer for :class:`TMService` instances.

    Registered via :func:`weakref.finalize` in ``TMService.__init__``. Runs
    at garbage collection time (not at interpreter shutdown) and is the
    modern, recommended replacement for ``__del__`` for cleanup that must
    not raise. Catches and logs every exception so that this callback can
    never propagate — finalize callbacks are explicitly allowed to swallow
    errors, and during interpreter teardown modules/file handles may
    already be gone.
    """
    try:
        svc.close()
    except Exception:
        _logger.exception("TMService GC finalizer: flush failed")


@contextmanager
def _file_lock(lock_path: Path, exclusive: bool = True):
    """Context manager for file locking.

    Acquires lock on enter, releases on exit.
    Works on both POSIX and Windows.

    Args:
        lock_path: Path to lock file
        exclusive: True for write lock, False for read lock

    Yields:
        The lock file object (for reference, not needed for unlock)
    """
    if sys.platform == 'win32':
        import msvcrt
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_file = open(lock_path, 'w')
        try:
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK if exclusive else msvcrt.LK_RLCK, 1)
            yield lock_file
        finally:
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            lock_file.close()
    else:
        import fcntl
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_file = open(lock_path, 'w')
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
            yield lock_file
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            lock_file.close()


def _acquire_lock(lock_path: Path) -> int:
    """Deprecated: Use _file_lock context manager instead."""
    if sys.platform == 'win32':
        import msvcrt
        lock_file = open(lock_path, 'w')
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
    else:
        import fcntl
        lock_file = open(lock_path, 'w')
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
    return id(lock_file)


def _release_lock(lock_file_id: int, lock_path: Path) -> None:
    """Deprecated: Use _file_lock context manager instead."""
    if sys.platform == 'win32':
        import msvcrt
        lock_file = open(lock_path, 'w')
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        lock_file.close()
    else:
        import fcntl
        lock_file = open(lock_path, 'w')
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        lock_file.close()


@dataclass
class TMMatch:
    source: str
    target: str
    similarity: float
    language_pair: str


class TMService:
    """Translation memory service with deferred writes and explicit flush.

    Entries added via :meth:`add` are kept in memory and marked dirty. They
    are persisted to the TMX file only when :meth:`flush` is called, or
    implicitly via :meth:`close`, the context-manager protocol
    (``with TMService(...) as svc:``), or the GC-time finalizer registered
    in :meth:`__init__`.

    Durability trade-off: if the process is hard-killed (SIGKILL, power
    loss, OOM) between :meth:`add` and the next :meth:`flush`, in-memory
    entries since the last successful save are lost. For crash-safe
    operation, either use the context manager, call :meth:`flush` at known
    checkpoints, or call :meth:`close` before shutdown.
    """

    def __init__(
        self,
        tmx_path: str,
        embedding_model: str = "paraphrase-multilingual-MiniLM-L12-v2",
    ) -> None:
        self._tmx_path = Path(tmx_path)
        self._embedding_model = embedding_model
        self._model = None
        self._entries: list[TMMatch] = []
        self._dirty: bool = False
        self._pending_writes: int = 0
        self._lock = threading.RLock()
        weakref.finalize(self, _safe_flush_on_gc, self)
        self._load()

    def _get_model(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError:
                raise ImportError(
                    "sentence-transformers not available. "
                    "Install ML deps: pip install omni-localizer[ml]"
                )
            self._model = SentenceTransformer(self._embedding_model)
        return self._model

    def _load(self) -> None:
        if not self._tmx_path.exists():
            return
        try:
            import hypomnema
            tmx = hypomnema.TMXFile(self._tmx_path)
            for tu in tmx.unit_iterator():
                src = tu.get_source_segment()
                tgt = tu.get_target_segment()
                if src and tgt:
                    self._entries.append(TMMatch(
                        source=src,
                        target=tgt,
                        similarity=1.0,
                        language_pair=f"{tmx.source_lang}-{tmx.target_lang}",
                    ))
        except Exception as e:
            _logger.warning(f"Failed to load TM entries from {self._tmx_path}: {e}")

    def _save(self) -> None:
        import hypomnema
        lock_path = self._tmx_path.with_suffix('.lock')
        with _file_lock(lock_path, exclusive=True):
            tmx = hypomnema.TMXFile(self._tmx_path)
            # add_unit() takes (source, target) only; languages must be
            # set on the file instance for <tuv xml:lang="..."> to round-trip.
            if self._entries and "-" in self._entries[0].language_pair:
                src, tgt = self._entries[0].language_pair.split("-", 1)
                tmx.source_lang = src
                tmx.target_lang = tgt
            for entry in self._entries:
                tmx.add_unit(entry.source, entry.target)
            tmx.write()

    def search(self, source_text: str, threshold: float = 0.85, *, src_lang: str, tgt_lang: str) -> list[TMMatch]:
        """Search for similar translations, filtered by language pair.

        Args:
            source_text: The text to search for.
            threshold: Minimum similarity score (0-1).
            src_lang: Source language code (required, OL#8).
            tgt_lang: Target language code (required, OL#8).

        Returns:
            List of matching TMMatch objects, sorted by similarity descending.
        """
        if not self._entries:
            return []
        lang_pair = f"{src_lang}-{tgt_lang}"
        entries = [e for e in self._entries if e.language_pair == lang_pair]
        if not entries:
            return []
        model = self._get_model()
        source_emb = model.encode([source_text])[0]
        entries_emb = model.encode([e.source for e in entries])
        similarities = self._cosine_sim(source_emb, entries_emb)
        results = []
        for entry, sim in zip(entries, similarities):
            if sim >= threshold:
                results.append(TMMatch(
                    source=entry.source,
                    target=entry.target,
                    similarity=float(sim),
                    language_pair=entry.language_pair,
                ))
        return sorted(results, key=lambda x: x.similarity, reverse=True)

    def _cosine_sim(self, source_emb, target_embs) -> list[float]:
        import numpy as np
        source_norm = np.linalg.norm(source_emb)
        target_norms = np.linalg.norm(target_embs, axis=1)
        dots = np.dot(target_embs, source_emb)
        return (dots / (source_norm * target_norms)).tolist()

    def add(self, source: str, target: str, src_lang: str, tgt_lang: str) -> None:
        with self._lock:
            self._entries.append(TMMatch(
                source=source,
                target=target,
                similarity=1.0,
                language_pair=f"{src_lang}-{tgt_lang}",
            ))
            self._dirty = True
            self._pending_writes += 1

    def flush(self) -> None:
        """Persist pending in-memory entries to the TMX file.

        No-op if no entries have been added since the last successful
        flush. Safe to call concurrently with :meth:`add`; serialization
        is handled by the instance's re-entrant lock.
        """
        with self._lock:
            self._flush_locked()

    def _flush_locked(self) -> None:
        if not self._dirty:
            return
        self._save()
        self._dirty = False
        self._pending_writes = 0

    def close(self) -> None:
        """Best-effort flush for shutdown. Errors are logged, not raised.

        Designed for use as the last action before a process exits
        (explicitly, via the context-manager ``__exit__``, or via the
        GC-time finalizer). Any failure during the underlying
        :meth:`flush` is captured with a full traceback via
        :func:`logging.exception` and swallowed — durability is best
        effort here, so callers cannot be left with a partially-flushed
        state or a raised exception they cannot handle during teardown.
        """
        try:
            self.flush()
        except Exception:
            _logger.exception("TMService.close(): flush failed; pending writes may be lost")

    def __enter__(self) -> "TMService":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
        return None
