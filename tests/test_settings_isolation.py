"""The test suite must never pick up real credentials or settings (e.g. from a local .env)."""

from app.core.config import Settings, get_settings
from conftest import PLACEHOLDER_SETTINGS


def assert_placeholder_settings(settings: Settings) -> None:
    assert settings.supabase_url == PLACEHOLDER_SETTINGS["SUPABASE_URL"]
    assert settings.supabase_anon_key == PLACEHOLDER_SETTINGS["SUPABASE_ANON_KEY"]
    assert settings.supabase_service_role_key == PLACEHOLDER_SETTINGS["SUPABASE_SERVICE_ROLE_KEY"]
    assert settings.openai_api_key == PLACEHOLDER_SETTINGS["OPENAI_API_KEY"]
    assert settings.anthropic_api_key == PLACEHOLDER_SETTINGS["ANTHROPIC_API_KEY"]
    assert settings.ai_provider == "openai"
    assert not settings.openai_base_url  # empty -> default OpenAI endpoint
    assert settings.openai_chat_model == PLACEHOLDER_SETTINGS["OPENAI_CHAT_MODEL"]
    assert settings.openai_embed_model == PLACEHOLDER_SETTINGS["OPENAI_EMBED_MODEL"]
    assert settings.embedding_dimensions == 1536
    assert settings.embedding_batch_size == 100
    assert settings.embedding_send_dimensions is True
    assert not settings.seed_token
    assert settings.environment == "test"


def test_settings_use_placeholder_values():
    assert_placeholder_settings(get_settings())


def test_placeholders_override_conflicting_env_file(tmp_path):
    """Environment variables (set by conftest) beat any value in a .env file."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join([
            "SUPABASE_URL=https://real-project.supabase.co",
            "SUPABASE_ANON_KEY=real-anon",
            "SUPABASE_SERVICE_ROLE_KEY=real-service-role",
            "OPENAI_API_KEY=AIza-real-gemini-key",
            "OPENAI_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/",
            "OPENAI_CHAT_MODEL=gemini-3.5-flash",
            "OPENAI_EMBED_MODEL=gemini-embedding-2",
            "EMBEDDING_DIMENSIONS=768",
            "EMBEDDING_BATCH_SIZE=1",
            "EMBEDDING_SEND_DIMENSIONS=false",
            "ANTHROPIC_API_KEY=real-anthropic",
            "AI_PROVIDER=anthropic",
            "SEED_TOKEN=real-admin-token",
            "ENVIRONMENT=production",
        ]),
        encoding="utf-8",
    )

    assert_placeholder_settings(Settings(_env_file=env_file))
