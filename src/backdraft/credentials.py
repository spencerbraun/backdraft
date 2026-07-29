"""Backdraft-scoped settings: the only way a credential reaches this tool.

The rule, decided after a real incident: **backdraft never reads a credential it
did not explicitly ask you to write.** Ambient provider variables — an
`OPENAI_API_KEY` exported for some other tool, an `ANTHROPIC_API_KEY` in a
dotfile — are never consulted. Presence of a generic key in the environment is
not consent to spend it or to send documents to its provider.

A setting is looked up in three places, most explicit first:

1. the `--config key=value` dict a command was invoked with;
2. a `BACKDRAFT_<NAME>` environment variable — still env, but exporting a
   backdraft-prefixed variable is unambiguous intent *for this tool*;
3. a `.backdraft/env` file — plain `KEY=VALUE` lines, written deliberately,
   living inside the state directory that is already gitignored.

Names in use: `BACKDRAFT_VLM_API_KEY`, `BACKDRAFT_VLM_MODEL`,
`BACKDRAFT_VLM_BASE_URL`, `BACKDRAFT_ENTAIL_API_KEY`, `BACKDRAFT_ENTAIL_MODEL`,
`BACKDRAFT_SNAPSHOT_QUALITY`, `BACKDRAFT_SNAPSHOT_MAX_HEIGHT`.
The same names are used verbatim in the env file.

Stdlib only, no imports from the package: this module sits beside the kernel so
that `extract` and `bind` can both use it without a sideways import.
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = ["setting", "env_file", "ENV_FILE_NAME"]

ENV_FILE_NAME = "env"
_STATE_DIR = ".backdraft"
_PREFIX = "BACKDRAFT_"


def setting(
    name: str,
    config: dict | None = None,
    *,
    config_key: str | None = None,
    start: Path | None = None,
) -> str | None:
    """The value of the backdraft-scoped setting `name`, or None.

    `name` is the full variable name (`BACKDRAFT_VLM_API_KEY`). `config_key`
    names the `--config` dict key that overrides it (`api_key`); omitted means
    the setting has no per-invocation form. Precedence: config → environment →
    `.backdraft/env` discovered from `start` (default: cwd, honoring
    `BACKDRAFT_HOME`).
    """
    if not name.startswith(_PREFIX):  # pragma: no cover - caller bug, fail loud
        raise ValueError(f"not a backdraft-scoped name: {name!r}")
    if config_key is not None and config and config.get(config_key):
        return str(config[config_key])
    if value := os.environ.get(name):
        return value
    return _read_env_file(start).get(name)


def env_file(start: Path | None = None) -> Path | None:
    """The `.backdraft/env` file that governs `start` (default cwd), if any.

    `BACKDRAFT_HOME` overrides discovery, accepting either the project root or
    the `.backdraft` directory itself — the same rule the CLI uses for the
    registry.
    """
    override = os.environ.get("BACKDRAFT_HOME")
    if override:
        home = Path(override).expanduser()
        root = home.parent if home.name == _STATE_DIR else home
        candidate = root / _STATE_DIR / ENV_FILE_NAME
        return candidate if candidate.is_file() else None
    current = (start or Path.cwd()).resolve()
    for parent in (current, *current.parents):
        candidate = parent / _STATE_DIR / ENV_FILE_NAME
        if candidate.is_file():
            return candidate
    return None


def _read_env_file(start: Path | None) -> dict[str, str]:
    """Parse the governing env file: `KEY=VALUE` lines, `#` comments, optional
    single or double quotes around the value. Unreadable or absent → empty."""
    path = env_file(start)
    if path is None:
        return {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    values: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator:
            continue
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key.startswith(_PREFIX):
            values[key] = value
    return values
