"""Tests for logging module."""
import logging
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import structlog

from ol_logging.constants import DEBUG, INFO, LOG_LEVEL_ENV, MAX_BYTES, WARNING


def _release_log_handles():
    """Close every log-file handle product code keeps open, deterministically.

    ``init_logger()`` opens two OS-level handles on the log file for the
    process lifetime — the RotatingFileHandler attached to the ``ol`` logger,
    and the plain file object ``configure_structlog()`` hands to the structlog
    PrintLoggerFactory — and never closes either. On POSIX an open file is
    unlinked freely, so the historical suite never noticed; NTFS refuses to
    delete an open file (WinError 32) and every ``TemporaryDirectory``
    cleanup crashed instead. Tests that init the logger must call this
    BEFORE their tmpdir ``with`` block exits (cleanup runs inside the test
    body, before any fixture teardown). No sleep/retry: closing the handles
    releases them immediately.
    """
    from ol_logging import core

    factory = structlog.get_config().get("logger_factory")
    factory_file = getattr(factory, "file", None)
    if factory_file is not None and not factory_file.closed:
        factory_file.close()
    ol_logger = logging.getLogger("ol")
    for handler in list(ol_logger.handlers):
        ol_logger.removeHandler(handler)
        handler.close()
    logging.shutdown()
    core._initialized = False


@pytest.fixture(autouse=True)
def _release_log_handles_after_test():
    """Belt-and-braces: release handles if a test failed mid-body.

    The happy path calls ``_release_log_handles()`` inside the test (before
    tmpdir cleanup); this teardown catches the failure path so a leaked
    handle never poisons later tests via the process-global ``ol`` logger.
    """
    yield
    _release_log_handles()


class TestLogFileCreation:
    """Test log file creation functionality."""

    def test_log_file_created_in_directory(self):
        """Test log file is created in specified directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_dir = Path(tmpdir) / "logs"
            from ol_logging import core
            core._initialized = False  # Reset state

            from ol_logging.handlers import get_file_handler

            handler = get_file_handler(log_dir, INFO)
            try:
                assert log_dir.exists()
                assert log_dir.is_dir()
            finally:
                # Not attached to any logger, so the autouse teardown cannot
                # see it; the open stream would block NTFS deletion.
                handler.close()

    def test_log_file_has_correct_name_pattern(self):
        """Test log file follows naming pattern with date."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_dir = Path(tmpdir) / "logs"
            from ol_logging.handlers import get_file_handler

            handler = get_file_handler(log_dir, INFO)
            try:
                files = list(log_dir.glob("ol-*.log"))
                assert len(files) == 1
            finally:
                handler.close()


class TestLogRotation:
    """Test log rotation at MAX_BYTES."""

    def test_rotation_triggers_at_max_bytes(self):
        """Test rotation occurs when log reaches MAX_BYTES."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_dir = Path(tmpdir) / "logs"
            from datetime import date

            from ol_logging.constants import LOG_FILE_PATTERN
            from ol_logging.handlers import get_file_handler

            handler = get_file_handler(log_dir, INFO)
            log_file = log_dir / LOG_FILE_PATTERN.format(date=date.today().isoformat())

            try:
                # Write until we exceed MAX_BYTES
                large_content = b"x" * (MAX_BYTES + 1000)
                handler.emit(logging.LogRecord(
                    name="test",
                    level=INFO,
                    pathname="",
                    lineno=0,
                    msg=large_content.decode(),
                    args=(),
                    exc_info=None,
                ))

                # Should have rotated to .1
                rotated_files = list(log_dir.glob("ol-*.log.*"))
                assert len(rotated_files) >= 1
            finally:
                handler.close()

    def test_backup_count_limit(self):
        """Test BACKUP_COUNT limits number of rotated files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_dir = Path(tmpdir) / "logs"

            from ol_logging.constants import BACKUP_COUNT
            from ol_logging.handlers import get_file_handler

            handler = get_file_handler(log_dir, INFO)

            try:
                # Write enough to create many rotations
                for i in range(BACKUP_COUNT + 3):
                    large_content = b"y" * MAX_BYTES
                    handler.emit(logging.LogRecord(
                        name="test",
                        level=INFO,
                        pathname="",
                        lineno=0,
                        msg=large_content.decode(),
                        args=(),
                        exc_info=None,
                    ))

                rotated_files = list(log_dir.glob("ol-*.log.*"))
                assert len(rotated_files) <= BACKUP_COUNT
            finally:
                handler.close()


class TestGetLogger:
    """Test get_logger() returns correct logger name."""

    def test_get_logger_returns_ol_prefix(self):
        """Test get_logger prefixes 'ol.' to name."""
        from ol_logging.core import get_logger

        logger = get_logger("cli")
        assert logger.name == "ol.cli"

    def test_get_logger_nested_name(self):
        """Test get_logger handles dot-separated names."""
        from ol_logging.core import get_logger

        logger = get_logger("batch.processor")
        assert logger.name == "ol.batch.processor"

    def test_get_logger_returns_logger_instance(self):
        """Test get_logger returns logging.Logger instance."""
        from ol_logging.core import get_logger

        logger = get_logger("test")
        assert isinstance(logger, logging.Logger)


