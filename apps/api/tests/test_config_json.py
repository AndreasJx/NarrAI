import json

import pytest

from app.ai import ai_configured
from app.config import Settings, apply_azure_json

AZURE_ENV = (
    "AZURE_OPENAI_ENDPOINT",
    "AZURE_OPENAI_API_KEY",
    "AZURE_OPENAI_CHAT_DEPLOYMENT",
    "AZURE_OPENAI_REASONING",
    "AZURE_OPENAI_REASONING_EFFORT",
)


@pytest.fixture()
def config_file(tmp_path, monkeypatch):
    for name in AZURE_ENV:
        monkeypatch.delenv(name, raising=False)
    path = tmp_path / "azure-openai.json"
    monkeypatch.setenv("AZURE_OPENAI_CONFIG_FILE", str(path))
    return path


def write(path, **values):
    path.write_text(json.dumps(values), encoding="utf-8")


def test_json_fills_the_azure_settings(config_file):
    write(config_file, endpoint="https://chat.dev.woopi.ai", api_key="k", chat_deployment="gpt-5.6-sol", reasoning_effort="medium", reasoning=True)
    settings = apply_azure_json(Settings(_env_file=None))
    assert settings.azure_openai_endpoint == "https://chat.dev.woopi.ai"
    assert settings.azure_openai_chat_deployment == "gpt-5.6-sol"
    assert settings.azure_openai_reasoning_effort == "medium"
    assert settings.azure_openai_config_source == str(config_file)
    assert ai_configured(settings)


def test_explicit_environment_wins_but_empty_values_do_not(config_file, monkeypatch):
    write(config_file, endpoint="https://from-json", api_key="json-key", chat_deployment="gpt-5.6-sol", reasoning=True)
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://from-env")
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "")
    monkeypatch.setenv("AZURE_OPENAI_REASONING", "false")
    settings = apply_azure_json(Settings(_env_file=None))
    assert settings.azure_openai_endpoint == "https://from-env"
    assert settings.azure_openai_api_key == "json-key"
    assert settings.azure_openai_reasoning is False


def test_missing_file_keeps_the_environment(config_file):
    settings = apply_azure_json(Settings(_env_file=None))
    assert settings.azure_openai_endpoint is None and settings.azure_openai_config_source == "env"


def test_invalid_files_fail_loudly(config_file):
    config_file.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError, match="Não foi possível ler"):
        apply_azure_json(Settings(_env_file=None))
    write(config_file, endpoint="https://x", apikey="typo")
    with pytest.raises(ValueError, match="Chaves desconhecidas.*apikey"):
        apply_azure_json(Settings(_env_file=None))


def test_example_file_matches_the_loader():
    from pathlib import Path

    example = json.loads((Path(__file__).resolve().parents[3] / "config" / "azure-openai.example.json").read_text(encoding="utf-8"))
    from app.config import AZURE_JSON_KEYS

    assert set(example) <= set(AZURE_JSON_KEYS)
