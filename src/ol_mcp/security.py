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
    "/proc",
    "/sys",
    "/System",
    "/Library",
    "/C:/Windows",
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

    ALLOWED_EXTENSIONS = {".json", ".tmx", ".xlf", ".xliff", ".md", ".yaml", ".yml"}

    @classmethod
    def get_allowed_extensions(cls) -> set[str]:
        """Return the effective allowed-extensions set.

        If the ``MCP_ALLOWED_EXTENSIONS`` env var is set (comma-separated,
        e.g. ``.txt,.csv,.yaml``), it overrides the class default.
        An empty or whitespace-only value falls back to ``ALLOWED_EXTENSIONS``.

        前导点可选（2026-09-17，ADR 0007 一致性对齐）：``MCP_ALLOWED_EXTENSIONS=txt``
        与 ``=.txt`` 现在等价。此前 OL 只接受带点的写法，而 OPP/ORF 的
        ``resolve_allowed_extensions()`` 会把 ``txt`` 补成 ``.txt`` —— 同一个环境变量
        在三份实现里语义不同，配置 ``txt`` 时 OL 永远判为"不在白名单"。
        收敛后三份实现的解析语义一致（前导点可选、纯空白视为未设置），并由
        ``tests/security/test_path_policy_parity.py`` 锁定。
        """
        raw = os.environ.get("MCP_ALLOWED_EXTENSIONS", "").strip()
        if not raw:
            return cls.ALLOWED_EXTENSIONS
        return {
            ext if ext.startswith(".") else f".{ext}"
            for ext in (part.strip() for part in raw.split(","))
            if ext
        }

    def __init__(
        self,
        allowed_directories: List[Path],
        max_file_size_bytes: int = 100_000_000,
    ):
        self.allowed_directories = [Path(d).resolve() for d in allowed_directories]
        self.max_file_size_bytes = max_file_size_bytes

    def validate_path(self, path: str, allow_missing: bool = False, skip_extension_check: bool = False) -> ValidationResult:
        """Validate a file path against security rules.

        Args:
            path: The path string to validate.
            allow_missing: If True, skip the existence check (for output paths).
                          If False (default), file must exist and be readable.
            skip_extension_check: If True, skip the allowed-extension check.
                                 Useful for pipeline tools (e.g. translate_file)
                                 that delegate format handling to downstream tools.

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
        if not skip_extension_check and input_path.suffix.lower() not in self.get_allowed_extensions():
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


def _parse_allowed_dirs(value: str) -> list[Path]:
    """按平台路径分隔符与逗号切分 allowlist 字符串。

    2026-09-17（ADR 0007 一致性对齐）：此前 OL 只按逗号切分，而 OPP/ORF 的
    ``_parse_allowed_dirs`` 按冒号/分号切分 —— 同一个 ``MCP_ALLOWED_DIRECTORIES``
    在三份实现里语义不同。``omni_mcp.orchestrator._path_denial_message`` 又明确告诉
    用户 "comma- or '<os.pathsep>'-separated"，OL 不认平台分隔符会让这条提示变成假话。

    统一后的契约（与 OPP/ORF 逐字一致）：按 ``os.pathsep``（POSIX ``":"``、
    Windows ``";"``）加逗号切分，去掉空白、丢弃空段；不含分隔符的值自然成为
    单元素列表。**绝不在 Windows 上按 ``":"`` 切分** —— 盘符本身含 ``":"``，
    那会把 ``C:\\work`` 切成 ``C`` 与 ``\\work``，allowlist 完全失效
    （三份实现由 ``tests/security/test_path_policy_parity.py`` 锁定）。

    Args:
        value: 环境变量原始值（可含平台分隔符、逗号与空白）。

    Returns:
        非空分段组成的 ``Path`` 列表；``value`` 为空白时返回 ``[]``。
    """
    if not value or not value.strip():
        return []
    parts: list[str] = []
    for chunk in value.split(os.pathsep):
        parts.extend(chunk.split(","))
    return [Path(part.strip()) for part in parts if part.strip()]


def get_default_validator() -> PathValidator:
    """Build PathValidator from env var allowlist.

    Env var precedence (highest to lowest):
    1. ``MCP_ALLOWED_DIRECTORIES`` — unified cross-module name (Phase 2)
    2. ``OL_MCP_ALLOWED_DIRS`` — OL-specific name (kept for backward compat)
    3. ``OL_ALLOWED_DIRECTORIES`` — legacy name (deprecated)

    List syntax is ``os.pathsep`` (POSIX ``":"``, Windows ``";"``) and/or
    comma separated (e.g.,
    ``MCP_ALLOWED_DIRECTORIES=/tmp/ol-work,/data/corpus``).

    Fail-CLOSED: at least one of the three env vars MUST be set. If all
    are unset (or empty), a ``ValueError`` is raised rather than silently
    granting access to ``cwd`` + ``/tmp``. Set
    ``MCP_ALLOWED_DIRECTORIES`` (or one of the legacy names) to an
    explicit comma-separated allowlist before starting the server.

    The validator is created fresh on each call so that env-var
    changes (e.g., between tests) are picked up. For long-running
    servers that need a stable validator, instantiate directly.
    """
    allowed = (
        os.environ.get("MCP_ALLOWED_DIRECTORIES", "")
        or os.environ.get("OL_MCP_ALLOWED_DIRS", "")
        or os.environ.get("OL_ALLOWED_DIRECTORIES", "")
    )
    if os.environ.get("OL_ALLOWED_DIRECTORIES") and not (
        os.environ.get("MCP_ALLOWED_DIRECTORIES") or os.environ.get("OL_MCP_ALLOWED_DIRS")
    ):
        _logger.warning("OL_ALLOWED_DIRECTORIES is deprecated, use MCP_ALLOWED_DIRECTORIES")
    dirs = [d.resolve() for d in _parse_allowed_dirs(allowed)]
    if not dirs:
        raise ValueError(
            "MCP_ALLOWED_DIRECTORIES (or OL_MCP_ALLOWED_DIRS / "
            "OL_ALLOWED_DIRECTORIES) must be set (fail-CLOSED security policy). "
            "Export it as a comma-separated list of allowed directories."
        )
    return PathValidator(allowed_directories=dirs)
