from __future__ import annotations

import hmac
import json
import logging
import re
import time
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from telegram import Update

from app.bot import build_application
from app.config import load_settings
from app.db import Database
from app.delivery import Delivery

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
# HTTP URLs include the bot token; never log them.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger("black-velvet")


def ok_response() -> JSONResponse:
    return JSONResponse(content={"ok": True}, status_code=200)


def create_app() -> FastAPI:
    settings = load_settings()
    if not settings.bot_token or not re.fullmatch(r"[A-Za-z0-9_-]{16,256}", settings.webhook_secret):
        raise ValueError("Set BOT_TOKEN and a WEBHOOK_SECRET of 16-256 letters, digits, _ or -")
    if settings.admin_group_id >= 0 or settings.allowed_group_id >= 0 or settings.admin_group_id == settings.allowed_group_id:
        raise ValueError("Set distinct negative ALLOWED_GROUP_ID and ADMIN_GROUP_ID")
    if min(settings.session_timeout_hours, settings.queue_timeout_hours) < 1:
        raise ValueError("Queue and session timeouts must be positive")
    db = Database(settings.db_path)
    application = build_application(settings, db)
    community = application.bot_data["community"]
    delivery = Delivery(community, application)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await db.init()
        await community.store.init()
        await application.initialize()
        await application.start()
        delivery.start()
        logger.info("bot ready; webhook registration is a separate operator command")
        try:
            yield
        finally:
            await delivery.stop()
            await application.stop()
            await application.shutdown()
            await db.close()

    api = FastAPI(title="black-velvet-bot", lifespan=lifespan)
    api.state.community = community
    api.state.delivery = delivery

    @api.get("/health")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    @api.post("/webhook")
    async def telegram_webhook(request: Request) -> JSONResponse:
        provided = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not hmac.compare_digest(provided.encode(), settings.webhook_secret.encode()):
            return JSONResponse({"ok": False}, status_code=403)
        body = await request.body()
        if len(body) > 2_000_000:
            return JSONResponse({"ok": False}, status_code=413)
        try:
            payload = json.loads(body)
            if not isinstance(payload, dict) or type(payload.get("update_id")) is not int:
                raise ValueError("invalid update")
            update = Update.de_json(payload, application.bot)
            if update is None:
                raise ValueError("invalid update")
        except (ValueError, TypeError, KeyError):
            return JSONResponse({"ok": False}, status_code=400)
        async with community.lock:
            try:
                message = update.message
                plain_activity = (message is not None and message.chat.id == settings.allowed_group_id
                                  and not message.new_chat_members and not message.left_chat_member
                                  and not (message.text or "").startswith(("/", "!ping")))
                if plain_activity:
                    # Activity is idempotent by timestamp. Avoid an inbox write per ordinary
                    # group message, and never persist its contents.
                    await community.observe(message, time.time())
                else:
                    await community.store.execute(
                        "INSERT OR IGNORE INTO inbox(update_id,lane,payload,created_at) VALUES(?,?,?,?)",
                        (update.update_id, str(update.chat_member.new_chat_member.user.id if update.chat_member else
                                              update.effective_user.id if update.effective_user else "system"),
                         json.dumps(payload, ensure_ascii=False), time.time()),
                    )
                if db.raw.in_transaction:
                    await db.raw.commit()
            except Exception:
                await db.raw.rollback()
                community.activity.clear()
                logger.error("unable to accept Telegram update")
                return JSONResponse({"ok": False}, status_code=503)
        return ok_response()

    return api


def main() -> None:
    settings = load_settings()
    uvicorn.run("app.main:create_app", host="0.0.0.0", port=settings.port, factory=True)


if __name__ == "__main__":
    main()
