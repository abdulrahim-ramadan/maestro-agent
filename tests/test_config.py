import pytest

from maestro import config
from maestro.config import ConfigError, Settings


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "load_dotenv", lambda: None)
    for name in ("LLM_API_KEY", "LLM_MODEL", "LLM_BASE_URL"):
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
