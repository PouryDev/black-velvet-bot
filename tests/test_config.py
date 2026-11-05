from app.config import ADMIN_GROUP_ID, ALLOWED_GROUP_ID, OWNER_USER_ID, PORT, TELEGRAM_API_BASE, WEBHOOK_URL, load_settings


def test_settings_and_hardcoded_admin_group(monkeypatch) -> None:
    monkeypatch.setenv("BOT_TOKEN", "123:test-token")
    monkeypatch.setenv("WEBHOOK_SECRET", "test-secret-123456")
    monkeypatch.setenv("ADMIN_GROUP_ID", "-999")
    monkeypatch.setenv("OWNER_USER_ID", "123")
    settings = load_settings()
    assert settings.allowed_group_id == ALLOWED_GROUP_ID == -1004489388121
    assert settings.admin_group_id == ADMIN_GROUP_ID == -1004357571815
    assert settings.owner_user_id == OWNER_USER_ID == 8971257024
    assert settings.port == PORT == 8033
    assert settings.webhook_url == WEBHOOK_URL == "https://black-velvet.pourydev.ir/webhook"
    assert settings.telegram_api_base == TELEGRAM_API_BASE
    assert settings.db_path == "/app/data/bot.db"
    assert settings.bot_token == "123:test-token"
    assert settings.webhook_secret == "test-secret-123456"


def test_environment_overrides(monkeypatch) -> None:
    monkeypatch.setenv("DB_PATH", "/tmp/custom.db")
    monkeypatch.setenv("TELEGRAM_API_BASE", "https://example.test/")
    settings = load_settings()
    assert settings.db_path == "/tmp/custom.db"
    assert settings.bot_api_url == "https://example.test/bot"
    assert settings.bot_file_api_url == "https://example.test/file/bot"
