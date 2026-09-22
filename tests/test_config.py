from app.config import ALLOWED_GROUP_ID, PORT, TELEGRAM_API_BASE, WEBHOOK_URL, load_settings


def test_hardcoded_settings() -> None:
    settings = load_settings()
    assert settings.allowed_group_id == ALLOWED_GROUP_ID == -1004489388121
    assert settings.port == PORT == 8033
    assert settings.webhook_url == WEBHOOK_URL == "https://black-velvet.pourydev.ir/webhook"
    assert settings.telegram_api_base == TELEGRAM_API_BASE
    assert settings.db_path == "/app/data/bot.db"
    assert settings.bot_token
