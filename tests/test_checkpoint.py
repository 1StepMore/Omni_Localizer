import os
import tempfile
from pathlib import Path

import pytest

from ol_checkpoint import CheckpointManager, HashMismatchError


class TestCheckpointManager:
    def setup_method(self):
        self.temp_dir = tempfile.mkdtemp()
        self.checkpoint_path = os.path.join(self.temp_dir, "checkpoint.json")
        self.source_path = os.path.join(self.temp_dir, "source.txt")

        with open(self.source_path, 'w') as f:
            f.write("test content for hashing")

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_save_and_load(self):
        manager = CheckpointManager(self.checkpoint_path, self.source_path)
        data = {
            "version": "1.0",
            "processed_units": ["unit1", "unit2"],
            "total_units": 100,
            "completed_units": 50
        }
        manager.save(data)
        loaded = manager.load()
        assert loaded["version"] == "1.0"
        assert loaded["processed_units"] == ["unit1", "unit2"]
        assert loaded["total_units"] == 100

    def test_load_nonexistent_raises(self):
        manager = CheckpointManager("/nonexistent/path.json")
        with pytest.raises(FileNotFoundError):
            manager.load()

    def test_hash_mismatch_raises(self):
        manager = CheckpointManager(self.checkpoint_path, self.source_path)
        data = {
            "version": "1.0",
            "file_hash": "wrong_hash_value",
            "processed_units": []
        }
        manager.save(data)
        with pytest.raises(HashMismatchError):
            manager.load()

    def test_resume_force_mode(self):
        manager = CheckpointManager(self.checkpoint_path)
        result = manager.resume("force")
        assert result.fresh_start == True
        assert result.mode == "force"

    def test_resume_force_without_data(self):
        manager = CheckpointManager(self.checkpoint_path)
        result = manager.resume("force")
        assert result.fresh_start == True

    def test_resume_merge_mode(self):
        manager = CheckpointManager(self.checkpoint_path)
        existing_data = {
            "version": "1.0",
            "processed_units": ["unit1", "unit2"]
        }
        manager.save(existing_data)
        result = manager.resume("merge")
        assert result.fresh_start == False
        assert result.mode == "merge"

    def test_resume_invalid_mode_raises(self):
        manager = CheckpointManager(self.checkpoint_path)
        with pytest.raises(ValueError):
            manager.resume("invalid")

    def test_resume_merge_without_data_raises(self):
        manager = CheckpointManager(self.checkpoint_path)
        with pytest.raises(FileNotFoundError):
            manager.resume("merge")

    def test_lock_file_created(self):
        manager = CheckpointManager(self.checkpoint_path)
        data = {"version": "1.0", "processed_units": []}
        manager.save(data)
        assert os.path.exists(self.checkpoint_path + ".lock")

    def test_atomic_write(self):
        manager = CheckpointManager(self.checkpoint_path)
        data = {"version": "1.0", "processed_units": list(range(100))}
        manager.save(data)
        assert os.path.exists(self.checkpoint_path)
        loaded = manager.load()
        assert len(loaded["processed_units"]) == 100


class TestHashMismatchError:
    def test_exception_message(self):
        error = HashMismatchError("hash mismatch")
        assert str(error) == "hash mismatch"

    def test_exception_inherits_from_base(self):
        from ol_core.exceptions import OLBaseError
        assert issubclass(HashMismatchError, OLBaseError)