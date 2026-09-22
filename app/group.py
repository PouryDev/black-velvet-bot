from __future__ import annotations

from telegram.ext import ContextTypes

from app.config import Settings
from app.rtl import ensure_rtl


async def send_to_group(
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    **kwargs,
):
    settings: Settings = context.bot_data["settings"]
    return await context.bot.send_message(
        chat_id=settings.allowed_group_id,
        text=ensure_rtl(text),
        **kwargs,
    )
