from __future__ import annotations

import json
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app import onboarding
from app.mentions import mention_user


def active(member) -> bool:
    return member.status in {"member", "administrator", "creator"} or (
        member.status == "restricted" and member.is_member
    )


class Admission:
    def __init__(self, community):
        self.community = community

    async def invite(self, application_id: int, key: str) -> None:
        await self.community.store.emit(key, "admission_invite", application_id=application_id, notice_key=key)

    async def queue_join(self, request) -> None:
        c = self.community
        access = await c.store.one("SELECT joined_at FROM admission_access WHERE application_id=?", (request["id"],))
        if access and access["joined_at"] is not None:
            return
        pending = await c.store.one("SELECT requested_at FROM admission_join_requests WHERE user_id=?", (request["user_id"],))
        if pending:
            await c.store.emit(f"admission-join:{request['id']}:{pending['requested_at']}", "admission_join",
                               application_id=request["id"], requested_at=pending["requested_at"])

    async def join_request(self, join) -> None:
        c = self.community
        if join.chat.id != c.settings.allowed_group_id or join.from_user.is_bot:
            return
        request = await c.store.one(
            "SELECT * FROM applications WHERE user_id=? AND status IN ('accepted','pending') ORDER BY id DESC LIMIT 1",
            (join.from_user.id,),
        )
        if not request:
            return
        access = await c.store.one("SELECT joined_at FROM admission_access WHERE application_id=?", (request["id"],))
        if access and access["joined_at"] is not None:
            return
        await c.store.execute(
            """INSERT INTO admission_join_requests VALUES(?,?) ON CONFLICT(user_id)
               DO UPDATE SET requested_at=MAX(requested_at,excluded.requested_at)""",
            (join.from_user.id, join.date.timestamp()),
        )
        if request["status"] == "accepted":
            await self.queue_join(request)

    async def joined(self, user) -> None:
        c = self.community
        request = await c.store.one(
            "SELECT id FROM applications WHERE user_id=? AND status='accepted' ORDER BY id DESC LIMIT 1", (user.id,),
        )
        if not request:
            return
        await c.store.execute("INSERT OR IGNORE INTO admission_access(application_id) VALUES(?)", (request["id"],))
        cursor = await c.store.execute(
            "UPDATE admission_access SET joined_at=? WHERE application_id=? AND joined_at IS NULL", (time.time(), request["id"]),
        )
        await c.store.execute("DELETE FROM admission_join_requests WHERE user_id=?", (user.id,))
        if cursor.rowcount:
            await c.store.emit(f"admission-group-welcome:{request['id']}", "send_message", chat_id=c.settings.allowed_group_id,
                               text=f"{mention_user(user)} به گروه —𝖫𝗎𝗌𝗍 𝖢𝗅𝗎𝖻 . خوش اومدی🖤\n"
                                    "جهت تکمیل فرم، لطفا فرم آخر رو پر کن طبق نمونه\n"
                                    "و برامون بفرست تا ادمینا تو کمترین مدت ثبتت کنن\n"
                                    "امیدوارم که بهت اینجا خوش بگذره.💋", parse_mode="HTML")

    async def deliver_invite(self, bot, application_id: int, notice_key: str) -> None:
        c = self.community
        request = await c.store.one("SELECT * FROM applications WHERE id=? AND status='accepted'", (application_id,))
        if not request:
            return
        await c.store.execute("INSERT OR IGNORE INTO admission_access(application_id) VALUES(?)", (application_id,))
        access = await c.store.one("SELECT * FROM admission_access WHERE application_id=?", (application_id,))
        data = json.loads(request["data"])
        await c.store.emit(f"admission-profile:{application_id}", "send_photo", chat_id=request["user_id"],
                           photo=data["photo"], caption=onboarding.card(data), show_caption_above_media=True)
        if access["joined_at"] is not None:
            return
        link = access["invite_link"]
        if not link:
            invite = await bot.create_chat_invite_link(c.settings.allowed_group_id,
                                                       name=f"Admission #{application_id}", creates_join_request=True)
            link = invite.invite_link
            await c.store.execute("UPDATE admission_access SET invite_link=? WHERE application_id=?", (link, application_id))
        await c.store.emit(f"{notice_key}:message", "send_message", chat_id=request["user_id"],
                           text=onboarding.WELCOME + "\n\n" + link,
                           reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("ورود به گروه", url=link)]]).to_dict())

    async def approve(self, bot, application_id: int, requested_at: float) -> None:
        c = self.community
        request = await c.store.one("SELECT * FROM applications WHERE id=? AND status='accepted'", (application_id,))
        if not request:
            return
        access = await c.store.one("SELECT joined_at FROM admission_access WHERE application_id=?", (application_id,))
        if access and access["joined_at"] is not None:
            return
        pending = await c.store.one("SELECT requested_at FROM admission_join_requests WHERE user_id=?", (request["user_id"],))
        if not pending or pending["requested_at"] != requested_at:
            return
        member = await bot.get_chat_member(c.settings.allowed_group_id, request["user_id"])
        if not active(member):
            await bot.approve_chat_join_request(c.settings.allowed_group_id, request["user_id"])
        await c.sync_member(member.user, member.status if active(member) else "member", time.time())
        await self.joined(member.user)
