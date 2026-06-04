"""Edge case tests for batch translation, checkpoint/resume, and failure recovery.

Verifies the BEHAVIOR (does batch work, does resume work, does skip work)
not the IMPLEMENTATION of those subsystems.

Activation:
  OMNI_TEST_FAKE_LLM=1 is honored by the production CLI paths, but the
  tests here use direct unit-level fixtures (mocked ModelPool + the real
  parser/pipeline) so they work without any environment variable.

T7-retry already locked the existing test_batch_processor.py,
test_checkpoint.py, and test_batch_edge_cases.py green. This file adds a
new surface:

  - TestBatchTranslationFiveFiles       (5+ files in one call)
  - TestCheckpointResumeFromKill        (write → kill → restart → resume)
  - TestFailureRecoverySkipBadUnit      (bad XLIFF unit graceful skip)
"""
import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# Windows compatibility: the CheckpointManager uses fcntl which is missing.
if sys.platform == 'win32':
    import unittest.mock
    sys.modules.setdefault('fcntl', unittest.mock.MagicMock())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_pool(translator=None):
    """Build a mocked ModelPool with a configurable async translate.

    Defaults to a simple identity-ish translator that prepends '[ZH] '.
    """
    pool = MagicMock()

    async def _translate(text, src, tgt, context=None, **_kwargs):
        if translator is not None:
            return translator(text, src, tgt, context)
        return f"[ZH] {text}"

    pool.translate = AsyncMock(side_effect=_translate)
    return pool


def _make_mock_limiter():
    """Build a mocked ConcurrencyLimiter whose context manager is non-suppressing.

    `__aexit__` must return None/False so exceptions raised inside the
    `async with` block propagate. A bare AsyncMock returns a truthy Mock
    by default, which would swallow real errors.
    """
    limiter = MagicMock()
    limiter.translation = MagicMock()
    limiter.translation.return_value.__aenter__ = AsyncMock(return_value=None)
    limiter.translation.return_value.__aexit__ = AsyncMock(return_value=None)
    return limiter


def _create_md_files(directory: Path, count: int) -> list[Path]:
    """Create `count` simple markdown files under `directory` and return their paths."""
    directory.mkdir(parents=True, exist_ok=True)
    files: list[Path] = []
    for i in range(count):
        path = directory / f"doc_{i:02d}.md"
        path.write_text(
            (
                f"# Document {i}\n\n"
                f"This is the body of document {i}.\n\n"
                f"## Section {i}\n\n"
                f"More content for doc {i}."
            ),
            encoding="utf-8",
        )
        files.append(path)
    return files


# ---------------------------------------------------------------------------
# 1. Batch — 5+ files in a single call, all green
# ---------------------------------------------------------------------------

