import asyncio
import hashlib
import json
import os
import random
import re
import sys
import time
from collections import OrderedDict
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pybreaker

from ol_pool.prompts import render_prompt


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
# Issue #4: gate ALL litellm imports (including the exception classes —
# they pull in the full package) on non-FAKE_LLM mode. In FAKE_LLM mode
# we provide local stub exception subclasses so the `except Timeout as e:`
# clauses in translate()/judge() remain syntactically valid even though
# they will never actually fire (FAKE mode returns early).
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")
os.environ.setdefault("DISABLE_LITELLM_TELEMETRY", "True")
os.environ.setdefault("LITELLM_TELEMETRY", "False")


class _StubLitellmError(Exception):
    """Base stub for litellm exception classes when OMNI_TEST_FAKE_LLM=1."""


class _StubTimeout(_StubLitellmError):
    pass


class _StubAuthenticationError(_StubLitellmError):
    pass


class _StubRateLimitError(_StubLitellmError):
    pass


class _StubRouterRateLimitError(_StubLitellmError):
    pass


if os.environ.get("OMNI_TEST_FAKE_LLM") != "1":
    import litellm  # noqa: E402
    from litellm.exceptions import AuthenticationError, RateLimitError, Timeout  # noqa: E402
    from litellm.types.router import RouterRateLimitError  # noqa: E402
    # Must be set before Router init — prevents litellm from lowercasing model names
    # (e.g. "openai/MiniMax-M2.7" stays uppercase so MiniMax API accepts it)
    litellm.disable_model_name_normalization = True
    from litellm import Router  # noqa: E402
else:
    # FAKE_LLM mode: skip the 26s `import litellm` and use stub classes.
    # `except Timeout as e:` etc. remain valid; the stubs are never actually
    # raised because __init__ returns early with _FakeModelPool.
    # Tests using `with patch("ol_pool.router.Router")` to set _test_mode
    # still work because @patch sets the module-level attribute at test time.
    AuthenticationError = _StubAuthenticationError
    RateLimitError = _StubRateLimitError
    Timeout = _StubTimeout
    RouterRateLimitError = _StubRouterRateLimitError
    Router = None  # type: ignore[assignment,misc]
    # Direct-call seam for intra-role 429 failover (_direct_acompletion).
    # Tests replace this module attribute with a fake exposing acompletion().
    litellm = None  # type: ignore[assignment]

from ol_config.loader import load_config
from ol_config.schema import LLMModelConfig, LLMPoolConfig, RateLimitBackoffConfig
from ol_logging.core import get_logger


class ModelPoolTruncationError(Exception):
    """Raised when an LLM response finishes due to max_tokens (finish_reason='length')
    rather than completing naturally. The caller can retry with a larger limit or
    fall back to a model with a larger context window."""


class ModelPoolSourceLanguageResidualError(Exception):
    """Raised when the LLM output still contains significant source-language text,
    indicating the model did not actually translate the content.
    Unlike ModelPoolTruncationError (finish_reason="length"), this catches
    cases where the LLM returns source text verbatim with finish_reason="stop".
    The caller should retry with the same input."""


_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def has_source_language_residual(text: str, source_lang: str, target_lang: str) -> bool:
    """Check if LLM output still contains significant source-language text.

    For zh->en: checks if >15% of non-whitespace characters are CJK.
    Returns False for other language pairs (future extension).
    """
    if not text.strip():
        return False
    if source_lang == "zh" and target_lang == "en":
        cjk_count = len(_CJK_RE.findall(text))
        alpha_count = len(re.findall(r"[a-zA-Z]", text))
        total = cjk_count + alpha_count
        if total == 0:
            return False
        ratio = cjk_count / total
        return ratio > 0.15
    return False


_logger = get_logger("pool")

#: Pipeline default completion ceiling per role. These mirror the historical
#: call-site constants. They are only written into ``litellm_params`` for a
#: role that opts into per-entry ceilings; see ``_router_max_tokens_kwargs``.
_ROLE_DEFAULT_MAX_TOKENS: dict[str, int] = {
    "translation": 4096,
    "judging": 2048,
    "restoration": 2048,
    "profiling": 2048,
}


def _effective_max_tokens(role: str, model: LLMModelConfig) -> int:
    """Return the completion ceiling a single deployment should use.

    A per-entry ``max_tokens`` wins; otherwise the role's pipeline default.
    """
    if model.max_tokens is not None:
        return model.max_tokens
    return _ROLE_DEFAULT_MAX_TOKENS.get(
        role, _ROLE_DEFAULT_MAX_TOKENS["translation"],
    )


# 2026-06-17 round 6 (FIX-#11): cache value is (pool, config_mtime) so
# config edits on disk are picked up without restarting the process.
_pool_cache: dict[str, tuple["ModelPool", float]] = {}


