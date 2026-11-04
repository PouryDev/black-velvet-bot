from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from telegram import Update, User
from telegram.error import RetryAfter
from telegram.ext import ExtBot

from app import texts
from app.bot import build_application
from app.community_store import CommunityStore, dumps
from app.config import Settings
from app.db import Database
from app.delivery import Delivery
from app.handlers.report import message_link


def timestamp(day=4, hour=12, minute=0, second=0):
    return int(datetime(2026, 11, day, hour, minute, second, tzinfo=timezone.utc).timestamp())


def payload(settings, message_id=100, user_id=101, target_id=42, at=None, chat_id=None,
            chat_type="supergroup", command="/report", username=None, sender_chat=None, target_extra=None):
    chat = {"id": chat_id or settings.allowed_group_id, "type": chat_type}
    if username:
        chat["username"] = username
    message = {
        "message_id": message_id, "date": at or timestamp(), "chat": chat,
        "from": {"id": user_id, "first_name": "Reporter <&>", "is_bot": False}, "text": command,
    }
    if sender_chat:
        message["sender_chat"] = sender_chat
    if target_id is not None:
        message["reply_to_message"] = {
            "message_id": target_id, "date": timestamp(), "chat": chat,
            "from": {"id": 202, "first_name": "Target <&>", "is_bot": False}, "text": "Message contents stay out of the report",
            **(target_extra or {}),
        }
    return {"update_id": message_id, "message": message}


@pytest.fixture
async def env(tmp_path):
    db = Database(str(tmp_path / "bot.db"))
    await db.init()
    app = build_application(Settings(bot_token="123:test-token", db_path=str(tmp_path / "bot.db")), db)
    object.__setattr__(app.bot, "_bot_user", User(999, "Bot", True, username="TestBot"))
    with (patch.object(ExtBot, "initialize", new_callable=AsyncMock),
          patch.object(ExtBot, "shutdown", new_callable=AsyncMock)):
        await app.initialize()
        c = app.bot_data["community"]
        await c.store.init()
        delivery = Delivery(c, app)
        delivery.throttle = AsyncMock()
        yield SimpleNamespace(c=c, worker=delivery)
        await app.shutdown()
    await db.close()


async def process(env, **kwargs):
    value = payload(env.c.settings, **kwargs)
    await env.c.store.execute("INSERT INTO inbox(update_id,lane,payload,created_at) VALUES(?,?,?,0)",
                              (value["update_id"], str(value["message"]["from"]["id"]), dumps(value)))
    await env.c.db.raw.commit()
    assert await env.worker.inbox_once()
    assert not env.c.failed


async def admin_reports(env):
    rows = await env.c.store.all("SELECT payload FROM outbox WHERE dedupe_key LIKE 'report:%' ORDER BY id")
    return [json.loads(row["payload"]) for row in rows]


async def last_reply(env):
    row = await env.c.store.one("SELECT payload FROM outbox WHERE dedupe_key LIKE 'report-reply:%' ORDER BY id DESC LIMIT 1")
    return json.loads(row["payload"])


@pytest.mark.asyncio
async def test_group_reply_reports_to_admins_with_identity_and_private_message_link(env):
    await process(env)
    reports = await admin_reports(env)
    assert len(reports) == 1
    report = reports[0]
    assert report["chat_id"] == env.c.settings.admin_group_id
    assert "گزارش جدید داشتیم از کاربر" in report["text"]
    assert 'tg://user?id=101' in report["text"]
    assert 'tg://user?id=202' in report["text"]
    assert "Reporter &lt;&amp;&gt;" in report["text"]
    assert "Message contents" not in report["text"]
    link = f"https://t.me/c/{str(env.c.settings.allowed_group_id)[4:]}/42"
    assert link in report["text"]
    assert report["reply_markup"]["inline_keyboard"][0][0]["url"] == link
    reply = await last_reply(env)
    assert reply["chat_id"] == env.c.settings.allowed_group_id
    assert reply["text"] == texts.REPORT_RECEIVED
    assert reply["reply_parameters"]["message_id"] == 100
    assert (await env.c.store.one("SELECT payload FROM inbox"))["payload"] == "{}"


