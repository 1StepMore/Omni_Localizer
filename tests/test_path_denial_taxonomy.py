"""Path-denial taxonomy: routing guard + exhaustiveness/totality.

Two jobs, both mechanical so neither depends on remembering a convention:

1. **Routing guard (AST).** The original defect was not a wrong string — it was
   that 20 call sites each *discarded* the validator's specific reason and
   re-emitted one frozen constant. A code review that reads the call site
   cannot see that; only an AST pass over every module can. So:

   (a) every ``validate_path(...)`` call in ``src/ol_mcp/*.py`` must have its
       result checked (``.success`` read) and routed through
       ``denial_for``;
   (b) no module other than the taxonomy owner and the error-taxonomy owner
       may reference the containment-message constant.

   Assertion (b) is the one that generalises: it catches the bug *class*
   (anyone reaching for a frozen generic message) rather than the bug.

2. **Totality/exhaustiveness.** ``ol_mcp.path_denials._REASON_MAP`` must cover
   *exactly* the set of reasons ``validate_path`` can emit — extracted from
   ``security.py``'s own AST, not a hand-copied list — so a new validator
   branch cannot ship without a taxonomy row.

Run directly (also what the pre-commit hook invokes)::

    OMNI_TEST_FAKE_LLM=1 python -m pytest tests/test_path_denial_taxonomy.py -q
"""
from __future__ import annotations

import ast
from pathlib import Path
from typing import List, Set

import pytest

from ol_mcp._errors import PATH_DENIED_MESSAGE
from ol_mcp.path_denials import (
    _REASON_MAP,
    PathDenial,
    denial_for,
)
from ol_mcp.security import ValidationResult

_SRC_DIR = Path(__file__).resolve().parents[1] / "src" / "ol_mcp"
_SECURITY_PY = _SRC_DIR / "security.py"

#: The taxonomy module. It owns the containment wording, so it is the one
#: place allowed to reference it.
_TAXONOMY_MODULE = "path_denials.py"

#: ``_errors`` defines ``PATH_DENIED_MESSAGE`` and uses it on the *exception*
#: route (``PathDeniedError`` -> ``_safe_user_message``). That route has no
#: ``ValidationResult`` and therefore no ``reason``, so its wording is opaque
#: by design and is locked by
#: ``tests/test_agent_surface_fidelity_regressions.py``. It is a definition
#: site, not a referencer, so it is exempt from (b).
_ERRORS_MODULE = "_errors.py"

_CONTAINMENT_MESSAGE_NAME = "PATH_DENIED_MESSAGE"

#: The 13 rejection branches of ``validate_path``, in check order. This is the
#: design's inventory; the tests below prove ``security.py`` and
#: ``_REASON_MAP`` both agree with it exactly.
EXPECTED_REASONS: tuple[str, ...] = (
    "invalid_format",
    "traversal",
    "unresolvable",
    "system_dir",
    "outside_allowed",
    "symlink_escape",
    "symlink_inaccessible",
    "blocked_extension",
    "extension_not_allowed",
    "missing",
    "not_a_file",
    "too_large",
    "stat_failed",
)


def _module_files() -> List[Path]:
    return sorted(p for p in _SRC_DIR.glob("*.py") if p.is_file())


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _called_func_names(tree: ast.AST) -> Set[str]:
    """Every bare function name invoked anywhere in *tree*."""
    names: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                names.add(func.id)
            elif isinstance(func, ast.Attribute):
                names.add(func.attr)
    return names


def _validate_path_targets(tree: ast.AST) -> Set[str]:
    """Names assigned from a ``validate_path(...)`` call.

    Covers both shapes present in the tree: ``v = vtor.validate_path(p)`` and
    ``_gv = _validator.validate_path(p)``.
    """
    targets: Set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        func = node.value.func
        if not (isinstance(func, ast.Name) or isinstance(func, ast.Attribute)):
            continue
        if (func.attr if isinstance(func, ast.Attribute) else func.id) != "validate_path":
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                targets.add(target.id)
    return targets


