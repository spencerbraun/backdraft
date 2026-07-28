"""backdraft.credentials: the only door a credential may come through."""

from __future__ import annotations

import pytest

from backdraft.credentials import env_file, setting

SCOPED = ("BACKDRAFT_VLM_API_KEY", "BACKDRAFT_HOME")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for name in SCOPED + ("OPENAI_API_KEY",):
        monkeypatch.delenv(name, raising=False)


def test_precedence_config_env_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".backdraft").mkdir()
    (tmp_path / ".backdraft" / "env").write_text("BACKDRAFT_VLM_API_KEY=from-file\n")
    assert setting("BACKDRAFT_VLM_API_KEY") == "from-file"
    monkeypatch.setenv("BACKDRAFT_VLM_API_KEY", "from-env")
    assert setting("BACKDRAFT_VLM_API_KEY") == "from-env"
    assert (
        setting("BACKDRAFT_VLM_API_KEY", {"api_key": "from-flag"}, config_key="api_key")
        == "from-flag"
    )


def test_env_file_discovered_walking_up(tmp_path, monkeypatch):
    (tmp_path / ".backdraft").mkdir()
    (tmp_path / ".backdraft" / "env").write_text("BACKDRAFT_VLM_API_KEY=root-key\n")
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)
    assert setting("BACKDRAFT_VLM_API_KEY") == "root-key"


def test_backdraft_home_overrides_discovery(tmp_path, monkeypatch):
    (tmp_path / ".backdraft").mkdir()
    (tmp_path / ".backdraft" / "env").write_text("BACKDRAFT_VLM_API_KEY=home-key\n")
    monkeypatch.setenv("BACKDRAFT_HOME", str(tmp_path))
    assert setting("BACKDRAFT_VLM_API_KEY") == "home-key"
    assert env_file() is not None


def test_parser_comments_quotes_and_foreign_keys(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".backdraft").mkdir()
    (tmp_path / ".backdraft" / "env").write_text(
        "# comment\n\nBACKDRAFT_VLM_API_KEY=\"quoted key\"\nOPENAI_API_KEY=smuggled\nnot a line\n"
    )
    assert setting("BACKDRAFT_VLM_API_KEY") == "quoted key"
    # A non-BACKDRAFT_ name in the file is ignored: the file cannot smuggle
    # ambient-style credentials back in under this module's roof.


def test_unscoped_name_is_a_caller_bug():
    with pytest.raises(ValueError):
        setting("OPENAI_API_KEY")


def test_no_file_no_env_is_none(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert setting("BACKDRAFT_VLM_API_KEY") is None
    assert env_file() is None