@pytest.mark.asyncio
async def test_daily_allowance_is_per_user_and_not_per_target_message(env):
    await process(env)
    await process(env, message_id=101, target_id=43)
    assert len(await admin_reports(env)) == 1
    assert (await last_reply(env))["text"] == texts.REPORT_DAILY_LIMIT
    await process(env, message_id=102, user_id=102, target_id=42)
    assert len(await admin_reports(env)) == 2
    assert len(await env.c.store.all("SELECT * FROM daily_reports")) == 2


@pytest.mark.asyncio
async def test_midnight_in_tehran_resets_allowance_and_keeps_only_latest_day(env):
    # Both reports have the same UTC date; Tehran's calendar day changes between them.
    await process(env, at=timestamp(hour=20, minute=29, second=59))
    assert (await env.c.store.one("SELECT report_day FROM daily_reports"))["report_day"] == "2026-11-04"
    await process(env, message_id=101, at=timestamp(hour=20, minute=30))
    assert len(await admin_reports(env)) == 2
    rows = await env.c.store.all("SELECT * FROM daily_reports")
    assert len(rows) == 1
    assert rows[0]["report_day"] == "2026-11-05"
    # Out-of-order older updates cannot reset or consume the newer day's allowance.
    await process(env, message_id=102, at=timestamp(hour=19))
    assert len(await admin_reports(env)) == 2
    assert (await env.c.store.one("SELECT report_day FROM daily_reports"))["report_day"] == "2026-11-05"


@pytest.mark.asyncio
async def test_missing_reply_does_not_consume_allowance(env):
    await process(env, target_id=None)
    assert (await last_reply(env))["text"] == texts.REPORT_USAGE
    assert not await env.c.store.all("SELECT * FROM daily_reports")
    await process(env, message_id=101)
    assert len(await admin_reports(env)) == 1


@pytest.mark.asyncio
async def test_report_for_other_bot_is_ignored_and_qualified_own_command_works(env):
    await process(env, command="/report@OtherBot")
    assert not await admin_reports(env)
    assert not await env.c.store.all("SELECT * FROM daily_reports")
    await process(env, message_id=101, command="/report@TestBot")
    assert len(await admin_reports(env)) == 1


@pytest.mark.asyncio
async def test_report_in_other_group_is_ignored(env):
    await process(env, chat_id=-1009999999999)
    assert not await admin_reports(env)
    assert not await env.c.store.all("SELECT * FROM daily_reports")
    assert not await env.c.store.all("SELECT * FROM outbox")


@pytest.mark.asyncio
async def test_private_report_shows_usage_without_entering_form(env):
    await env.c.store.execute("INSERT INTO forms VALUES(101,'nonce','profile',0,'{}',0)")
    await process(env, chat_id=101, chat_type="private", target_id=None)
    assert not await admin_reports(env)
    assert not await env.c.store.all("SELECT * FROM daily_reports")
    response = json.loads((await env.c.store.one("SELECT payload FROM outbox"))["payload"])
    assert response["chat_id"] == 101 and response["text"] == texts.REPORT_USAGE
    assert (await env.c.store.one("SELECT step FROM forms WHERE user_id=101"))["step"] == 0


@pytest.mark.asyncio
async def test_unlinkable_target_does_not_consume_allowance(env):
    await process(env, chat_type="group")
    assert not await admin_reports(env)
    assert not await env.c.store.all("SELECT * FROM daily_reports")
    assert (await last_reply(env))["text"] == texts.REPORT_LINK_UNAVAILABLE


@pytest.mark.asyncio
async def test_anonymous_sender_cannot_share_a_daily_identity(env):
    await process(env, sender_chat={"id": env.c.settings.allowed_group_id, "type": "supergroup", "title": "Black Velvet"})
    assert not await admin_reports(env)
    assert not await env.c.store.all("SELECT * FROM daily_reports")
    assert (await last_reply(env))["text"] == texts.REPORT_IDENTIFIED_USER


