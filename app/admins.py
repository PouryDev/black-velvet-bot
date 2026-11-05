from __future__ import annotations

import time

from telegram.error import BadRequest

from app.commands import parse_command
from app.mentions import mention_user


class BotAdmins:
    """Bot permissions are independent of Telegram administrator privileges."""

    def __init__(self, community):
        self.community = community

    async def allowed(self, user_id: int, bot) -> bool:
        c = self.community
        if user_id == c.settings.owner_user_id and user_id > 0:
            return True
        if not await c.store.one("SELECT 1 FROM bot_admins WHERE user_id=?", (user_id,)):
            return False
        member = await bot.get_chat_member(c.settings.admin_group_id, user_id)
        return member.status in {"member", "administrator", "creator"} or (
            member.status == "restricted" and member.is_member
        )

    async def command(self, message, bot) -> None:
        c = self.community
        command = parse_command(message.text)
        if not command or command[0] not in {"addadmin", "removeadmin", "admins"}:
            return
        if command[1] and command[1].lower() != bot.username.lower():
            return
        actor = message.from_user
        if (message.sender_chat is not None or actor is None or actor.is_bot
                or actor.id != c.settings.owner_user_id or actor.id <= 0):
            await c.say(c.settings.admin_group_id, "فقط ادمین اصلی می‌تواند ادمین‌های ربات را مدیریت کند.")
            return
        name = command[0]
        if name == "admins":
            rows = await c.store.all("SELECT user_id FROM bot_admins ORDER BY user_id")
            ids = [c.settings.owner_user_id] + [r["user_id"] for r in rows if r["user_id"] != c.settings.owner_user_id]
            await c.say(c.settings.admin_group_id, "ادمین‌های ربات (اولین شناسه ادمین اصلی است):\n" + "\n".join(map(str, ids)))
            return
        parts = message.text.split()
        target_id = None
        if len(parts) == 2 and parts[1].isascii() and parts[1].isdigit():
            target_id = int(parts[1])
        elif len(parts) == 1 and message.reply_to_message:
            replied = message.reply_to_message
            if replied.sender_chat is None and replied.from_user and not replied.from_user.is_bot:
                target_id = replied.from_user.id
        if target_id is None or not 0 < target_id < 2**63:
            await c.say(c.settings.admin_group_id,
                        f"روی پیام خود کاربر ریپلای کن و /{name} بزن، یا /{name} USER_ID را با آیدی عددی مثبت بفرست.")
            return
        if target_id == c.settings.owner_user_id:
            await c.say(c.settings.admin_group_id, "دسترسی ادمین اصلی ثابت است و قابل حذف یا تغییر نیست.")
            return
        if name == "removeadmin":
            cursor = await c.store.execute("DELETE FROM bot_admins WHERE user_id=?", (target_id,))
            text = f"دسترسی ادمین ربات برای {target_id} حذف شد." if cursor.rowcount else "این کاربر ادمین ربات نیست."
            await c.say(c.settings.admin_group_id, text)
            return
        try:
            member = await bot.get_chat_member(c.settings.admin_group_id, target_id)
        except BadRequest:
            await c.say(c.settings.admin_group_id, "کاربر پیدا نشد؛ ابتدا او را عضو گروه ادمین‌ها کن.")
            return
        if member.user.is_bot or not (member.status in {"member", "administrator", "creator"} or (
                member.status == "restricted" and member.is_member)):
            await c.say(c.settings.admin_group_id, "فقط حساب شخصیِ عضو گروه ادمین‌ها را می‌توان ادمین ربات کرد.")
            return
        await c.store.execute("INSERT OR IGNORE INTO bot_admins VALUES(?,?,?)", (target_id, actor.id, time.time()))
        await c.say(c.settings.admin_group_id, f"{mention_user(member.user)} به ادمین‌های ربات اضافه شد.", parse_mode="HTML")
