from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from telegram import User
from telegram.error import Forbidden, RetryAfter
from telegram.ext import ExtBot

from app import onboarding
from app.bot import build_application
from app.community_store import dumps
from app.config import Settings
from app.db import Database
from app.delivery import Delivery

NOW = int(datetime(2026, 11, 5, tzinfo=timezone.utc).timestamp())
PROFILE = dict(name="Member", age=24, gender="male", orientation="straight", position="top",
               interest="One line", limits="One line", status="single", photo="photo-id",
               username="member_one", first_name="Member")


def who(user_id=101, bot=False):
    return {"id": user_id, "first_name": "Member <&>", "username": f"member_{user_id}", "is_bot": bot}


@pytest.fixture
async def env(tmp_path):
    path = str(tmp_path / "bot.db")
    db = Database(path)
    await db.init()
    app = build_application(Settings(bot_token="123:test-token", owner_user_id=900, db_path=path), db)
    object.__setattr__(app.bot, "_bot_user", User(999, "Bot", True, username="TestBot"))
    with (patch.object(ExtBot, "initialize", new_callable=AsyncMock),
          patch.object(ExtBot, "shutdown", new_callable=AsyncMock),
          patch.object(ExtBot, "answer_callback_query", new_callable=AsyncMock),
          patch.object(ExtBot, "get_chat_member", new_callable=AsyncMock,
                       side_effect=lambda chat_id, user_id: SimpleNamespace(status="member", user=User.de_json(who(user_id), None))),
          patch.object(ExtBot, "get_chat", new_callable=AsyncMock, return_value=SimpleNamespace(username="member_one")),
          patch.object(ExtBot, "create_chat_invite_link", new_callable=AsyncMock,
                       return_value=SimpleNamespace(invite_link="https://t.me/+request-link")),
          patch.object(ExtBot, "approve_chat_join_request", new_callable=AsyncMock, return_value=True),
          patch.object(ExtBot, "send_message", new_callable=AsyncMock),
          patch.object(ExtBot, "send_photo", new_callable=AsyncMock),
          patch.object(ExtBot, "edit_message_caption", new_callable=AsyncMock)):
        await app.initialize()
        c = app.bot_data["community"]
        await c.store.init()
        worker = Delivery(c, app)
        worker.throttle = AsyncMock()
        yield SimpleNamespace(c=c, worker=worker, bot=app.bot, path=path)
        await app.shutdown()
    await db.close()


async def process(env, update_id, **body):
    value = {"update_id": update_id, **body}
    await env.c.store.execute("INSERT INTO inbox(update_id,lane,payload,created_at) VALUES(?,?,?,0)",
                              (update_id, str(update_id), dumps(value)))
    await env.c.db.raw.commit()
    assert await env.worker.inbox_once()
    assert not env.c.failed
    assert (await env.c.store.one("SELECT status FROM inbox WHERE update_id=?", (update_id,)))["status"] == "done"


async def command(env, update_id, text, actor=900, chat_id=None, extra=None):
    await process(env, update_id, message={
        "message_id": update_id, "date": NOW, "from": who(actor), "text": text,
        "chat": {"id": chat_id or env.c.settings.admin_group_id, "type": "supergroup"}, **(extra or {}),
    })


async def application(env, status="pending", user_id=101):
    cursor = await env.c.store.execute("INSERT INTO applications(user_id,data,status,created_at) VALUES(?,?,?,0)",
                                       (user_id, dumps(PROFILE), status))
    await env.c.db.raw.commit()
    return cursor.lastrowid


async def decision(env, update_id, request_id=1, actor=900, action="accept", chat_id=None):
    await process(env, update_id, callback_query={
        "id": str(update_id), "chat_instance": "test", "data": f"admission:{request_id}:{action}", "from": who(actor),
        "message": {"message_id": 77, "date": NOW, "chat": {"id": chat_id or env.c.settings.admin_group_id, "type": "supergroup"}},
    })