@pytest.mark.asyncio
async def test_same_command_replayed_does_not_duplicate_report_or_spend_another_allowance(env):
    await process(env)
    duplicate = payload(env.c.settings)
    duplicate["update_id"] = 200
    await env.c.store.execute("INSERT INTO inbox(update_id,lane,payload,created_at) VALUES(200,'101',?,0)", (dumps(duplicate),))
    await env.c.db.raw.commit()
    await env.worker.inbox_once()
    assert len(await admin_reports(env)) == 1
    assert len(await env.c.store.all("SELECT * FROM outbox")) == 2


@pytest.mark.asyncio
async def test_allowance_and_queued_report_survive_database_reopen(env):
    await process(env)
    reopened = Database(env.c.settings.db_path)
    await reopened.init()
    try:
        store = CommunityStore(reopened)
        await store.init()
        assert not await store.claim_report(env.c.settings.allowed_group_id, 101, "2026-11-04", 101, 43)
        assert (await store.one("SELECT target_message_id FROM daily_reports"))["target_message_id"] == 42
        assert len(await store.all("SELECT id FROM outbox WHERE dedupe_key LIKE 'report:%' AND status='pending'")) == 1
        await reopened.raw.rollback()
    finally:
        await reopened.close()


@pytest.mark.asyncio
async def test_admin_delivery_retry_preserves_one_report_and_daily_allowance(env):
    await process(env)
    with patch.object(ExtBot, "send_message", new_callable=AsyncMock, side_effect=RetryAfter(3)):
        await env.worker.outbox_once()
    row = await env.c.store.one("SELECT * FROM outbox WHERE dedupe_key LIKE 'report:%'")
    assert row["status"] == "pending" and row["attempts"] == 1
    await env.c.store.execute("UPDATE outbox SET next_attempt=0 WHERE id=?", (row["id"],))
    await env.c.db.raw.commit()
    with patch.object(ExtBot, "send_message", new_callable=AsyncMock) as sender:
        await env.worker.outbox_once()
        assert sender.await_args.kwargs["chat_id"] == env.c.settings.admin_group_id
    assert len(await env.c.store.all("SELECT * FROM daily_reports")) == 1
    assert (await env.c.store.one("SELECT status FROM outbox WHERE id=?", (row["id"],)))["status"] == "done"


@pytest.mark.parametrize("username,extra,expected", [
    ("BlackVelvetGroup", {}, "https://t.me/BlackVelvetGroup/42"),
    (None, {"is_topic_message": True, "message_thread_id": 7}, "https://t.me/c/4489388121/42?thread=7"),
    (None, {"reply_to_message": {"message_id": 41, "date": timestamp(), "chat": {"id": -1004489388121, "type": "supergroup"}}},
     "https://t.me/c/4489388121/42"),
])
def test_message_link_for_public_private_topics_and_normal_replies(username, extra, expected):
    value = payload(Settings(allowed_group_id=-1004489388121), username=username, target_extra=extra)
    target = Update.de_json(value, None).message.reply_to_message
    assert message_link(target) == expected


@pytest.mark.asyncio
async def test_failure_between_quota_claim_and_admin_queue_rolls_back_both(env):
    value = payload(env.c.settings)
    await env.c.store.execute("INSERT INTO inbox(update_id,lane,payload,created_at) VALUES(100,'101',?,0)", (dumps(value),))
    await env.c.db.raw.commit()
    original = env.c.store.emit

    async def fail_admin_queue(key, method, **kwargs):
        if key.startswith("report:"):
            raise RuntimeError("temporary queue failure")
        await original(key, method, **kwargs)

    env.c.store.emit = fail_admin_queue
    await env.worker.inbox_once()
    assert not await env.c.store.all("SELECT * FROM daily_reports")
    assert not await admin_reports(env)
    assert (await env.c.store.one("SELECT status FROM inbox WHERE update_id=100"))["status"] == "pending"

    env.c.store.emit = original
    await env.c.store.execute("UPDATE inbox SET next_attempt=0 WHERE update_id=100")
    await env.c.db.raw.commit()
    await env.worker.inbox_once()
    assert not env.c.failed
    assert len(await env.c.store.all("SELECT * FROM daily_reports")) == 1
    assert len(await admin_reports(env)) == 1
