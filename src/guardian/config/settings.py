"""Typed application settings using pydantic-settings."""

from functools import lru_cache
from typing import Literal
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings with environment variable support."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Core Application Settings
    app_name: str = Field(
        default="OpenSource Guardian",
        description="Human-readable name of the service",
    )
    environment: Literal["development", "testing", "staging", "production"] = Field(
        default="development",
        description="Deployment environment name",
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO",
        description="Logging level",
    )

    # Server Host and Port
    host: str = Field(
        default="0.0.0.0",
        description="Bind host for the HTTP server",
    )
    port: int = Field(
        default=8000,
        ge=1,
        le=65535,
        description="Port for the HTTP server",
    )

    # Optional internal secret key (masked via SecretStr to prevent leak in logs/repr)
    api_secret_key: SecretStr | None = Field(
        default=None,
        description="Optional API secret key for internal routes",
    )

    # GitHub Integration Settings
    github_token: SecretStr | None = Field(
        default=None,
        description="Optional GitHub personal access token for authenticated requests",
    )
    github_api_base_url: str = Field(
        default="https://api.github.com",
        description="Base URL for the GitHub REST API",
    )
    default_repo: str = Field(
        default="aadesh-2006/OpenSource-Guardian",
        description="Default GitHub repository context (owner/repo)",
    )

    # Switch Agent Bridge Settings
    switch_api_url: str = Field(
        default="http://localhost:8080",
        description="Base URL for the Switch Agent Bridge",
    )
    switch_agent_id: str | None = Field(
        default=None,
        description="Registered Switch agent ID",
    )
    switch_api_key: SecretStr | None = Field(
        default=None,
        description="Secret API key for Switch authentication",
    )
    switch_rooms: str = Field(
        default="default",
        description="Comma-separated list of Switch room IDs to join",
    )
    switch_connection_id: str | None = Field(
        default=None,
        description="Optional fixed UUID for Switch WebSocket connection",
    )

    def safe_summary(self) -> dict[str, str | int]:
        """Return non-sensitive configuration parameters for logging or diagnostics."""
        return {
            "app_name": self.app_name,
            "environment": self.environment,
            "log_level": self.log_level,
            "host": self.host,
            "port": self.port,
            "github_api_base_url": self.github_api_base_url,
            "switch_api_url": self.switch_api_url,
            "switch_agent_id": self.switch_agent_id or "",
            "switch_rooms": self.switch_rooms,
        }


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
