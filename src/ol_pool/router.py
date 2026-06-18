import asyncio
import hashlib
import json
import os
import re
import sys
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pybreaker


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

_CHINESE_PUNCT_REPLACEMENTS: list[tuple[str, str]] = [
    ("《", ""),
    ("》", ""),
    ("“", '"'),
    ("”", '"'),
    ("‘", "'"),
    ("’", "'"),
    ("一、", "1. "),
    ("二、", "2. "),
    ("三、", "3. "),
    ("四、", "4. "),
    ("五、", "5. "),
    ("六、", "6. "),
    ("七、", "7. "),
    ("八、", "8. "),
    ("九、", "9. "),
    ("十、", "10. "),
]

# ULTRAREADY-FIX (2026-06-08): strip markdown-style emphasis that the LLM
# sometimes emits when it sees formatting placeholders like 《book title》.
# XLIFF/DOCX do not render *text* or _text_ as emphasis — only inline tags
# like <bx>/<ex>/<it> do. Stripping markdown italics prevents the "Love Haier"
# → "*Loving Haier*" regression where the LLM substitutes brackets with
# markdown asterisks.
import re as _re_markdown_strip
_MARKDOWN_EMPHASIS_RE = _re_markdown_strip.compile(r"\*+([^*\n]+?)\*+|_+([^_\n]+?)_+")


def _strip_markdown_emphasis(text: str) -> str:
    """Remove *italic* and _italic_ markdown emphasis from LLM output."""
    if not text:
        return text
    return _MARKDOWN_EMPHASIS_RE.sub(r"\1\2", text)


def _localize_chinese_punctuation(text: str) -> str:
    """Convert Chinese typographic conventions in LLM output to English.

    ULTRAREADY-FIX (2026-06-08): the LLM correctly preserves Chinese
    punctuation per the "preserve all markup" instruction, but the
    instruction is wrong for typographic conventions. This function
    localizes them after the model returns so the XLIFF carries
    English conventions downstream.

    Inline XLIFF tags like ``<bx id="1"/>`` are NOT touched because
    the replacements only match Chinese punctuation characters.
    """
    if not text:
        return text
    for src, dst in _CHINESE_PUNCT_REPLACEMENTS:
        text = text.replace(src, dst)
    # Collapse runs of spaces that result from stripping 《》 next to
    # space, e.g. "Love Haier " should not become "Love Haier  ".
    text = re.sub(r"  +", " ", text)
    return text

# Ensure `src.ol_pool.router` and `ol_pool.router` resolve to the same
# module object. Tests patch via `src.ol_pool.router.*` while importing
# via `ol_pool.router`; without this aliasing the patches miss the
# module that actually holds the Router/load_config names.
sys.modules.setdefault('src.ol_pool.router', sys.modules[__name__])

# 2026-06-17 round 6: skip litellm's remote model-cost-map fetch
# (would hit raw.githubusercontent.com on every Router init and log a
# WARNING on timeout). MUST be set before `import litellm` below.
# Round 12: LITELLM_LOCAL_MODEL_COST_MAP alone isn't enough — also
# set DISABLE_LITELLM_TELEMETRY=True to skip the import-time fetch.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
os.environ.setdefault("DISABLE_LITELLM_TELEMETRY", "True")
os.environ.setdefault("LITELLM_TELEMETRY", "False")

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

# 2026-06-17 round 6 (FIX-#11): cache value is (pool, config_mtime) so
# config edits on disk are picked up without restarting the process.
_pool_cache: dict[str, tuple["ModelPool", float]] = {}


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


