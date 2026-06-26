"""Path validation with directory allowlist and file size limits.

Mirrors ``orf/mcp/security.py:PathValidator`` with OL-specific
extensions (glossary .json, TMX .tmx, XLIFF .xlf/.xliff, MD .md).

Added in round 16 (Phase A1) to close the OL MCP path-traversal
gap identified in the round-15 security audit. Previously, tools
accepting file paths (``load_glossary``, ``search_tm``,
``translate_xliff``) had zero validation -- any agent could
read arbitrary files on the host.
"""

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

_logger = logging.getLogger(__name__)

SYSTEM_DIRS: set = {
    "/etc",
    "/usr",
    "/var",
    "/System",
    "/Library",
    "C:\\Windows",
}

BLOCKED_EXTENSIONS: set = {
    ".exe",
    ".bat",
    ".cmd",
    ".sh",
    ".ps1",
    ".vbs",
    ".js",
}


@dataclass
class ValidationResult:
    """Result of path validation.

    Attributes:
        success: True if path passed all validation checks.
        error: Error message if validation failed, None otherwise.
        resolved_path: The resolved Path object if successful, None otherwise.
    """
    success: bool
    error: Optional[str] = None
    resolved_path: Optional[Path] = None


class PathValidator:
    """Validates file paths against security rules for OL MCP.

    Checks (in order):
    - Path format is valid (no ValueError/OSError on Path())
    - Path doesn't contain traversal components (..)
    - Path resolves without error
    - Path doesn't target a system directory (/etc, /usr, /var, etc.)
    - Path is within allowed directories (from OL_ALLOWED_DIRECTORIES)
    - Path is not a symlink pointing outside allowed directories
    - File extension is not blocked (.exe, .bat, .sh, etc.)
    - File extension is in the allowed set (.json, .tmx, .xlf, .xliff, .md)
    - File exists (unless allow_missing=True, for output paths)
    - Path is a file, not a directory
    - File size is within max_file_size_bytes (default 100MB)

    Args:
        allowed_directories: List of root directories that are allowed to access.
        max_file_size_bytes: Maximum allowed file size in bytes (default: 100MB).
    """

    ALLOWED_EXTENSIONS = {".json", ".tmx", ".xlf", ".xliff", ".md"}

    def __init__(
        self,
        allowed_directories: List[Path],
        max_file_size_bytes: int = 100_000_000,
    ):
        self.allowed_directories = [Path(d).resolve() for d in allowed_directories]
        self.max_file_size_bytes = max_file_size_bytes

    def validate_path(self, path: str, allow_missing: bool = False) -> ValidationResult:
        """Validate a file path against security rules.

        Args:
            path: The path string to validate.
            allow_missing: If True, skip the existence check (for output paths).
                          If False (default), file must exist and be readable.

        Returns:
            ValidationResult with success=True if valid, or success=False
            with an error message.
        """
        try:
            input_path = Path(path)
        except (ValueError, OSError) as e:
            return ValidationResult(
                success=False,
                error=f"Invalid path format: {e}",
            )

        # Path traversal check
        if ".." in input_path.parts:
            return ValidationResult(
                success=False,
                error="Path traversal detected (.. components are not allowed)",
            )

        # Resolve the path (follows symlinks)
        try:
            resolved = input_path.resolve()
        except (ValueError, OSError) as e:
            return ValidationResult(
                success=False,
                error=f"Cannot resolve path: {e}",
            )

        # System directory check
        for sys_dir in SYSTEM_DIRS:
            sys_path = Path(sys_dir)
            try:
                resolved_parts = resolved.parts
                sys_parts = sys_path.parts
                if len(resolved_parts) >= len(sys_parts):
                    if all(
                        a == b for a, b in zip(resolved_parts[:len(sys_parts)], sys_parts)
                    ):
                        return ValidationResult(
                            success=False,
                            error=f"Access to system directory not allowed: {sys_dir}",
                        )
            except ValueError:
                pass

        # Allowed directories check
        is_in_allowed = False
        for allowed_dir in self.allowed_directories:
            try:
                resolved.relative_to(allowed_dir)
                is_in_allowed = True
                break
            except ValueError:
                pass

        if not is_in_allowed:
            return ValidationResult(
                success=False,
                error=(
                    f"Path is not within allowed directories: "
                    f"{', '.join(str(d) for d in self.allowed_directories)}"
                ),
            )

        # Symlink check (re-validate the target is in allowed dirs)
        if input_path.is_symlink():
            try:
                link_target = input_path.resolve()
                link_in_allowed = False
                for allowed_dir in self.allowed_directories:
                    try:
                        link_target.relative_to(allowed_dir)
                        link_in_allowed = True
                        break
                    except ValueError:
                        pass
                if not link_in_allowed:
                    return ValidationResult(
                        success=False,
                        error="Symlink points outside allowed directories",
                    )
            except (ValueError, OSError):
                return ValidationResult(
                    success=False,
                    error="Symlink target is not accessible",
                )

        # Blocked extension check (executable blacklist)
        if input_path.suffix.lower() in BLOCKED_EXTENSIONS:
            return ValidationResult(
                success=False,
                error=f"File extension '{input_path.suffix}' is blocked",
            )

        # Allowed extension check (document whitelist)
        if input_path.suffix.lower() not in self.ALLOWED_EXTENSIONS:
            return ValidationResult(
                success=False,
                error=f"Extension '{input_path.suffix}' not in allowed set",
            )

        # Existence check
        if not resolved.exists():
            if allow_missing:
                return ValidationResult(success=True, resolved_path=resolved)
            return ValidationResult(
                success=False,
                error="File does not exist",
            )

        # Must be a file, not a directory
        if not resolved.is_file():
            return ValidationResult(
                success=False,
                error="Path must be a file, not a directory",
            )

        # File size check
        try:
            file_size = resolved.stat().st_size
            if file_size > self.max_file_size_bytes:
                return ValidationResult(
                    success=False,
                    error=(
                        f"File size ({file_size} bytes) exceeds limit of "
                        f"{self.max_file_size_bytes} bytes"
                    ),
                )
        except OSError as e:
            return ValidationResult(
                success=False,
                error=f"Cannot access file to check size: {e}",
            )

        return ValidationResult(
            success=True,
            resolved_path=resolved,
        )


def get_default_validator() -> PathValidator:
    """Build PathValidator from OL_MCP_ALLOWED_DIRS env var.

    Comma-separated list of allowed directories (e.g.,
    ``OL_MCP_ALLOWED_DIRS=/tmp/ol-work,/data/corpus``). If
    empty or unset, defaults to the current working directory.

    The old name ``OL_ALLOWED_DIRECTORIES`` is still accepted as
    a backward-compat fallback.

    The validator is created fresh on each call so that env-var
    changes (e.g., between tests) are picked up. For long-running
    servers that need a stable validator, instantiate directly.
    """
    allowed = os.environ.get("OL_MCP_ALLOWED_DIRS",
                 os.environ.get("OL_ALLOWED_DIRECTORIES", ""))
    if os.environ.get("OL_ALLOWED_DIRECTORIES") and not os.environ.get("OL_MCP_ALLOWED_DIRS"):
        _logger.warning("OL_ALLOWED_DIRECTORIES is deprecated, use OL_MCP_ALLOWED_DIRS")
    if allowed.strip():
        dirs = [Path(d).resolve() for d in allowed.split(",") if d.strip()]
    else:
        # Default: allow cwd (project root) and /tmp (standard test workspace).
        dirs = [Path.cwd().resolve(), Path("/tmp").resolve()]
    return PathValidator(allowed_directories=dirs)
