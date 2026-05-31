import asyncio
import os
import re
from typing import Any

# E2E-05 fix: Must be set BEFORE importing litellm.
# liteLLM imports submodules on `import litellm`, which can trigger HuggingFace
# network access for model metadata (e.g. bert-base-multilingual-cased) before
# LITELLM_OFFLINE is read. Setting this here prevents that.
os.environ.setdefault("LITELLM_OFFLINE", "true")
os.environ.setdefault("LITELLM_DISABLE_MODEL_LIST_AUTO_UPDATE", "true")

import litellm
from litellm.exceptions import AuthenticationError, RateLimitError, Timeout
from litellm.types.router import RouterRateLimitError

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
        raise NotImplementedError("Use ModelPool.get_instance() instead")

    @classmethod
    def get_instance(cls, config_path: str = "config/default.yaml") -> "ModelPool":
        if config_path not in _pool_cache:
            config, _ = load_config(config_path)
            global_timeout = max(
                (m.timeout for role in ("translation", "judging", "restoration")
                 for m in getattr(config.llm_pool, role, [])),
                default=180.0,
            )
            self = cls.__new__(cls)
            self._router = Router(
                model_list=self._build_model_list(config.llm_pool),
                routing_strategy="simple-shuffle",
                num_retries=2,
                timeout=global_timeout,
                fallbacks=self._build_fallbacks(config.llm_pool),
            )
            _pool_cache[config_path] = self
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
                if model.max_tokens is not None:
                    litellm_params["max_tokens"] = model.max_tokens
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
        _logger.debug(f"Translation request: {len(text)} chars, {source_lang}→{target_lang}")
        _logger.debug("Model selected: translation")

        if isinstance(context, str):
            prompt = context
        else:
            prompt_parts = [
                f"You are a professional translator. Translate the following {source_lang} text to {target_lang}. ",
                f"IMPORTANT: Provide only the {target_lang} translation. Do not include any instructions, explanations, or text in any other language.",
                f"Source ({source_lang}): {text}",
            ]
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

        for attempt in range(4):  # 1 initial + 3 retries
            try:
                response = await self._router.acompletion(
                    model="translation",
                    messages=[
                        {
                            "role": "user",
                            "content": prompt,
                        },
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
            except (RateLimitError, RouterRateLimitError) as e:
                if attempt < 3:
                    wait = 2 ** attempt * 10
                    _logger.warning(f"RateLimitError/RouterRateLimitError, retrying in {wait}s (attempt {attempt + 1}/4): {e}")
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
        terminology_section = ""
        if glossary:
            terms = ", ".join(f"{k} → {v}" for k, v in glossary.items())
            terminology_section = f"\nTerminology: {terms}"
        prompt = f"""Evaluate translation quality:

Source ({source_lang}): {source}
Target ({target_lang}): {target}{terminology_section}

Rate the translation on a scale of 0-100 for:
- Accuracy (30%)
- Fluency (30%)
- Adequacy (40%)

Return a JSON object with:
{{"score": <int 0-100>, "reason": "<brief explanation>"}}
Only return valid JSON, nothing else."""

        response = await self._router.acompletion(
            model="judging",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
        )
        import json
        content = response.choices[0].message.content.strip()
        try:
            result = json.loads(content)
        except json.JSONDecodeError:
            _logger.warning(f"Judge parse failed, using fallback score=50. Raw response: {content[:300]}")
            result = {"score": 50, "reason": content[:200] if content else "Parse failed", "parse_failed": True}
        return result
