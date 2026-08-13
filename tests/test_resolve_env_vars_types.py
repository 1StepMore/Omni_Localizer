"""Test P1-T5: _resolve_env_vars should have correct type signature."""
from typing import get_type_hints

from ol_pool.router import _resolve_env_vars


def test_resolve_env_vars_signature_accepts_none():
    """_resolve_env_vars should accept None input (signature should include str | None)."""
    hints = get_type_hints(_resolve_env_vars)
    param_hint = hints.get("value")
    # After the fix, this should be str | None
    assert param_hint is not str, (
        f"_resolve_env_vars(value) type hint is {param_hint}, but it should accept None. "
        f"The function has 'if value is None: return None' but signature says str only."
    )


def test_resolve_env_vars_return_type_includes_none():
    """_resolve_env_vars should declare return type as str | None."""
    hints = get_type_hints(_resolve_env_vars)
    return_hint = hints.get("return")
    assert return_hint is not str, (
        f"_resolve_env_vars return type is {return_hint}, but it returns None. "
        f"Should be str | None."
    )


def test_resolve_env_vars_with_none_returns_none():
    """_resolve_env_vars(None) should return None (defensive behavior)."""
    # After the fix, this should work without mypy errors
    try:
        result = _resolve_env_vars(None)  # type: ignore[arg-type]
        assert result is None
    except TypeError as e:
        raise AssertionError(
            f"_resolve_env_vars(None) raised TypeError: {e}. "
            f"The signature should accept None."
        )
