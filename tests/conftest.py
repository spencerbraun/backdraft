"""Root conftest: re-export the shared fixture sets for the root-level suites."""

import pytest

# So a failed `assert_golden` shows the diff and not just its message.
pytest.register_assert_rewrite("golden_util")

from conftest_registry import *  # noqa: E402,F401,F403
from conftest_render import *  # noqa: E402,F401,F403


@pytest.fixture(scope="session")
def _empty_config(tmp_path_factory: pytest.TempPathFactory):
    return tmp_path_factory.mktemp("xdg-config")


@pytest.fixture(autouse=True)
def _no_user_theme(_empty_config, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the user-wide theme lookup at an empty directory, everywhere.

    `render` reads `~/.config/backdraft/theme.toml` when no theme is flagged, so
    without this a developer who has one would see their own artifacts under
    test. Autouse and session-shared: it costs one directory for the whole run.
    """
    monkeypatch.setenv("XDG_CONFIG_HOME", str(_empty_config))
