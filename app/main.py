from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from telegram import Update

from app.bot import build_application
from app.config import load_settings
from app.db import Database

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("black-velvet")

def ok_response() -> JSONResponse:
    return JSONResponse(content={"ok": True}, status_code=200)


def create_app() -> FastAPI:
    settings = load_settings()
    db = Database(settings.db_path)
    application = build_application(settings, db)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        await db.init()
        await application.initialize()
        await application.start()
        logger.info(
            "bot is up on port %s; set webhook yourself to POST /webhook via %s",
            settings.port,
            settings.telegram_api_base,
        )
        yield
        await application.stop()
        await application.shutdown()
        await db.close()

    api = FastAPI(title="black-velvet-bot", lifespan=lifespan)

    @api.get("/health")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    @api.post("/webhook")
    async def telegram_webhook(request: Request) -> JSONResponse:
        try:
            payload = await request.json()
            update = Update.de_json(payload, application.bot)
            if update is not None:
                await application.process_update(update)
        except Exception:
            logger.exception("webhook processing failed")
        return ok_response()

    return api


def main() -> None:
    settings = load_settings()
    uvicorn.run(
        "app.main:create_app",
        host="0.0.0.0",
        port=settings.port,
        factory=True,
    )


if __name__ == "__main__":
    main()
