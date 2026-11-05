from __future__ import annotations

import argparse
import asyncio
import logging
import sqlite3
from pathlib import Path

from telegram import Bot

from app.config import load_settings


async def register_webhook() -> None:
    settings = load_settings()
    if not settings.bot_token or not settings.webhook_secret:
        raise SystemExit("Set BOT_TOKEN and WEBHOOK_SECRET first")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    async with Bot(settings.bot_token, base_url=settings.bot_api_url, base_file_url=settings.bot_file_api_url) as bot:
        await bot.set_webhook(settings.webhook_url, secret_token=settings.webhook_secret,
                              allowed_updates=["message", "callback_query", "chat_member", "my_chat_member", "chat_join_request"],
                              max_connections=4, drop_pending_updates=False)
    print("Webhook registered with secret header and membership updates. No pending updates dropped.")


def main() -> None:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("webhook")
    backup = commands.add_parser("backup")
    backup.add_argument("destination")
    commands.add_parser("status")
    commands.add_parser("retry-failed")
    args = parser.parse_args()
    if args.command == "webhook":
        try:
            asyncio.run(register_webhook())
        except Exception as error:
            raise SystemExit(f"Telegram setup failed ({type(error).__name__}); check token, webhook URL and connection") from None
        return
    path = Path(load_settings().db_path).resolve()
    with sqlite3.connect(f"{path.as_uri()}?mode=rw", uri=True) as source:
        if args.command == "backup":
            target = Path(args.destination).resolve()
            if target == path or target.exists():
                raise SystemExit("Choose a new backup file path")
            target.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(target) as destination:
                source.backup(destination)
            target.chmod(0o600)
            print("Consistent SQLite backup created")
        elif args.command == "status":
            for table in ("inbox", "outbox"):
                print(table, source.execute(f"SELECT status,COUNT(*) FROM {table} GROUP BY status").fetchall())
            print("delivery failures", source.execute("SELECT id,method,last_error FROM outbox WHERE status='failed'").fetchall())
        else:
            count = source.execute("UPDATE outbox SET status='pending',next_attempt=0 WHERE status='failed'").rowcount
            source.commit()
            print(f"Queued {count} failed deliveries for retry. Ended role sessions will stay ended.")


if __name__ == "__main__":
    main()
