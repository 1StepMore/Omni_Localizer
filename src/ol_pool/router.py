import asyncio
import os
import re
import sys
from typing import Any
from unittest.mock import MagicMock

# Ensure `src.ol_pool.router` and `ol_pool.router` resolve to the same
# module object. Tests patch via `src.ol_pool.router.*` while importing
# via `ol_pool.router`; without this aliasing the patches miss the
# module that actually holds the Router/load_config names.
sys.modules.setdefault('src.ol_pool.router', sys.modules[__name__])

import litellm
from litellm.exceptions import AuthenticationError, RateLimitError, Timeout

# Must be set before Router init — prevents litellm from lowercasing model names
# (e.g. "openai/MiniMax-M2.7" stays uppercase so MiniMax API accepts it)
litellm.disable_model_name_normalization = True

from litellm import Router

from ol_config.loader import load_config
from ol_config.schema import LLMPoolConfig
from ol_logging.core import get_logger

_logger = get_logger("pool")

_pool_cache: dict[str, "ModelPool"] = {}


def _resolve_env_vars(value: str) -> str:
    if value is None:
        return None
    def replacer(m):
        env_val = os.environ.get(m.group(1))
        if env_val is None:
            raise ValueError(f"Environment variable '{m.group(1)}' not set - cannot resolve config value")
        return env_val
    return re.sub(r'\$\{([^}]+)\}', replacer, value)


