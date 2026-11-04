from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from telegram import User
from telegram.ext import ExtBot

from app.bot import build_application
from app.community_store import dumps
from app.config import Settings
from app.db import Database
from app.delivery import Delivery


@pytest.fixture
async def runtime(tmp_path):
    db = Database(str(tmp_path / "bot.db"))
    await db.init()
    settings = Settings(bot_token="123:test-token", db_path=str(tmp_path / "bot.db"))
    app = build_application(settings, db)
    object.__setattr__(app.bot, "_bot_user", User(999, "Bot", True, username="TestBot"))
    with (patch.object(ExtBot, "initialize", new_callable=AsyncMock),
          patch.object(ExtBot, "shutdown", new_callable=AsyncMock),
          patch.object(ExtBot, "get_chat_member", new_callable=AsyncMock,
                       return_value=SimpleNamespace(status="left"))):
        await app.initialize()
        c = app.bot_data["community"]
        await c.store.init()
        worker = Delivery(c, app)
        yield c, worker
        await app.shutdown()
    await db.close()


async def queue(c, update_id, text, user_id=101, chat_id=None):
    payload = {"update_id": update_id, "message": {
        "message_id": update_id, "date": 1700000000,
        "chat": {"id": chat_id or user_id, "type": "supergroup" if chat_id else "private"},
        "from": {"id": user_id, "first_name": "Member", "username": f"member_{user_id}", "is_bot": False},
        "text": text,
    }}
    await c.store.execute("INSERT INTO inbox(update_id,lane,payload,created_at) VALUES(?,?,?,0)",
                          (update_id, str(user_id), dumps(payload)))
    await c.db.raw.commit()


@pytest.mark.asyncio
async def test_real_application_routes_private_form_and_scrubs_completed_inbox(runtime):
    c, worker = runtime
    await queue(c, 1, "/register")
    await queue(c, 2, "My name")
    await worker.inbox_once()
    await worker.inbox_once()
    form = await c.store.one("SELECT * FROM forms WHERE user_id=101")
    assert form["step"] == 1
    assert json.loads(form["data"])["name"] == "My name"
    assert all(r["payload"] == "{}" and r["status"] == "done" for r in await c.store.all("SELECT * FROM inbox"))
    assert not c.failed
    assert not [r for r in await c.store.all("SELECT payload FROM outbox") if json.loads(r["payload"])["chat_id"] < 0]


@pytest.mark.asyncio
async def test_retries_preserve_user_order_without_blocking_other_users(runtime):
    c, worker = runtime
    await queue(c, 1, "/register")
    await queue(c, 2, "My name")
    await queue(c, 3, "/start", user_id=202)
    original = c.route
    c.route = AsyncMock(side_effect=RuntimeError("temporary error"))
    await worker.inbox_once()
    assert (await c.store.one("SELECT attempts FROM inbox WHERE update_id=1"))["attempts"] == 1
    c.route = original
    await worker.inbox_once()
    assert (await c.store.one("SELECT status FROM inbox WHERE update_id=3"))["status"] == "done"
    assert (await c.store.one("SELECT status FROM inbox WHERE update_id=2"))["status"] == "pending"
    await c.store.execute("UPDATE inbox SET next_attempt=0 WHERE update_id=1")
    await c.db.raw.commit()
    await worker.inbox_once()
    await worker.inbox_once()
    assert (await c.store.one("SELECT step FROM forms WHERE user_id=101"))["step"] == 1


@pytest.mark.asyncio
async def test_foreign_group_cannot_trigger_public_commands(runtime):
    c, worker = runtime
    await queue(c, 1, "/register", chat_id=-9999)
    await worker.inbox_once()
    assert await c.store.one("SELECT 1 FROM outbox") is None
    assert not c.failed


@pytest.mark.asyncio
async def test_existing_public_register_stays_in_main_group(runtime):
    c, worker = runtime
    await queue(c, 1, "/register", chat_id=c.settings.allowed_group_id)
    await worker.inbox_once()
    assert not c.failed
    outbox = await c.store.all("SELECT payload FROM outbox")
    assert len(outbox) == 1
    assert json.loads(outbox[0]["payload"])["chat_id"] == c.settings.allowed_group_id
