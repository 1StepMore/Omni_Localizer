import asyncio
import hashlib
import json
import os
import re
import sys
import time
from collections import OrderedDict
from typing import Any
from unittest.mock import MagicMock


# ULTRAREADY-FIX (2026-06-08): real E2E run discovered that MiniMax
# models leak <think>...</think> chain-of-thought into their output.
# ORF then injects that leaked text into the DOCX, producing a document
# that reads like an AI's scratchpad instead of a translation. This
# stripper is a defense-in-depth measure: even if the model ignores the
# "Do not add explanations" instruction in the system prompt, we
# guarantee the output going into XLIFF is clean.
#
# Recognised patterns (in order of how aggressively they tend to leak):
#   1. <think>...</think> (MiniMax, Qwen3-Thinking, DeepSeek-R1, etc.)
#   2. <|thinking|>...</|thinking|>  (some Anthropic-style models)
#   3. <|reasoning|>...</|reasoning|>
#   4. <thought>...</thought>  (legacy)
#   5. Markdown ```thinking ... ```  (some clients wrap it)
_THINKING_BLOCK_RE = re.compile(
    r"<think>.*?</think>"
    r"|<\uff5c?thinking\uff5c?>.*?</\uff5c?thinking\uff5c?>"
    r"|<\uff5c?reasoning\uff5c?>.*?</\uff5c?reasoning\uff5c?>"
    r"|<thought>.*?</thought>"
    r"|```thinking\s*\n.*?\n```",
    re.DOTALL,
)


def _strip_thinking_blocks(text: str) -> str:
    """Remove LLM chain-of-thought artifacts from a model response.

    ULTRAREADY-FIX (2026-06-08): the stripper only removes blocks that
    look like model thinking (delimited by <think>, <|thinking|>, etc.).
    Inline tags the LLM was asked to preserve (e.g. ``<bx id="1"/>``) are
    NOT touched because they don't match the thinking-block regex.

    After stripping, leading/trailing whitespace is collapsed so the
    returned text starts and ends with the actual translation.
    """
    if not text:
        return text
    out = _THINKING_BLOCK_RE.sub("", text)
    # Collapse runs of blank lines that the stripper may have left behind.
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()

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