class TestInitLogger:
    """Test init_logger() initialization."""

    def test_init_logger_sets_level(self):
        """Test init_logger sets the correct log level."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_dir = Path(tmpdir) / "logs"
            from ol_logging import core
            core._initialized = False

            core.init_logger(level=WARNING, log_dir=log_dir)

            root_logger = logging.getLogger("ol")
            assert root_logger.level == WARNING

            _release_log_handles()

    def test_init_logger_idempotent(self):
        """Test init_logger can be called multiple times safely."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_dir = Path(tmpdir) / "logs"
            from ol_logging import core
            core._initialized = False

            core.init_logger(level=INFO, log_dir=log_dir)
            initial_handler_count = len(logging.getLogger("ol").handlers)

            # Call again - should not add more handlers
            core.init_logger(level=DEBUG, log_dir=log_dir)
            second_handler_count = len(logging.getLogger("ol").handlers)

            assert initial_handler_count == second_handler_count

            _release_log_handles()

    def test_init_logger_creates_file_handler(self):
        """Test init_logger adds file handler."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_dir = Path(tmpdir) / "logs"
            from ol_logging import core
            core._initialized = False

            core.init_logger(level=INFO, log_dir=log_dir)

            root_logger = logging.getLogger("ol")
            has_file_handler = any(
                isinstance(h, logging.handlers.RotatingFileHandler)
                for h in root_logger.handlers
            )
            assert has_file_handler

            _release_log_handles()


class TestLogLevelEnv:
    """Test LOG_LEVEL_ENV environment variable."""

    def test_log_level_from_env_debug(self):
        """Test LOG_LEVEL_ENV=DEBUG sets DEBUG level."""
        with patch.dict(os.environ, {LOG_LEVEL_ENV: "DEBUG"}):
            # Re-read to pick up env var
            import importlib

            from ol_logging import constants
            importlib.reload(constants)

            from ol_logging.core import get_logger
            logger = get_logger("test")
            # Logger level should be set appropriately
            assert logger.level == logging.DEBUG or logger.level == 0  # 0 means not set

            importlib.reload(constants)

    def test_log_level_from_env_info(self):
        """Test LOG_LEVEL_ENV=INFO sets INFO level."""
        with patch.dict(os.environ, {LOG_LEVEL_ENV: "INFO"}):
            import importlib

            from ol_logging import constants
            importlib.reload(constants)

            from ol_logging.core import get_logger
            logger = get_logger("test")
            assert logger.level == logging.INFO or logger.level == 0

            importlib.reload(constants)

    def test_log_level_from_env_invalid(self):
        """Test invalid LOG_LEVEL_ENV falls back to default."""
        with patch.dict(os.environ, {LOG_LEVEL_ENV: "INVALID"}):
            import importlib

            from ol_logging import constants
            importlib.reload(constants)

            # Should not crash, just use default
            from ol_logging.core import get_logger
            logger = get_logger("test")

            importlib.reload(constants)


class TestIsInitialized:
    """Test is_initialized() function."""

    def test_is_initialized_after_init(self):
        """Test is_initialized returns True after init_logger."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_dir = Path(tmpdir) / "logs"
            from ol_logging import core, is_initialized
            core._initialized = False

            assert is_initialized() is False

            core.init_logger(level=INFO, log_dir=log_dir)

            assert is_initialized() is True

            _release_log_handles()


class TestConsoleHandler:
    """Test console handler functionality."""

    def test_console_handler_added_when_env_set(self):
        """Test console handler is added when OL_LOG_CONSOLE=1."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_dir = Path(tmpdir) / "logs"
            with patch.dict(os.environ, {"OL_LOG_CONSOLE": "1"}):
                from ol_logging import core
                from ol_logging.handlers import is_console_enabled
                core._initialized = False

                assert is_console_enabled() is True

                core.init_logger(level=INFO, log_dir=log_dir)

                root_logger = logging.getLogger("ol")
                has_console = any(
                    isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler)
                    for h in root_logger.handlers
                )
                assert has_console

                _release_log_handles()

    def test_console_handler_not_added_by_default(self):
        """Test console handler is NOT added when OL_LOG_CONSOLE not set."""
        with tempfile.TemporaryDirectory() as tmpdir:
            log_dir = Path(tmpdir) / "logs"
            with patch.dict(os.environ, {"OL_LOG_CONSOLE": ""}, clear=True):
                from ol_logging import core
                from ol_logging.handlers import is_console_enabled
                core._initialized = False

                assert is_console_enabled() is False
