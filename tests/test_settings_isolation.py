"""The test suite must never pick up real credentials (e.g. from a local .env)."""

from app.core.config import get_settings
from conftest import PLACEHOLDER_SETTINGS


def test_settings_use_placeholder_credentials():
    settings = get_settings()

    assert settings.supabase_url == PLACEHOLDER_SETTINGS["SUPABASE_URL"]
    assert settings.supabase_anon_key == PLACEHOLDER_SETTINGS["SUPABASE_ANON_KEY"]
    assert settings.supabase_service_role_key == PLACEHOLDER_SETTINGS["SUPABASE_SERVICE_ROLE_KEY"]
    assert settings.openai_api_key == PLACEHOLDER_SETTINGS["OPENAI_API_KEY"]
    assert settings.anthropic_api_key == PLACEHOLDER_SETTINGS["ANTHROPIC_API_KEY"]
    assert settings.ai_provider == "openai"
