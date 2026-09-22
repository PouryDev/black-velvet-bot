from __future__ import annotations

from telegram.ext import Application, TypeHandler

from app.config import Settings
from app.db import Database
from app.handlers import fuck, register
from app.handlers.guards import leave_foreign_chats


async def on_error(update: object, context) -> None:
    context.application.logger.exception("handler failed", exc_info=context.error)


def build_application(settings: Settings, db: Database) -> Application:
    application = (
        Application.builder()
        .token(settings.bot_token)
        .base_url(settings.bot_api_url)
        .base_file_url(settings.bot_file_api_url)
        .updater(None)
        .build()
    )
    application.bot_data["settings"] = settings
    application.bot_data["db"] = db
    application.add_handler(TypeHandler(object, leave_foreign_chats), group=-1)
    application.add_handler(register.build_handler())
    application.add_handler(fuck.build_handler())
    application.add_error_handler(on_error)
    return application
