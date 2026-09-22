from __future__ import annotations

from dataclasses import dataclass

BOT_TOKEN = "8562157615:AAE9aOQTaDVfRwxpVN_JHK1X72IFOFjNIeE"
ALLOWED_GROUP_ID = -1004489388121
WEBHOOK_URL = "https://black-velvet.pourydev.ir/webhook"
TELEGRAM_API_BASE = "https://snowy-tree-5c79.pk74ever.workers.dev"
PORT = 8033
DB_PATH = "/app/data/bot.db"


@dataclass(frozen=True)
class Settings:
    bot_token: str = BOT_TOKEN
    allowed_group_id: int = ALLOWED_GROUP_ID
    webhook_url: str = WEBHOOK_URL
    telegram_api_base: str = TELEGRAM_API_BASE
    port: int = PORT
    db_path: str = DB_PATH

    @property
    def bot_api_url(self) -> str:
        return f"{self.telegram_api_base.rstrip('/')}/bot"

    @property
    def bot_file_api_url(self) -> str:
        return f"{self.telegram_api_base.rstrip('/')}/file/bot"


def load_settings() -> Settings:
    return Settings()
