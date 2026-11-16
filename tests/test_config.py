from typer.testing import CliRunner

from bastion.cli import app
from bastion.config import Settings, get_settings

BASTION_VARS = ["BASTION_MODE", "ANTHROPIC_API_KEY", "BASTION_PASSCODE", "BASTION_MODEL_FAST"]


def clean_env(monkeypatch):
    for var in BASTION_VARS:
        monkeypatch.delenv(var, raising=False)


def test_defaults_are_replay_and_keyless(monkeypatch):
    clean_env(monkeypatch)
    settings = Settings(_env_file=None)
    assert settings.mode == "replay"
    assert not settings.has_api_key
    assert settings.passcode is None
    assert settings.model_fast == "claude-haiku-5-5"
    assert settings.model_smart == "claude-sonnet-5-5"


def test_env_overrides_and_empty_values_mean_unset(monkeypatch):
    clean_env(monkeypatch)
    monkeypatch.setenv("BASTION_MODE", "live")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("BASTION_PASSCODE", "open-sesame")
    settings = Settings(_env_file=None)
    assert settings.mode == "live"
    assert not settings.has_api_key
    assert settings.passcode.get_secret_value() == "open-sesame"


def test_secrets_do_not_appear_in_repr(monkeypatch):
    clean_env(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-real-key-value")
    assert "not-a-real-key-value" not in repr(Settings(_env_file=None))


def test_preflight_reports_presence_not_value(monkeypatch, tmp_path):
    clean_env(monkeypatch)
    monkeypatch.chdir(tmp_path)  # no .env here
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-real-key-value")
    get_settings.cache_clear()
    result = CliRunner().invoke(app, ["preflight"])
    get_settings.cache_clear()
    assert result.exit_code == 0
    assert "KEY_SET" in result.output
    assert "not-a-real-key-value" not in result.output
