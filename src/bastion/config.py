"""Runtime configuration. Values come from environment variables or a local `.env` file."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

Mode = Literal["replay", "record", "live"]

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        populate_by_name=True,
        env_parse_none_str="",
    )

    mode: Mode = Field("replay", validation_alias="BASTION_MODE")
    anthropic_api_key: SecretStr | None = Field(None, validation_alias="ANTHROPIC_API_KEY")
    passcode: SecretStr | None = Field(None, validation_alias="BASTION_PASSCODE")
    db_path: Path = Field(Path("./data/bastion.db"), validation_alias="BASTION_DB_PATH")
    model_fast: str = Field("claude-haiku-5-5", validation_alias="BASTION_MODEL_FAST")
    model_smart: str = Field("claude-sonnet-5-5", validation_alias="BASTION_MODEL_SMART")
    api_url: str = Field("http://localhost:8000", validation_alias="BASTION_API_URL")
    seed_on_start: bool = Field(True, validation_alias="BASTION_SEED_ON_START")
    fixtures_dir: Path = Field(REPO_ROOT / "fixtures" / "llm", validation_alias="BASTION_FIXTURES")
    prices_path: Path = Field(
        REPO_ROOT / "config" / "prices.yaml", validation_alias="BASTION_PRICES_PATH"
    )

    @property
    def has_api_key(self) -> bool:
        return self.anthropic_api_key is not None


@lru_cache
def get_settings() -> Settings:
    return Settings()