async def join(env, update_id, user_id=101, chat_id=None):
    await process(env, update_id, chat_join_request={
        "chat": {"id": chat_id or env.c.settings.allowed_group_id, "type": "supergroup"},
        "from": who(user_id), "user_chat_id": user_id, "date": NOW + update_id,
    })


async def flush(env):
    for _ in range(40):
        if not await env.worker.outbox_once():
            return
    raise AssertionError("outbox did not drain")


@pytest.mark.asyncio
async def test_owner_manages_bot_admins_by_id_and_reply_and_permissions_persist(env):
    await command(env, 1, "/addadmin 901", actor=902)
    assert not await env.c.store.all("SELECT * FROM bot_admins")
    await command(env, 2, "/addadmin@TestBot 901")
    await command(env, 3, "/addadmin", extra={"reply_to_message": {
        "message_id": 10, "date": NOW, "from": who(902),
        "chat": {"id": env.c.settings.admin_group_id, "type": "supergroup"},
    }})
    await command(env, 4, "/addadmin 903", actor=901)
    await command(env, 5, "/removeadmin 902", actor=901)
    assert [r["user_id"] for r in await env.c.store.all("SELECT user_id FROM bot_admins ORDER BY user_id")] == [901, 902]
    await command(env, 6, "/admins")
    await command(env, 7, "/removeadmin 901")
    assert [r["user_id"] for r in await env.c.store.all("SELECT user_id FROM bot_admins")] == [902]
    reopened = Database(env.path)
    await reopened.init()
    try:
        assert await reopened.raw.execute_fetchall("SELECT user_id FROM bot_admins")
    finally:
        await reopened.close()


@pytest.mark.asyncio
async def test_owner_cannot_be_removed_and_anonymous_wrong_chat_or_bot_suffix_cannot_grant(env):
    await command(env, 1, "/removeadmin 900")
    await command(env, 2, "/addadmin 901", extra={"sender_chat": {"id": env.c.settings.admin_group_id, "type": "supergroup"}})
    await command(env, 3, "/addadmin 901", chat_id=-999)
    await command(env, 4, "/addadmin@OtherBot 901")
    await command(env, 5, "/addadmin @unresolved_username")
    assert not await env.c.store.all("SELECT * FROM bot_admins")
    assert await env.c.admins.allowed(900, env.bot)


@pytest.mark.asyncio
@pytest.mark.parametrize("status,is_bot", [("left", False), ("kicked", False), ("member", True)])
async def test_addadmin_requires_human_member_of_admin_group(env, status, is_bot):
    env.bot.get_chat_member.side_effect = None
    env.bot.get_chat_member.return_value = SimpleNamespace(status=status, user=User.de_json(who(901, is_bot), None))
    await command(env, 1, "/addadmin 901")
    assert not await env.c.store.all("SELECT * FROM bot_admins")


@pytest.mark.asyncio
async def test_telegram_admin_without_bot_grant_cannot_decide_and_revocation_takes_effect(env):
    await application(env)
    env.bot.get_chat_member.side_effect = lambda chat_id, user_id: SimpleNamespace(status="administrator", user=User.de_json(who(user_id), None))
    await decision(env, 1, actor=901)
    assert (await env.c.store.one("SELECT status FROM applications"))["status"] == "pending"
    await command(env, 2, "/addadmin 901")
    await command(env, 3, "/removeadmin 901")
    await decision(env, 4, actor=901)
    assert (await env.c.store.one("SELECT status FROM applications"))["status"] == "pending"
    await command(env, 5, "/addadmin 901")
    await decision(env, 6, actor=901)
    assert (await env.c.store.one("SELECT status FROM applications"))["status"] == "accepted"


