import os
from dataclasses import dataclass

from dotenv import load_dotenv


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Settings:
    api_key: str
    model: str
    base_url: str | None
    temperature: float = 0.2
    max_steps: int = 15
    tpm_limit: int | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        api_key = os.getenv("LLM_API_KEY", "").strip()
        model = os.getenv("LLM_MODEL", "").strip()
        base_url = os.getenv("LLM_BASE_URL", "").strip() or None

        missing = [name for name, value in (("LLM_API_KEY", api_key), ("LLM_MODEL", model)) if not value]
        if missing:
            raise ConfigError(f"missing required environment variables: {', '.join(missing)} (see .env.example)")

        return cls(api_key=api_key, model=model, base_url=base_url, tpm_limit=_parse_tpm_limit())


def _parse_tpm_limit() -> int | None:
    raw_value = os.getenv("LLM_TPM_LIMIT", "").strip()
    if not raw_value:
        return None
    if not raw_value.isdigit() or int(raw_value) == 0:
        raise ConfigError(f"LLM_TPM_LIMIT must be a positive whole number of tokens per minute, got '{raw_value}'")
    return int(raw_value)
