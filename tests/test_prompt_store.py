"""Prompt-store render tests — OL#112 (CODE_CONVENTIONS D1, 提示词是一等资产).

Covers the three things the issue asks for:

1. a required variable missing → a loud error naming that variable;
2. rendering with the normal variable set → non-empty output;
3. the rendered default prompts are **byte-identical** to what
   ``router.py`` produced before the prompts moved into ``prompts/``.

Point 3 is pinned as SHA-256 digests captured from the pre-extraction code
(``git show HEAD:src/ol_pool/router.py``, prompts built by ``ModelPool.translate``
and ``ModelPool.judge``). A digest mismatch means the LLM-facing bytes changed —
a translation-quality regression, not a refactor detail.

``TestPromptSingleDefinition`` is the drift guard the issue names: a prompt
copied into a second module and edited there would silently diverge. It asserts
each prompt's text exists in exactly one place in ``src/`` — its ``.txt`` file.
"""
from __future__ import annotations

import ast
import hashlib
from pathlib import Path

import pytest

from ol_pool.prompts import (
    PROMPTS_DIR,
    PromptRenderError,
    available_prompts,
    load_prompt,
    prompt_variables,
    render_prompt,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"

# sha256 of the exact prompt bytes ModelPool sent to the LLM before #112.
BASELINE_DIGESTS = {
    "translate_system/en-zh": "8d246fcd5d482a272d8f1ae3af20006dd955b25ee01590064985815f0cbba607",
    "translate_system/zh-en": "ebb45d46ae4264bf3401264ac1ec84962afa1ad7a675a53dad7c2754f350d34e",
    "translate_user/plain-en-zh": "8d2196dbd517dd71fa7339ecef6749afd403b91d6e09fee008ddf1a0439d4d47",
    "translate_user/plain-zh-en": "d1189f26e748ccb23e74394c484dfe4a85c42d8a75afadea7a298c3bf44f7ccb",
    "translate_user/tm-glossary-en-zh": "09c20dfd34b9a721ee5a08ea13216ab00038c98047db58b2cb6d60ad5837f98b",
    "judge_system/en-zh": "36ecfc545bb11c690ee7eaa299a6ff2e7e0bfa19eb21f0bd93e4ea0f6b49a4b6",
    "judge_system/zh-en": "36ecfc545bb11c690ee7eaa299a6ff2e7e0bfa19eb21f0bd93e4ea0f6b49a4b6",
    "judge_user/en-zh": "4c448b27e5161004a759f231b7eb0590b81a65fe5a95799baa94476279d0da4e",
    "judge_user/zh-en": "f93374a5420ba85ece0645eb4b59abcf9c4ad1d0bde0d55d8cb89c350ee3d3df",
    "judge_user/glossary-en-zh": "e17b6d7221414757b3b5fee9bcf20072c5e43cd38eabc37cd3b446cce1093e3c",
}

DELIMITED = "[USER_TEXT_START]\nHello world. 价格是 100 美元。\n[USER_TEXT_END]"
SHORT_DELIMITED = "[USER_TEXT_START]\nHello world\n[USER_TEXT_END]"


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def rendered_baseline_cases() -> dict[str, str]:
    """Each baseline case rebuilt from the prompt store."""
    return {
        "translate_system/en-zh": render_prompt(
            "translate_system", source_lang="en", target_lang="zh"
        ),
        "translate_system/zh-en": render_prompt(
            "translate_system", source_lang="zh", target_lang="en"
        ),
        "translate_user/plain-en-zh": render_prompt(
            "translate_user", source_lang="en", target_lang="zh", user_text=DELIMITED
        ),
        "translate_user/plain-zh-en": render_prompt(
            "translate_user", source_lang="zh", target_lang="en", user_text=DELIMITED
        ),
        "translate_user/tm-glossary-en-zh": "\n\n".join([
            "Translation Memory (top 3 matches):\n- a → b\n- c → d\n- e → f",
            "Glossary (top 5 terms):\n- t1 → T1\n- t2 → T2\n- t3 → T3\n- t4 → T4\n- t5 → T5",
            render_prompt(
                "translate_user", source_lang="en", target_lang="zh", user_text=SHORT_DELIMITED
            ),
        ]),
        "judge_system/en-zh": render_prompt("judge_system"),
        "judge_system/zh-en": render_prompt("judge_system"),
        "judge_user/en-zh": render_prompt(
            "judge_user",
            source_lang="en",
            source="Hello",
            target_lang="zh",
            target="你好",
            terminology_section="",
        ),
        "judge_user/zh-en": render_prompt(
            "judge_user",
            source_lang="zh",
            source="Hello",
            target_lang="en",
            target="你好",
            terminology_section="",
        ),
        "judge_user/glossary-en-zh": render_prompt(
            "judge_user",
            source_lang="en",
            source="Hello",
            target_lang="zh",
            target="你好",
            terminology_section="\nTerminology: term → 术语",
        ),
    }


class TestPromptStoreBasics:
    def test_store_lists_the_four_extracted_prompts(self):
        assert available_prompts() == [
            "judge_system",
            "judge_user",
            "translate_system",
            "translate_user",
        ]

    @pytest.mark.parametrize("name", ["judge_system", "judge_user", "translate_system",
                                      "translate_user"])
    def test_prompt_file_is_non_empty(self, name):
        assert load_prompt(name).strip()

    def test_declared_variables_are_stable(self):
        assert prompt_variables("translate_system") == ["source_lang", "target_lang"]
        assert prompt_variables("translate_user") == ["source_lang", "target_lang", "user_text"]
        assert prompt_variables("judge_user") == [
            "source", "source_lang", "target", "target_lang", "terminology_section",
        ]
        assert prompt_variables("judge_system") == []


class TestRenderIsNonEmpty:
    def test_translate_system_render_is_non_empty(self):
        out = render_prompt("translate_system", source_lang="en", target_lang="zh")
        assert out
        assert "en to zh" in out

    def test_translate_user_render_contains_the_user_text(self):
        out = render_prompt(
            "translate_user", source_lang="en", target_lang="zh", user_text=DELIMITED
        )
        assert out == f"Translate from en to zh: {DELIMITED}"

    def test_judge_system_render_is_non_empty(self):
        assert render_prompt("judge_system")

    def test_judge_user_render_embeds_both_texts(self):
        out = render_prompt(
            "judge_user",
            source_lang="en",
            source="Hello",
            target_lang="zh",
            target="你好",
            terminology_section="",
        )
        assert "[USER_TEXT_START]\nHello\n[USER_TEXT_END]" in out
        assert "[USER_TEXT_START]\n你好\n[USER_TEXT_END]" in out
        assert "$" not in out, "every placeholder must be substituted"


class TestMissingVariableFailsLoud:
    def test_missing_required_variable_names_the_variable(self):
        with pytest.raises(PromptRenderError) as excinfo:
            render_prompt("translate_system", source_lang="en")
        assert "target_lang" in str(excinfo.value)

    def test_missing_source_names_the_variable(self):
        with pytest.raises(PromptRenderError, match="source_lang"):
            render_prompt("judge_user", target_lang="zh", target="你好",
                          terminology_section="")

    def test_missing_variable_does_not_render_empty_string(self):
        with pytest.raises(PromptRenderError):
            render_prompt("translate_user", source_lang="en", target_lang="zh")

    def test_undeclared_variable_fails_loud(self):
        with pytest.raises(PromptRenderError, match="target_lnag"):
            render_prompt(
                "translate_system", source_lang="en", target_lang="zh", target_lnag="zh"
            )

    def test_unknown_prompt_name_fails_loud(self):
        with pytest.raises(PromptRenderError, match="unknown prompt 'nope'"):
            load_prompt("nope")

    def test_path_traversal_name_fails_loud(self):
        with pytest.raises(PromptRenderError, match="unknown prompt"):
            load_prompt("../../etc/passwd")


class TestPromptsAreByteIdenticalToPreExtraction:
    """(c) the refactor changed the bytes the LLM sees — prove it did not."""

    def test_every_baseline_case_is_covered_by_the_store(self):
        assert sorted(rendered_baseline_cases()) == sorted(BASELINE_DIGESTS)

    @pytest.mark.parametrize("case", sorted(BASELINE_DIGESTS))
    def test_rendered_prompt_digest_matches_pre_refactor_baseline(self, case: str) -> None:
        assert digest(rendered_baseline_cases()[case]) == BASELINE_DIGESTS[case], (
            f"{case}: rendered prompt differs from the bytes router.py sent before "
            f"OL#112 — this is a translation-quality change, not a refactor"
        )


# A copied prompt drifts even when the copier re-did the interpolations, so the
# prose has to be matched independently of the placeholders. Window size 100 is
# the smallest that separates these prompts from the unrelated prompts that
# share boilerplate (the SECURITY paragraph, the USER_TEXT delimiters).
_WINDOW = 100
_WINDOW_STEP = 20


def _collapsed(text: str) -> str:
    return " ".join(text.split())


def _windows(prompt: str) -> list[str]:
    """Overlapping slices of the whitespace-collapsed prompt."""
    flat = _collapsed(prompt)
    if len(flat) <= _WINDOW:
        return [flat]
    return [flat[i:i + _WINDOW] for i in range(0, len(flat) - _WINDOW + 1, _WINDOW_STEP)]


class TestPromptSingleDefinition:
    """The bug class the issue names: a prompt copied to a second location drifts."""

    @pytest.mark.parametrize("name", ["judge_system", "judge_user", "translate_system",
                                      "translate_user"])
    def test_prompt_text_is_defined_only_by_its_own_file(self, name: str) -> None:
        needle = _collapsed(load_prompt(name))
        owners = [
            path.relative_to(SRC).as_posix()
            for path in SRC.rglob("*")
            if path.is_file()
            and path.suffix in {".py", ".txt"}
            and needle in _collapsed(path.read_text(encoding="utf-8", errors="ignore"))
        ]
        assert owners == [f"ol_pool/prompts/{name}.txt"], (
            f"prompt {name!r} must be defined exactly once under "
            f"src/ol_pool/prompts/; found copies in {owners}"
        )

    @pytest.mark.parametrize("name", ["judge_system", "judge_user", "translate_system",
                                      "translate_user"])
    def test_prompt_prose_is_not_inlined_in_any_python_source(self, name: str) -> None:
        needles = _windows(load_prompt(name))
        offenders = {
            path.relative_to(SRC).as_posix(): [
                w for w in needles
                if w in _collapsed(path.read_text(encoding="utf-8", errors="ignore"))
            ]
            for path in SRC.rglob("*.py")
        }
        hits = {p: len(w) for p, w in offenders.items() if w}
        assert not hits, (
            f"prompt {name!r} prose is duplicated in {hits} — a second home for a "
            f"prompt drifts silently; keep it in prompts/{name}.txt"
        )


class TestPackagingIncludesPrompts:
    def test_package_data_covers_txt(self):
        pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        package_data = pyproject.split("[tool.setuptools.package-data]", 1)[1]
        assert '"*.txt"' in package_data.split("\n\n", 1)[0], (
            "setuptools package-data must include \"*.txt\" or an installed "
            "wheel ships no prompts and every render fails at runtime"
        )

    def test_manifest_ships_the_prompt_directory(self):
        manifest = (REPO_ROOT / "MANIFEST.in").read_text(encoding="utf-8")
        assert "recursive-include src/ol_pool/prompts *.txt" in manifest

    def test_prompt_files_live_next_to_the_loader(self) -> None:
        assert PROMPTS_DIR.name == "prompts"
        assert all(p.suffix == ".txt" for p in PROMPTS_DIR.glob("*.txt"))


class TestRouterUsesTheStore:
    """router.py must consume the store, not rebuild prompts inline."""

    def test_router_imports_render_prompt(self):
        tree = ast.parse((SRC / "ol_pool/router.py").read_text(encoding="utf-8"))
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module == "ol_pool.prompts"
            for alias in node.names
        }
        assert "render_prompt" in imported

    @pytest.mark.parametrize(
        ("func", "prompt"),
        [("translate", "translate_system"), ("translate", "translate_user"),
         ("judge", "judge_system"), ("judge", "judge_user")],
    )
    def test_function_renders_its_prompt(self, func: str, prompt: str) -> None:
        source = (SRC / "ol_pool/router.py").read_text(encoding="utf-8")
        assert f'"{prompt}"' in source, f"{func} must render {prompt} from the store"
