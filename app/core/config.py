# Copyright 2024
# Directory: yt-rag/app/core/config.py

"""
Configuration management for the RAG application.
Handles environment variables and application settings.
"""

from typing import Literal, Optional
from pydantic_settings import BaseSettings
from pydantic import Field

# Used when OPENAI_BASE_URL is unset or empty. Passed explicitly because the
# OpenAI SDK would otherwise fall back to the raw OPENAI_BASE_URL environment
# variable, and an empty value there yields an unusable client.
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    # Supabase Configuration
    supabase_url: str = Field(..., env="SUPABASE_URL")
    supabase_anon_key: str = Field(..., env="SUPABASE_ANON_KEY")
    supabase_service_role_key: str = Field(..., env="SUPABASE_SERVICE_ROLE_KEY")
    
    # AI Provider Configuration
    ai_provider: Literal["openai", "anthropic"] = Field(default="openai", env="AI_PROVIDER")
    
    # OpenAI-compatible Configuration (used for embeddings always, and for chat
    # when AI_PROVIDER=openai). Point OPENAI_BASE_URL at any OpenAI-compatible
    # endpoint (e.g. Google Gemini) and put that provider's key in OPENAI_API_KEY.
    openai_api_key: str = Field(..., env="OPENAI_API_KEY")
    openai_base_url: Optional[str] = Field(default=None, env="OPENAI_BASE_URL")  # empty/unset = api.openai.com
    openai_embed_model: str = Field(default="text-embedding-3-small", env="OPENAI_EMBED_MODEL")
    openai_chat_model: str = Field(default="gpt-4o", env="OPENAI_CHAT_MODEL")
    # Per-request limits for OpenAI-compatible calls. A hung request counts as a
    # failure, so /answer can fall back to retrieved passages instead of waiting
    # for the SDK's 10-minute default.
    openai_timeout_seconds: float = Field(default=30.0, gt=0, env="OPENAI_TIMEOUT_SECONDS")
    openai_max_retries: int = Field(default=1, ge=0, env="OPENAI_MAX_RETRIES")
    
    # Anthropic Configuration
    anthropic_api_key: str = Field(default="", env="ANTHROPIC_API_KEY")
    anthropic_chat_model: str = Field(default="claude-3-5-sonnet-20240620", env="ANTHROPIC_CHAT_MODEL")
    
    # Admin token for POST /seed (sent as "Authorization: Bearer <token>").
    # Unset or empty leaves /seed open, which is meant for local development only.
    seed_token: Optional[str] = Field(default=None, env="SEED_TOKEN")

    # Application Configuration
    environment: str = Field(default="development", env="ENVIRONMENT")
    log_level: str = Field(default="INFO", env="LOG_LEVEL")
    
    # RAG Configuration
    default_top_k: int = Field(default=6)
    chunk_size: int = Field(default=400)  # Approximate tokens
    chunk_overlap: int = Field(default=60)  # 15% overlap
    temperature: float = Field(default=0.1)
    # Every stored/searched embedding has exactly this many values; must match
    # VECTOR(n) in sql/init_supabase.sql. Longer provider vectors are truncated
    # and re-normalized; shorter ones are an error.
    embedding_dimensions: int = Field(default=1536, ge=1)
    # Max texts per embedding request.
    embedding_batch_size: int = Field(default=100, ge=1)
    # Send `dimensions=embedding_dimensions` with each embedding request. Turn off
    # for OpenAI-compatible providers that reject the parameter.
    embedding_send_dimensions: bool = Field(default=True)
    
    class Config:
        """Pydantic configuration."""
        env_file = ".env"
        case_sensitive = False


# Global settings instance
settings = Settings()


def get_settings() -> Settings:
    """Get application settings instance."""
    return settings
