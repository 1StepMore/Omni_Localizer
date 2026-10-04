"""Shared config-path resolution for the OL CLI surface.

Single source of truth for the documented 4-level precedence:

    1. explicit ``--config <path>`` argument
    2. ``config/local.yaml`` in the current working directory (OPTIONAL)
    3. the ``OL_CONFIG_PATH`` environment variable
    4. ``config/default.yaml``

Level 2 exists because ``ol init`` writes ``config/local.yaml``. A file the
tool generates must be honoured by every other command, otherwise ``ol init``
is decorative and the error hint ``run 'ol init' to generate a valid
config/local.yaml`` is a dead end. Level 2 never errors when absent — it
falls through to level 3, then 4.

Both level 2 and level 4 are RELATIVE paths, resolved by the OS against the
process working directory. Running the CLI from outside the OL project root
therefore finds neither and ``load_config`` raises
``Config file not found: config/default.yaml``; pass ``--config <abs path>``
or export ``OL_CONFIG_PATH=<abs path>`` in that case. This module
deliberately does not search parent directories or the installed package
root — a machine-local lookup table would make "which config am I running?"
unanswerable.

This module imports nothing from OL: no ``schema`` (pydantic), no ``loader``,
no ``router`` (litellm). ``cli._shared.precheck_api_keys`` runs on the
fail-fast path and must stay free of those heavy imports.
"""
from __future__ import annotations

import os
from pathlib import Path

#: Environment variable consulted at precedence level 3.
CONFIG_PATH_ENV_VAR = "OL_CONFIG_PATH"

#: Repo-relative path of the config `ol init` generates (level 2).
LOCAL_CONFIG_RELPATH = "config/local.yaml"

#: Repo-relative fallback config (level 4).
DEFAULT_CONFIG_RELPATH = "config/default.yaml"


def resolve_config_path(config_path: str | Path | None = None) -> Path:
    """Resolve the OL YAML config for a CLI invocation.

    Applies, in order: ``config_path`` → ``config/local.yaml`` (when it is a
    file) → ``$OL_CONFIG_PATH`` → ``config/default.yaml``.

    Args:
        config_path: The explicit ``--config`` value, or ``None`` when the
            user did not pass the flag.

    Returns:
        The first match as a ``Path``. An explicit ``config_path`` is
        returned verbatim (never existence-checked) so a typo in an explicit
        flag still surfaces as the caller's own "file not found" error.
        ``Path`` is not guaranteed to exist — callers that load the config
        get the canonical ``FileNotFoundError`` from
        ``ol_config.loader.load_config``.
    """
    if config_path:
        return Path(config_path)

    local = Path(LOCAL_CONFIG_RELPATH)
    if local.is_file():
        return local

    env_path = os.environ.get(CONFIG_PATH_ENV_VAR)
    if env_path:
        return Path(env_path)

    return Path(DEFAULT_CONFIG_RELPATH)
