from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Server
    host: str = "127.0.0.1"
    port: int = 8765
    log_level: str = "info"

    # AI providers — all optional; Ollama is the default
    ollama_base_url: str = "http://localhost:11434"
    ollama_default_model: str = "qwen2.5:3b"

    openai_api_key: str = ""
    openai_default_model: str = "gpt-4o-mini"

    anthropic_api_key: str = ""
    anthropic_default_model: str = "claude-3-5-haiku-20241022"

    # Provider priority: first available wins
    # Options: "ollama", "openai", "anthropic"
    ai_provider_priority: list[str] = Field(
        default=["ollama", "openai", "anthropic"]
    )

    # Privacy
    privacy_mode: str = "local"  # local | hybrid | cloud


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
