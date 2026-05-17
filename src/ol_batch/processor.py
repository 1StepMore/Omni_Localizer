"""Batch processing orchestration for file translation."""

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ol_batch.config import BatchConfig, BatchResult
from ol_concurrency.scheduler import ConcurrencyLimiter
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
    ) -> None:
        self._config = config
        self._pool = model_pool
        self._limiter = limiter

    async def process_batch(
        self,
        files: list[Path],
        output_dir: Path,
    ) -> BatchResult:
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
                    failed.append((file, str(result)))
                elif result is not None:
                    succeeded.append(result)
                else:
                    failed.append((file, "Unknown error"))
        except asyncio.CancelledError:
            raise
        except Exception:
            raise

        return BatchResult(
            succeeded=succeeded,
            failed=failed,
            total=len(files),
        )

    async def _process_single_file(
        self,
        input_path: Path,
        output_dir: Path,
    ) -> Optional[Path]:
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
            "en",
            "zh",
        )

        if shield_map:
            translated = unshield_markdown(translated, shield_map)

        repaired = MDRepairPipeline().repair(translated, original_text, shield_map)

        output_file = output_dir / input_path.name
        output_file.write_text(repaired, encoding="utf-8")

        return output_file


class QueueTimeoutError(Exception):
    """Raised when translation queue times out."""
    pass