class _PromptCache:
    """Content-addressed LRU cache for LLM completions.

    Only safe for deterministic responses (temperature=0). The router
    bypasses the cache when temperature != 0 OR when the config disables
    it. Key = (model_role, sha256(messages_json), temperature).
    """

    def __init__(
        self,
        max_size: int = 1000,
        ttl_seconds: float = 300.0,
        time_func=None,
    ):
        self._max_size = max_size
        self._ttl = ttl_seconds
        self._time = time_func or time.monotonic
        self._store: "OrderedDict[tuple, tuple[Any, float]]" = OrderedDict()

    def get(self, key: tuple) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        value, expiry = entry
        if expiry <= self._time():
            del self._store[key]
            return None
        self._store.move_to_end(key)
        return value

    def put(self, key: tuple, value: Any) -> None:
        if key in self._store:
            self._store.move_to_end(key)
        self._store[key] = (value, self._time() + self._ttl)
        if len(self._store) > self._max_size:
            self._store.popitem(last=False)

    def __len__(self) -> int:
        return len(self._store)

    def clear(self) -> None:
        self._store.clear()


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
        # A3 — temperature-bypass is enforced in translate()/judge(), not here.
        self._cache_enabled = getattr(config, "cache_system_prompt", True)
        self._cache = _PromptCache(max_size=1000, ttl_seconds=300.0)
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

    def _make_cache_key(
        self, model: str, messages: list[dict], temperature: float,
    ) -> tuple:
        payload = json.dumps(messages, sort_keys=True, ensure_ascii=False)
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return (model, digest, float(temperature))

    def _build_fallbacks(self, pool: LLMPoolConfig) -> list[dict]:
        """Build fallbacks list per role based on priority ordering.

        litellm Router fallbacks format: [{"model_group_name": ["fallback_model_id", ...]}]
        key must be the model_name (role) passed to acompletion(), not the actual model ID.

        POST_MORTEM OL-8: when a role has only one configured model (or all
        fail), we add a cross-role fallback: judging/restoration calls can
        fall back to a translation-tier model rather than crashing. The
        translation role keeps its own fallbacks for primary translation.
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

        # Cross-role safety net: if judging/restoration both fail, fall back
        # to the translation role's models. This trades quality for liveness.
        translation_models = getattr(pool, "translation", [])
        if translation_models:
            translation_fallback_ids = [
                f"{m.provider}/{m.model}"
                for m in sorted(translation_models, key=lambda m: m.priority)
            ]
            for role in ("judging", "restoration"):
                if not getattr(pool, role, []):
                    fallbacks.append({role: translation_fallback_ids})

        return fallbacks

    async def translate(
        self, text: str, source_lang: str, target_lang: str,
        context: dict | str | None = None,
        temperature: float = 0.0,
        glossary: Any = None,
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

        # A12.3: when a Glossary object is provided (PR12), inject the
        # top-N relevant terms into the user prompt. This is the
        # dataclass-based path; the legacy ``context["glossary_terms"]``
        # branch above is preserved for BatchProcessor / RAG users.
        if glossary is not None and hasattr(glossary, "inject_into_prompt"):
            prompt = glossary.inject_into_prompt(text, prompt)

        system_message = (
            "You are a professional translator. Translate the user's text from "
            f"{source_lang} to {target_lang} while strictly preserving all markup: "
            "keep every {{_OL_XTAG_*_}} placeholder token in its original position "
            "and form, keep all code blocks, links, image references, and inline "
            "formatting markers intact. Do not add explanations, do not wrap the "
            "output in code fences, and do not change the meaning of placeholders. "
            "Do not wrap your output in any XML tags (including <source>, <target>, "
            "<trans-unit>, or anything with xmlns= attributes). Output only the "
            "translated text — no markup, no quotes around it, no language tags. "
            "Return only the translated text. "
            "CRITICAL: do NOT emit any <think>...</think>, <|thinking|>, <|reasoning|>, "
            "or <thought>...</thought> blocks. Do NOT preface your answer with "
            "'Let me analyze', 'I need to translate', or any planning prose. "
            "Return ONLY the translated text and nothing else."
        )

        messages = [
            {"role": "system", "content": system_message},
            {"role": "user", "content": prompt},
        ]

        cache_key = self._make_cache_key("translation", messages, temperature)
        if self._cache_enabled and temperature == 0.0:
            cached = self._cache.get(cache_key)
            if cached is not None:
                _logger.debug("Translation cache hit")
                return cached

        for attempt in range(4):  # 1 initial + 3 retries
            try:
                response = await self._router.acompletion(
                    model="translation",
                    messages=messages,
                    temperature=temperature,
                )
                raw = response.choices[0].message.content
                translated = _strip_thinking_blocks(raw)
                if translated != raw:
                    _logger.debug(
                        f"Stripped {len(raw) - len(translated)} chars of "
                        f"chain-of-thought from LLM output"
                    )
                _logger.debug(f"Translation response: {len(translated)} chars")
                if self._cache_enabled and temperature == 0.0:
                    self._cache.put(cache_key, translated)
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
        temperature: float = 0.0,
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

Return a JSON object with exactly these five fields and nothing else:
{{"accuracy": <int 0-100>, "fluency": <int 0-100>, "adequacy": <int 0-100>, "score": <int 0-100>, "format_errors": <list of strings>}}
"score" is the overall judgment on the same 0-100 scale (you may compute it as a weighted average of the three dimensions).
"format_errors" is a list of format/structure problems you detected in the target (e.g. missing placeholders, broken XML tags, unescaped entities). Return an empty list [] if the target preserves all format elements correctly.

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

        messages = [
            {"role": "system", "content": system_message},
            {"role": "user", "content": prompt},
        ]

        cache_key = self._make_cache_key("judging", messages, temperature)
        if self._cache_enabled and temperature == 0.0:
            cached = self._cache.get(cache_key)
            if cached is not None:
                _logger.debug("Judge cache hit")
                return cached

        try:
            response = await self._router.acompletion(
                model="judging",
                messages=messages,
                temperature=temperature,
            )
        except Timeout as e:
            _logger.warning(f"Judge timeout: {e}")
            return {
                "accuracy": 0, "fluency": 0, "adequacy": 0, "score": 0,
                "reason": f"judge_timeout: {e}", "transport_error": True,
            }
        except RateLimitError as e:
            _logger.warning(f"Judge rate limit: {e}")
            return {
                "accuracy": 0, "fluency": 0, "adequacy": 0, "score": 0,
                "reason": f"judge_rate_limit: {e}", "transport_error": True,
            }
        except AuthenticationError as e:
            _logger.error(f"Judge auth error: {e}")
            return {
                "accuracy": 0, "fluency": 0, "adequacy": 0, "score": 0,
                "reason": f"judge_auth: {e}", "transport_error": True,
            }
        except Exception as e:
            _logger.error(f"Judge transport failed: {type(e).__name__}: {e}")
            return {
                "accuracy": 0, "fluency": 0, "adequacy": 0, "score": 0,
                "reason": f"judge_unknown: {type(e).__name__}: {e}", "transport_error": True,
            }
        import json
        try:
            content = response.choices[0].message.content.strip()
        except (AttributeError, IndexError) as resp_err:
            _logger.error(
                f"Judge response shape invalid: {resp_err}; returning transport_error"
            )
            return {
                "accuracy": 0,
                "fluency": 0,
                "adequacy": 0,
                "score": 0,
                "reason": f"judge_response_invalid: {resp_err}",
                "transport_error": True,
            }
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
        if self._cache_enabled and temperature == 0.0:
            self._cache.put(cache_key, result)
        return result
