from unittest.mock import AsyncMock, Mock

import pytest

from app.config import Settings
from app.manage import register_webhook


@pytest.mark.asyncio
async def test_webhook_registers_without_checking_group_admin_permissions(monkeypatch):
    settings = Settings(bot_token="123:test-token", webhook_secret="test-secret-123456", admin_group_id=0)
    monkeypatch.setattr("app.manage.load_settings", lambda: settings)
    bot = AsyncMock()
    bot.__aenter__.return_value = bot
    bot.get_chat_member.side_effect = AssertionError("Webhook setup must not check group permissions")
    monkeypatch.setattr("app.manage.Bot", Mock(return_value=bot))

    await register_webhook()

    bot.get_chat_member.assert_not_awaited()
    bot.set_webhook.assert_awaited_once_with(
        settings.webhook_url, secret_token=settings.webhook_secret,
        allowed_updates=["message", "callback_query", "chat_member", "my_chat_member"],
        max_connections=4, drop_pending_updates=False,
    )