class _PromptCache:
    """Content-addressed LRU cache for LLM completions.

    Only safe for deterministic responses (temperature=0). The router
    bypasses the cache when temperature != 0 OR when the config disables
    it. Key = (model_role, source_lang, target_lang, sha256(messages_json), temperature).
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


def _resolve_env_vars(value: str | None) -> str | None:
    """Resolve ${ENV_VAR} patterns in a value.

    Wave 4 (L-C2): replaced regex-based implementation with a simple split-join
    loop to prevent ReDoS on nested ${...${...}...} patterns. The old regex
    ``\\$\\{([^}]+)\\}`` could cause catastrophic backtracking under adversarial
    input. The new implementation is O(n) with no backtracking.
    """
    if value is None:
        return None
    parts = value.split("${")
    if len(parts) == 1:
        return value
    result = [parts[0]]
    for part in parts[1:]:
        close_idx = part.find("}")
        if close_idx == -1:
            result.append("${" + part)
            continue
        var_name = part[:close_idx]
        env_val = os.environ.get(var_name)
        if env_val is None:
            raise ValueError(
                f"Environment variable '{var_name}' not set - "
                f"cannot resolve config value"
            )
        result.append(env_val)
        result.append(part[close_idx + 1:])
    return "".join(result)


def _unresolved_env_vars(model: LLMModelConfig) -> list[str]:
    """Names of ``${VAR}`` refs in a model's api_key/base_url that are unset.

    Mirrors :func:`_resolve_env_vars`' parsing without raising, so it can be
    used as a pre-filter. ``_resolve_env_vars`` still runs on every model that
    survives, so the resolved value stays fail-closed.
    """
    missing: list[str] = []
    for value in (model.api_key, model.base_url):
        if not value:
            continue
        for part in value.split("${")[1:]:
            close_idx = part.find("}")
            if close_idx == -1:
                continue
            name = part[:close_idx]
            if name and name not in missing and os.environ.get(name) is None:
                missing.append(name)
    return missing


def partition_usable_models(
    pool: LLMPoolConfig,
) -> tuple[dict[str, list], list[tuple[str, LLMModelConfig, list[str]]]]:
    """Split each role's models into usable ones and skipped-but-reasoned ones.

    A missing key for ONE provider must not disable the whole pool. The pool
    lists multiple providers per role (the committed ``config/default.yaml``
    uses two; the schema requires at least two per role), so a user holding
    only the lower-priority keys can still serve every request; previously the
    missing priority-1 key raised inside ``_build_model_list`` at ``__init__``
    and every role became unusable — a hard fail that contradicted the
    documented two-layer env contract (``schema._check_env_vars`` WARNS at
    startup, and a model is only unusable once actually selected).

    Returns ``(usable_by_role, skipped)`` where ``skipped`` carries the role,
    the model, and its unresolved env-var names so the caller can warn once.
    """
    usable: dict[str, list] = {}
    skipped: list[tuple[str, LLMModelConfig, list[str]]] = []
    for role in ("translation", "judging", "restoration", "profiling"):
        kept: list = []
        for model in getattr(pool, role, []) or []:
            missing = _unresolved_env_vars(model)
            if missing:
                skipped.append((role, model, missing))
            else:
                kept.append(model)
        usable[role] = kept
    return usable, skipped


def _rate_limited_model_label(exc: BaseException, role: str) -> str:
    """Best-effort model identifier carried by a rate-limit error.

    litellm exceptions usually expose ``model`` and/or ``llm_provider``. When
    neither is present (e.g. a router-level error) the role name is the only
    honest label available.
    """
    for attr in ("model", "llm_provider"):
        value = getattr(exc, attr, None)
        if isinstance(value, str) and value and value != "test":
            return value
    return role


def _parse_retry_after_value(value: Any) -> float | None:
    """Parse a ``Retry-After`` header value (delta-seconds or HTTP-date)."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return max(float(value), 0.0)
    if isinstance(value, bytes):
        try:
            value = value.decode("latin-1")
        except Exception:  # expected: bytes decode is total; keep best-effort
            return None
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped:
        return None
    try:
        return max(float(stripped), 0.0)
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(stripped)
    except (TypeError, ValueError, OverflowError):
        return None
    if when is None:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return max((when - datetime.now(timezone.utc)).total_seconds(), 0.0)


def _extract_retry_after(exc: BaseException | None) -> float | None:
    """Best-effort ``Retry-After`` read across litellm/httpx error shapes.

    Never raises: a missing or malformed header is simply "no signal".
    """
    if exc is None:
        return None
    header_sources: list[Any] = []
    try:
        response = getattr(exc, "response", None)
        if response is not None:
            header_sources.append(getattr(response, "headers", None))
    except Exception:  # expected: provider .response property may raise
        pass
    try:
        header_sources.append(getattr(exc, "response_headers", None))
    except Exception:  # expected: provider .response_headers may raise
        pass
    try:
        header_sources.append(getattr(exc, "headers", None))
    except Exception:  # expected: provider .headers property may raise
        pass

    for headers in header_sources:
        if not headers:
            continue
        for name in ("retry-after", "Retry-After"):
            try:
                value = headers.get(name)
            except Exception:  # expected: header mapping may be a proxy
                continue
            parsed = _parse_retry_after_value(value)
            if parsed is not None:
                return parsed
    return None


def compute_rate_limit_backoff(
    attempt: int,
    exc: BaseException | None,
    cfg: RateLimitBackoffConfig | None = None,
) -> float:
    """Seconds to wait before the next 429 retry.

    Priority:
    1) ``Retry-After`` carried by ``exc`` (seconds or HTTP-date), capped at
       ``cfg.max_delay_s``;
    2) otherwise ``cfg.base_delay_s * 2**attempt``, capped at
       ``cfg.max_delay_s``;
    3) ``cfg.jitter`` adds ``[0, 25%]`` of the chosen delay.

    The final value is clamped to ``cfg.max_delay_s`` so backoff can never
    grow past the configured ceiling (and thus past the caller's timeout wall).
    """
    if cfg is None:
        cfg = RateLimitBackoffConfig()
    if not cfg.enabled:
        return 0.0

    retry_after = _extract_retry_after(exc)
    if retry_after is not None:
        wait = min(retry_after, cfg.max_delay_s)
    else:
        wait = min(cfg.base_delay_s * (2 ** max(attempt, 0)), cfg.max_delay_s)

    if cfg.jitter:
        wait += random.uniform(0.0, wait * 0.25)
    return min(wait, cfg.max_delay_s)


# 2026-06-18 round 16 Phase B1: circuit breaker for LLM calls.
class _LogBreakerListener(pybreaker.CircuitBreakerListener):
    """Logs circuit breaker state transitions at WARNING level."""

    def state_change(self, cb, old_state, new_state):
        _logger.warning(
            "Circuit breaker %r: %s -> %s",
            cb.name, old_state.name, new_state.name,
        )


class ModelPoolInitError(RuntimeError):
    """Raised when ModelPool fails to initialize the LLM Router.

    Common causes: missing API key env vars, invalid config, network issues
    preventing Router from reaching its endpoint. The original exception
    is preserved via __cause__ for debugging.

    Recovery: either set the missing env vars, set OMNI_TEST_FAKE_LLM=1
    for fake mode, or fix the config file.
    """