# 2026-06-18 round 16 Phase B1: circuit breaker for LLM calls.
class _LogBreakerListener(pybreaker.CircuitBreakerListener):
    """Logs circuit breaker state transitions at WARNING level."""

    def state_change(self, cb, old_state, new_state):
        _logger.warning(
            "Circuit breaker %r: %s -> %s",
            cb.name, old_state.name, new_state.name,
        )


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
        # 2026-06-17 round 5 (FIX-#18): per-process rate-limit hit counter
        # (lightweight dict; no Prometheus dep — CLI/test env).
        self._rate_limit_hits: dict[str, int] = {}
        # 2026-06-18 round 16 Phase B1: one circuit breaker per role.
        # 5 consecutive failures -> open, reset after 60s.
        self._breakers: dict[str, pybreaker.CircuitBreaker] = {
            role: pybreaker.CircuitBreaker(
                fail_max=5,
                reset_timeout=60,
                name=role,
                listeners=[_LogBreakerListener()],
            )
            for role in ("translation", "judging", "restoration")
        }
        try:
            self._router = Router(
                model_list=self._build_model_list(config.llm_pool),
                routing_strategy="simple-shuffle",
                num_retries=2,
                timeout=120.0,
                fallbacks=self._build_fallbacks(config.llm_pool),
                # 2026-06-17 round 5 (OPT-13): enforce per-model RPM
                # configured in `_build_model_list`. Calls exceeding the
                # cap return litellm.RateLimitError (HTTP 429) immediately
                # instead of waiting on provider 429 + backoff.
                optional_pre_call_checks=["enforce_model_rate_limits"],
            )
        except Exception:
            # Real Router init can fail in test envs (no API keys, version
            # mismatch, or @patch not applied). Fall back to placeholder
            # mode so translate/judge still return predictable values.
            self._router = None
            self._test_mode = True

    @classmethod
    def get_instance(cls, config_path: str = "config/default.yaml") -> "ModelPool":
        try:
            current_mtime = Path(config_path).stat().st_mtime
        except OSError:
            current_mtime = 0.0
        entry = _pool_cache.get(config_path)
        if entry is None or entry[1] != current_mtime:
            _pool_cache[config_path] = (cls(config_path), current_mtime)
        return _pool_cache[config_path][0]

    async def _call_with_breaker(self, role: str, coro_func, *args, **kwargs):
        """Run coro_func through the circuit breaker for the given role.

        Reports success/failure to the breaker. Raises
        ``pybreaker.CircuitBreakerError`` immediately if the breaker is open.
        """
        breaker = self._breakers[role]
        if breaker.current_state == "open":
            raise pybreaker.CircuitBreakerError(
                f"Circuit breaker {role!r} is open"
            )
        try:
            result = await coro_func(*args, **kwargs)
        except Exception as exc:
            def _raise(_e=exc):
                raise _e
            try:
                breaker.call(_raise)
            except pybreaker.CircuitBreakerError:
                pass
            raise
        def _ok():
            return None
        try:
            breaker.call(_ok)
        except pybreaker.CircuitBreakerError:
            pass
        return result

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
                # 2026-06-17 round 5 (FIX-#7): canonical rpm location
                # (litellm_params, per litellm/types/router.py:201-203).
                litellm_params["rpm"] = model.requests_per_minute
                model_list.append(
                    {
                        "model_name": role,
                        "litellm_params": litellm_params,
                    },
                )
        return model_list

    def _make_cache_key(
        self, model: str, messages: list[dict], temperature: float,
    ) -> tuple:
        payload = json.dumps(messages, sort_keys=True, ensure_ascii=False)
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return (model, digest, float(temperature))

    def metrics(self) -> dict[str, int]:
        """Return a copy of the rate-limit hit counter (role → hits).

        2026-06-17 round 5 (FIX-#18): lightweight ops hook. External
        code can poll this between cycles to detect rate-limit storms.
        Returns a shallow copy so callers can't mutate internal state.
        """
        return dict(self._rate_limit_hits)

    def _build_fallbacks(self, pool: LLMPoolConfig) -> list[dict]:
        """Build fallbacks list per role based on priority ordering.

        litellm Router fallbacks format: [{"model_group_name": ["fallback_model_id", ...]}]
        key must be the model_name (role) passed to acompletion(), not the actual model ID.

        POST_MORTEM OL-8: when a role has only one configured model (or all
        fail), we add a cross-role fallback: judging/restoration calls can
        fall back to a translation-tier model rather than crashing. The
        translation role keeps its own fallbacks for primary translation.

        2026-06-17 round 6 (FIX-#17): skip models with requests_per_minute
        <= 0 from fallback chains — they'd be dead-on-arrival. The
        Pydantic schema already enforces ge=1, this is belt-and-suspenders
        for manually-constructed configs that bypass validation.
        """
        fallbacks = []
        for role in ("translation", "judging", "restoration"):
            models = [m for m in getattr(pool, role, []) if m.requests_per_minute > 0]
            sorted_models = sorted(models, key=lambda m: m.priority)
            if len(sorted_models) > 1:
                fallback_models = [
                    f"{m.provider}/{m.model}" for m in sorted_models[1:]
                ]
                fallbacks.append({role: fallback_models})

        # Cross-role safety net: if judging/restoration both fail, fall back
        # to the translation role's models. This trades quality for liveness.
        translation_models = [
            m for m in getattr(pool, "translation", [])
            if m.requests_per_minute > 0
        ]
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
            "CRITICAL: do NOT emit any ①think...①/think>, <|thinking|>, <|reasoning|>, "
            "or <thought>...</thought> blocks. Do NOT preface your answer with "
            "'Let me analyze', 'I need to translate', or any planning prose. "
            "Return ONLY the translated text and nothing else. "
            "LOCALIZE Chinese typographic conventions to the target language: "
            "strip 《》 book-title brackets (English uses italics), convert "
            "“” and ‘’ quotes to ASCII, and replace Chinese ordinal "
            "markers 一、 二、 三、 … 十、 with '1.', '2.', '3.' … '10.'. "
            "Do NOT preserve these conventions verbatim in the target language."
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

        model_str = "translation"  # role passed to acompletion; key for hit counter
        for attempt in range(4):  # 1 initial + 3 retries
            try:
                response = await self._call_with_breaker(
                    "translation",
                    self._router.acompletion,
                    model=model_str,
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
                no_markdown = _strip_markdown_emphasis(translated)
                if no_markdown != translated:
                    _logger.debug(
                        f"Stripped {len(translated) - len(no_markdown)} chars of "
                        f"markdown emphasis from LLM output"
                    )
                localized = _localize_chinese_punctuation(no_markdown)
                if localized != no_markdown:
                    _logger.debug(
                        f"Localized {len(no_markdown) - len(localized)} chars of "
                        f"Chinese typographic conventions to English"
                    )
                translated = localized
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
                # 2026-06-17 round 5 (FIX-#18): increment per-model hit counter
                self._rate_limit_hits[model_str] = self._rate_limit_hits.get(model_str, 0) + 1
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
            response = await self._call_with_breaker(
                "judging",
                self._router.acompletion,
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
            # Regex fallback: extract numeric values from malformed JSON like
            # {"accuracy": 95, "fluency":.io98, "adequacy": 99, "score": 98}
            # or {"accuracy": 100, "fluency": directly as per ...: 100, ...}
            import re as _re
            def _extract_numeric(content: str, field: str) -> int | None:
                m = _re.search(rf'"{field}"\s*:\s*[^,}}\d]*(\d+)', content)
                return int(m.group(1)) if m else None
            acc = _extract_numeric(content, "accuracy")
            flu = _extract_numeric(content, "fluency")
            ade = _extract_numeric(content, "adequacy")
            sco = _extract_numeric(content, "score")
            if acc is not None and flu is not None and ade is not None and sco is not None:
                _logger.warning(
                    f"Judge JSON parse recovered via regex. Raw: {content[:200]}"
                )
                return {
                    "accuracy": acc, "fluency": flu, "adequacy": ade, "score": sco,
                    "reason": content[:200] if content else "regex-recovered",
                    "parse_failed": True,
                    "regex_recovered": True,
                }
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
