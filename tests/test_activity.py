from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from telegram import Update, User

from app.community import Community
from app.community_store import DAY, WEEK
from app.config import Settings
from app.db import Database
from app.delivery import Delivery

BASE = 1_700_000_000.0


def message(settings, at, user_id=1):
    return Update.de_json({"update_id": 1, "message": {
        "message_id": 1, "date": int(at), "chat": {"id": settings.allowed_group_id, "type": "supergroup"},
        "from": {"id": user_id, "first_name": "Member", "username": "member_one", "is_bot": False},
        "text": "activity",
    }}, None).message


@pytest.fixture
async def env(tmp_path, monkeypatch):
    clock = [BASE]
    monkeypatch.setattr("app.community.time.time", lambda: clock[0])
    db = Database(str(tmp_path / "bot.db"))
    await db.init()
    c = Community(Settings(db_path=str(tmp_path / "bot.db")), db)
    await c.store.init()
    who = User(1, "Member", False, username="member_one")
    bot = SimpleNamespace(get_chat_member=AsyncMock(return_value=SimpleNamespace(status="member", user=who)),
                          ban_chat_member=AsyncMock(return_value=True), send_message=AsyncMock())
    delivery = Delivery(c, SimpleNamespace(bot=bot))
    delivery.throttle = AsyncMock()
    yield c, delivery, bot, clock
    await db.close()


@pytest.mark.asyncio
async def test_activity_writes_at_most_once_daily_and_reloads_conservatively(env):
    c, _, _, clock = env
    await c.observe(message(c.settings, BASE), BASE)
    await c.db.raw.commit()
    changes = c.db.raw.total_changes
    for minute in range(1, 120):
        await c.observe(message(c.settings, BASE + minute * 60), BASE + minute * 60)
    assert c.db.raw.total_changes == changes
    assert c.activity[1].seen == BASE + 119 * 60
    clock[0] = BASE + DAY
    await c.maintain(clock[0])
    assert c.db.raw.total_changes == changes
    await c.observe(message(c.settings, clock[0]), clock[0])
    stored = await c.store.one("SELECT * FROM members WHERE user_id=1")
    assert stored["last_seen"] == clock[0]
    restarted = Community(c.settings, c.db)
    assert restarted.last_activity(stored) == stored["last_seen"] + DAY
    assert await c.store.one("SELECT 1 FROM inbox") is None


@pytest.mark.asyncio
async def test_seven_fourteen_twenty_one_days_and_no_duplicate_warning(env):
    c, delivery, bot, clock = env
    await c.observe(message(c.settings, BASE), BASE)
    for stage in (1, 2):
        clock[0] = BASE + stage * WEEK
        await c.maintain(clock[0])
        await c.maintain(clock[0])
        await c.db.raw.commit()
        row = await c.store.one("SELECT * FROM members WHERE user_id=1")
        assert row["warnings"] == stage
        assert await delivery.outbox_once()
        assert not await delivery.outbox_once()
    assert bot.send_message.await_count == 2
    clock[0] = BASE + 3 * WEEK
    await c.maintain(clock[0])
    await c.db.raw.commit()
    await delivery.outbox_once()
    bot.ban_chat_member.assert_awaited_once_with(c.settings.allowed_group_id, 1)
    assert bot.send_message.await_count == 2
    assert (await c.store.one("SELECT status FROM members"))["status"] == "kicked"


@pytest.mark.asyncio
async def test_recent_message_cancels_queued_ban(env):
    c, delivery, bot, clock = env
    await c.observe(message(c.settings, BASE), BASE)
    clock[0] = BASE + 3 * WEEK
    await c.maintain(clock[0])
    await c.db.raw.commit()
    await c.observe(message(c.settings, clock[0]), clock[0])
    await c.db.raw.commit()
    await delivery.outbox_once()
    bot.ban_chat_member.assert_not_awaited()
    assert (await c.store.one("SELECT inactivity_stage FROM members"))["inactivity_stage"] == 0


@pytest.mark.asyncio
async def test_warning_recovers_one_per_active_week_not_one_message(env):
    c, _, _, clock = env
    await c.observe(message(c.settings, BASE), BASE)
    clock[0] = BASE + 2 * WEEK
    await c.maintain(clock[0])
    clock[0] += 1
    returned = clock[0]
    await c.observe(message(c.settings, clock[0]), clock[0])
    assert (await c.store.one("SELECT warnings FROM members"))["warnings"] == 2
    for week in (1, 2):
        clock[0] = returned + week * 6 * DAY
        await c.observe(message(c.settings, clock[0]), clock[0])
        clock[0] = returned + week * WEEK
        await c.maintain(clock[0])
        assert (await c.store.one("SELECT warnings FROM members"))["warnings"] == 2 - week


@pytest.mark.asyncio
async def test_crash_grace_does_not_ban_early(env):
    c, _, _, clock = env
    await c.observe(message(c.settings, BASE), BASE)
    await c.observe(message(c.settings, BASE + DAY - 1), BASE + DAY - 1)
    c.activity.clear()  # abrupt process loss: DB only knows the upper bound
    clock[0] = BASE + 3 * WEEK
    await c.maintain(clock[0])
    assert await c.store.one("SELECT 1 FROM outbox WHERE method='inactivity_ban'") is None
    clock[0] += DAY
    await c.maintain(clock[0])
    assert await c.store.one("SELECT 1 FROM outbox WHERE method='inactivity_ban'")


@pytest.mark.asyncio
async def test_administrator_never_banned(env):
    c, delivery, bot, clock = env
    await c.observe(message(c.settings, BASE), BASE)
    clock[0] += 3 * WEEK
    await c.maintain(clock[0])
    await c.db.raw.commit()
    bot.get_chat_member.return_value.status = "administrator"
    await delivery.outbox_once()
    bot.ban_chat_member.assert_not_awaited()
    assert (await c.store.one("SELECT status FROM members"))["status"] == "administrator"
