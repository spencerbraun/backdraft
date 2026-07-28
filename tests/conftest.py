"""Root conftest: re-export the shared fixture sets for the root-level suites."""

import pytest

# So a failed `assert_golden` shows the diff and not just its message.
pytest.register_assert_rewrite("golden_util")

from conftest_registry import *  # noqa: E402,F401,F403
from conftest_render import *  # noqa: E402,F401,F403
