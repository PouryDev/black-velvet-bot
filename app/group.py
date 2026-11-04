from __future__ import annotations

import hashlib

from telegram.ext import ContextTypes

from app.config import Settings
from app.rtl import ensure_rtl


async def send_to_group(
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    **kwargs,
):
    settings: Settings = context.bot_data["settings"]
    community = context.bot_data.get("community")
    if community is not None:
        keyboard = kwargs.get("reply_markup")
        if keyboard is not None:
            kwargs["reply_markup"] = keyboard.to_dict()
        text = ensure_rtl(text)
        digest = hashlib.sha256(text.encode()).hexdigest()[:16]
        await community.store.emit(f"{community.event}:public:{digest}", "send_message",
                                   chat_id=settings.allowed_group_id, text=text, **kwargs)
        return None
    return await context.bot.send_message(
        chat_id=settings.allowed_group_id,
        text=ensure_rtl(text),
        **kwargs,
    )
