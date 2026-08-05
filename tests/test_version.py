"""One version, in three places that must agree.

A release bumps `pyproject.toml` and `.claude-plugin/plugin.json`, and the
package reports `backdraft.__version__`. Nothing made them agree, and they did
not: the package said 0.1.0 while the project shipped 0.2.0 through 0.5.0.
`__version__` now derives from the installed distribution's metadata, which is
built from `pyproject.toml`, so these tests are what catch the remaining way to
get it wrong — bumping one file and forgetting the other.
"""

from __future__ import annotations

import json
import pathlib
import tomllib

import backdraft

REPO = pathlib.Path(__file__).parents[1]
PYPROJECT = REPO / "pyproject.toml"
PLUGIN = REPO / ".claude-plugin" / "plugin.json"


def project_version() -> str:
    """The one version this repo declares. `pyproject.toml` is the authority."""
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["version"]


def test_the_package_reports_the_projects_version() -> None:
    """Fails on a stale environment as well as a stale string — both are the bug.

    The fix for either is the same: `uv sync`, which is what CI does before it
    runs this.
    """
    assert backdraft.__version__ == project_version()


def test_the_plugin_manifest_carries_the_same_version() -> None:
    """The two files a release has to bump together."""
    manifest = json.loads(PLUGIN.read_text(encoding="utf-8"))
    assert manifest["version"] == project_version()


def test_the_version_is_not_the_uninstalled_placeholder() -> None:
    """`0+unknown` is honest in a bare checkout and wrong anywhere tests run."""
    assert backdraft.__version__ != "0+unknown"
