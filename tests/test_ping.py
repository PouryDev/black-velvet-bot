from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock

import pytest
from telegram import Chat, Message, Update, User

from app import texts
from app.config import Settings
from app.handlers.ping import ping


class DummyContext:
    def __init__(self) -> None:
        self.bot_data = {
            "settings": Settings(
                bot_token="token",
                allowed_group_id=-1001,
                webhook_secret="secret",
                telegram_api_base="https://example.com",
                port=8033,
                db_path="/tmp/bot.db",
            )
        }
        self.bot = AsyncMock()


@pytest.mark.asyncio
async def test_ping_sends_welcome_to_env_group() -> None:
    context = DummyContext()
    chat = Chat(id=42, type="private")
    user = User(id=9, is_bot=False, first_name="x")
    message = Message(message_id=1, date=datetime.now(), chat=chat, from_user=user, text="!ping")
    update = Update(update_id=1, message=message)
    await ping(update, context)  # type: ignore[arg-type]
    context.bot.send_message.assert_awaited_once_with(
        chat_id=-1001,
        text=texts.PING_WELCOME,
    )