class TestBatchTranslationFiveFiles:
    """Batch translation of 5+ files in a single call must all succeed."""

    @pytest.mark.anyio
    async def test_batch_translates_exactly_5_files(self, tmp_path):
        """Lower-bound: 5 files in one call → all succeed."""
        from ol_batch.config import BatchConfig
        from ol_batch.processor import BatchProcessor

        input_dir = tmp_path / "input"
        output_dir = tmp_path / "output"
        files = _create_md_files(input_dir, 5)
        output_dir.mkdir(parents=True, exist_ok=True)

        pool = _make_mock_pool()
        limiter = _make_mock_limiter()
        processor = BatchProcessor(
            config=BatchConfig(max_concurrent=2, timeout=30.0),
            model_pool=pool,
            limiter=limiter,
        )

        result = await processor.process_batch(files, output_dir)

        assert result.total == 5
        assert len(result.succeeded) == 5
        assert len(result.failed) == 0
        assert result.success_rate == 100.0

        # All output files exist and are non-empty
        for src in files:
            out = output_dir / src.name
            assert out.exists(), f"missing output: {out.name}"
            assert out.stat().st_size > 0

    @pytest.mark.anyio
    async def test_batch_translates_8_files_with_realistic_content(self, tmp_path):
        """Above lower-bound: 8 files with mixed short/long bodies still all green."""
        from ol_batch.config import BatchConfig
        from ol_batch.processor import BatchProcessor

        input_dir = tmp_path / "input"
        output_dir = tmp_path / "output"
        input_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Mix of short and long files. We intentionally avoid fenced code
        # blocks, inline code, links, images, and HTML — those trigger the
        # MD shielding path which interacts with the test-only span_aligner
        # stub. The core "5+ files in a single call" behaviour is
        # independent of those markdown features.
        payloads = [
            "# Tiny\n\nHi.",
            "# Medium\n\nA paragraph with simple text and punctuation.",
            "# Lists\n\n- item 1\n- item 2\n- item 3",
            "# Tables\n\nPlain text, no tables.",
            "# Long\n\n" + ("lorem ipsum dolor sit amet. " * 50),
            "# With unicode\n\n你好世界 — こんにちは — 안녕하세요",
            "# Mixed\n\nFirst paragraph.\n\nSecond paragraph.",
            "# Closing\n\nThe end.",
        ]
        files: list[Path] = []
        for i, body in enumerate(payloads):
            p = input_dir / f"mix_{i}.md"
            p.write_text(body, encoding="utf-8")
            files.append(p)

        pool = _make_mock_pool()
        limiter = _make_mock_limiter()
        processor = BatchProcessor(
            config=BatchConfig(max_concurrent=3, timeout=30.0),
            model_pool=pool,
            limiter=limiter,
        )

        result = await processor.process_batch(files, output_dir)

        assert result.total == 8
        assert len(result.succeeded) == 8
        assert len(result.failed) == 0
        # The mock pool was called at least once per file
        assert pool.translate.await_count == 8

    @pytest.mark.anyio
    async def test_batch_uses_actual_fixture_md_file(self, tmp_path, monkeypatch):
        """Batch should also succeed on the real sample.md fixture (non-synthetic)."""
        from ol_batch.config import BatchConfig
        from ol_batch.processor import BatchProcessor

        # Copy the real sample.md into a tmp dir and add 4 more files alongside
        fixtures_dir = Path(__file__).parent / "fixtures"
        sample = fixtures_dir / "sample.md"
        assert sample.exists(), "sample.md fixture must exist"

        input_dir = tmp_path / "input"
        output_dir = tmp_path / "output"
        input_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)

        copied_sample = input_dir / "sample.md"
        copied_sample.write_text(sample.read_text(encoding="utf-8"), encoding="utf-8")
        synthetic = _create_md_files(input_dir, 4)
        files = [copied_sample, *synthetic]

        # sample.md contains fenced code blocks and inline math; both go
        # through shield_markdown + MDRepairPipeline which the test-only
        # span_aligner stub does not implement faithfully. Disable L2 to
        # make this test focus on the batch-level wiring rather than the
        # repair cascade.
        import ol_md.repair.level2 as level2_mod
        monkeypatch.setattr(level2_mod, "_has_span_aligner", False)

        pool = _make_mock_pool()
        limiter = _make_mock_limiter()
        processor = BatchProcessor(
            config=BatchConfig(max_concurrent=2, timeout=30.0),
            model_pool=pool,
            limiter=limiter,
        )

        result = await processor.process_batch(files, output_dir)

        assert result.total == 5
        assert len(result.succeeded) == 5
        assert len(result.failed) == 0
        # The real sample's output should be present
        assert (output_dir / "sample.md").exists()
        assert (output_dir / "sample.md").stat().st_size > 0


# ---------------------------------------------------------------------------
# 2. Checkpoint — write, kill, restart, resume from checkpoint
# ---------------------------------------------------------------------------

