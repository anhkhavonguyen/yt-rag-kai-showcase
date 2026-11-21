"""Settings only the evaluation command reads.

DD_APP_KEY (a Datadog application key) is needed to record runs as Datadog
experiments. It belongs in the local .env only: the web app never reads it, and
it must never be added to Render or render.yaml.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class EvalSettings(BaseSettings):
    """DD_APP_KEY, from the environment or .env. Everything else in .env is ignored here."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    dd_app_key: str = ""
