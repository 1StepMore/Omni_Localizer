"""Batch processing orchestration for file translation."""

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ol_batch.config import BatchConfig, BatchResult
from ol_cli import (
    _generate_frontmatter,
    _generate_skip_frontmatter,
    _get_ol_version,
    _validate_lang_code,
)
from ol_concurrency.scheduler import ConcurrencyLimiter, QueueTimeoutError
from ol_logging.core import get_logger
from ol_md.pipeline import MDRepairPipeline
from ol_md.shield import shield_markdown, unshield_markdown
from ol_pool.router import ModelPool
from ol_terminology.glossary import get_relevant_terms
from ol_terminology.rag_injector import build_translate_prompt


@dataclass
class TranslationResult:
    """Result of a single file translation."""

    output_path: Path
    skipped: bool = False
    skip_reason: str | None = None
    detected_source_lang: str | None = None


@dataclass
class BatchProcessor:
    """Orchestrates parallel file translation with rate limiting."""

    def __init__(
        self,
        config: BatchConfig,
        model_pool: ModelPool,
        limiter: ConcurrencyLimiter,
        add_frontmatter: bool = True,
        src_lang: str = "en",
        tgt_lang: str = "zh",
        tm_service: Any = None,
        glossary: dict[str, dict[str, Any]] | None = None,
        detect_language: bool = True,
    ) -> None:
        self._config = config
        self._pool = model_pool
        self._limiter = limiter
        self.add_frontmatter = add_frontmatter
        self.src_lang = src_lang
        self.tgt_lang = tgt_lang
        self._tm_service = tm_service
        self._glossary = glossary or {}
        self._detect_language = detect_language
        self._logger = get_logger("batch.processor")

    async def process_batch(
        self,
        files: list[Path],
        output_dir: Path,
        add_frontmatter: bool = True,
        src_lang: str = "en",
        tgt_lang: str = "zh",
        detect_language: bool = True,
    ) -> BatchResult:
        self.add_frontmatter = add_frontmatter
        self.src_lang = src_lang
        self.tgt_lang = tgt_lang
        self._detect_language = detect_language
        self._logger.info(f"Batch processing started: {len(files)} files")
        output_dir.mkdir(parents=True, exist_ok=True)

        succeeded: list[Path] = []
        failed: list[tuple[Path, str]] = []

        try:
            tasks = [self._process_single_file(file, output_dir) for file in files]

            results = await asyncio.gather(*tasks, return_exceptions=True)

            for file, result in zip(files, results):
                if isinstance(result, Exception):
                    error_msg = str(result)
                    # Unwrap ExceptionGroup if present
                    if isinstance(result, ExceptionGroup):
                        if result.exceptions:
                            error_msg = str(result.exceptions[0])
                    self._logger.error(f"File failed: {file.name} - {error_msg}")
                    failed.append((file, error_msg))
                elif isinstance(result, TranslationResult) and result is not None:
                    succeeded.append(result.output_path)
                else:
                    failed.append((file, "Unknown error"))
        except asyncio.CancelledError:
            raise
        except Exception:
            raise

        result = BatchResult(
            succeeded=succeeded,
            failed=failed,
            total=len(files),
        )
        self._logger.info(f"Batch complete: {result.success_rate:.1f}% success rate")
        return result

    async def _process_single_file(
        self,
        input_path: Path,
        output_dir: Path,
    ) -> TranslationResult | None:
        self._logger.debug(f"Processing file: {input_path.name}")
        try:
            async with self._limiter.translation(timeout=self._config.timeout):
                return await self._translate_file(input_path, output_dir)
        except TimeoutError:
            raise QueueTimeoutError(
                f"Translation timed out for {input_path.name} after {self._config.timeout}s",
            )
        except Exception as e:
            raise RuntimeError(f"Failed to process {input_path.name}: {e}")

    async def _translate_file(
        self,
        input_path: Path,
        output_dir: Path,
    ) -> TranslationResult:
        original_text = input_path.read_text(encoding="utf-8")

        # Optional language detection for early exit
        if self._detect_language and input_path.suffix == ".md":
            try:
                from langdetect import detect

                detected_source_lang = detect(original_text)
                if detected_source_lang == self.tgt_lang:
                    output_file = output_dir / input_path.name
                    skipped_content = original_text

                    if self.add_frontmatter and not original_text.strip().startswith("---"):
                        safe_src = _validate_lang_code(detected_source_lang)
                        safe_tgt = _validate_lang_code(self.tgt_lang)
                        frontmatter = _generate_skip_frontmatter(
                            source_lang=safe_src,
                            target_lang=safe_tgt,
                            original_filename=input_path.name,
                            ol_version=_get_ol_version(),
                            detected_source_lang=detected_source_lang,
                        )
                        skipped_content = frontmatter + original_text

                    output_file.write_text(skipped_content, encoding="utf-8")
                    return TranslationResult(
                        output_path=output_file,
                        skipped=True,
                        skip_reason="already_in_target_language",
                        detected_source_lang=detected_source_lang,
                    )
            except ImportError:
                # langdetect not installed, proceed with translation
                self._logger.warning("langdetect not available, skipping language detection")
            except Exception as e:
                self._logger.warning(f"Language detection failed: {e}, proceeding with translation")

        shielded, shield_map = shield_markdown(original_text)

        context = None
        if self._tm_service:
            tm_matches = self._tm_service.search(shielded, threshold=0.85)[:3]
            if tm_matches:
                # Convert TMMatch dataclass instances to dicts for build_translate_prompt
                tm_match_dicts = [
                    {"source": m.source, "target": m.target, "score": m.similarity}
                    for m in tm_matches
                ]
                glossary_terms = get_relevant_terms(shielded, glossary=self._glossary, top_k=5)
                context = build_translate_prompt(
                    text=shielded,
                    src_lang=self.src_lang,
                    tgt_lang=self.tgt_lang,
                    tm_matches=tm_match_dicts,
                    glossary_terms=glossary_terms,
                )

        translated = await self._pool.translate(
            shielded,
            self.src_lang,
            self.tgt_lang,
            context,
        )

        if shield_map:
            translated = unshield_markdown(translated, shield_map)

        repaired = MDRepairPipeline().repair(translated, original_text, shield_map)

        if (
            self.add_frontmatter
            and input_path.suffix == ".md"
            and not repaired.strip().startswith("---")
        ):
            safe_src = _validate_lang_code(self.src_lang)
            safe_tgt = _validate_lang_code(self.tgt_lang)
            frontmatter = _generate_frontmatter(
                source_lang=safe_src,
                target_lang=safe_tgt,
                original_filename=input_path.name,
                ol_version=_get_ol_version(),
            )
            repaired = frontmatter + repaired

        output_file = output_dir / input_path.name
        output_file.write_text(repaired, encoding="utf-8")

        return TranslationResult(output_path=output_file)
