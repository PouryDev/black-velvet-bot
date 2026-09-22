from __future__ import annotations

from telegram import Update
from telegram.ext import ApplicationHandlerStop, ContextTypes

from app.config import Settings


async def leave_foreign_chats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    settings: Settings = context.bot_data["settings"]
    chat = update.effective_chat
    if chat is None:
        raise ApplicationHandlerStop

    if chat.type in {"group", "supergroup", "channel"} and chat.id != settings.allowed_group_id:
        try:
            await context.bot.leave_chat(chat.id)
        except Exception:
            pass
        raise ApplicationHandlerStop

    if chat.id != settings.allowed_group_id:
        raise ApplicationHandlerStop
