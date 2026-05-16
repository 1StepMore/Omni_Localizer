import json
import tempfile
from pathlib import Path

import pytest

from ol_checkpoint.checkpoint import CheckpointManager, ResumeResult
from ol_checkpoint.exceptions import HashMismatchError


class TestResumeResult:
    def test_creation(self):
        r = ResumeResult(mode='force', fresh_start=True, recovered_units=0, warnings=[])
        assert r.mode == 'force'
        assert r.fresh_start is True
        assert r.recovered_units == 0


class TestCheckpointManagerResume:
    def test_resume_force_deletes_checkpoint(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ckpt_path = Path(tmpdir) / "checkpoint.json"
            ckpt_path.write_text(json.dumps({"processed_units": ["u1", "u2"]}))

            mgr = CheckpointManager(str(ckpt_path))
            result = mgr.resume('force')

            assert result.fresh_start is True
            assert result.mode == 'force'
            assert not ckpt_path.exists()

    def test_resume_force_nonexistent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ckpt_path = Path(tmpdir) / "nonexistent.json"
            mgr = CheckpointManager(str(ckpt_path))
            result = mgr.resume('force')

            assert result.fresh_start is True
            assert result.recovered_units == 0

    def test_resume_merge_recovered_count(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ckpt_path = Path(tmpdir) / "checkpoint.json"
            data = {"processed_units": ["u1", "u2", "u3"]}
            ckpt_path.write_text(json.dumps(data))

            mgr = CheckpointManager(str(ckpt_path))
            result = mgr.resume('merge')

            assert result.fresh_start is False
            assert result.recovered_units == 3
            assert result.mode == 'merge'

    def test_resume_merge_nonexistent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ckpt_path = Path(tmpdir) / "nonexistent.json"
            mgr = CheckpointManager(str(ckpt_path))
            result = mgr.resume('merge')

            assert result.fresh_start is False
            assert result.recovered_units == 0

    def test_resume_invalid_mode(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ckpt_path = Path(tmpdir) / "checkpoint.json"
            mgr = CheckpointManager(str(ckpt_path))

            with pytest.raises(ValueError, match="Invalid resume mode"):
                mgr.resume('invalid')


class TestCheckpointManagerHashMismatch:
    def test_hash_mismatch_raises_error(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            src_path = Path(tmpdir) / "source.txt"
            src_path.write_text("original content")

            ckpt_path = Path(tmpdir) / "checkpoint.json"
            ckpt_path.write_text(json.dumps({
                "processed_units": ["u1"],
                "file_hash": "different_hash"
            }))

            mgr = CheckpointManager(str(ckpt_path), source_path=str(src_path))
            with pytest.raises(HashMismatchError):
                mgr.load()


class TestCheckpointManagerGC:
    def test_gc_keeps_latest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ckpt_base = Path(tmpdir) / "checkpoint"
            for i in range(5):
                p = ckpt_base.with_suffix(f".v{i}.json")
                p.write_text(json.dumps({"v": i}))

            mgr = CheckpointManager(str(ckpt_base))
            mgr.gc(keep_latest=2)

            remaining = list(Path(tmpdir).glob("checkpoint*.json"))
            assert len(remaining) == 2

    def test_gc_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ckpt_path = Path(tmpdir) / "checkpoint.json"
            mgr = CheckpointManager(str(ckpt_path))
            mgr.gc(keep_latest=3)
            assert True

    def test_gc_preserves_lock_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            ckpt_base = Path(tmpdir) / "checkpoint"
            ckpt_path = ckpt_base.with_suffix(".json")
            ckpt_path.write_text(json.dumps({"units": []}))
            lock_path = ckpt_base.with_suffix(".lock")
            lock_path.write_text("")

            mgr = CheckpointManager(str(ckpt_base))
            mgr.gc(keep_latest=1)

            remaining = list(Path(tmpdir).glob("checkpoint*"))
            assert len(remaining) >= 1