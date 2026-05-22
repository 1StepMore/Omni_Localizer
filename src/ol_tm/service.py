import logging
import sys
from dataclasses import dataclass
from pathlib import Path

_logger = logging.getLogger("tm")


def _acquire_lock(lock_path: Path) -> int:
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
    def __init__(
        self,
        tmx_path: str,
        embedding_model: str = "paraphrase-multilingual-MiniLM-L12-v2",
    ) -> None:
        self._tmx_path = Path(tmx_path)
        self._embedding_model = embedding_model
        self._model = None
        self._entries: list[TMMatch] = []
        self._load()

    def _get_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
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
        _acquire_lock(lock_path)
        try:
            tmx = hypomnema.TMXFile(self._tmx_path)
            for entry in self._entries:
                tmx.add_unit(entry.source, entry.target)
            tmx.write()
        finally:
            _release_lock(0, lock_path)

    def search(self, source_text: str, threshold: float = 0.85) -> list[TMMatch]:
        if not self._entries:
            return []
        model = self._get_model()
        source_emb = model.encode([source_text])[0]
        entries_emb = model.encode([e.source for e in self._entries])
        similarities = self._cosine_sim(source_emb, entries_emb)
        results = []
        for entry, sim in zip(self._entries, similarities):
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
        self._entries.append(TMMatch(
            source=source,
            target=target,
            similarity=1.0,
            language_pair=f"{src_lang}-{tgt_lang}",
        ))
        self._save()
