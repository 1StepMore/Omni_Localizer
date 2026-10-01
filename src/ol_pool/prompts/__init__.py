"""Central prompt store — OL#112 / CODE_CONVENTIONS D1 ("提示词是一等资产").

Prompt text is a first-class, diffable, versionable asset: it lives in
``*.txt`` files in this directory, never as inline string literals in
``router.py``. Editing a prompt touches only a file under ``prompts/``.

Template syntax is stdlib :class:`string.Template` (``$name``), chosen
because it is dependency-free and — unlike ``str.format`` — does not treat
the ``{``/``}`` braces these prompts legitimately contain (``{{_OL_XTAG_*_}}``,
the JSON schema in the judge prompt) as syntax. A literal ``$`` in prompt
text must be written ``$$``.

Rendering fails loud (:class:`PromptRenderError`) when a declared variable is
missing **or** an undeclared one is supplied, so a typo or a renamed
placeholder can never silently degrade a prompt into a hole.

The ``.txt`` files hold the exact bytes that are sent to the LLM — no trailing
newline, no whitespace stripping — so a rendered prompt is byte-identical to
what the code sent before the extraction.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from string import Template

__all__ = [
    "PROMPTS_DIR",
    "PromptRenderError",
    "available_prompts",
    "load_prompt",
    "prompt_variables",
    "render_prompt",
]

PROMPTS_DIR = Path(__file__).resolve().parent

_SUFFIX = ".txt"

# Mirrors ``string.Template``'s own identifier grammar. Spelled out here
# instead of using the undocumented ``Template.get_identifiers()``.
_IDENTIFIER_RE = re.compile(
    r"\$(?:(?P<named>[_a-zA-Z][_a-zA-Z0-9]*)|\{(?P<braced>[_a-zA-Z][_a-zA-Z0-9]*)\})"
)


class PromptRenderError(ValueError):
    """A prompt file is missing/unknown, or its variables do not line up."""


def available_prompts() -> list[str]:
    """Names of every prompt in the store, sorted."""
    return sorted(p.stem for p in PROMPTS_DIR.glob(f"*{_SUFFIX}"))


def _identifiers(template: str) -> list[str]:
    return sorted({m["named"] or m["braced"] for m in _IDENTIFIER_RE.finditer(template)})


@lru_cache(maxsize=None)
def load_prompt(name: str) -> str:
    """Read the raw text of prompt ``name`` from the store (cached).

    Raises:
        PromptRenderError: if ``name`` is not a plain prompt name with a
            readable ``.txt`` file behind it (never a path escape).
    """
    path = PROMPTS_DIR / f"{name}{_SUFFIX}"
    if path.parent != PROMPTS_DIR or not path.is_file():
        known = ", ".join(available_prompts())
        raise PromptRenderError(f"unknown prompt {name!r}; available prompts: {known}")
    return path.read_text(encoding="utf-8")


def prompt_variables(name: str) -> list[str]:
    """Sorted variable names prompt ``name`` declares."""
    return _identifiers(load_prompt(name))


def render_prompt(name: str, **variables: str) -> str:
    """Render prompt ``name`` with ``variables``.

    Raises:
        PromptRenderError: naming every missing and every undeclared variable.
    """
    template = load_prompt(name)
    declared = set(_identifiers(template))
    missing = sorted(declared - variables.keys())
    undeclared = sorted(variables.keys() - declared)
    if missing or undeclared:
        problems: list[str] = []
        if missing:
            problems.append(f"missing required variable(s): {', '.join(missing)}")
        if undeclared:
            problems.append(f"undeclared variable(s): {', '.join(undeclared)}")
        raise PromptRenderError(
            f"prompt {name!r} cannot be rendered — " + "; ".join(problems)
        )
    return Template(template).substitute(**variables)
