from __future__ import annotations

from datetime import datetime

import pytest
from telegram import Chat, Message, Update, User
from telegram.ext import ApplicationHandlerStop

from app.config import Settings
from app.handlers.guards import leave_foreign_chats


class DummyBot:
    def __init__(self) -> None:
        self.left: list[int] = []

    async def leave_chat(self, chat_id: int) -> bool:
        self.left.append(chat_id)
        return True


class DummyContext:
    def __init__(self, settings: Settings, bot: DummyBot) -> None:
        self.bot_data = {"settings": settings}
        self.bot = bot


def _settings() -> Settings:
    return Settings(
        bot_token="token",
        allowed_group_id=-1001,
        webhook_url="https://example.com/webhook",
        webhook_secret="secret",
        telegram_api_base="https://snowy-tree-5c79.pk74ever.workers.dev",
        port=8033,
        db_path="/tmp/bot.db",
    )


def _update(chat_id: int, chat_type: str = "supergroup") -> Update:
    chat = Chat(id=chat_id, type=chat_type, title="chat")
    user = User(id=9, is_bot=False, first_name="x")
    message = Message(message_id=1, date=datetime.now(), chat=chat, from_user=user, text="hi")
    return Update(update_id=1, message=message)


@pytest.mark.asyncio
async def test_leaves_foreign_group() -> None:
    bot = DummyBot()
    context = DummyContext(_settings(), bot)
    with pytest.raises(ApplicationHandlerStop):
        await leave_foreign_chats(_update(-2002), context)  # type: ignore[arg-type]
    assert bot.left == [-2002]


@pytest.mark.asyncio
async def test_allows_configured_group() -> None:
    bot = DummyBot()
    context = DummyContext(_settings(), bot)
    await leave_foreign_chats(_update(-1001), context)  # type: ignore[arg-type]
    assert bot.left == []


@pytest.mark.asyncio
async def test_ignores_private_chats() -> None:
    bot = DummyBot()
    context = DummyContext(_settings(), bot)
    with pytest.raises(ApplicationHandlerStop):
        await leave_foreign_chats(_update(99, chat_type="private"), context)  # type: ignore[arg-type]
    assert bot.left == []
