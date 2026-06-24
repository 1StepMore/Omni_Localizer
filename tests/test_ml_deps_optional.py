"""Tests for ML dep optionality (OL Issue #6).

Verify that:
1. `import ol` does NOT eagerly import keybert/transformers/yake/sentence_transformers
2. ML features raise clean ImportError when deps are not installed
"""
import os
import subprocess
import sys


def test_import_ol_without_ml_deps():
    """import ol must not trigger keybert/transformers/yake/sentence_transformers import.

    Uses a subprocess to avoid conftest.py pre-stubs that already populate
    sys.modules with stubs for all ML packages (done to speed up test collection).
    """
    env = os.environ.copy()
    env["OMNI_TEST_FAKE_LLM"] = "1"
    # Remove PYTHONPATH to ensure we test the installed package, not local sources
    env.pop("PYTHONPATH", None)

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import ol
import sys

failed = []
for mod in ('keybert', 'transformers', 'yake', 'sentence_transformers'):
    if mod in sys.modules:
        failed.append(mod)

if failed:
    print(f'FAIL: {failed} were eagerly imported by import ol', flush=True)
    sys.exit(1)
print('OK: no ML deps eagerly imported by import ol', flush=True)
""",
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, (
        f"stdout={result.stdout} stderr={result.stderr}"
    )


def test_ml_extract_terms_raises_clean_error():
    """extract_terms raises ImportError with pip install hint when ML deps are missing.

    Uses a subprocess with PYTHONPATH to load ol sources but without ML packages.
    The key is to ensure keybert/yake/sentence_transformers/transformers are NOT
    in sys.modules before the import.
    """
    env = os.environ.copy()
    env["OMNI_TEST_FAKE_LLM"] = "1"

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys
# Sanity: unimport any pre-stubbed ML packages that may have leaked in
for _mod in list(sys.modules.keys()):
    if _mod in ('keybert', 'yake', 'sentence_transformers', 'transformers') or \
       _mod.startswith('keybert.') or _mod.startswith('yake.') or \
       _mod.startswith('sentence_transformers.') or _mod.startswith('transformers.'):
        del sys.modules[_mod]

from ol_terminology.extractor import extract_terms

try:
    extract_terms(["test text"])
except ImportError as e:
    msg = str(e)
    if "pip install omni-localizer[ml]" in msg:
        print(f"OK: got clean ImportError with install hint: {msg}", flush=True)
        sys.exit(0)
    else:
        print(f"FAIL: ImportError missing pip install hint. Got: {msg}", flush=True)
        sys.exit(1)
except Exception as e:
    print(f"FAIL: unexpected exception type {type(e).__name__}: {e}", flush=True)
    sys.exit(1)
else:
    print("FAIL: extract_terms did not raise when ML deps are missing", flush=True)
    sys.exit(1)
""",
        ],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, (
        f"stdout={result.stdout} stderr={result.stderr}"
    )
