from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", case_sensitive=False)

    cdp_url: str = Field(default="http://127.0.0.1:9222", validation_alias="CDP_URL")
    port: int = Field(default=8000, validation_alias="ARENA_GATEWAY_PORT")
    default_model: str = Field(default="gemini-4-argon-high", validation_alias="DEFAULT_MODEL")
    request_timeout: int = Field(default=180, ge=1, validation_alias="REQUEST_TIMEOUT_SEC")
    mock_mode: bool = Field(default=False, validation_alias="MOCK_ARENA")
    fallback_mock: bool = Field(default=False, validation_alias="FALLBACK_MOCK")