class ModelPool:
    _instance: "ModelPool | None" = None
    # Default 429 policy for instances constructed via __new__ (tests) or
    # configs that predate the field. __init__ overrides it from config.
    _rate_limit_backoff: RateLimitBackoffConfig = RateLimitBackoffConfig()

    def __init__(self, config_path: str = "config/default.yaml"):
        # Detect test mode: if the Router class has been replaced with a
        # MagicMock (by @patch in tests), short-circuit translate/judge to
        # return placeholder values instead of attempting real LLM calls.
        self._test_mode = isinstance(Router, MagicMock)
        # Issue #30: short-circuit to _FakeModelPool when OMNI_TEST_FAKE_LLM=1
        if os.environ.get("OMNI_TEST_FAKE_LLM") == "1":
            from ol_pool.fake import _FakeModelPool  # local import to avoid circular
            self._test_mode = True
            self._router = None
            self._fake_pool = _FakeModelPool()
            self._cache_enabled = False
            self._cache = _PromptCache(max_size=0, ttl_seconds=0.0)
            self._rate_limit_hits = {}
            self._rate_limit_backoff = RateLimitBackoffConfig()
            return
        result = load_config(config_path)
        try:
            config = result[0]
        except (TypeError, IndexError):
            config = result
        # 429 policy: defaults apply even when config/*.yaml predates the
        # field, and a test double without a real schema object is ignored.
        _backoff_cfg = getattr(config.llm_pool, "rate_limit_backoff", None)
        self._rate_limit_backoff = (
            _backoff_cfg
            if isinstance(_backoff_cfg, RateLimitBackoffConfig)
            else RateLimitBackoffConfig()
        )
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
            for role in ("translation", "judging", "restoration", "profiling")
        }
        # Fail-open per model, fail-closed per role (OL#99): one unset
        # provider key must not disable every role, but a role that lost EVERY
        # model to the filter is a hard error. Starvation is read off what the
        # filter removed -- an already-empty role (or a test-double pool) has
        # nothing to starve and is the config's business, not this filter's.
        self._usable_by_role, _skipped = partition_usable_models(config.llm_pool)
        for role, model, missing in _skipped:
            _logger.warning(
                "Skipping %s/%s for role %r: %s not set. "
                "Set it to use this model; the pool continues with the "
                "remaining priorities.",
                model.provider, model.model, role, ", ".join(missing),
            )
        starved = sorted({
            role
            for role, _model, _missing in _skipped
            if not self._usable_by_role.get(role)
        })
        if starved:
            unconfigured = sorted({
                var
                for _role, _model, missing in _skipped
                for var in missing
            })
            raise ModelPoolInitError(
                f"No usable model for role(s) {', '.join(starved)}: every "
                f"configured model references unset env var(s) "
                f"{', '.join(unconfigured)}. "
                f"Set them, set OMNI_TEST_FAKE_LLM=1 for fake mode, "
                f"or fix the config file."
            )
        try:
            self._router = Router(
                model_list=self._build_model_list(
                    config.llm_pool, usable=self._usable_by_role,
                ),
                routing_strategy="simple-shuffle",
                num_retries=2,
                timeout=120.0,
                fallbacks=self._build_fallbacks(
                    config.llm_pool, usable=self._usable_by_role,
                ),
                # E2E-83: the previous 'enforce_model_rate_limits' pre-call
                # check maintained a per-model RPM token bucket and raised
                # litellm.RouterRateLimitError synchronously. For large
                # requests (>~50KB / >~20K tokens) the bucket empties
                # fast and the check started rejecting requests even
                # when the provider itself would accept them, and our
                # outer translate() retry loop then waited 10/20/40
                # seconds (cumulative ~70s) on backoffs the in-memory
                # bucket could not recover from in time.
                #
                # Per-model RPM is NOT hard-enforced any more — it reaches
                # litellm only as a routing weight / cooldown input. Rejection
                # comes from the provider's HTTP 429, handled by the
                # translate() backoff loop instead of an in-process bucket.
                #
                # Do not try to tune 429s via rpm: AMD Radeon answers with
                # `model_concurrency_rate_limit_exceeded` (a CONCURRENCY
                # number) and Zhipu with `code 1305 该模型当前访问量过大`, so
                # for both the ceiling is simultaneous requests, not
                # requests-per-minute. Set `max_parallel_requests` on such a
                # model instead — it maps to
                # litellm_params['max_parallel_requests'], enforced by a
                # per-deployment semaphore.
                #
                # To re-enable the aggressive pre-call rpm check, pass
                #   optional_pre_call_checks=['enforce_model_rate_limits']
                # directly to the Router here.
            )
        except Exception as _router_init_exc:
            _logger.exception(
                "ModelPool Router init failed: %s", _router_init_exc,
            )
            raise ModelPoolInitError(
                f"ModelPool initialization failed: {_router_init_exc}. "
                f"Set OMNI_TEST_FAKE_LLM=1 for fake mode, "
                f"or configure the required API keys."
            ) from _router_init_exc

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

    def _build_model_list(
        self,
        pool: LLMPoolConfig,
        usable: dict[str, list] | None = None,
    ) -> list[dict]:
        usable = usable if usable is not None else partition_usable_models(pool)[0]
        model_list = []
        for role in ("translation", "judging", "restoration", "profiling"):
            role_models = usable.get(role, [])
            # LiteLLM request kwargs override deployment litellm_params, so a
            # per-entry ceiling only has an effect when the caller does NOT pin
            # `max_tokens` itself. Opt in per role: if ANY entry declares
            # `max_tokens`, every entry of that role gets an explicit ceiling
            # (its own override, else the role default) and the call sites stop
            # pinning a value (see _router_max_tokens_kwargs). Roles with no
            # override keep the historical call-site constant, so their
            # litellm_params stay byte-identical.
            role_has_override = any(
                m.max_tokens is not None for m in role_models
            )
            for model in role_models:
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
                # Same updateLiteLLMParams dict as rpm. Omitted when unset so
                # existing configs keep imposing no client-side cap.
                if model.max_parallel_requests is not None:
                    litellm_params["max_parallel_requests"] = (
                        model.max_parallel_requests
                    )
                # Per-entry overrides. `extra_body` is omitted when unset so
                # existing configs keep producing byte-identical
                # litellm_params. `max_tokens` is emitted for the whole role
                # once any entry declares it, because the call site then stops
                # pinning a value and every deployment must carry its own.
                if role_has_override:
                    litellm_params["max_tokens"] = _effective_max_tokens(
                        role, model,
                    )
                if model.extra_body is not None:
                    litellm_params["extra_body"] = model.extra_body
                model_list.append(
                    {
                        "model_name": role,
                        "litellm_params": litellm_params,
                    },
                )
        return model_list

    def _router_max_tokens_kwargs(self, role: str) -> dict[str, int]:
        """Per-call ``max_tokens`` kwargs for a Router completion.

        LiteLLM's Router merges request kwargs LAST, so a pinned call-site
        value would override every deployment-level ceiling. When a role
        declares any per-entry ``max_tokens``, the ceiling therefore has to be
        resolved by the deployments themselves and this returns nothing.
        Roles without overrides keep the historical call-site constant.
        """
        models = getattr(self, "_usable_by_role", {}).get(role) or []
        if any(m.max_tokens is not None for m in models):
            return {}
        return {"max_tokens": _ROLE_DEFAULT_MAX_TOKENS.get(role, 2048)}

    def _role_max_tokens_ceiling(self, role: str) -> int:
        """Largest effective ceiling across a role's usable deployments."""
        models = getattr(self, "_usable_by_role", {}).get(role) or []
        if not models:
            return _ROLE_DEFAULT_MAX_TOKENS.get(role, 2048)
        return max(_effective_max_tokens(role, m) for m in models)

    def _make_cache_key(
        self, model: str, messages: list[dict], temperature: float,
        source_lang: str = "", target_lang: str = "",
    ) -> tuple:
        payload = json.dumps(messages, sort_keys=True, ensure_ascii=False)
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return (model, source_lang, target_lang, digest, float(temperature))

    def metrics(self) -> dict[str, int]:
        """Return a copy of the rate-limit hit counter (role → hits).

        2026-06-17 round 5 (FIX-#18): lightweight ops hook. External
        code can poll this between cycles to detect rate-limit storms.
        Returns a shallow copy so callers can't mutate internal state.
        """
        return dict(self._rate_limit_hits)

    def _build_fallbacks(
        self,
        pool: LLMPoolConfig,
        usable: dict[str, list] | None = None,
    ) -> list[dict]:
        """Build cross-role fallbacks whose TARGETS are litellm group names.

        litellm Router fallbacks format:
        ``[{"model_group_name": ["fallback_model_group", ...]}]``.
        Both the key AND every value must be names of groups registered in
        ``model_list``. litellm resolves a failing group's fallback with
        ``get_fallback_model_group()``, which returns the entry's VALUE list,
        and then routes the retry to those values *as model groups*. The key
        is the ``model=`` argument passed to ``acompletion()`` (always a role
        name in this pool).

        _build_model_list registers every model under ``model_name = role``
        (translation / judging / restoration / profiling), so the registered
        group name is the ROLE, never ``provider/model``.

        e2e-test-suite#141: this used to emit ``provider/model`` ids as values,
        naming no registered group. A provider rate limit then produced
        ``No fallback model group found for original model_group=...`` and the
        fallback never engaged — a hard failure where a reroute was intended.

        Intra-role fallback is inexpressible under this scheme: every model of
        a role is registered under the SAME single group name, so there is
        nothing to fall back to *within* a role (Router(num_retries=2) already
        retries inside the group). The only expressible fallback is CROSS-ROLE.

        POST_MORTEM OL-8: keep the liveness net — a non-translation role
        (judging / restoration / profiling) whose models are all unusable (e.g.
        provider 429s, or rpm-0 entries) reroutes onto translation, trading
        quality for liveness. ``translation`` is the designated liveness role
        and therefore gets no entry of its own: it is the rescue *target*, and
        silently serving a translation request from a judge-tier model is worse
        than a clear error.

        2026-06-17 round 6 (FIX-#17): a role only qualifies as a TARGET when it
        has at least one model with requests_per_minute > 0 — zero-RPM models
        are dead-on-arrival. The Pydantic schema already enforces ge=1, this is
        belt-and-suspenders for manually-constructed configs that bypass
        validation. A role with no usable target gets no entry at all.

        OL#99: `usable` must be the same filtered mapping _build_model_list
        used, or a fallback would name a group the Router never received.
        """
        usable = usable if usable is not None else partition_usable_models(pool)[0]
        # translation first: it is the highest-priority fallback TARGET.
        roles = ("translation", "judging", "restoration", "profiling")
        registered = [role for role in roles if usable.get(role)]
        targets = [
            role for role in registered
            if any(m.requests_per_minute > 0 for m in usable.get(role, []))
        ]
        fallbacks = []
        for role in registered:
            if role == "translation":
                continue  # designated liveness role: rescue target, not a source
            candidates = [target for target in targets if target != role]
            if candidates:
                fallbacks.append({role: candidates})
        return fallbacks

    async def _direct_acompletion(
        self,
        model: LLMModelConfig,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
    ):
        """Call one specific model directly, bypassing the Router.

        The Router registers every model of a role under a single group name,
        so litellm cannot address one member of that group. A direct completion
        is therefore the only way to step to the next priority within a role
        after a 429 (see ``_intra_role_failover``).
        """
        if litellm is None:  # pragma: no cover - only reachable in FAKE_LLM mode
            raise RuntimeError(
                "litellm is unavailable; cannot perform intra-role failover"
            )
        params: dict[str, Any] = {
            "model": f"{model.provider}/{model.model}",
            "messages": messages,
            "temperature": temperature,
            "max_tokens": (
                model.max_tokens
                if model.max_tokens is not None
                else max_tokens
            ),
        }
        if model.extra_body is not None:
            params["extra_body"] = model.extra_body
        if model.api_key:
            params["api_key"] = _resolve_env_vars(model.api_key)
        if model.base_url:
            params["api_base"] = _resolve_env_vars(model.base_url)
        if model.timeout is not None:
            params["timeout"] = model.timeout
        return await litellm.acompletion(**params)

    def _process_translation_response(
        self,
        response: Any,
        text: str,
        source_lang: str,
        target_lang: str,
        max_tokens: int | None = None,
    ) -> str:
        """Validate, clean and return a successful translation response.

        Shared by the Router path and the intra-role failover path so they
        cannot drift on truncation / chain-of-thought / residual checks.
        ``max_tokens`` is the effective completion ceiling for the deployment
        that answered; it is used by the OL#47 secondary heuristic.
        """
        _limit = max_tokens or _ROLE_DEFAULT_MAX_TOKENS["translation"]
        if response.choices[0].finish_reason == "length":
            raise ModelPoolTruncationError(
                f"Translation response truncated at {_limit} tokens "
                f"(finish_reason=length) for ~{len(text)} chars input"
            )

        # OL#47 secondary heuristic: detect truncated output even
        # when the API reports finish_reason="stop".  Three signals:
        #   a. Output ends with "..." or ".." (abrupt termination)
        #   b. Output ends with non-sentence-terminal punctuation
        #      (, ; : — –) for inputs longer than 500 chars
        #   c. usage.completion_tokens >= 90 % of the effective ceiling
        if response.choices[0].finish_reason == "stop":
            _content = response.choices[0].message.content or ""
            _truncated = False
            _trunc_reasons: list[str] = []

            # (a) trailing ellipsis / double-dot
            if _content.endswith("...") or _content.endswith(".."):
                _truncated = True
                _trunc_reasons.append("output ends with '...' or '..'")

            # (b) non-sentence-terminal punctuation on long inputs
            if not _truncated and len(text) > 500:
                _non_terminal = (",", ";", ":", "—", "–")
                if any(_content.rstrip().endswith(p) for p in _non_terminal):
                    _truncated = True
                    _trunc_reasons.append(
                        "output ends with non-sentence-terminal punctuation"
                    )

            # (c) completion_tokens near the max_tokens limit
            if not _truncated:
                _usage = getattr(response, "usage", None)
                if _usage is not None:
                    _ct = getattr(_usage, "completion_tokens", None)
                    # isinstance(_ct, int) guards against MagicMock
                    # objects (the existing happy-path test doesn't
                    # set usage, so getattr would return a MagicMock
                    # instance that is truthy but not an int).
                    if isinstance(_ct, int) and _ct >= int(0.9 * _limit):
                        _truncated = True
                        _trunc_reasons.append(
                            f"completion_tokens ({_ct}) >= 90% of max_tokens "
                            f"({_limit})"
                        )

            if _truncated:
                raise ModelPoolTruncationError(
                    f"Translation response appears truncated (finish_reason=stop, "
                    f"heuristics: {'; '.join(_trunc_reasons)}) "
                    f"for ~{len(text)} chars input"
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
        if has_source_language_residual(translated, source_lang, target_lang):
            raise ModelPoolSourceLanguageResidualError(
                f"Translation output contains {source_lang}-language residual "
                f"for {target_lang} target (CJK ratio > 15%)"
            )
        _logger.debug(f"Translation response: {len(translated)} chars")
        return translated

    async def _intra_role_failover(
        self,
        role: str,
        messages: list[dict],
        temperature: float,
        max_tokens: int,
        text: str,
        source_lang: str,
        target_lang: str,
        cache_key: tuple,
        original_exc: BaseException,
    ) -> str:
        """Step through a role's remaining models after a 429.

        Models are ordered by ``priority`` and drawn ONLY from
        ``self._usable_by_role[role]``. Cross-role downgrade is deliberately
        not attempted: a judging/restoration/profiling model must never answer
        a translation request. If every same-role model is rate limited, the
        original exception is re-raised (fail-closed).
        """
        models = sorted(
            self._usable_by_role.get(role) or [],
            key=lambda m: (m.priority, m.provider, m.model),
        )
        hit_label = _rate_limited_model_label(original_exc, role)
        attempted: set[str] = set()
        for model in models:
            model_id = f"{model.provider}/{model.model}"
            if hit_label in (model_id, model.model):
                attempted.add(model_id)

        switches = 0
        wait_exc: BaseException = original_exc
        backoff_cfg = self._rate_limit_backoff
        for tier, model in enumerate(models, start=1):
            model_id = f"{model.provider}/{model.model}"
            if model_id in attempted:
                continue
            attempted.add(model_id)
            switches += 1
            retry_after = _extract_retry_after(wait_exc)
            wait = compute_rate_limit_backoff(switches - 1, wait_exc, backoff_cfg)
            await asyncio.sleep(wait)
            _logger.warning(
                "rate-limited on %s (attempt %d/%d): waiting %.1fs "
                "(retry_after=%s, remaining same-role models=%d); "
                "switching to %s (tier %d/%d)",
                hit_label, switches, backoff_cfg.max_attempts_per_model,
                wait,
                f"{retry_after:g}" if retry_after is not None else "none",
                max(len(models) - tier, 0),
                model_id, tier, len(models),
            )
            try:
                response = await self._direct_acompletion(
                    model, messages, temperature, max_tokens,
                )
            except (RateLimitError, RouterRateLimitError) as exc:
                hit_label = _rate_limited_model_label(exc, role)
                wait_exc = exc
                continue
            translated = self._process_translation_response(
                response, text, source_lang, target_lang,
                max_tokens=_effective_max_tokens(role, model),
            )
            if self._cache_enabled and temperature == 0.0:
                self._cache.put(cache_key, translated)
            return translated

        _logger.error(
            "Translation failed: every %s-tier model was rate limited", role,
        )
        raise original_exc

    async def translate(
        self, text: str, source_lang: str, target_lang: str,
        context: dict | str | None = None,
        temperature: float = 0.0,
        glossary: Any = None,
        system_message_override: str | None = None,
        extra_instruction: str | None = None,
    ) -> str:
        if self._test_mode:
            return "placeholder"
        _logger.debug(f"Translation request: {len(text)} chars, {source_lang}→{target_lang}")
        _logger.debug("Model selected: translation")

        # H1-H3: Wrap user text in delimiters to isolate instructions from data
        _delimited_text = (
            "[USER_TEXT_START]\n"
            f"{text}\n"
            "[USER_TEXT_END]"
        )

        # E2E-74 fix: build the user prompt based on the ``context`` type and
        # ALWAYS assign ``prompt`` before use. The previous implementation
        # only assigned ``prompt`` inside the ``isinstance(context, str)``
        # branch AND tried to call ``context.get(...)`` on the str, so any
        # caller passing ``context=None`` (the CLI's default) or
        # ``context=dict`` (the type hint) hit ``UnboundLocalError`` /
        # ``AttributeError`` at the message construction below.
        prompt_parts: list[str] = []
        if isinstance(context, str) and context:
            # Pre-built prompt (e.g. from build_translate_prompt); it already
            # contains the delimited text + TM/glossary section, so use it
            # verbatim. The previous code overwrote it with a fresh build.
            prompt = context
        elif isinstance(context, dict):
            tm_matches = context.get("tm_matches") or []
            glossary_terms = context.get("glossary_terms") or []
            if tm_matches:
                top_tm = tm_matches[:3]
                tm_lines = "\n".join(
                    f"- {m.get('source', '')} → {m.get('target', '')}"
                    for m in top_tm
                )
                prompt_parts.append(
                    f"Translation Memory (top {len(top_tm)} matches):\n{tm_lines}"
                )
            if glossary_terms:
                top_glossary = glossary_terms[:5]
                glossary_lines = "\n".join(
                    f"- {g.get('source', '')} → {g.get('target', '')}"
                    for g in top_glossary
                )
                prompt_parts.append(
                    f"Glossary (top {len(top_glossary)} terms):\n{glossary_lines}"
                )
            prompt_parts.append(
                render_prompt(
                    "translate_user",
                    source_lang=source_lang,
                    target_lang=target_lang,
                    user_text=_delimited_text,
                )
            )
            prompt = "\n\n".join(prompt_parts)
        else:
            prompt = render_prompt(
                "translate_user",
                source_lang=source_lang,
                target_lang=target_lang,
                user_text=_delimited_text,
            )

        # A12.3: when a Glossary object is provided (PR12), inject the
        # top-N relevant terms into the user prompt. This is the
        # dataclass-based path; the legacy ``context["glossary_terms"]``
        # branch above is preserved for BatchProcessor / RAG users.
        if glossary is not None and hasattr(glossary, "inject_into_prompt"):
            prompt = glossary.inject_into_prompt(text, prompt)

        # Issue #189: callers may append a one-off retranslation instruction
        # (e.g. after detecting the LLM echoed the source back unchanged).
        # Appended to the already-assembled prompt — no new template.
        if extra_instruction:
            prompt = f"{prompt}\n\n{extra_instruction}"

        if system_message_override is not None and system_message_override:
            system_message = system_message_override
        else:
            system_message = render_prompt(
                "translate_system", source_lang=source_lang, target_lang=target_lang
            )

        messages = [
            {"role": "system", "content": system_message},
            {"role": "user", "content": prompt},
        ]

        cache_key = self._make_cache_key("translation", messages, temperature, source_lang=source_lang, target_lang=target_lang)
        if self._cache_enabled and temperature == 0.0:
            cached = self._cache.get(cache_key)
            if cached is not None:
                _logger.debug("Translation cache hit")
                return cached

        # E2E-83: log a warning for unusually large requests so the
        # caller has visibility into slow translations. We don't block
        # the request — the previous pre-call check that fast-failed
        # on size has been removed.
        _prompt_chars = sum(len(m.get("content") or "") for m in messages)
        if _prompt_chars > 50_000:
            _logger.warning(
                f"Large translation request: ~{_prompt_chars} chars across "
                f"{len(messages)} message(s). Translation may take 60-180s "
                f"and may exceed some model context windows."
            )

        model_str = "translation"  # role passed to acompletion; key for hit counter
        backoff_cfg = self._rate_limit_backoff
        max_attempts = backoff_cfg.max_attempts_per_model
        for attempt in range(max_attempts):  # 1 initial + (max_attempts-1) retries
            try:
                response = await self._call_with_breaker(
                    "translation",
                    self._router.acompletion,
                    model=model_str,
                    messages=messages,
                    temperature=temperature,
                    **self._router_max_tokens_kwargs("translation"),
                )
                translated = self._process_translation_response(
                    response, text, source_lang, target_lang,
                    max_tokens=self._role_max_tokens_ceiling("translation"),
                )
                if self._cache_enabled and temperature == 0.0:
                    self._cache.put(cache_key, translated)
                return translated
            except Timeout as e:
                if attempt < max_attempts - 1:
                    wait = 2 ** attempt * 5
                    _logger.warning(f"Timeout, retrying in {wait}s (attempt {attempt + 1}/{max_attempts})")
                    await asyncio.sleep(wait)
                else:
                    _logger.error(f"Translation failed after {max_attempts} attempts: {e}")
                    raise
            except (RateLimitError, RouterRateLimitError) as e:
                # 2026-06-17 round 5 (FIX-#18): increment per-model hit counter
                self._rate_limit_hits[model_str] = self._rate_limit_hits.get(model_str, 0) + 1
                if attempt < max_attempts - 1:
                    retry_after = _extract_retry_after(e)
                    wait = compute_rate_limit_backoff(attempt, e, backoff_cfg)
                    _logger.warning(
                        "rate-limited on %s (attempt %d/%d): waiting %.1fs "
                        "(retry_after=%s, remaining same-role models=%d): %s",
                        _rate_limited_model_label(e, model_str),
                        attempt + 1, max_attempts, wait,
                        f"{retry_after:g}" if retry_after is not None else "none",
                        len(self._usable_by_role.get(model_str) or []),
                        e,
                    )
                    await asyncio.sleep(wait)
                else:
                    _logger.error(f"Translation failed after {max_attempts} attempts: {e}")
                    # Intra-role only: step to the next priority model within
                    # the SAME role. Never a cross-role downgrade.
                    return await self._intra_role_failover(
                        role=model_str,
                        messages=messages,
                        temperature=temperature,
                        max_tokens=4096,
                        text=text,
                        source_lang=source_lang,
                        target_lang=target_lang,
                        cache_key=cache_key,
                        original_exc=e,
                    )
            except AuthenticationError:
                _logger.error("Translation failed: AuthenticationError (no retry)")
                raise
            except ModelPoolTruncationError:
                _logger.error("Translation failed: response truncated (max_tokens limit)")
                raise
            except ModelPoolSourceLanguageResidualError as e:
                if attempt < max_attempts - 1:
                    wait = 2 ** attempt * 5
                    _logger.warning(f"Source language residual detected, retrying in {wait}s (attempt {attempt + 1}/{max_attempts})")
                    await asyncio.sleep(wait)
                else:
                    _logger.error(f"Translation failed after {max_attempts} attempts due to source language residual: {e}")
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
            if hasattr(self, "_fake_pool"):
                return await self._fake_pool.judge(
                    source, target,
                    source_lang=source_lang,
                    target_lang=target_lang,
                    **({"glossary": glossary} if glossary else {}),
                )
            return {"score": 0, "reason": "placeholder"}
        terminology_section = ""
        if glossary:
            terms = ", ".join(f"{k} → {v}" for k, v in glossary.items())
            terminology_section = f"\nTerminology: {terms}"
        prompt = render_prompt(
            "judge_user",
            source_lang=source_lang,
            source=source,
            target_lang=target_lang,
            target=target,
            terminology_section=terminology_section,
        )

        system_message = render_prompt("judge_system")

        messages = [
            {"role": "system", "content": system_message},
            {"role": "user", "content": prompt},
        ]

        cache_key = self._make_cache_key("judging", messages, temperature, source_lang=source_lang, target_lang=target_lang)
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
                **self._router_max_tokens_kwargs("judging"),
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
        # Truncation detection: fail-closed when finish_reason == "length"
        if response.choices[0].finish_reason == "length":
            _logger.warning(
                "Judge response truncated (finish_reason=length); returning fail-closed"
            )
            return {
                "accuracy": 0, "fluency": 0, "adequacy": 0, "score": 0,
                "reason": "truncated", "truncated": True,
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
        # Issue #130: centralised text-level + field-level JSON tolerance.
        from ol_pool.json_tolerance import (
            repair_json_once,
            repair_json_text,
            salvage_fields,
        )

        _judge_expectations = {
            "accuracy": float,
            "fluency": float,
            "adequacy": float,
            "score": float,
        }
        _judge_fields = ("accuracy", "fluency", "adequacy", "score")

        def _judge_all_valid(parsed: dict) -> bool:
            for field in _judge_fields:
                value = parsed.get(field)
                if value is None or isinstance(value, bool):
                    return False
                if not isinstance(value, (int, float)):
                    return False
            return True

        def _parse_judge_text(text: str):
            """Return ``(result, invalid_fields)`` or ``(None, [])``.

            ``result`` is a dict (possibly with ``None`` fields) when the text
            was at least structurally recoverable; ``None`` means no dict
            could be recovered at all.
            """
            try:
                parsed = json.loads(repair_json_text(text))
            except (json.JSONDecodeError, ValueError):
                parsed = None
            if isinstance(parsed, dict):
                salvaged, invalid = salvage_fields(parsed, _judge_expectations)
                for field in _judge_fields:
                    if salvaged.get(field) is None and field not in invalid:
                        invalid.append(field)
                return salvaged, invalid
            # Regex fallback (kept for callers/tests depending on the keys):
            # scrape numeric values from malformed JSON that even the
            # syntactic repair cannot save, e.g.
            # {"accuracy": 100, "fluency": directly as per ...: 100, ...}
            import re as _re
            def _extract_numeric(text: str, field: str) -> int | None:
                m = _re.search(rf'"{field}"\s*:\s*[^,}}\d]*(\d+)', text)
                return int(m.group(1)) if m else None
            acc = _extract_numeric(text, "accuracy")
            flu = _extract_numeric(text, "fluency")
            ade = _extract_numeric(text, "adequacy")
            sco = _extract_numeric(text, "score")
            if None not in (acc, flu, ade, sco):
                _logger.warning(
                    f"Judge JSON parse recovered via regex. Raw: {text[:200]}"
                )
                return {
                    "accuracy": acc, "fluency": flu, "adequacy": ade, "score": sco,
                    "reason": text[:200] if text else "regex-recovered",
                    "parse_failed": True,
                    "regex_recovered": True,
                }, []
            return None, []

        result, invalid_fields = _parse_judge_text(content)
        if result is not None and _judge_all_valid(result):
            if self._cache_enabled and temperature == 0.0:
                self._cache.put(cache_key, result)
            return result

        # Field-level failure or unparseable text → exactly ONE repair attempt.
        if result is None:
            parse_error: Exception = ValueError("judge response was not valid JSON")
        else:
            parse_error = ValueError(
                f"judge fields invalid: {', '.join(invalid_fields)}"
            )

        async def _repair_call(prompt: str) -> str:
            _resp = await self._call_with_breaker(
                "judging",
                self._router.acompletion,
                model="judging",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                **self._router_max_tokens_kwargs("judging"),
            )
            try:
                return _resp.choices[0].message.content or ""
            except (AttributeError, IndexError):
                return ""

        try:
            repaired = await repair_json_once(content, parse_error, _repair_call)
        except Exception as repair_err:  # expected — fall through to fail-closed
            _logger.error(
                f"Judge JSON second-pass repair failed: "
                f"{type(repair_err).__name__}: {repair_err}"
            )
            repaired = None

        if isinstance(repaired, dict):
            salvaged, invalid_fields = salvage_fields(repaired, _judge_expectations)
            for field in _judge_fields:
                if salvaged.get(field) is None and field not in invalid_fields:
                    invalid_fields.append(field)
            if _judge_all_valid(salvaged):
                if self._cache_enabled and temperature == 0.0:
                    self._cache.put(cache_key, salvaged)
                return salvaged
            result = salvaged

        # Fail-CLOSED: bad values are never treated as valid scores.
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
            "invalid_fields": invalid_fields,
        }

    async def profile(
        self, content: str, source_lang: str = "", **kwargs: Any,
    ) -> dict[str, Any]:
        """Profile a document's writing style by calling the LLM via the
        'profiling' role group. Issue #36 — was previously missing, causing
        ``ol profile-doc`` and the profile_doc MCP tool to crash with
        ``AttributeError: 'ModelPool' object has no attribute 'profile'``
        whenever OMNI_TEST_FAKE_LLM was unset.

        Mirrors the contract of :meth:`ol_pool.fake._FakeModelPool.profile`
        so :func:`ol_style.doc_profiler.profile_document` can use either
        pool transparently. In test_mode the call is delegated to
        _FakeModelPool.profile() to keep the test seam stable; in real
        LLM mode the request is routed through the 'profiling' role group
        in the litellm Router and the JSON response is parsed into a dict
        for the caller.

        Args:
            content: The pre-built profiling prompt (typically the output
                of :func:`ol_style.doc_profiler._build_profiling_prompt`).
                The parameter is named ``content`` to match the call site
                in :func:`ol_style.doc_profiler.profile_document`.
            source_lang: Source language code (e.g. ``"en"``) used for
                cache keying and routing context.
            **kwargs: Reserved for future use (e.g. custom temperature).

        Returns:
            Parsed JSON dict on success, or a dict containing
            ``raw_response`` if the model returned non-JSON output.
            On transport errors, returns a dict with ``error`` and
            ``transport_error`` keys describing the failure (so the
            caller can surface a StyleGuide with a fallback summary).
        """
        if self._test_mode:
            if hasattr(self, "_fake_pool"):
                return await self._fake_pool.profile(
                    content, source_lang=source_lang, **kwargs,
                )
            return {}

        _logger.debug(f"Profile request: {len(content)} chars, lang={source_lang}")
        _logger.debug("Model selected: profiling")

        # The caller (profile_document) builds the full user prompt; we
        # just pass it through. No system message needed — the prompt
        # already contains the [USER_TEXT_START] delimited content and
        # the JSON output instructions.
        messages = [
            {"role": "user", "content": content},
        ]

        cache_key = self._make_cache_key(
            "profiling", messages, 0.0,
            source_lang=source_lang, target_lang="",
        )
        if self._cache_enabled:
            cached = self._cache.get(cache_key)
            if cached is not None:
                _logger.debug("Profile cache hit")
                return cached

        try:
            response = await self._call_with_breaker(
                "profiling",
                self._router.acompletion,
                model="profiling",
                messages=messages,
                temperature=0.0,
                **self._router_max_tokens_kwargs("profiling"),
            )
        except Timeout as e:
            _logger.warning(f"Profile timeout: {e}")
            return {"error": f"profile_timeout: {e}", "transport_error": True}
        except RateLimitError as e:
            _logger.warning(f"Profile rate limit: {e}")
            return {"error": f"profile_rate_limit: {e}", "transport_error": True}
        except AuthenticationError as e:
            _logger.error(f"Profile auth error: {e}")
            return {"error": f"profile_auth: {e}", "transport_error": True}
        except Exception as e:  # expected — return error response for any transport failure
            _logger.error(f"Profile transport failed: {type(e).__name__}: {e}")
            return {
                "error": f"profile_unknown: {type(e).__name__}: {e}",
                "transport_error": True,
            }

        # Truncation detection: finish_reason == "length" → return error dict
        if response.choices[0].finish_reason == "length":
            _logger.warning(
                "Profile response truncated (finish_reason=length); returning error"
            )
            return {"error": "truncated", "truncated": True, "transport_error": True}

        try:
            raw_text = response.choices[0].message.content or ""
        except (AttributeError, IndexError) as resp_err:
            _logger.error(
                f"Profile response shape invalid: {resp_err}; returning empty dict"
            )
            return {"error": f"profile_response_invalid: {resp_err}", "transport_error": True}

        # Issue #36 / #130: strip fences then apply the shared syntactic
        # repair. Parse the LLM JSON response into a dict; on failure, make
        # exactly one LLM-assisted repair attempt. _parse_profile_response in
        # ol_style.doc_profiler accepts both str and dict; returning a parsed
        # dict hits the fast path. On total failure, wrap the raw text under
        # "raw_response" so downstream parsing still has a chance.
        from ol_pool.json_tolerance import repair_json_once, repair_json_text

        def _parse_profile_text(text: str):
            try:
                parsed_obj = json.loads(repair_json_text(text))
            except (json.JSONDecodeError, ValueError):
                return None
            return parsed_obj if isinstance(parsed_obj, dict) else None

        parsed = _parse_profile_text(raw_text)
        if parsed is None:
            async def _repair_call(prompt: str) -> str:
                _resp = await self._call_with_breaker(
                    "profiling",
                    self._router.acompletion,
                    model="profiling",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.0,
                    **self._router_max_tokens_kwargs("profiling"),
                )
                try:
                    return _resp.choices[0].message.content or ""
                except (AttributeError, IndexError):
                    return ""

            try:
                repaired = await repair_json_once(
                    raw_text,
                    ValueError("profile response was not valid JSON"),
                    _repair_call,
                )
                if isinstance(repaired, dict):
                    parsed = repaired
            except Exception as repair_err:  # expected — fall back to raw text
                _logger.warning(
                    f"Profile JSON second-pass repair failed: "
                    f"{type(repair_err).__name__}: {repair_err}"
                )

        if parsed is not None:
            if self._cache_enabled:
                self._cache.put(cache_key, parsed)
            return parsed

        _logger.warning(
            f"Profile response not valid JSON, returning raw text. Head: {raw_text[:120]!r}"
        )
        return {"raw_response": raw_text}
