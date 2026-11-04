from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import timedelta

from telegram import ReplyParameters, Update
from telegram.error import BadRequest, Forbidden, RetryAfter

from app.community import Community
from app.community_store import DAY, WEEK

logger = logging.getLogger(__name__)


def _permission_error(error: Exception) -> bool:
    if isinstance(error, Forbidden):
        return True
    if not isinstance(error, BadRequest):
        return False
    description = str(error).lower().replace("_", " ")
    return any(phrase in description for phrase in (
        "not enough rights", "administrator rights", "not an administrator",
        "chat admin required", "not enough permissions", "have no rights",
        "bot is not a member",
    ))


class Delivery:
    """One local worker and SQLite outbox; no Redis or additional process required."""

    def __init__(self, community: Community, application):
        self.community = community
        self.store = community.store
        self.application = application
        self.bot = application.bot
        self.sent_at: dict[int, float] = {}
        self.last_global = 0.0
        self.tasks: list[asyncio.Task] = []
        self.stopping = asyncio.Event()

    def start(self) -> None:
        self.tasks = [asyncio.create_task(self.inbox_loop()), asyncio.create_task(self.outbox_loop()),
                      asyncio.create_task(self.maintenance_loop())]

    async def stop(self) -> None:
        self.stopping.set()
        _, pending = await asyncio.wait(self.tasks, timeout=10) if self.tasks else (set(), set())
        for task in pending:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        async with self.community.lock:
            await self.community.flush_activity()
            await self.community.db.raw.commit()

    async def pause(self, seconds: float) -> None:
        try:
            await asyncio.wait_for(self.stopping.wait(), timeout=seconds)
        except asyncio.TimeoutError:
            pass

    async def inbox_once(self) -> bool:
        async with self.community.lock:
            row = await self.store.one("""SELECT i.* FROM inbox AS i WHERE i.status='pending' AND i.next_attempt<=?
                   AND NOT EXISTS (SELECT 1 FROM inbox AS earlier WHERE earlier.lane=i.lane
                                   AND earlier.status='pending' AND earlier.update_id<i.update_id)
                   ORDER BY i.update_id LIMIT 1""", (time.time(),))
            if not row:
                return False
            self.community.failed = False
            self.community.db.managed_transaction = True
            try:
                await self.application.process_update(Update.de_json(json.loads(row["payload"]), self.bot))
                if self.community.failed:
                    raise RuntimeError("update handler failed")
                await self.store.execute("UPDATE inbox SET status='done',payload='{}' WHERE update_id=?", (row["update_id"],))
                await self.community.db.raw.commit()
            except asyncio.CancelledError:
                await self.community.db.raw.rollback()
                self.community.activity.clear()
                raise
            except Exception:
                await self.community.db.raw.rollback()
                self.community.activity.clear()
                # Do not print raw payloads, profile contents or Telegram request URLs.
                logger.error("update %s failed; retained for retry", row["update_id"])
                await self.store.execute("UPDATE inbox SET attempts=attempts+1,next_attempt=? WHERE update_id=?",
                                         (time.time() + min(300, 2 ** min(row["attempts"] + 1, 8)), row["update_id"]))
                await self.community.db.raw.commit()
            finally:
                self.community.db.managed_transaction = False
            return True

    async def inbox_loop(self) -> None:
        while not self.stopping.is_set():
            try:
                if not await self.inbox_once():
                    await self.pause(0.2)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.error("inbox worker failed; retrying")
                await self.pause(2)

    async def throttle(self, chat_id: int) -> None:
        interval = 3.1 if chat_id < 0 else 1.05
        now = time.monotonic()
        delay = max(self.sent_at.get(chat_id, 0) + interval - now, self.last_global + 0.04 - now, 0)
        if delay:
            await asyncio.sleep(delay)
        self.sent_at[chat_id] = self.last_global = time.monotonic()

    async def perform(self, method: str, payload: dict):
        c = self.community
        if method in {"inactivity_warning", "inactivity_ban"}:
            user_id = payload["user_id"]
            row = await self.store.one("SELECT * FROM members WHERE user_id=?", (user_id,))
            threshold = (payload.get("stage", 3)) * WEEK
            if not row or row["status"] not in {"member", "restricted"} or time.time() - c.last_activity(row) < threshold:
                return None
            if method == "inactivity_warning" and (
                time.time() - c.last_activity(row) >= 3 * WEEK or row["inactivity_stage"] != payload["stage"]
            ):
                return None
            member = await self.bot.get_chat_member(c.settings.allowed_group_id, user_id)
            if member.status not in {"member", "restricted"} or (member.status == "restricted" and not member.is_member):
                await c.sync_member(member.user, member.status if member.status != "restricted" else "left", time.time())
                return None
            if method == "inactivity_ban":
                await self.bot.ban_chat_member(c.settings.allowed_group_id, user_id)
                await c.sync_member(member.user, "kicked", time.time())
                return True
            await self.throttle(c.settings.allowed_group_id)
            # Mention by ID works even for members without public usernames.
            return await self.bot.send_message(c.settings.allowed_group_id,
                f'<a href="tg://user?id={user_id}">عضو گروه</a>، اخطار بی‌فعالیتی {payload["stage"]} از ۲. '
                'در صورت ۲۱ روز سکوت پیاپی از گروه بن می‌شوی.', parse_mode="HTML")
        if method == "role_turn":
            session = await self.store.one("SELECT * FROM role_sessions WHERE id=? AND status='active'", (payload["session_id"],))
            if not session or not session["pending"] or session["sequence"] + 1 != payload["sequence"]:
                return None
            if not await c.member(self.bot, payload["author"]) or not await c.member(self.bot, payload["partner"]):
                await c.end_session(session, "یکی از طرفین دیگر عضو گروه نیست.")
                return None
            await self.throttle(c.settings.allowed_group_id)
            return await self.bot.send_message(
                chat_id=c.settings.allowed_group_id, text=payload["text"],
                reply_parameters=ReplyParameters(message_id=session["last_message_id"], allow_sending_without_reply=True)
                if session["last_message_id"] else None,
            )
        if method == "session_notice":
            if not await self.store.one("SELECT 1 FROM role_sessions WHERE id=? AND status='active'", (payload["session_id"],)):
                return None
            await self.throttle(payload["chat_id"])
            return await self.bot.send_message(**{key: value for key, value in payload.items() if key != "session_id"})
        await self.throttle(payload["chat_id"])
        return await getattr(self.bot, method)(**payload)

    async def outbox_once(self) -> bool:
        # The lock includes sending: it prevents /end or a membership change from advancing
        # a session while its pending turn is being sent. Inbound HTTP requests queue briefly.
        async with self.community.lock:
            row = await self.store.one("SELECT * FROM outbox WHERE status='pending' AND next_attempt<=? ORDER BY id LIMIT 1", (time.time(),))
            if not row:
                return False
            payload = json.loads(row["payload"])
            try:
                result = await self.perform(row["method"], payload)
                if row["method"] == "role_turn" and result is not None:
                    await self.store.execute(
                        "UPDATE role_sessions SET next_user=?,sequence=?,pending=0,last_message_id=?,updated_at=? WHERE id=? AND status='active'",
                        (payload["partner"], payload["sequence"], result.message_id, time.time(), payload["session_id"]),
                    )
                    await self.store.emit(f"turn-delivered:{payload['session_id']}:{payload['sequence']}", "session_notice",
                                          session_id=payload["session_id"], chat_id=payload["partner"],
                                          text=payload["text"] + "\n\nنوبت توست؛ پاسخت را اینجا بنویس.")
                await self.store.execute("UPDATE outbox SET status='done',payload='{}',last_error=NULL WHERE id=?", (row["id"],))
                await self.community.db.raw.commit()
            except asyncio.CancelledError:
                await self.community.db.raw.rollback()
                raise
            except Exception as error:
                await self.community.db.raw.rollback()
                permanent = isinstance(error, (Forbidden, BadRequest))
                delay = min(300, 2 ** min(row["attempts"] + 1, 8))
                if isinstance(error, RetryAfter):
                    retry = error.retry_after
                    delay = (retry.total_seconds() if isinstance(retry, timedelta) else retry) + 1
                await self.store.execute("UPDATE outbox SET status=?,attempts=attempts+1,next_attempt=?,last_error=? WHERE id=?",
                                         ("failed" if permanent else "pending", time.time() + delay, type(error).__name__, row["id"]))
                if row["method"] == "inactivity_ban" and _permission_error(error):
                    settings = self.community.settings
                    # One durable reminder per group/day, even if many members need a ban.
                    await self.store.emit(
                        f"ban-permission:{settings.allowed_group_id}:{int(time.time() // DAY)}",
                        "send_message", chat_id=settings.admin_group_id,
                        text=(
                            "بن خودکار به دلیل نداشتن دسترسی انجام نشد.\n"
                            f"لطفاً ربات را در گروه اصلی ({settings.allowed_group_id}) ادمین کنید "
                            "و مجوز Ban users (بن کردن اعضا) را بدهید."
                        ),
                    )
                if permanent and row["method"] in {"role_turn", "session_notice"}:
                    session = await self.store.one("SELECT * FROM role_sessions WHERE id=? AND status='active'", (payload["session_id"],))
                    if session:
                        await self.community.end_session(session, "ارسال پیام به یکی از مقصدها ممکن نبود؛ بعداً دوباره تلاش کن.")
                await self.community.db.raw.commit()
                logger.warning("outbox %s: %s", row["id"], type(error).__name__)
            return True

    async def outbox_loop(self) -> None:
        while not self.stopping.is_set():
            try:
                if not await self.outbox_once():
                    await self.pause(0.2)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.error("outbox worker failed; retrying")
                await self.pause(2)

    async def maintenance_loop(self) -> None:
        while not self.stopping.is_set():
            async with self.community.lock:
                try:
                    await self.community.maintain(time.time())
                    await self.community.db.raw.commit()
                except asyncio.CancelledError:
                    await self.community.db.raw.rollback()
                    self.community.activity.clear()
                    raise
                except Exception:
                    await self.community.db.raw.rollback()
                    self.community.activity.clear()
                    logger.error("maintenance failed; retrying on next interval")
            await self.pause(60)
