from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from telegram import User

from app import onboarding
from app.community import Community
from app.config import Settings
from app.db import Database


def profile(username="member_one", gender="male", position="top"):
    return dict(name="Member", age=24, gender=gender, orientation="bisexual", position=position,
                interest="A one-line answer", limits="Another one-line answer", status="single",
                photo="telegram-photo-file-id", username=username, first_name="Member")


def user(user_id=1, username="member_one"):
    return User(user_id, "Member", False, username=username)


@pytest.fixture
async def env(tmp_path):
    db = Database(str(tmp_path / "bot.db"))
    await db.init()
    c = Community(Settings(bot_token="123:test-token", db_path=str(tmp_path / "bot.db")), db)
    await c.store.init()
    bot = SimpleNamespace(username="TestBot", get_chat_member=AsyncMock(return_value=SimpleNamespace(status="left")),
                          get_chat=AsyncMock(return_value=SimpleNamespace(username="member_one")))
    c.event = "test"
    yield c, bot
    await db.close()


async def fill_form(c, bot, who=None):
    who = who or user()
    await c.begin_form(who, bot)
    data = profile(who.username)
    for index, field in enumerate(onboarding.FIELDS):
        c.event = f"field:{index}"
        form = await c.store.one("SELECT * FROM forms WHERE user_id=?", (who.id,))
        await c.advance_form(who, form, str(data[field]) if field != "photo" else None,
                             data[field] if field == "photo" else None)
    return await c.store.one("SELECT * FROM forms WHERE user_id=?", (who.id,))


def query(c, action="accept", request_id=1, chat_id=None):
    return SimpleNamespace(data=f"admission:{request_id}:{action}", from_user=user(900, "admin_one"),
                           message=SimpleNamespace(chat=SimpleNamespace(id=chat_id or c.settings.admin_group_id), message_id=77),
                           answer=AsyncMock())


async def payloads(c):
    return [json.loads(r["payload"]) for r in await c.store.all("SELECT payload FROM outbox ORDER BY id")]


@pytest.mark.parametrize("field,value", [("age", "17"), ("age", "101"), ("age", "adult"),
                                          ("interest", "two\nlines"), ("limits", "two\rwords"),
                                          ("limits", "a\u2028b"), ("name", "x" * 49)])
def test_invalid_fields(field, value):
    with pytest.raises(ValueError):
        onboarding.validate_value(field, value)


def test_card_and_choices_are_bounded():
    data = profile()
    data.update(name="x" * 48, interest="x" * 160, limits="x" * 160, status="@" + "x" * 32)
    assert onboarding.units(onboarding.card(data) + "\n\n✅ قبول شد") < 1024
    assert onboarding.validate_value("age", "۲۴") == 24
    assert onboarding.validate_value("status", "@partner_one") == "@partner_one"
    for step in range(10):
        keyboard = onboarding.form_keyboard("0123456789", step)
        if keyboard:
            assert all(len(b.callback_data.encode()) <= 64 for row in keyboard.inline_keyboard for b in row)
    assert [b.text for b in onboarding.decision_keyboard(1).inline_keyboard[0]] == ["قبول", "رد"]


@pytest.mark.asyncio
async def test_no_username_cannot_enter_or_submit_funnel(env):
    c, bot = env
    await c.begin_form(user(username=None), bot)
    assert await c.store.one("SELECT 1 FROM forms") is None
    form = await fill_form(c, bot)
    await c.submit_form(user(username=None), form, bot)
    assert await c.store.one("SELECT 1 FROM applications") is None


@pytest.mark.asyncio
async def test_admission_card_and_exactly_one_accept_welcome(env):
    c, bot = env
    form = await fill_form(c, bot)
    await c.submit_form(user(), form, bot)
    requests = await c.store.all("SELECT * FROM applications")
    assert len(requests) == 1
    card_payload = next(p for p in await payloads(c) if p["chat_id"] == c.settings.admin_group_id)
    assert "USERNAME: @member_one" in card_payload["caption"]
    assert card_payload["show_caption_above_media"] is True
    assert card_payload["photo"] == profile()["photo"]
    bot.get_chat_member.return_value = SimpleNamespace(status="administrator")
    q = query(c)
    await c.decide(q, bot)
    await c.decide(q, bot)
    assert (await c.store.one("SELECT status FROM applications"))["status"] == "accepted"
    assert await c.store.profile(1)
    welcomes = [p for p in await payloads(c) if p.get("text") == onboarding.WELCOME]
    assert len(welcomes) == 1
    assert "تا دقایقی دیگر" in welcomes[0]["text"]
    assert not hasattr(bot, "approve_chat_join_request")


@pytest.mark.asyncio
async def test_reject_is_silent_and_nonadmins_cannot_decide(env):
    c, bot = env
    await c.store.execute("INSERT INTO applications(user_id,data,created_at) VALUES(?,?,0)", (1, json.dumps(profile())))
    await c.decide(query(c, "reject"), bot)
    assert (await c.store.one("SELECT status FROM applications"))["status"] == "pending"
    bot.get_chat_member.return_value = SimpleNamespace(status="administrator")
    await c.decide(query(c, "reject", chat_id=-999), bot)
    assert (await c.store.one("SELECT status FROM applications"))["status"] == "pending"
    await c.decide(query(c, "reject"), bot)
    assert (await c.store.one("SELECT status FROM applications"))["status"] == "rejected"
    assert not [p for p in await payloads(c) if p["chat_id"] == 1]


@pytest.mark.asyncio
async def test_username_removed_before_accept_blocks_decision(env):
    c, bot = env
    await c.store.execute("INSERT INTO applications(user_id,data,created_at) VALUES(?,?,0)", (1, json.dumps(profile())))
    bot.get_chat_member.return_value = SimpleNamespace(status="administrator")
    bot.get_chat.return_value = SimpleNamespace(username=None)
    await c.decide(query(c), bot)
    assert (await c.store.one("SELECT status FROM applications"))["status"] == "pending"
    assert not [p for p in await payloads(c) if p["chat_id"] == 1]


@pytest.mark.asyncio
async def test_existing_member_completes_profile_without_admission(env):
    c, bot = env
    bot.get_chat_member.return_value = SimpleNamespace(status="member")
    form = await fill_form(c, bot)
    await c.submit_form(user(), form, bot)
    assert await c.store.profile(1)
    assert await c.db.get_user(1)
    assert await c.store.one("SELECT 1 FROM applications") is None