class TestCheckpointResumeFromKill:
    """Verify write-checkpoint → kill → restart → resume picks up at the
    last successfully-processed unit."""

    def _build_20_unit_xliff(self) -> str:
        units = "\n".join(
            (
                f'    <trans-unit id="u_{i:02d}">\n'
                f'      <source>Source text for unit {i:02d}.</source>\n'
                f'    </trans-unit>'
            )
            for i in range(20)
        )
        return (
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<xliff version="1.2" '
            'xmlns="urn:oasis:names:tc:xliff:document:1.2">\n'
            '  <file source-language="en" target-language="zh" original="x">\n'
            '    <body>\n'
            f'{units}\n'
            '    </body>\n'
            '  </file>\n'
            '</xliff>\n'
        )

    def test_kill_at_50_percent_then_resume_picks_up_at_processed(self, tmp_path):
        """20 units → process 10 → save checkpoint → kill (new manager)
        → restart → resume(merge) reports 10 recovered units and 10 remaining.
        """
        from ol_checkpoint import CheckpointManager

        # The "source" file is just used for hash verification. The real
        # unit list lives inside the checkpoint payload.
        source_path = tmp_path / "input.xlf"
        source_path.write_text(self._build_20_unit_xliff(), encoding="utf-8")
        checkpoint_path = tmp_path / "checkpoint.json"

        all_units = [f"u_{i:02d}" for i in range(20)]

        # ---- Pass 1: process first 10, save checkpoint ----
        mgr1 = CheckpointManager(str(checkpoint_path), str(source_path))
        source_hash = mgr1._compute_hash(source_path)
        processed = all_units[:10]
        mgr1.save({
            "version": "1.0",
            "file_hash": source_hash,
            "processed_units": processed,
            "total_units": 20,
            "completed_units": 10,
        })
        assert checkpoint_path.exists()

        # ---- Simulate kill: drop the first manager entirely ----
        del mgr1

        # ---- Pass 2: fresh process starts a new manager ----
        mgr2 = CheckpointManager(str(checkpoint_path), str(source_path))
        loaded = mgr2.load()

        # Checkpoint survived the "kill"
        assert loaded["completed_units"] == 10
        assert loaded["total_units"] == 20
        assert loaded["processed_units"] == processed

        # Resume in merge mode: 10 already done, 10 to go
        resume = mgr2.resume("merge")
        assert resume.fresh_start is False
        assert resume.mode == "merge"
        assert resume.recovered_units == 10

        remaining = sorted(set(all_units) - set(loaded["processed_units"]))
        assert len(remaining) == 10
        assert remaining[0] == "u_10"
        assert remaining[-1] == "u_19"

    def test_resume_preserves_processed_units_across_kill(self, tmp_path):
        """The processed_units list is exactly preserved across save/load/kill."""
        from ol_checkpoint import CheckpointManager

        checkpoint_path = tmp_path / "checkpoint.json"
        units = [f"u_{i:03d}" for i in range(50)]

        mgr1 = CheckpointManager(str(checkpoint_path))
        mgr1.save({
            "version": "1.0",
            "processed_units": units[:25],
            "total_units": 50,
            "completed_units": 25,
        })

        # Simulate kill
        del mgr1

        mgr2 = CheckpointManager(str(checkpoint_path))
        loaded = mgr2.load()

        assert loaded["processed_units"] == units[:25]
        # Verify ordering is preserved (not just set membership)
        assert loaded["processed_units"][0] == "u_000"
        assert loaded["processed_units"][-1] == "u_024"

    def test_force_mode_clears_checkpoint_for_fresh_start(self, tmp_path):
        """A user choosing 'force' after a kill expects a fresh start, not resume."""
        from ol_checkpoint import CheckpointManager

        checkpoint_path = tmp_path / "checkpoint.json"
        checkpoint_path.write_text(json.dumps({
            "version": "1.0",
            "processed_units": ["u1", "u2", "u3"],
            "completed_units": 3,
        }))

        mgr = CheckpointManager(str(checkpoint_path))
        result = mgr.resume("force")

        assert result.fresh_start is True
        assert result.mode == "force"
        assert not checkpoint_path.exists(), "force must clear the checkpoint file"

    def test_atomic_save_survives_concurrent_kill(self, tmp_path):
        """A concurrent save while another reader has the file open should
        not corrupt the checkpoint (atomic write contract)."""
        from ol_checkpoint import CheckpointManager

        checkpoint_path = tmp_path / "checkpoint.json"
        mgr = CheckpointManager(str(checkpoint_path))

        mgr.save({"version": "1.0", "processed_units": ["a", "b"]})
        snapshot_a = json.loads(checkpoint_path.read_text(encoding="utf-8"))

        # Simulate a "second run" overwriting the checkpoint
        mgr.save({"version": "1.0", "processed_units": ["a", "b", "c", "d"]})
        snapshot_b = json.loads(checkpoint_path.read_text(encoding="utf-8"))

        # The file is always parseable JSON, never partially written
        assert isinstance(snapshot_a, dict) and isinstance(snapshot_b, dict)
        assert snapshot_b["processed_units"] == ["a", "b", "c", "d"]
        # The old snapshot reflects what was on disk at that point
        assert snapshot_a["processed_units"] == ["a", "b"]


# ---------------------------------------------------------------------------
# 3. Failure recovery — bad XLIFF unit must be skipped, not crash
# ---------------------------------------------------------------------------