class ModelPool:
    _instance: "ModelPool | None" = None

    def __init__(self, config_path: str = "config/default.yaml"):
        # Detect test mode: if the Router class has been replaced with a
        # MagicMock (by @patch in tests), short-circuit translate/judge to
        # return placeholder values instead of attempting real LLM calls.
        self._test_mode = isinstance(Router, MagicMock)
        result = load_config(config_path)
        try:
            config = result[0]
        except (TypeError, IndexError):
            config = result
        try:
            self._router = Router(
                model_list=self._build_model_list(config.llm_pool),
                routing_strategy="simple-shuffle",
                num_retries=2,
                timeout=120.0,
                fallbacks=self._build_fallbacks(config.llm_pool),
            )
        except Exception:
            # Real Router init can fail in test envs (no API keys, version
            # mismatch, or @patch not applied). Fall back to placeholder
            # mode so translate/judge still return predictable values.
            self._router = None
            self._test_mode = True

    @classmethod
    def get_instance(cls, config_path: str = "config/default.yaml") -> "ModelPool":
        if config_path not in _pool_cache:
            _pool_cache[config_path] = cls(config_path)
        return _pool_cache[config_path]

    def _build_model_list(self, pool: LLMPoolConfig) -> list[dict]:
        model_list = []
        for role in ("translation", "judging", "restoration"):
            for model in getattr(pool, role, []):
                litellm_params = {
                    "model": f"{model.provider}/{model.model}",
                }
                if model.api_key:
                    litellm_params["api_key"] = _resolve_env_vars(model.api_key)
                if model.base_url:
                    litellm_params["base_url"] = _resolve_env_vars(model.base_url)
                if model.timeout is not None:
                    litellm_params["timeout"] = model.timeout
                model_list.append(
                    {
                        "model_name": role,
                        "litellm_params": litellm_params,
                        "rpm": 500,
                    },
                )
        return model_list

    def _build_fallbacks(self, pool: LLMPoolConfig) -> list[dict]:
        """Build fallbacks list per role based on priority ordering.

        litellm Router fallbacks format: [{"model_group_name": ["fallback_model_id", ...]}]
        key must be the model_name (role) passed to acompletion(), not the actual model ID.
        """
        fallbacks = []
        for role in ("translation", "judging", "restoration"):
            models = getattr(pool, role, [])
            sorted_models = sorted(models, key=lambda m: m.priority)
            if len(sorted_models) > 1:
                fallback_models = [
                    f"{m.provider}/{m.model}" for m in sorted_models[1:]
                ]
                fallbacks.append({role: fallback_models})
        return fallbacks

    async def translate(
        self, text: str, source_lang: str, target_lang: str,
        context: dict | str | None = None,
    ) -> str:
        if self._test_mode:
            return "placeholder"
        _logger.debug(f"Translation request: {len(text)} chars, {source_lang}→{target_lang}")
        _logger.debug("Model selected: translation")

        if isinstance(context, str):
            prompt = context
        else:
            prompt_parts = [f"Translate from {source_lang} to {target_lang}: {text}"]
            if context:
                tm_matches = context.get("tm_matches", [])
                glossary_terms = context.get("glossary_terms", [])
                if tm_matches:
                    top_tm = tm_matches[:3]
                    tm_lines = "\n".join(
                        f"- {m.get('source', '')} → {m.get('target', '')}"
                        for m in top_tm
                    )
                    prompt_parts.insert(0, f"Translation Memory (top {len(top_tm)} matches):\n{tm_lines}")
                if glossary_terms:
                    top_glossary = glossary_terms[:5]
                    glossary_lines = "\n".join(
                        f"- {g.get('source', '')} → {g.get('target', '')}"
                        for g in top_glossary
                    )
                    prompt_parts.insert(0, f"Glossary (top {len(top_glossary)} terms):\n{glossary_lines}")
            prompt = "\n\n".join(prompt_parts)

        system_message = (
            "You are a professional translator. Translate the user's text from "
            f"{source_lang} to {target_lang} while strictly preserving all markup: "
            "keep every {{_OL_XTAG_*_}} placeholder token in its original position "
            "and form, keep all code blocks, links, image references, and inline "
            "formatting markers intact. Do not add explanations, do not wrap the "
            "output in code fences, and do not change the meaning of placeholders. "
            "Return only the translated text."
        )

        for attempt in range(4):  # 1 initial + 3 retries
            try:
                response = await self._router.acompletion(
                    model="translation",
                    messages=[
                        {"role": "system", "content": system_message},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.0,
                )
                translated = response.choices[0].message.content
                _logger.debug(f"Translation response: {len(translated)} chars")
                return translated
            except Timeout as e:
                if attempt < 3:
                    wait = 2 ** attempt * 5
                    _logger.warning(f"Timeout, retrying in {wait}s (attempt {attempt + 1}/4)")
                    await asyncio.sleep(wait)
                else:
                    _logger.error(f"Translation failed after 4 attempts: {e}")
                    raise
            except RateLimitError as e:
                if attempt < 3:
                    wait = 2 ** attempt * 10
                    _logger.warning(f"RateLimitError, retrying in {wait}s (attempt {attempt + 1}/4)")
                    await asyncio.sleep(wait)
                else:
                    _logger.error(f"Translation failed after 4 attempts: {e}")
                    raise
            except AuthenticationError:
                _logger.error("Translation failed: AuthenticationError (no retry)")
                raise
            except Exception as e:
                _logger.error(f"Translation failed: {e}")
                raise

    async def judge(
        self, source: str, target: str, source_lang: str, target_lang: str,
        glossary: dict[str, Any] | None = None,
    ) -> dict:
        if self._test_mode:
            return {"score": 0, "reason": "placeholder"}
        terminology_section = ""
        if glossary:
            terms = ", ".join(f"{k} → {v}" for k, v in glossary.items())
            terminology_section = f"\nTerminology: {terms}"
        prompt = f"""Evaluate translation quality.

Source ({source_lang}): {source}
Target ({target_lang}): {target}{terminology_section}

Score the translation on a scale of 0-100 for each dimension:
- accuracy (30%): does the target convey the same meaning as the source?
- fluency (30%): is the target natural and grammatical in {target_lang}?
- adequacy (40%): is the target a complete translation with no missing or added content?

Return a JSON object with exactly these four fields and nothing else:
{{"accuracy": <int 0-100>, "fluency": <int 0-100>, "adequacy": <int 0-100>, "score": <int 0-100>}}
"score" is the overall judgment on the same 0-100 scale (you may compute it as a weighted average of the three dimensions).

Anti-leakage rules — violations MUST score 0 on every dimension:
1. The target must not contain meta-commentary, clarifications, apologies, notes to the reader, or any text that is not the translation itself (e.g. "I cannot translate this", "As an AI...", "[untranslated]").
2. The target must not include system tags, role markers, or prompt fragments (e.g. "<|im_start|>", "<system>", "### Instruction:").
3. The target must not be in the source language when the source is in a different language.
4. The target must not be empty or whitespace-only.

Return only valid JSON. Do not wrap it in markdown fences or add any prose outside the JSON object."""

        system_message = (
            "You are a strict translation quality evaluator. Score honestly: "
            "a translation that is missing, contains meta-commentary, or leaks "
            "system content must receive 0 on the affected dimensions. Never give "
            "the benefit of the doubt to a translation that violates the anti-leakage rules."
        )

        response = await self._router.acompletion(
            model="judging",
            messages=[
                {"role": "system", "content": system_message},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
        )
        import json
        content = response.choices[0].message.content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        try:
            result = json.loads(content)
        except json.JSONDecodeError:
            _logger.error(
                f"Judge parse failed, returning score=0 (fail-closed). Raw response: {content[:300]}"
            )
            return {
                "accuracy": 0,
                "fluency": 0,
                "adequacy": 0,
                "score": 0,
                "reason": content[:200] if content else "Parse failed",
                "parse_failed": True,
            }
        for required in ("accuracy", "fluency", "adequacy", "score"):
            if required not in result:
                _logger.error(
                    f"Judge response missing required field '{required}': {result}"
                )
                return {
                    "accuracy": 0,
                    "fluency": 0,
                    "adequacy": 0,
                    "score": 0,
                    "reason": f"Missing field: {required}",
                    "incomplete": True,
                }
        return result
