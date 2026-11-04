from __future__ import annotations

import os
from dataclasses import dataclass

ALLOWED_GROUP_ID = -1004357571815
ADMIN_GROUP_ID = -5534254496
WEBHOOK_URL = "https://black-velvet.pourydev.ir/webhook"
TELEGRAM_API_BASE = "https://api.telegram.org"
PORT = 8033
DB_PATH = "/app/data/bot.db"


@dataclass(frozen=True)
class Settings:
    bot_token: str = ""
    allowed_group_id: int = ALLOWED_GROUP_ID
    webhook_url: str = WEBHOOK_URL
    telegram_api_base: str = TELEGRAM_API_BASE
    port: int = PORT
    db_path: str = DB_PATH
    admin_group_id: int = ADMIN_GROUP_ID
    webhook_secret: str = ""
    session_timeout_hours: int = 48
    queue_timeout_hours: int = 24

    @property
    def bot_api_url(self) -> str:
        return f"{self.telegram_api_base.rstrip('/')}/bot"

    @property
    def bot_file_api_url(self) -> str:
        return f"{self.telegram_api_base.rstrip('/')}/file/bot"


def load_settings() -> Settings:
    return Settings(
        bot_token=os.environ.get("BOT_TOKEN", ""),
        allowed_group_id=int(os.environ.get("ALLOWED_GROUP_ID", ALLOWED_GROUP_ID)),
        webhook_url=os.environ.get("WEBHOOK_URL", WEBHOOK_URL),
        telegram_api_base=os.environ.get("TELEGRAM_API_BASE", TELEGRAM_API_BASE),
        port=int(os.environ.get("PORT", PORT)),
        db_path=os.environ.get("DB_PATH", DB_PATH),
        webhook_secret=os.environ.get("WEBHOOK_SECRET", ""),
        session_timeout_hours=int(os.environ.get("SESSION_TIMEOUT_HOURS", "48")),
        queue_timeout_hours=int(os.environ.get("QUEUE_TIMEOUT_HOURS", "24")),
    )
