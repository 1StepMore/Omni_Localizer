"""A11 — Real-LLM test harness fixtures.

This conftest is scoped to ``tests/real_llm/``. The root
``tests/conftest.py`` inserts a ``_HeavyImportBlocker`` at
``sys.meta_path[0]`` so the unit tests run fast (litellm/torch/
transformers are stubbed). The ``real_model_pool`` fixture
below removes that blocker, re-imports the real ``litellm``, and
re-binds it in ``ol_pool.router``'s namespace before instantiating
``ModelPool`` from ``config/local.yaml`` — so real LLM calls work when
the gate env vars are set.

Gating contract (enforced both here and on individual tests):
- ``OMNI_RUN_REAL_LLM=1`` — master switch. When unset, real-LLM tests
  skip cleanly without touching the model pool.
- ``MINIMAX_API_KEY`` — required for ``config/local.yaml`` to resolve
  ``${MINIMAX_API_KEY}`` in the translation/judging/restoration roles.

Markers (registered in ``pyproject.toml``):
- ``real_llm_required`` — tests that ALWAYS need a real LLM. Skipped in
  normal CI via the conftest's ``pytest_collection_modifyitems`` hook.
- ``real_llm_optional`` — tests that *can* use a real LLM if the env
  is available, but otherwise fall back to mocks. (Reserved for
  future use; the A11 suite only ships ``real_llm_required`` tests.)

Cost gate: the ``cost_estimator`` fixture returns a fresh
``CostEstimator(budget_usd=5.0)`` per test. The nightly workflow and
the runbook document the per-night budget expectation ($5-15/month).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from tests.real_llm.cost_estimator import CostEstimator


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_REAL_LLM_DIR = Path(__file__).resolve().parent
_OL_ROOT = _REAL_LLM_DIR.parent.parent  # .../Omni_Localizer/
_LOCAL_CONFIG = _OL_ROOT / "config" / "local.yaml"
_CORPUS_DIR = _OL_ROOT / "tests" / "fixtures" / "real_llm_corpus"


# ---------------------------------------------------------------------------
# Marker → skipif wiring
# ---------------------------------------------------------------------------

_REAL_LLM_REQUIRED_SKIP = pytest.mark.skipif(
    not os.environ.get("OMNI_RUN_REAL_LLM"),
    reason=(
        "OMNI_RUN_REAL_LLM not set; real-LLM test skipped. "
        "Set OMNI_RUN_REAL_LLM=1 (and MINIMAX_API_KEY) to enable. "
        "See docs/real_llm_runbook.md."
    ),
)

_REAL_LLM_OPTIONAL_SKIP = pytest.mark.skipif(
    not (os.environ.get("OMNI_RUN_REAL_LLM") and os.environ.get("MINIMAX_API_KEY")),
    reason=(
        "Real LLM unavailable (need OMNI_RUN_REAL_LLM=1 and MINIMAX_API_KEY). "
        "Test falls back to a mock or is skipped; see docs/real_llm_runbook.md."
    ),
)


def pytest_collection_modifyitems(config, items):  # noqa: ARG001
    """Apply skipif markers to any test carrying ``real_llm_required``
    or ``real_llm_optional``. The marker registration in
    ``pyproject.toml`` silences PytestUnknownMarkWarning.
    """
    for item in items:
        if "real_llm_required" in item.keywords:
            item.add_marker(_REAL_LLM_REQUIRED_SKIP)
        if "real_llm_optional" in item.keywords:
            item.add_marker(_REAL_LLM_OPTIONAL_SKIP)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def corpus_dir() -> Path:
    """Path to the real-LLM corpus directory.

    The directory ships with 5 simple English business paragraphs plus
    a ``reference_outputs.json``. Available in any environment — no
    LLM required. Tests use this to load inputs and expected behavior
    without duplicating fixtures.
    """
    assert _CORPUS_DIR.exists(), (
        f"Real-LLM corpus dir missing: {_CORPUS_DIR}. "
        f"Run from the Omni_Localizer repo root, or check the PR14 corpus drop."
    )
    return _CORPUS_DIR


@pytest.fixture
def cost_estimator() -> "CostEstimator":
    """A fresh ``CostEstimator`` with a $5 budget, per-test.

    Pure-Python class; no I/O, no LLM. Available in normal CI so the
    cost-estimator unit tests can be re-run against the same fixture
    the real-LLM tests use in nightly CI.
    """
    from tests.real_llm.cost_estimator import CostEstimator
    return CostEstimator(budget_usd=5.0)


@pytest.fixture(scope="session")
def real_model_pool():
    """Real ``ModelPool`` from ``config/local.yaml``.

    Skips unless:
      - ``OMNI_RUN_REAL_LLM=1`` (master gate)
      - ``MINIMAX_API_KEY`` is set (required for local.yaml env-var
        resolution)

    The root ``tests/conftest.py`` installs a ``_HeavyImportBlocker``
    that stubs litellm for fast unit tests. To make real LLM calls
    work, this fixture:

    1. Removes the blocker from ``sys.meta_path``.
    2. Drops the stubbed ``litellm`` and ``litellm.*`` entries from
       ``sys.modules`` so a fresh ``import litellm`` returns the real
       package.
    3. Re-binds ``Router`` and the exception classes in
       ``ol_pool.router``'s namespace — the module-level
       ``from litellm import Router`` already ran with the stub.
    4. Clears ``ol_pool.router._pool_cache`` so a previously-stubbed
       pool doesn't leak in.
    5. Re-imports ``ol_pool.router`` so the new module-level
       ``litellm.disable_model_name_normalization = True`` and
       ``from litellm import Router`` re-bind to the real classes.

    The fixture is session-scoped: a single ``ModelPool`` instance is
    shared across the 4 real-LLM tests in a nightly run.
    """
    if not os.environ.get("OMNI_RUN_REAL_LLM"):
        pytest.skip(
            "OMNI_RUN_REAL_LLM not set; real-LLM pool not instantiated. "
            "Set OMNI_RUN_REAL_LLM=1 to enable."
        )
    if not os.environ.get("MINIMAX_API_KEY"):
        pytest.skip(
            "MINIMAX_API_KEY not set; cannot resolve ${MINIMAX_API_KEY} "
            "in config/local.yaml. See docs/real_llm_runbook.md."
        )
    if not _LOCAL_CONFIG.exists():
        pytest.skip(
            f"config/local.yaml missing at {_LOCAL_CONFIG}. "
            f"Real-LLM suite needs the local config with env-var-bound API keys."
        )

    # 1. Remove the heavy_import_blocker installed by the root conftest.
    for blocker in list(sys.meta_path):
        if type(blocker).__name__ == "_HeavyImportBlocker":
            sys.meta_path.remove(blocker)

    # 2. Drop stubbed litellm modules so re-import returns the real ones.
    for mod_name in list(sys.modules):
        if mod_name == "litellm" or mod_name.startswith("litellm."):
            del sys.modules[mod_name]

    # 3-4. Patch ol_pool.router's namespace and clear its pool cache.
    # ol_pool.router was already imported by the root conftest's
    # sys.path manipulation; its module-level ``from litellm import Router``
    # captured the stub class. We re-import the module so it picks up
    # the freshly-imported real litellm at the top.
    for mod_name in list(sys.modules):
        if mod_name == "ol_pool.router" or mod_name.startswith("ol_pool."):
            del sys.modules[mod_name]

    # Re-import. ``ol_pool.router`` will execute its module body again,
    # including ``from litellm import Router``, but now litellm is real.
    from ol_pool import router as router_mod  # noqa: PLC0415  (re-import in fixture)
    router_mod._pool_cache.clear()

    # 5. Instantiate the real ModelPool from config/local.yaml.
    pool = router_mod.ModelPool.get_instance(str(_LOCAL_CONFIG))

    # Sanity: the pool must NOT be in test_mode (i.e. Router was real).
    if getattr(pool, "_test_mode", True):
        pytest.fail(
            "real_model_pool fixture: ModelPool is in _test_mode=True after "
            "cleanup. The litellm re-import / re-bind did not take effect. "
            "Check sys.modules / sys.meta_path state."
        )
    return pool
