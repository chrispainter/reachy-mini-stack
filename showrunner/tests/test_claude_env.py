"""The key-loading contract: .env is read, the shell still wins, errors are useful."""

import os
from unittest.mock import patch

import pytest

import showrunner.claude as claude_mod


def test_env_file_path_points_at_the_package_root():
    assert claude_mod.ENV_FILE.name == ".env"
    assert claude_mod.ENV_FILE.parent.name == "showrunner"
    # The package root holds pyproject.toml, not the inner source dir.
    assert (claude_mod.ENV_FILE.parent / "pyproject.toml").is_file()


def test_missing_key_raises_a_message_naming_the_env_file():
    with patch.dict(os.environ, {}, clear=True):
        claude_mod._client = None
        with pytest.raises(RuntimeError) as exc:
            claude_mod.get_client()
    assert "ANTHROPIC_API_KEY" in str(exc.value)
    assert ".env" in str(exc.value)


def test_exported_variable_is_honoured():
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-test"}, clear=True):
        claude_mod._client = None
        client = claude_mod.get_client()
    assert client is not None
    claude_mod._client = None


def test_dotenv_does_not_override_an_exported_variable(tmp_path):
    """load_dotenv(override=False) is the default — the shell must win."""
    from dotenv import load_dotenv

    env_file = tmp_path / ".env"
    env_file.write_text("ANTHROPIC_API_KEY=from-file\n")
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "from-shell"}, clear=True):
        load_dotenv(env_file)
        assert os.environ["ANTHROPIC_API_KEY"] == "from-shell"
