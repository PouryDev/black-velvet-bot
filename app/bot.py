from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import Application, TypeHandler

from app.community import Community, route
from app.config import Settings
from app.db import Database
from app.handlers import fuck, ping, register


async def on_error(update: object, context) -> None:
    context.bot_data["community"].failed = True
    logging.getLogger(__name__).error("handler failed: %s", type(context.error).__name__)


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
    application.bot_data["community"] = Community(settings, db)
    application.add_handler(TypeHandler(Update, route), group=-10)
    ping.add_handlers(application)
    register.add_handlers(application)
    fuck.add_handlers(application)
    application.add_error_handler(on_error)
    return application