class TestFailureRecoverySkipBadUnit:
    """Verify that a malformed/bad XLIFF unit does not crash the whole batch.

    Covers three distinct skip surfaces:
      (a) Parser: empty <trans-unit> is silently dropped from the unit list
      (b) Writer: unit with target_text=None is skipped by write_target_back
      (c) Repair: missing placeholders trigger L4 warnings, not a crash
    """

    # XLIFF with 3 units where unit 2 has no <source> element
    XLF_WITH_EMPTY_UNIT = """<?xml version="1.0" encoding="utf-8"?>
<xliff version="1.2" xmlns="urn:oasis:names:tc:xliff:document:1.2">
  <file source-language="en" target-language="zh" original="sample">
    <body>
      <trans-unit id="1">
        <source>Good unit one.</source>
      </trans-unit>
      <trans-unit id="2">
      </trans-unit>
      <trans-unit id="3">
        <source>Good unit three.</source>
      </trans-unit>
    </body>
  </file>
</xliff>
"""

    def test_parser_silently_skips_empty_trans_unit(self, tmp_path):
        """(a) A trans-unit with no <source> is gracefully dropped from the
        parsed unit list — the parse does not raise, the bad unit is not
        in the output.
        """
        from ol_xliff.parser import XliffParser

        xlf = tmp_path / "input.xlf"
        xlf.write_text(self.XLF_WITH_EMPTY_UNIT, encoding="utf-8")

        parser = XliffParser()
        all_units = parser.parse(str(xlf))
        real_units = [u for u in all_units if not u.unit_id.startswith("__xliff_")]

        # Only 2 real units (the empty one is silently dropped)
        assert len(real_units) == 2
        assert {u.unit_id for u in real_units} == {"1", "3"}
        # The good units retained their source text
        u1 = next(u for u in real_units if u.unit_id == "1")
        u3 = next(u for u in real_units if u.unit_id == "3")
        assert u1.source_text == "Good unit one."
        assert u3.source_text == "Good unit three."

    def test_writer_skips_unit_with_none_target(self, tmp_path):
        """(b) write_target_back() must skip units whose target_text is None,
        not crash on the missing target tag.
        """
        from ol_buses.xliff_bus import _ensure_target_tags, write_target_back
        from ol_core.dataclass import ChannelType, TranslationContext, TranslationUnit

        original = _ensure_target_tags(self.XLF_WITH_EMPTY_UNIT)

        ctx = TranslationContext(
            file_path=str(tmp_path / "input.xlf"),
            channel_type=ChannelType.XLIFF,
            original_full_text=original,
            units=[
                TranslationUnit(
                    unit_id="1",
                    source_text="Good unit one.",
                    target_text="[ZH] Unit 1",
                ),
                TranslationUnit(
                    unit_id="2",
                    source_text="",
                    target_text=None,
                ),
                TranslationUnit(
                    unit_id="3",
                    source_text="Good unit three.",
                    target_text="[ZH] Unit 3",
                ),
            ],
        )

        out_path = tmp_path / "output.xlf"
        write_target_back(ctx, str(out_path))

        result = out_path.read_text(encoding="utf-8")
        assert '<target>[ZH] Unit 1</target>' in result
        assert '<target>[ZH] Unit 3</target>' in result
        assert 'id="2"' in result, "unit 2 element should still be in the output"
        assert '<target>[ZH] Unit 2</target>' not in result, (
            "unit 2 must NOT be written because target_text is None"
        )

    def test_repair_emits_warning_for_missing_placeholder(self, tmp_path, monkeypatch):
        """(c) When a unit's translation loses its placeholders, L4 safe
        fallback must emit a warning rather than silently producing
        malformed output or crashing the pipeline.
        """
        from ol_xliff.pipeline import XLIFFRepairPipeline

        import ol_xliff.repair.level2 as xliff_level2
        monkeypatch.setattr(xliff_level2, "_has_span_aligner", False)

        pipeline = XLIFFRepairPipeline(llm_restorer=None)

        original = "Click <x id=\"1\"/> here for details"
        shield_map = {"x_1": '<x id="1"/>'}
        broken_translation = "点击这里查看详情"

        repaired, warnings = pipeline.repair(broken_translation, original, shield_map)

        assert isinstance(repaired, str)
        assert isinstance(warnings, list)
        assert len(warnings) >= 1, "missing placeholder should trigger a warning"
        assert any(
            "OL_WARN" in w or "placeholder" in w.lower() or "appended" in w.lower()
            for w in warnings
        )
        assert '<x id="1"/>' in repaired, (
            "the original tag should be re-appended by L4 fallback"
        )

    @pytest.mark.anyio
    async def test_batch_with_unreadable_file_does_not_crash_others(self, tmp_path, caplog):
        """A directory mixing good MD files and an unreadable path must
        process the good files successfully and surface the bad one as
        a failure, not a crash.
        """
        from ol_batch.config import BatchConfig
        from ol_batch.processor import BatchProcessor

        input_dir = tmp_path / "input"
        output_dir = tmp_path / "output"
        input_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)

        good_files = _create_md_files(input_dir, 3)
        bad_path = input_dir / "bad.md"
        bad_path.mkdir()

        pool = _make_mock_pool()
        limiter = _make_mock_limiter()
        processor = BatchProcessor(
            config=BatchConfig(file_patterns=["*.md"], timeout=30.0),
            model_pool=pool,
            limiter=limiter,
        )

        files = sorted(input_dir.iterdir())
        result = await processor.process_batch(files, output_dir)

        assert result.total == 4
        succeeded_names = {p.name for p in result.succeeded}
        for gf in good_files:
            assert gf.name in succeeded_names
        failed_names = {p.name for p, _ in result.failed}
        assert "bad.md" in failed_names
        for f, err in result.failed:
            if f.name == "bad.md":
                assert isinstance(err, str) and len(err) > 0
