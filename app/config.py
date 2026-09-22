from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _require(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


@dataclass(frozen=True)
class Settings:
    bot_token: str
    allowed_group_id: int
    webhook_url: str
    webhook_secret: str
    telegram_api_base: str
    port: int
    db_path: str

    @property
    def bot_api_url(self) -> str:
        return f"{self.telegram_api_base.rstrip('/')}/bot"

    @property
    def bot_file_api_url(self) -> str:
        return f"{self.telegram_api_base.rstrip('/')}/file/bot"


def load_settings() -> Settings:
    return Settings(
        bot_token=_require("BOT_TOKEN"),
        allowed_group_id=int(_require("ALLOWED_GROUP_ID")),
        webhook_url=_require("WEBHOOK_URL"),
        webhook_secret=os.getenv("WEBHOOK_SECRET", "").strip(),
        telegram_api_base=os.getenv(
            "TELEGRAM_API_BASE",
            "https://snowy-tree-5c79.pk74ever.workers.dev",
        ).rstrip("/"),
        port=int(os.getenv("PORT", "8033")),
        db_path=os.getenv("DB_PATH", "/app/data/bot.db"),
    )