@pytest.mark.asyncio
async def test_accept_sends_one_private_profile_and_invite_and_duplicate_callback_is_safe(env):
    await application(env)
    await decision(env, 1)
    await decision(env, 2)
    await flush(env)
    env.bot.create_chat_invite_link.assert_awaited_once_with(env.c.settings.allowed_group_id, name="Admission #1", creates_join_request=True)
    profile = env.bot.send_photo.await_args.kwargs
    assert profile["chat_id"] == 101 and profile["show_caption_above_media"] is True
    assert profile["caption"] == onboarding.card(PROFILE)
    assert "reply_markup" not in profile
    welcomes = [call.kwargs for call in env.bot.send_message.await_args_list if call.kwargs.get("chat_id") == 101]
    assert len(welcomes) == 1 and "https://t.me/+request-link" in welcomes[0]["text"]
    assert welcomes[0]["reply_markup"]["inline_keyboard"][0][0]["url"] == "https://t.me/+request-link"
    assert "فوروارد" in welcomes[0]["text"]
    env.bot.approve_chat_join_request.assert_not_awaited()


@pytest.mark.asyncio
async def test_only_accepted_applicant_is_autoapproved_and_mentions_once_after_join(env):
    await application(env)
    await decision(env, 1)
    env.bot.get_chat_member.side_effect = lambda chat_id, user_id: SimpleNamespace(status="left", user=User.de_json(who(user_id), None))
    await join(env, 2, user_id=202)
    await join(env, 3, chat_id=-999)
    await join(env, 4)
    await flush(env)
    env.bot.approve_chat_join_request.assert_awaited_once_with(env.c.settings.allowed_group_id, 101)
    notices = [call.kwargs for call in env.bot.send_message.await_args_list if call.kwargs.get("chat_id") == env.c.settings.allowed_group_id]
    assert len(notices) == 1 and "tg://user?id=101" in notices[0]["text"]
    assert "Member &lt;&amp;&gt;" in notices[0]["text"] and "فوروارد" in notices[0]["text"]
    assert notices[0]["parse_mode"] == "HTML"
    await process(env, 5, message={"message_id": 5, "date": NOW, "from": who(900),
                                  "chat": {"id": env.c.settings.allowed_group_id, "type": "supergroup"}, "new_chat_members": [who()]})
    await join(env, 6)
    await flush(env)
    assert env.bot.approve_chat_join_request.await_count == 1
    assert len(await env.c.store.all("SELECT id FROM outbox WHERE dedupe_key LIKE 'admission-group-welcome:%'")) == 1
    assert not await env.c.store.all("SELECT * FROM admission_join_requests")


@pytest.mark.asyncio
async def test_manual_join_member_event_and_service_message_only_announce_once(env):
    await application(env, status="accepted")
    await process(env, 1, chat_member={
        "chat": {"id": env.c.settings.allowed_group_id, "type": "supergroup"}, "from": who(900), "date": NOW,
        "old_chat_member": {"status": "left", "user": who()},
        "new_chat_member": {"status": "member", "user": who()},
    })
    await process(env, 2, message={"message_id": 2, "date": NOW, "from": who(900),
                                  "chat": {"id": env.c.settings.allowed_group_id, "type": "supergroup"}, "new_chat_members": [who()]})
    await flush(env)
    assert env.bot.send_message.await_count == 1
    assert "فوروارد" in env.bot.send_message.await_args.kwargs["text"]
    env.bot.approve_chat_join_request.assert_not_awaited()


@pytest.mark.asyncio
async def test_bot_admin_who_left_admin_group_cannot_review_forms(env):
    await application(env)
    await command(env, 1, "/addadmin 901")
    env.bot.get_chat_member.side_effect = lambda chat_id, user_id: SimpleNamespace(status="left", user=User.de_json(who(user_id), None))
    await decision(env, 2, actor=901)
    assert (await env.c.store.one("SELECT status FROM applications"))["status"] == "pending"


