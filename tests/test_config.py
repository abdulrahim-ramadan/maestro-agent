import pytest

from maestro import config
from maestro.config import ConfigError, Settings


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "load_dotenv", lambda: None)
    for name in ("LLM_API_KEY", "LLM_MODEL", "LLM_BASE_URL", "LLM_TPM_LIMIT"):
        monkeypatch.delenv(name, raising=False)


def test_all_missing_variables_are_named() -> None:
    with pytest.raises(ConfigError) as error:
        Settings.from_env()

    assert "LLM_API_KEY" in str(error.value)
    assert "LLM_MODEL" in str(error.value)


def test_missing_model_is_named(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "test-key")

    with pytest.raises(ConfigError, match="LLM_MODEL"):
        Settings.from_env()


def test_blank_value_counts_as_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "   ")
    monkeypatch.setenv("LLM_MODEL", "test-model")

    with pytest.raises(ConfigError, match="LLM_API_KEY"):
        Settings.from_env()


def configure_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("LLM_MODEL", "test-model")


def test_tpm_limit_defaults_to_no_pacing(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_required(monkeypatch)
    monkeypatch.setenv("LLM_TPM_LIMIT", "  ")

    assert Settings.from_env().tpm_limit is None


def test_tpm_limit_is_read_as_integer(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_required(monkeypatch)
    monkeypatch.setenv("LLM_TPM_LIMIT", " 8000 ")

    assert Settings.from_env().tpm_limit == 8000


@pytest.mark.parametrize("value", ["eight thousand", "0", "-5", "7.5"])
def test_invalid_tpm_limit_is_a_config_error(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    configure_required(monkeypatch)
    monkeypatch.setenv("LLM_TPM_LIMIT", value)

    with pytest.raises(ConfigError, match="LLM_TPM_LIMIT must be a positive whole number"):
        Settings.from_env()
