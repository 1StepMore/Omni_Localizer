import hashlib
import json
import os
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from ol_checkpoint.exceptions import HashMismatchError


@dataclass
class ResumeResult:
    mode: str
    fresh_start: bool
    recovered_units: int = 0
    warnings: list[str] = field(default_factory=list)


class CheckpointManager:
    def __init__(self, checkpoint_path: str, source_path: str | None = None):
        self._path = Path(checkpoint_path)
        self._source_path = Path(source_path) if source_path else None
        self._lock_path = self._path.with_suffix('.lock')

    def _compute_hash(self, file_path: Path) -> str:
        h = hashlib.sha256()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                h.update(chunk)
        return h.hexdigest()

    def _acquire_lock(self, exclusive: bool = True):
        lock_file = open(self._lock_path, 'w')
        if sys.platform == 'win32':
            import msvcrt
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        return lock_file

    def _release_lock(self, lock_file):
        if sys.platform == 'win32':
            import msvcrt
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        lock_file.close()

    def save(self, data: dict) -> None:
        lock = self._acquire_lock(exclusive=True)
        try:
            temp_fd, temp_path = tempfile.mkstemp(
                dir=self._path.parent,
                suffix='.tmp',
            )
            try:
                os.write(temp_fd, json.dumps(data, indent=2).encode('utf-8'))
                os.close(temp_fd)
                os.replace(temp_path, self._path)
            except Exception:
                os.unlink(temp_path)
                raise
        finally:
            self._release_lock(lock)

    def load(self) -> dict:
        if not self._path.exists():
            raise FileNotFoundError(f"Checkpoint not found: {self._path}")

        lock = self._acquire_lock(exclusive=False)
        try:
            with open(self._path, encoding='utf-8') as f:
                data = json.load(f)

            if self._source_path and self._source_path.exists():
                expected_hash = self._compute_hash(self._source_path)
                if 'file_hash' in data and data['file_hash'] != expected_hash:
                    raise HashMismatchError(
                        f"Hash mismatch: checkpoint={data['file_hash']}, "
                        f"source={expected_hash}",
                    )
        finally:
            self._release_lock(lock)

        return data

    def resume(
        self,
        mode: Literal['force', 'merge'],
    ) -> ResumeResult:
        if mode == 'force':
            if self._path.exists():
                self._path.unlink()
            return ResumeResult(mode='force', fresh_start=True, recovered_units=0, warnings=[])
        elif mode == 'merge':
            warnings: list[str] = []
            recovered = 0
            if self._path.exists():
                try:
                    existing = self.load()
                    recovered = len(existing.get('processed_units', []))
                except HashMismatchError as e:
                    raise HashMismatchError(
                        "Hash mismatch detected. Use --force to restart fresh or --merge to continue anyway.",
                    ) from e
            return ResumeResult(mode='merge', fresh_start=False, recovered_units=recovered, warnings=warnings)
        else:
            raise ValueError(f"Invalid resume mode: {mode}. Use 'force' or 'merge'.")

    def gc(self, keep_latest: int = 3) -> None:
        checkpoint_dir = self._path.parent
        if not checkpoint_dir.exists():
            return
        checkpoint_files = sorted(
            checkpoint_dir.glob(f"{self._path.stem}*"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for old_file in checkpoint_files[keep_latest:]:
            old_file.unlink()
