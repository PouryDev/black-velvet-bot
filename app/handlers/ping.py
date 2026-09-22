from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes, MessageHandler, filters

from app import texts
from app.group import send_to_group


async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    await send_to_group(context, texts.PING_WELCOME)


def add_handlers(application) -> None:
    application.add_handler(MessageHandler(filters.Regex(r"^!ping\s*$"), ping))