@pytest.mark.asyncio
async def test_rejected_applicant_join_is_ignored(env):
    await application(env, status="rejected")
    await join(env, 1)
    await flush(env)
    env.bot.approve_chat_join_request.assert_not_awaited()
    env.bot.send_message.assert_not_awaited()
    assert not await env.c.store.all("SELECT * FROM admission_join_requests")


@pytest.mark.asyncio
async def test_pending_request_before_decision_waits_and_reject_remains_silent(env):
    await application(env)
    await join(env, 1)
    await flush(env)
    env.bot.approve_chat_join_request.assert_not_awaited()
    await decision(env, 2, action="reject")
    await flush(env)
    env.bot.send_message.assert_not_awaited()
    env.bot.send_photo.assert_not_awaited()
    assert not await env.c.store.all("SELECT * FROM admission_join_requests")


@pytest.mark.asyncio
async def test_pending_join_before_accept_is_approved_and_member_retry_skips_duplicate_api(env):
    await application(env)
    await join(env, 1)
    await decision(env, 2)
    # Simulate Telegram having already approved it before a lost response/retry.
    await flush(env)
    env.bot.approve_chat_join_request.assert_not_awaited()
    assert (await env.c.store.one("SELECT joined_at FROM admission_access"))["joined_at"] is not None


@pytest.mark.asyncio
async def test_start_for_previously_accepted_user_reuses_link_without_new_application(env):
    await application(env, status="accepted")
    env.bot.get_chat_member.side_effect = lambda chat_id, user_id: SimpleNamespace(status="left", user=User.de_json(who(user_id), None))
    for update_id in (1, 2):
        await process(env, update_id, message={"message_id": update_id, "date": NOW, "from": who(),
                                              "chat": {"id": 101, "type": "private"}, "text": "/start"})
        await flush(env)
    env.bot.create_chat_invite_link.assert_awaited_once()
    env.bot.send_photo.assert_awaited_once()
    assert len(await env.c.store.all("SELECT * FROM applications")) == 1


@pytest.mark.asyncio
async def test_invite_permission_failure_alerts_admins_and_retry_works(env):
    await application(env)
    await decision(env, 1)
    env.bot.create_chat_invite_link.side_effect = Forbidden("not enough rights")
    await flush(env)
    row = await env.c.store.one("SELECT * FROM outbox WHERE method='admission_invite'")
    assert row["status"] == "failed"
    assert any("Invite users" in call.kwargs.get("text", "") for call in env.bot.send_message.await_args_list)
    assert (await env.c.store.one("SELECT status FROM applications"))["status"] == "accepted"
    env.bot.create_chat_invite_link.side_effect = None
    await env.c.store.execute("UPDATE outbox SET status='pending',next_attempt=0 WHERE id=?", (row["id"],))
    await env.c.db.raw.commit()
    await flush(env)
    assert (await env.c.store.one("SELECT status FROM outbox WHERE id=?", (row["id"],)))["status"] == "done"
    env.bot.send_photo.assert_awaited_once()


@pytest.mark.asyncio
async def test_rate_limited_join_is_retried_without_rejecting_applicant(env):
    await application(env, status="accepted")
    env.bot.get_chat_member.side_effect = lambda chat_id, user_id: SimpleNamespace(status="left", user=User.de_json(who(user_id), None))
    env.bot.approve_chat_join_request.side_effect = RetryAfter(1)
    await join(env, 1)
    await env.worker.outbox_once()
    row = await env.c.store.one("SELECT * FROM outbox WHERE method='admission_join'")
    assert row["status"] == "pending" and row["attempts"] == 1
    assert not await env.c.store.one("SELECT joined_at FROM admission_access")
    env.bot.approve_chat_join_request.side_effect = None
    await env.c.store.execute("UPDATE outbox SET next_attempt=0 WHERE id=?", (row["id"],))
    await env.c.db.raw.commit()
    await flush(env)
    assert (await env.c.store.one("SELECT joined_at FROM admission_access"))["joined_at"] is not None
