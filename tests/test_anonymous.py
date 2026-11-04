from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from telegram import User
from telegram.error import Forbidden, RetryAfter

from app.community import Community
from app.community_store import dumps
from app.config import Settings
from app.db import Database
from app.delivery import Delivery


def data(user_id, position):
    return dict(name=f"Name{user_id}", age=24, gender="male", orientation="bisexual", position=position,
                interest="free text", limits="free text", status="single", photo="photo-id",
                username=f"member_{user_id}", first_name=f"Name{user_id}")


def who(user_id):
    return User(user_id, f"Name{user_id}", False, username=f"member_{user_id}")


@pytest.fixture
async def env(tmp_path):
    db = Database(str(tmp_path / "bot.db"))
    await db.init()
    c = Community(Settings(db_path=str(tmp_path / "bot.db")), db)
    await c.store.init()
    sent_id = [1000]

    async def send(*args, **kwargs):
        sent_id[0] += 1
        return SimpleNamespace(message_id=sent_id[0])

    async def get_chat(user_id):
        return SimpleNamespace(username=f"member_{user_id}")

    bot = SimpleNamespace(get_chat_member=AsyncMock(return_value=SimpleNamespace(status="member")),
                          get_chat=AsyncMock(side_effect=get_chat), send_message=AsyncMock(side_effect=send))
    delivery = Delivery(c, SimpleNamespace(bot=bot))
    delivery.throttle = AsyncMock()
    yield c, bot, delivery
    await db.close()


async def search(c, bot, user_id, position, wanted):
    await c.save_profile(user_id, data(user_id, position))
    await c.store.execute("INSERT INTO private_searches VALUES(?,?,?,?)", (user_id, str(user_id), "male", dumps(wanted)))
    row = await c.store.one("SELECT * FROM private_searches WHERE user_id=?", (user_id,))
    c.event = f"search:{user_id}"
    await c.match_or_enqueue(user_id, row, bot)


async def matched(c, bot):
    await search(c, bot, 101, "top", ["bottom"])
    await search(c, bot, 202, "bottom", ["top"])
    await c.db.raw.commit()
    return await c.store.session(101)


async def drain(delivery):
    for _ in range(30):
        if not await delivery.outbox_once():
            break
    else:
        pytest.fail("outbox did not drain")


@pytest.mark.asyncio
async def test_private_match_and_relay_replies_without_public_identity(env):
    c, bot, delivery = env
    session = await matched(c, bot)
    assert session["next_user"] == 101
    assert not await c.store.all("SELECT * FROM private_queue")
    assert not await c.store.all("SELECT * FROM queue")
    await drain(delivery)
    private = [call.kwargs["text"] for call in bot.send_message.await_args_list if call.kwargs["chat_id"] > 0]
    assert any("@member_101" in text for text in private)
    assert any("@member_202" in text for text in private)
    c.event = "wrong-turn"
    await c.relay(who(202), SimpleNamespace(text="too soon"), session, bot)
    assert not await c.store.one("SELECT * FROM outbox WHERE method='role_turn'")
    c.event = "first-turn"
    await c.relay(who(101), SimpleNamespace(text="First turn"), session, bot)
    await c.db.raw.commit()
    await drain(delivery)
    after_first = await c.store.session(101)
    assert after_first["next_user"] == 202
    assert after_first["sequence"] == 1
    assert not after_first["pending"]
    c.event = "second-turn"
    await c.relay(who(202), SimpleNamespace(text="Second turn"), after_first, bot)
    await c.db.raw.commit()
    await drain(delivery)
    posts = [call.kwargs for call in bot.send_message.await_args_list if call.kwargs["chat_id"] == c.settings.allowed_group_id]
    assert len(posts) == 2
    assert posts[0]["reply_parameters"] is None
    assert posts[1]["reply_parameters"].message_id == after_first["last_message_id"]
    assert all("@member" not in post["text"] and "Name" not in post["text"] for post in posts)
    assert posts[0]["text"].endswith("First turn")
    assert posts[1]["text"].endswith("Second turn")
    assert (await c.store.session(101))["next_user"] == 101
    assert all(r["payload"] == "{}" for r in await c.store.all("SELECT payload FROM outbox WHERE status='done'"))


@pytest.mark.asyncio
async def test_session_survives_database_reopen(env):
    c, bot, delivery = env
    session = await matched(c, bot)
    await drain(delivery)
    c.event = "persisted-turn"
    await c.relay(who(101), SimpleNamespace(text="Persist this pending turn"), session, bot)
    await c.db.raw.commit()
    await c.db.close()
    db = Database(c.settings.db_path)
    await db.init()
    restarted = Community(c.settings, db)
    await restarted.store.init()
    worker = Delivery(restarted, SimpleNamespace(bot=bot))
    worker.throttle = AsyncMock()
    try:
        assert (await restarted.store.session(101))["pending"]
        await drain(worker)
        restored = await restarted.store.session(101)
        assert restored["next_user"] == 202
        assert restored["last_message_id"]
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_end_cancels_unpublished_turn_and_blocks_additional_match(env):
    c, bot, delivery = env
    session = await matched(c, bot)
    c.event = "turn"
    await c.relay(who(101), SimpleNamespace(text="Unpublished"), session, bot)
    await c.end_session(session, "finished")
    await c.db.raw.commit()
    await drain(delivery)
    assert not [call for call in bot.send_message.await_args_list if call.kwargs["chat_id"] < 0]
    assert await c.store.session(101) is None


@pytest.mark.asyncio
async def test_retry_after_preserves_turn_until_actual_delivery(env):
    c, bot, delivery = env
    session = await matched(c, bot)
    await drain(delivery)
    c.event = "retry-turn"
    await c.relay(who(101), SimpleNamespace(text="Retry this"), session, bot)
    await c.db.raw.commit()
    # Acknowledgement comes before the actual role turn.
    bot.send_message.side_effect = RetryAfter(3)
    await delivery.outbox_once()
    assert (await c.store.session(101))["next_user"] == 101
    assert (await c.store.session(101))["pending"]
    row = await c.store.one("SELECT * FROM outbox WHERE method='role_turn'")
    assert row["status"] == "pending"
    assert row["next_attempt"] >= time.time() + 2


@pytest.mark.asyncio
async def test_blocked_private_recipient_ends_session(env):
    c, bot, delivery = env
    await matched(c, bot)
    # The queued message for entering the queue is delivered normally first.
    first = await c.store.one("SELECT id FROM outbox WHERE method='send_message'")
    await c.store.execute("UPDATE outbox SET status='done' WHERE id=?", (first["id"],))
    await c.db.raw.commit()
    bot.send_message.side_effect = Forbidden("bot was blocked")
    await delivery.outbox_once()
    assert await c.store.session(101) is None


@pytest.mark.asyncio
async def test_nonmember_cannot_search_and_incompatible_preferences_stay_queued(env):
    c, bot, _ = env
    bot.get_chat_member.return_value.status = "left"
    c.event = "nonmember"
    await c.start_search(who(101), bot)
    assert not await c.store.all("SELECT * FROM private_searches")
    bot.get_chat_member.return_value.status = "member"
    await search(c, bot, 101, "top", ["bottom"])
    await search(c, bot, 202, "bottom", ["vers"])
    assert await c.store.session(101) is None
    assert len(await c.store.all("SELECT * FROM private_queue")) == 2
