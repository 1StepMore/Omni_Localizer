"""OL#73: ``ol translate-md --images-json`` forwards the OPP images manifest.

Locks the public CLI behavior removed in PR #81 / 12679b1:

1. ``--images-json <path>`` copies that manifest next to the translated .md.
2. Omitting the flag auto-detects ``{stem}_images.json`` (OPP default).
3. Omitting the flag auto-detects ``{stem}.images.json`` (alternate).
4. No manifest present -> the command is a graceful no-op.
5. The cache-hit fast path also forwards the manifest.

The LLM call is intercepted by ``OMNI_TEST_FAKE_LLM=1``; the CLI command
itself is invoked through the real registered Typer app.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from ol_cli import app

runner = CliRunner()

_MINIMAL_POOL = {
    "translation": [
        {"provider": "openai", "model": "glm-4-flash", "priority": 1,
         "role": "translation", "api_key": "test-key",
         "base_url": "https://open.bigmodel.cn/api/paas/v4"},
        {"provider": "openai", "model": "agnes-2.0-flash", "priority": 2,
         "role": "translation", "api_key": "test-key",
         "base_url": "https://apihub.agnes-ai.com/v1"},
    ],
    "judging": [
        {"provider": "openai", "model": "agnes-2.0-flash", "priority": 1,
         "role": "judging", "api_key": "test-key",
         "base_url": "https://apihub.agnes-ai.com/v1"},
        {"provider": "openai", "model": "glm-4-flash", "priority": 2,
         "role": "judging", "api_key": "test-key",
         "base_url": "https://open.bigmodel.cn/api/paas/v4"},
    ],
    "restoration": [
        {"provider": "openai", "model": "glm-4-flash", "priority": 1,
         "role": "restoration", "api_key": "test-key",
         "base_url": "https://open.bigmodel.cn/api/paas/v4"},
        {"provider": "openai", "model": "agnes-2.0-flash", "priority": 2,
         "role": "restoration", "api_key": "test-key",
         "base_url": "https://apihub.agnes-ai.com/v1"},
    ],
}


@pytest.fixture(autouse=True)
def _fake_llm_env(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("OMNI_TEST_FAKE_LLM", "1")
    # Isolate the content-addressed cache so cache-path tests are hermetic.
    monkeypatch.setenv("OMNI_CACHE_DIR", str(tmp_path / "cache"))


@pytest.fixture
def tmp_config(tmp_path: Path) -> Path:
    cfg = {
        "project_id": "test-images-json",
        "source_lang": "en",
        "target_lang": "zh",
        "llm_pool": _MINIMAL_POOL,
        "max_md_concurrent": 1,
        "enable_lqa": False,
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.dump(cfg), encoding="utf-8")
    return path


def _write_md(path: Path) -> None:
    path.write_text(
        "# Hello\n\nThis is a test paragraph with an image reference.\n",
        encoding="utf-8",
    )


def _write_manifest(path: Path, count: int) -> None:
    data = {"images": [{"id": f"img_{i}", "paragraph_index": i} for i in range(count)]}
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _invoke(
    input_md: Path, out_dir: Path, config: Path, *extra: str,
):
    return runner.invoke(
        app,
        [
            "translate-md", str(input_md),
            "--config", str(config),
            "-s", "en", "-t", "zh",
            "-o", str(out_dir),
            "--no-frontmatter", "--no-restoration",
            *extra,
        ],
    )


class TestImagesJsonForwarding:
    def test_explicit_flag_copies_manifest(self, tmp_path: Path, tmp_config: Path):
        _write_md(tmp_path / "input.md")
        _write_manifest(tmp_path / "my_images.json", count=2)
        out_dir = tmp_path / "out"
        out_dir.mkdir()

        result = _invoke(
            tmp_path / "input.md", out_dir, tmp_config,
            "--no-cache", "--images-json", str(tmp_path / "my_images.json"),
        )

        assert result.exit_code == 0, f"CLI failed: {result.output}"
        copied = out_dir / "my_images.json"
        assert copied.exists(), f"manifest not forwarded to {copied}"
        assert len(json.loads(copied.read_text(encoding="utf-8"))["images"]) == 2

    def test_auto_detect_stem_suffix(self, tmp_path: Path, tmp_config: Path):
        _write_md(tmp_path / "report.md")
        _write_manifest(tmp_path / "report_images.json", count=3)
        out_dir = tmp_path / "out"
        out_dir.mkdir()

        result = _invoke(tmp_path / "report.md", out_dir, tmp_config, "--no-cache")

        assert result.exit_code == 0, f"CLI failed: {result.output}"
        copied = out_dir / "report_images.json"
        assert copied.exists(), f"auto-detected manifest not forwarded to {copied}"
        assert len(json.loads(copied.read_text(encoding="utf-8"))["images"]) == 3

    def test_auto_detect_dot_suffix(self, tmp_path: Path, tmp_config: Path):
        _write_md(tmp_path / "doc.md")
        _write_manifest(tmp_path / "doc.images.json", count=1)
        out_dir = tmp_path / "out"
        out_dir.mkdir()

        result = _invoke(tmp_path / "doc.md", out_dir, tmp_config, "--no-cache")

        assert result.exit_code == 0, f"CLI failed: {result.output}"
        assert (out_dir / "doc.images.json").exists()

    def test_no_manifest_is_graceful_noop(self, tmp_path: Path, tmp_config: Path):
        _write_md(tmp_path / "plain.md")
        out_dir = tmp_path / "out"
        out_dir.mkdir()

        result = _invoke(tmp_path / "plain.md", out_dir, tmp_config, "--no-cache")

        assert result.exit_code == 0, f"CLI failed: {result.output}"
        assert (out_dir / "plain.md").exists()
        assert [p.name for p in out_dir.glob("*.json")] == []

    def test_cache_hit_path_also_forwards_manifest(self, tmp_path: Path, tmp_config: Path):
        _write_md(tmp_path / "cached.md")
        _write_manifest(tmp_path / "cached_images.json", count=2)
        out_dir = tmp_path / "out"
        out_dir.mkdir()

        # First run populates the cache+output (and forwards the manifest).
        first = _invoke(tmp_path / "cached.md", out_dir, tmp_config)
        assert first.exit_code == 0, f"first run failed: {first.output}"

        # Remove the forwarded manifest + MD to prove the second run
        # takes the cache-hit path and re-forwards.
        (out_dir / "cached_images.json").unlink()
        (out_dir / "cached.md").unlink()

        second = _invoke(tmp_path / "cached.md", out_dir, tmp_config)

        assert second.exit_code == 0, f"cache-hit run failed: {second.output}"
        assert (out_dir / "cached.md").exists(), "cache-hit did not restore MD"
        assert (out_dir / "cached_images.json").exists(), (
            "cache-hit path did not forward the images manifest"
        )