def _denial_for_args(tree: ast.AST) -> Set[str]:
    """Names passed as the sole argument to ``denial_for(...)``."""
    args: Set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "denial_for"
            and len(node.args) == 1
            and isinstance(node.args[0], ast.Name)
        ):
            args.add(node.args[0].id)
    return args


def _success_checked(tree: ast.AST, target: str) -> bool:
    """True if ``<target>.success`` is read anywhere (the result is checked)."""
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and node.attr == "success"
            and isinstance(node.value, ast.Name)
            and node.value.id == target
        ):
            return True
    return False


def _defines(path: Path, func_name: str) -> bool:
    """True if *path* declares ``def <func_name>`` at module level."""
    return any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name
        for node in _parse(path).body
    )


def _validator_reasons_from_source() -> List[str]:
    """Every ``reason=`` literal on a ``ValidationResult(...)`` in security.py.

    Read from the source AST rather than a hand-copied tuple, so a branch added
    to ``validate_path`` without a ``reason=`` shows up as a mismatch instead of
    silently passing. Collected in *source* order (``ast.walk`` is breadth
    first and would scramble it) because the order is part of the contract.
    """
    reasons: List[tuple[int, str]] = []
    for node in ast.walk(_parse(_SECURITY_PY)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Name) and func.id == "ValidationResult"):
            continue
        for kw in node.keywords:
            if kw.arg == "reason" and isinstance(kw.value, ast.Constant):
                assert isinstance(kw.value.value, str), (
                    f"security.py: reason= must be a literal string, got "
                    f"{kw.value.value!r}"
                )
                reasons.append((node.lineno, kw.value.value))
    return [reason for _, reason in sorted(reasons)]


# ── 1. Routing guard (AST) ────────────────────────────────────────────


@pytest.mark.ast_guard
@pytest.mark.parametrize("path", _module_files(), ids=lambda p: p.name)
def test_every_validate_path_is_routed_through_denial_for(path: Path) -> None:
    """(a) No call site may validate a path and then ignore the reason."""
    tree = _parse(path)
    targets = _validate_path_targets(tree)
    if not targets:
        pytest.skip(f"{path.name} calls validate_path not at all")

    routed = _denial_for_args(tree)
    unrouted = sorted(targets - routed)
    assert not unrouted, (
        f"{path.name}: validate_path result(s) {unrouted} are never passed to "
        f"denial_for(). Route every denial through ol_mcp.path_denials.denial_for "
        f"so the reported code/message match the branch that rejected the path."
    )

    unchecked = sorted(t for t in targets if not _success_checked(tree, t))
    assert not unchecked, (
        f"{path.name}: validate_path result(s) {unchecked} are never checked for "
        f".success — an unchecked validation is a silent pass."
    )


@pytest.mark.ast_guard
def test_denial_for_is_the_only_sanctioned_denial_entry_point() -> None:
    """Sanity: the helper is actually reachable from the tool modules.

    Guards against a refactor that satisfies (a) by inlining a lookup table
    into every module.
    """
    taxonomy = _SRC_DIR / _TAXONOMY_MODULE
    assert _defines(taxonomy, "denial_for"), (
        f"{_TAXONOMY_MODULE} must define denial_for; the guard's premise is "
        f"that it is the single entry point"
    )

    callers = sorted(
        p.name
        for p in _module_files()
        if p.name != _TAXONOMY_MODULE
        and "denial_for" in _called_func_names(_parse(p))
    )
    assert len(callers) >= 12, (
        f"expected the sweep to span every tool module that validates a path, "
        f"but only {callers} call denial_for"
    )


