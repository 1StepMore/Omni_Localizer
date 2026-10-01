"""Path-denial taxonomy: which rejection reason maps to which agent-visible code.

Why this module exists
----------------------
``ol_mcp.security.PathValidator.validate_path`` has 13 distinct rejection
branches, but every OL MCP tool used to report *all* of them as one frozen
containment sentence (``PATH_DENIED_MESSAGE``).  The specific reason was
discarded at the call site, so "your file does not exist" was
indistinguishable from "that directory is not allowlisted".

That ambiguity caused two real misdiagnoses: a maintainer chasing a missing
``OL_MCP_ALLOWED_DIRS`` env var when the allowlist was in fact fine and the
file simply did not exist (e2e-test-suite#109, and again in the
``ol-path-denied`` regression scenario), and ``generate_report``, whose real
cause is an extension-policy rejection, reading as a containment failure.

This module is the single place that turns a ``ValidationResult.reason`` into
the ``(code, message)`` pair tools hand back to the agent.  Tools must not
invent denial messages; they call :func:`denial_for`.

Design rules (locked by ``tests/test_path_denial_taxonomy.py``)
------------------------------------------------------------
1. **Total.** Every reason ``validate_path`` can emit has exactly one entry.
   An unmapped reason raises ``KeyError`` rather than silently falling back to
   a generic message, so a new validator branch cannot ship without a taxonomy
   entry.
2. **No raw exception text.** Messages are static constants.  Reasons whose
   ``ValidationResult.error`` embeds ``str(e)`` from ``OSError`` /
   ``ValueError`` (``invalid_format``, ``unresolvable``, ``stat_failed``) or
   enumerates the allowlist (``outside_allowed``) must not leak host internals
   (mount points, usernames, errno strings) into an agent-visible payload.
3. **Containment wording is frozen** for the branches that carry it, because
   suite-level scenarios pin those bytes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterator, Optional

from ol_mcp._errors import FILE_NOT_FOUND, OL_PATH_DENIED
from ol_mcp.security import ValidationResult

#: Frozen containment wording. Module-private on purpose: tool modules must
#: reach it through :func:`denial_for`, never by importing a constant, or the
#: "every denial looks identical" bug returns.  ``tests/
#: test_path_denial_taxonomy.py`` locks this against the sibling
#: ``_errors.PATH_DENIED_MESSAGE`` (the *exception* route's opaque wording,
#: which has no reason available and is intentionally separate).
_CONTAINMENT_MESSAGE = "Path is not within the allowed directories."


@dataclass(frozen=True, slots=True)
class PathDenial:
    """The agent-visible shape of one path rejection.

    Attributes:
        code: Stable error code. Clients switch on this string; never change
            one that is already released (``OL_PATH_DENIED``).
        message: Static, human-readable reason. Names the branch that rejected
            the path; never interpolates exception text or the allowlist.
    """

    code: str
    message: str

    def __iter__(self) -> Iterator[str]:
        """Yield ``(code, message)`` so a denial splats positionally.

        ``_error_response(code, message)`` is the commonest consumer, and this
        keeps every call site a single ``*denial_for(result)`` expression
        instead of unpacking a two-field dataclass by hand at 15 sites.
        """
        yield self.code
        yield self.message


#: Total map from ``ValidationResult.reason`` to its agent-visible denial.
#: Keys are in ``validate_path``'s check order, which is the order an agent
#: hits them.  Every one of the 13 branches is present; the exhaustiveness
#: test asserts that set equality, so adding a validator branch without
#: adding a row here fails the suite.
#:
#: Two policies decide the ``message`` column:
#:
#: * **Reasons 1-9** are path-*policy* denials — the allowlist, the system-dir
#:   blacklist, the traversal rule, the extension rules. They keep the
#:   byte-identical ``OL_PATH_DENIED`` code (clients switch on that string) and
#:   gain a message that names the branch, so an agent can tell a traversal
#:   from a system-dir hit from a blacklisted extension.
#: * **Reasons 10-13** are not policy denials at all — the path cleared every
#:   policy gate and then failed on the filesystem. Reporting them as
#:   ``OL_PATH_DENIED`` told the agent to widen an allowlist that was already
#:   correct, which is exactly the misdiagnosis this module exists to end. They
#:   get ``FILE_NOT_FOUND``, mirroring ``omni_mcp.orchestrator`` and OL's own
#:   ``translate_file`` (``FILE_NOT_FOUND`` for a missing user-supplied input).
#:
#: Four reasons deliberately keep the frozen containment sentence:
#: ``outside_allowed``, ``traversal`` and ``symlink_escape`` are the three the
#: design froze, and ``extension_not_allowed`` is a **fourth, forced by shipped
#: evidence**: ``scenarios/agent-surface/tool-ol-generate_report.yaml`` asserts
#: the literal ``Path is not within the allowed directories.`` for
#: ``output_dir="/tmp/omni-agent-surface"``, and that path is denied by the
#: extension whitelist (a suffixless directory), not by containment. Widening
#: the frozen set to match reality was preferred over editing that scenario.
#: The cost is recorded honestly: ``generate_report`` keeps reporting a
#: containment message for an extension-policy denial.
_REASON_MAP: Dict[str, PathDenial] = {
    # ── path-policy denials: keep OL_PATH_DENIED, name the branch ──
    "invalid_format": PathDenial(
        OL_PATH_DENIED, "Path format is invalid and cannot be parsed."
    ),
    "traversal": PathDenial(OL_PATH_DENIED, _CONTAINMENT_MESSAGE),
    "unresolvable": PathDenial(
        OL_PATH_DENIED, "Path could not be resolved to a real location."
    ),
    "system_dir": PathDenial(
        OL_PATH_DENIED, "Path targets a protected system directory."
    ),
    "outside_allowed": PathDenial(OL_PATH_DENIED, _CONTAINMENT_MESSAGE),
    "symlink_escape": PathDenial(OL_PATH_DENIED, _CONTAINMENT_MESSAGE),
    "symlink_inaccessible": PathDenial(
        OL_PATH_DENIED, "Symlink target could not be read or resolved."
    ),
    "blocked_extension": PathDenial(
        OL_PATH_DENIED, "File extension is on the blocked executable blacklist."
    ),
    "extension_not_allowed": PathDenial(OL_PATH_DENIED, _CONTAINMENT_MESSAGE),
    # ── filesystem failures: not an allowlist problem ──
    "missing": PathDenial(FILE_NOT_FOUND, "File does not exist."),
    "not_a_file": PathDenial(FILE_NOT_FOUND, "Path must be a file, not a directory."),
    "too_large": PathDenial(FILE_NOT_FOUND, "File exceeds the maximum allowed size."),
    "stat_failed": PathDenial(
        FILE_NOT_FOUND, "File could not be read to verify its size."
    ),
}


def denial_for(result: ValidationResult) -> Optional[PathDenial]:
    """Return the agent-visible denial for a failed validation.

    Args:
        result: The :class:`~ol_mcp.security.ValidationResult` returned by
            ``validate_path``.

    Returns:
        ``None`` when *result* succeeded — callers sit inside
        ``if not result.success:``, so success has nothing to report.

    Raises:
        KeyError: *result* failed but carries no ``reason``, or a reason with
            no entry in :data:`_REASON_MAP`.  This is deliberate: a new
            ``validate_path`` branch must fail loudly here rather than ship
            with a silently wrong or silently generic message.
    """
    if result.success:
        return None
    reason = result.reason
    if reason is None or reason not in _REASON_MAP:
        raise KeyError(
            f"no path-denial taxonomy entry for reason {reason!r}; add it to "
            f"ol_mcp.path_denials._REASON_MAP before shipping a new "
            f"validate_path branch"
        )
    return _REASON_MAP[reason]