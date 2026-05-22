"""Batch processing orchestration for file translation."""

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ol_batch.config import BatchConfig, BatchResult
from ol_cli import _generate_frontmatter, _get_ol_version, _escape_yaml_value, _validate_lang_code
from ol_concurrency.scheduler import ConcurrencyLimiter, QueueTimeoutError
from ol_logging.core import get_logger
from ol_pool.router import ModelPool
from ol_md.shield import shield_markdown, unshield_markdown
from ol_md.pipeline import MDRepairPipeline


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
    ) -> None:
        self._config = config
        self._pool = model_pool
        self._limiter = limiter
        self.add_frontmatter = add_frontmatter
        self.src_lang = src_lang
        self.tgt_lang = tgt_lang
        self._logger = get_logger("batch.processor")

    async def process_batch(
        self,
        files: list[Path],
        output_dir: Path,
        add_frontmatter: bool = True,
        src_lang: str = "en",
        tgt_lang: str = "zh",
    ) -> BatchResult:
        self.add_frontmatter = add_frontmatter
        self.src_lang = src_lang
        self.tgt_lang = tgt_lang
        self._logger.info(f"Batch processing started: {len(files)} files")
        output_dir.mkdir(parents=True, exist_ok=True)

        succeeded: list[Path] = []
        failed: list[tuple[Path, str]] = []

        try:
            tasks = [
                self._process_single_file(file, output_dir)
                for file in files
            ]

            results = await asyncio.gather(*tasks, return_exceptions=True)

            for file, result in zip(files, results):
                if isinstance(result, Exception):
                    self._logger.error(f"File failed: {file.name} - {result}")
                    failed.append((file, str(result)))
                elif result is not None:
                    succeeded.append(result)
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
    ) -> Optional[Path]:
        self._logger.debug(f"Processing file: {input_path.name}")
        try:
            async with self._limiter.translation(timeout=self._config.timeout):
                return await self._translate_file(input_path, output_dir)
        except asyncio.TimeoutError:
            raise QueueTimeoutError(
                f"Translation timed out for {input_path.name} after {self._config.timeout}s"
            )
        except Exception as e:
            raise RuntimeError(f"Failed to process {input_path.name}: {e}")

    async def _translate_file(
        self,
        input_path: Path,
        output_dir: Path,
    ) -> Path:
        original_text = input_path.read_text(encoding="utf-8")

        shielded, shield_map = shield_markdown(original_text)

        translated = await self._pool.translate(
            shielded,
            self.src_lang,
            self.tgt_lang,
        )

        if shield_map:
            translated = unshield_markdown(translated, shield_map)

        repaired = MDRepairPipeline().repair(translated, original_text, shield_map)

        if self.add_frontmatter and input_path.suffix == '.md' and not repaired.strip().startswith('---'):
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

        return output_file