@pytest.mark.ast_guard
@pytest.mark.parametrize("path", _module_files(), ids=lambda p: p.name)
def test_only_the_taxonomy_module_references_the_containment_message(
    path: Path,
) -> None:
    """(b) The containment message is private to the taxonomy owner.

    This is the assertion that generalises. The original bug was 20 copies of
    "report the frozen string"; any new one is caught here regardless of which
    module introduces it.
    """
    if path.name in (_TAXONOMY_MODULE, _ERRORS_MODULE):
        pytest.skip(f"{path.name} owns the containment wording")

    tree = _parse(path)
    offenders: List[str] = []

    for node in ast.walk(tree):
        # from ol_mcp._errors import PATH_DENIED_MESSAGE
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == _CONTAINMENT_MESSAGE_NAME:
                    offenders.append(f"line {node.lineno}: import of {_CONTAINMENT_MESSAGE_NAME}")
                if alias.asname == _CONTAINMENT_MESSAGE_NAME:
                    offenders.append(f"line {node.lineno}: import aliased to {_CONTAINMENT_MESSAGE_NAME}")
        # a bare reference / attribute access
        elif isinstance(node, ast.Name) and node.id == _CONTAINMENT_MESSAGE_NAME:
            offenders.append(f"line {node.lineno}: reference to {_CONTAINMENT_MESSAGE_NAME}")
        elif isinstance(node, ast.Attribute) and node.attr == _CONTAINMENT_MESSAGE_NAME:
            offenders.append(f"line {node.lineno}: attribute .{_CONTAINMENT_MESSAGE_NAME}")

    assert not offenders, (
        f"{path.name} references the containment-message constant, which would "
        f"re-create the 'every denial looks identical' defect:\n  "
        + "\n  ".join(offenders)
        + "\nUse ol_mcp.path_denials.denial_for(result) instead."
    )


@pytest.mark.ast_guard
def test_taxonomy_container_is_importable_without_circular_dependency() -> None:
    """``path_denials`` imports ``security``; ``security`` must not import back."""
    security_imports = _called_func_names(_parse(_SECURITY_PY))
    assert "denial_for" not in security_imports, (
        "ol_mcp.security must not depend on ol_mcp.path_denials — the taxonomy "
        "reads ValidationResult, so a back-import would be circular"
    )


# ── 2. Totality / exhaustiveness ──────────────────────────────────────


def test_validator_emits_exactly_the_expected_reasons() -> None:
    reasons = _validator_reasons_from_source()
    assert len(reasons) == len(set(reasons)), (
        f"security.py sets a duplicate reason= literal: {sorted(reasons)}"
    )
    assert tuple(reasons) == EXPECTED_REASONS, (
        "the set of reasons validate_path emits drifted from the design "
        f"inventory:\n  security.py: {reasons}\n  expected: {list(EXPECTED_REASONS)}"
    )


def test_every_validator_reason_has_exactly_one_mapping_entry() -> None:
    emitted = set(_validator_reasons_from_source())
    mapped = set(_REASON_MAP)
    assert mapped == emitted, (
        "path-denial taxonomy is not total over the validator's reasons.\n"
        f"  unmapped (must be added to _REASON_MAP): {sorted(emitted - mapped)}\n"
        f"  stale (no longer emitted; remove from _REASON_MAP): {sorted(mapped - emitted)}"
    )
    assert len(_REASON_MAP) == len(emitted), (
        f"expected {len(emitted)} mapping entries, found {len(_REASON_MAP)} — "
        f"each reason must map to exactly one denial"
    )


def test_mapping_order_matches_the_validator_check_order() -> None:
    assert tuple(_REASON_MAP) == EXPECTED_REASONS, (
        "_REASON_MAP must stay in validate_path's check order so the table reads "
        "as the pipeline it describes"
    )


@pytest.mark.parametrize("reason", EXPECTED_REASONS)
def test_denial_for_returns_an_entry_for_every_reason(reason: str) -> None:
    result = ValidationResult(success=False, error="diagnostic text", reason=reason)
    denial = denial_for(result)
    assert denial is not None, f"{reason}: denial_for returned None for a failure"
    assert isinstance(denial, PathDenial)
    assert denial.code
    assert denial.message
    # Splatting into _error_response(code, message) is the call-site contract.
    assert tuple(denial) == (denial.code, denial.message)


def test_denial_for_returns_none_on_success() -> None:
    assert denial_for(ValidationResult(success=True)) is None


def test_denial_for_raises_on_unmapped_reason() -> None:
    """Fail loud: a new branch must not ship with a silently wrong message."""
    with pytest.raises(KeyError, match="no path-denial taxonomy entry"):
        denial_for(ValidationResult(success=False, reason="brand_new_branch"))


def test_denial_for_raises_when_reason_is_missing() -> None:
    """A failure with no reason is the same class of defect as an unmapped one."""
    with pytest.raises(KeyError, match="no path-denial taxonomy entry"):
        denial_for(ValidationResult(success=False, error="something went wrong"))


# ── 3. Message hygiene ────────────────────────────────────────────────


@pytest.mark.parametrize("reason", EXPECTED_REASONS)
def test_no_canonical_message_interpolates_raw_exception_text(reason: str) -> None:
    """Reasons whose ``error`` embeds ``str(e)`` must not leak it to agents.

    ``invalid_format``, ``unresolvable`` and ``stat_failed`` carry OS/ValueError
    text (mount points, usernames, errno strings); ``outside_allowed``
    enumerates the allowlist. None of that may reach an agent-visible payload.
    """
    denial = _REASON_MAP[reason]
    assert "{" not in denial.message and "}" not in denial.message, (
        f"{reason}: canonical message must be a static string, got "
        f"{denial.message!r}"
    )
    assert "e)" not in denial.message, (
        f"{reason}: canonical message looks like it interpolates an exception: "
        f"{denial.message!r}"
    )


@pytest.mark.parametrize("reason", EXPECTED_REASONS)
def test_canonical_message_never_names_a_host_path(reason: str) -> None:
    """No allowlist enumeration, no absolute paths in a canonical message."""
    denial = _REASON_MAP[reason]
    assert "/" not in denial.message, (
        f"{reason}: canonical message leaks a path or enumerates the allowlist: "
        f"{denial.message!r}"
    )


def test_containment_wording_matches_the_error_taxonomy_copy() -> None:
    """Lock the two intentional copies of the containment sentence.

    ``_errors.PATH_DENIED_MESSAGE`` serves the *exception* route (no reason
    available, so its wording must stay opaque). ``path_denials``'s private copy
    serves the *tool envelope* route. They are equal today on purpose, and this
    is the executable evidence — the same pattern
    ``tests/security/test_path_policy_characterization.py`` uses for OL/ORF/
    orchestrator wording drift.
    """
    from ol_mcp.path_denials import _CONTAINMENT_MESSAGE

    assert _CONTAINMENT_MESSAGE == PATH_DENIED_MESSAGE, (
        "the two intentional copies of the containment sentence diverged: "
        f"{_CONTAINMENT_MESSAGE!r} vs {PATH_DENIED_MESSAGE!r}"
    )


def test_taxonomy_module_does_not_leak_the_containment_constant() -> None:
    """It must stay module-private, not re-exported for tool modules to grab."""
    import ol_mcp.path_denials as taxonomy

    public = [
        name
        for name in vars(taxonomy)
        if not name.startswith("_") and "CONTAINMENT" in name.upper()
    ]
    assert not public, (
        f"path_denials must keep the containment message private; found {public}"
    )


def test_result_shape_is_stable() -> None:
    """``ValidationResult`` keeps its positional field order.

    Adding ``reason`` last preserves ``ValidationResult(success, error,
    resolved_path)`` for any caller constructing it positionally.
    """
    fields = [f.name for f in ValidationResult.__dataclass_fields__.values()]
    assert fields == ["success", "error", "resolved_path", "reason"], fields


def test_successful_result_has_no_reason() -> None:
    assert ValidationResult(success=True).reason is None