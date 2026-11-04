from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationHandlerStop, ContextTypes
from telegram.error import TelegramError

from app import onboarding, texts
from app.commands import parse_command
from app.community_store import DAY, WEEK, CommunityStore, dumps
from app.config import Settings
from app.db import Database
from app.positions import CODE_TO_POSITION, POSITION_CODES, POSITION_ORDER

ACTIVE = {"member", "administrator", "creator", "restricted"}


@dataclass
class Activity:
    seen: float
    persisted: float


class Community:
    def __init__(self, settings: Settings, db: Database):
        self.settings = settings
        self.db = db
        self.store = CommunityStore(db)
        self.lock = asyncio.Lock()
        self.activity: dict[int, Activity] = {}
        self.event = ""
        self.failed = False

    async def say(self, user_id: int, text: str, suffix: str = "reply", **kwargs) -> None:
        await self.store.emit(f"{self.event}:{suffix}:{user_id}", "send_message", chat_id=user_id, text=text, **kwargs)

    async def member(self, bot, user_id: int) -> bool:
        member = await bot.get_chat_member(self.settings.allowed_group_id, user_id)
        return member.status in ACTIVE and (member.status != "restricted" or member.is_member)

    async def sync_member(self, user, status: str, now: float) -> None:
        previous = await self.store.one("SELECT status FROM members WHERE user_id=?", (user.id,))
        await self.store.execute(
            """INSERT INTO members(user_id,username,first_name,status,tracked_since)
               VALUES(?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET
               username=excluded.username,first_name=excluded.first_name,status=excluded.status""",
            (user.id, user.username, user.first_name, status, now),
        )
        if previous and previous["status"] not in ACTIVE and status in ACTIVE:
            await self.store.execute(
                "UPDATE members SET tracked_since=?,last_seen=NULL,safe_seen=NULL,inactivity_stage=0,recovery_since=NULL WHERE user_id=?",
                (now, user.id),
            )
        if status not in ACTIVE:
            self.activity.pop(user.id, None)
            await self.store.execute("DELETE FROM private_queue WHERE user_id=?", (user.id,))
            await self.db.raw.execute("DELETE FROM queue WHERE user_id=?", (user.id,))
            session = await self.store.session(user.id)
            if session:
                await self.end_session(session, "نشست به دلیل خروج یکی از اعضا از گروه پایان یافت.")

    async def observe(self, message, now: float) -> None:
        user = message.from_user
        if user is None or user.is_bot or message.sender_chat is not None:
            return
        # Service messages are membership changes, not activity.
        if not (message.text or message.photo or message.video or message.sticker or message.animation
                or message.voice or message.audio or message.document or message.video_note
                or message.poll or message.contact or message.location or message.dice):
            return
        seen = min(message.date.timestamp(), now)
        cached = self.activity.get(user.id)
        if cached and now - cached.persisted < DAY and seen - cached.seen < WEEK:
            cached.seen = max(cached.seen, seen)
            return
        row = await self.store.one("SELECT * FROM members WHERE user_id=?", (user.id,))
        await self.sync_member(user, row["status"] if row and row["status"] in ACTIVE else "member", now)
        old_seen = cached.seen if cached else row["last_seen"] if row else None
        seen = max(seen, cached.seen if cached else old_seen or seen)
        recovery = row["recovery_since"] if row else None
        if recovery is None or old_seen is None or seen - old_seen >= WEEK:
            recovery = seen
        # This upper bound prevents a crash losing cached activity from causing an early ban.
        await self.store.execute(
            "UPDATE members SET last_seen=?,safe_seen=?,inactivity_stage=0,recovery_since=? WHERE user_id=?",
            (seen, now + DAY, recovery, user.id),
        )
        self.activity[user.id] = Activity(seen, now)

    async def flush_activity(self) -> None:
        for user_id, activity in list(self.activity.items()):
            await self.store.execute(
                "UPDATE members SET last_seen=?,safe_seen=? WHERE user_id=?",
                (activity.seen, activity.seen, user_id),
            )

    async def start(self, update: Update, bot) -> None:
        user = update.effective_user
        welcome = onboarding.START_WELCOME
        try:
            is_member = await self.member(bot, user.id)
        except TelegramError:
            await self.say(user.id, welcome + "\n\nفعلاً امکان بررسی عضویتت وجود ندارد؛ کمی بعد دوباره /start را بزن.")
            return
        if is_member:
            await self.sync_member(user, "member", time.time())
            await self.say(user.id, welcome + "\n\n" + onboarding.START_MEMBER_GUIDE)
            return
        request = await self.store.one(
            "SELECT status FROM applications WHERE user_id=? AND status IN ('pending','accepted') ORDER BY id DESC LIMIT 1",
            (user.id,),
        )
        if request:
            text = "درخواستت در انتظار بررسی ادمین‌هاست." if request["status"] == "pending" else "درخواستت قبول شده؛ منتظر اضافه‌شدن توسط ادمین‌ها بمان."
        else:
            text = onboarding.START_JOIN
        await self.say(user.id, welcome + "\n\n" + text, reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("درخواست عضویت", callback_data="join:begin")],
        ]).to_dict())

    async def begin_form(self, user, bot) -> None:
        if not user.username:
            await self.say(user.id, onboarding.NEED_USERNAME)
            return
        existing = await self.store.one("SELECT * FROM forms WHERE user_id=?", (user.id,))
        if existing:
            await self.prompt(existing)
            return
        is_member = await self.member(bot, user.id)
        if is_member and await self.store.session(user.id):
            await self.say(user.id, "ابتدا با /end نشست فعلی را تمام کن؛ سپس پروفایلت را ویرایش کن.")
            return
        if not is_member:
            prior = await self.store.one(
                "SELECT status FROM applications WHERE user_id=? AND status IN ('pending','accepted') LIMIT 1", (user.id,),
            )
            if prior:
                await self.say(user.id, "درخواستت قبلاً ثبت شده؛ منتظر بررسی یا اضافه‌شدن به گروه بمان.")
                return
            if not self.settings.admin_group_id:
                await self.say(user.id, "ثبت‌نام هنوز توسط مدیر راه‌اندازی نشده است.")
                return
        await self.store.execute("DELETE FROM private_queue WHERE user_id=?", (user.id,))
        await self.store.execute("DELETE FROM private_searches WHERE user_id=?", (user.id,))
        await self.store.execute(
            "INSERT INTO forms(user_id,nonce,purpose,step,data,updated_at) VALUES(?,?,?,?,?,?)",
            (user.id, uuid.uuid4().hex[:10], "profile" if is_member else "admission", 0,
             dumps({"username": user.username, "first_name": user.first_name}), time.time()),
        )
        await self.prompt(await self.store.one("SELECT * FROM forms WHERE user_id=?", (user.id,)))

    async def prompt(self, form) -> None:
        step = form["step"]
        keyboard = onboarding.form_keyboard(form["nonce"], step)
        if step == len(onboarding.FIELDS):
            data = json.loads(form["data"])
            await self.store.emit(
                f"{self.event}:preview:{form['user_id']}", "send_photo", chat_id=form["user_id"],
                photo=data["photo"], caption=onboarding.card(data), show_caption_above_media=True,
                reply_markup=keyboard.to_dict(),
            )
        else:
            await self.say(form["user_id"], onboarding.PROMPTS[step] + "\n/discard لغو فرم",
                           reply_markup=keyboard.to_dict() if keyboard else None)

    async def advance_form(self, user, form, value: str | None = None, photo: str | None = None) -> None:
        if not user.username:
            await self.say(user.id, onboarding.NEED_USERNAME)
            return
        step = form["step"]
        if step >= len(onboarding.FIELDS):
            await self.say(user.id, "با دکمه تأیید و ارسال یا اصلاح فرم ادامه بده.")
            return
        data = json.loads(form["data"])
        data["username"] = user.username
        field = onboarding.FIELDS[step]
        try:
            if field == "photo":
                if not photo:
                    raise ValueError(onboarding.PROMPTS[step])
                data[field] = photo
                onboarding.card(data)
            else:
                if value is None:
                    raise ValueError("این مرحله فقط متن یا انتخاب گزینه می‌پذیرد.")
                data[field] = onboarding.validate_value(field, value)
        except ValueError as error:
            await self.say(user.id, str(error))
            return
        await self.store.execute("UPDATE forms SET data=?,step=?,updated_at=? WHERE user_id=?",
                                 (dumps(data), step + 1, time.time(), user.id))
        await self.prompt(await self.store.one("SELECT * FROM forms WHERE user_id=?", (user.id,)))

    async def save_profile(self, user_id: int, data: dict) -> None:
        await self.store.execute(
            "INSERT INTO member_profiles VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET data=excluded.data,updated_at=excluded.updated_at",
            (user_id, dumps(data), time.time()),
        )
        # Keep the existing public registration/matcher compatible without a second profile model.
        await self.store.execute(
            """INSERT INTO users(user_id,username,first_name,gender,position,positions,registered_at)
               VALUES(?,?,?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET username=excluded.username,
               first_name=excluded.first_name,gender=excluded.gender,position=excluded.position,positions=excluded.positions""",
            (user_id, data["username"], data.get("first_name"), data["gender"], data["position"],
             dumps([data["position"]]), str(time.time())),
        )

    async def submit_form(self, user, form, bot) -> None:
        if not user.username:
            await self.say(user.id, onboarding.NEED_USERNAME)
            return
        data = json.loads(form["data"])
        data["username"] = user.username
        data["first_name"] = user.first_name
        caption = onboarding.card(data)
        is_member = await self.member(bot, user.id)
        if is_member:
            await self.save_profile(user.id, data)
            await self.sync_member(user, "member", time.time())
            await self.say(user.id, "پروفایلت ذخیره شد. برای جست‌وجوی ناشناس /fuck را بزن.")
        else:
            if not self.settings.admin_group_id:
                await self.say(user.id, "ثبت‌نام هنوز توسط مدیر راه‌اندازی نشده است.")
                return
            prior = await self.store.one("SELECT id FROM applications WHERE user_id=? AND status IN ('pending','accepted')", (user.id,))
            if prior:
                await self.say(user.id, "درخواستت قبلاً ثبت شده است.")
                return
            cursor = await self.store.execute(
                "INSERT INTO applications(user_id,data,created_at) VALUES(?,?,?)", (user.id, dumps(data), time.time()),
            )
            request_id = cursor.lastrowid
            await self.store.emit(f"application:{request_id}", "send_photo", chat_id=self.settings.admin_group_id,
                                  photo=data["photo"], caption=caption, show_caption_above_media=True,
                                  reply_markup=onboarding.decision_keyboard(request_id).to_dict())
            await self.say(user.id, "درخواستت ارسال شد؛ منتظر تأیید ادمین‌ها بمان.")
        await self.store.execute("DELETE FROM forms WHERE user_id=?", (user.id,))

    async def answer(self, query, text: str, **kwargs) -> None:
        try:
            await query.answer(text, **kwargs)
        except TelegramError:
            pass

    async def decide(self, query, bot) -> None:
        if query.message is None or query.message.chat.id != self.settings.admin_group_id:
            return
        admin = await bot.get_chat_member(self.settings.admin_group_id, query.from_user.id)
        if admin.status not in {"creator", "administrator"}:
            await self.answer(query, "فقط ادمین‌های گروه اجازه بررسی دارند.", show_alert=True)
            return
        try:
            _, request_id, action = query.data.split(":")
            request_id = int(request_id)
        except (ValueError, TypeError):
            return
        if action not in {"accept", "reject"}:
            return
        request = await self.store.one("SELECT * FROM applications WHERE id=?", (request_id,))
        if not request or request["status"] != "pending":
            await self.answer(query, "این درخواست قبلاً بررسی شده است.", show_alert=True)
            return
        data = json.loads(request["data"])
        if action == "accept":
            applicant = await bot.get_chat(request["user_id"])
            if not applicant.username:
                await self.answer(query, "کاربر دیگر username ندارد؛ ابتدا باید username تنظیم کند.", show_alert=True)
                return
            data["username"] = applicant.username
            await self.save_profile(request["user_id"], data)
            await self.store.emit(f"welcome:{request_id}", "send_message", chat_id=request["user_id"], text=onboarding.WELCOME)
        await self.store.execute("UPDATE applications SET status=?,decided_by=?,decided_at=?,data=? WHERE id=? AND status='pending'",
                                 ("accepted" if action == "accept" else "rejected", query.from_user.id, time.time(), dumps(data), request_id))
        await self.store.emit(f"decision:{request_id}", "edit_message_caption", chat_id=query.message.chat.id,
                              message_id=query.message.message_id,
                              caption=onboarding.card(data) + ("\n\n✅ قبول شد" if action == "accept" else "\n\n❌ رد شد"),
                              show_caption_above_media=True, reply_markup={"inline_keyboard": []})
        await self.answer(query, "قبول شد" if action == "accept" else "رد شد")

    async def start_search(self, user, bot) -> None:
        if not await self.member(bot, user.id):
            await self.say(user.id, "جست‌وجوی ناشناس فقط برای اعضای گروه فعال است.")
            return
        if not await self.store.profile(user.id):
            await self.say(user.id, "ابتدا با /register پروفایل کاملت را ثبت کن.")
            return
        if await self.store.session(user.id):
            await self.say(user.id, "یک نشست فعال داری؛ برای پایان /end را بزن.")
            return
        if await self.store.one("SELECT 1 FROM private_queue WHERE user_id=?", (user.id,)):
            await self.say(user.id, "از قبل در صف هستی. برای خروج /cancel را بزن.")
            return
        nonce = uuid.uuid4().hex[:10]
        await self.store.execute(
            "INSERT OR REPLACE INTO private_searches(user_id,nonce,gender,positions) VALUES(?,?,NULL,'[]')", (user.id, nonce),
        )
        await self.search_prompt(user.id)

    async def search_prompt(self, user_id: int) -> None:
        search = await self.store.one("SELECT * FROM private_searches WHERE user_id=?", (user_id,))
        nonce = search["nonce"]
        if search["gender"] is None:
            buttons = [[InlineKeyboardButton(label, callback_data=f"seek:{nonce}:g:{gender}")]
                       for gender, label in (("male", "مرد"), ("female", "زن"), ("trans", "ترنس"))]
            text = "دنبال چه جنسیتی هستی؟"
        else:
            selected = json.loads(search["positions"])
            buttons = [[InlineKeyboardButton(position.replace("_", " ") + (" ✅" if position in selected else ""),
                                            callback_data=f"seek:{nonce}:p:{POSITION_CODES[position]}")]
                       for position in POSITION_ORDER]
            buttons.append([InlineKeyboardButton("ورود به صف", callback_data=f"seek:{nonce}:ok:-")])
            text = "پوزیشن‌های مورد نظر را انتخاب کن (۱ تا ۳ گزینه). تطبیق بر اساس انتخاب هر دو طرف است."
        await self.say(user_id, text + "\n/cancel لغو", reply_markup=InlineKeyboardMarkup(buttons).to_dict())

    async def search_callback(self, query, bot) -> None:
        try:
            _, nonce, action, value = query.data.split(":")
        except ValueError:
            return
        user_id = query.from_user.id
        search = await self.store.one("SELECT * FROM private_searches WHERE user_id=? AND nonce=?", (user_id, nonce))
        if not search or not await self.member(bot, user_id):
            await self.say(user_id, "این انتخاب منقضی شده یا دیگر عضو گروه نیستی؛ /fuck را بزن.")
            return
        if action == "g" and search["gender"] is None and value in {"male", "female", "trans"}:
            await self.store.execute("UPDATE private_searches SET gender=? WHERE user_id=?", (value, user_id))
        elif action == "p" and search["gender"]:
            selected = json.loads(search["positions"])
            position = CODE_TO_POSITION.get(value)
            if not position:
                return
            if position in selected:
                selected.remove(position)
            elif len(selected) < 3:
                selected.append(position)
            else:
                await self.say(user_id, "حداکثر ۳ گزینه انتخاب کن.")
                return
            await self.store.execute("UPDATE private_searches SET positions=? WHERE user_id=?", (dumps(selected), user_id))
        elif action == "ok" and search["gender"] and json.loads(search["positions"]):
            await self.match_or_enqueue(user_id, search, bot)
            return
        else:
            return
        await self.search_prompt(user_id)

    async def match_or_enqueue(self, user_id: int, search, bot) -> None:
        profile = await self.store.profile(user_id)
        if not profile or profile["age"] < 18 or await self.store.session(user_id):
            return
        wanted = set(json.loads(search["positions"]))
        candidates = await self.store.all("SELECT * FROM private_queue WHERE user_id!=? ORDER BY queued_at,user_id", (user_id,))
        for candidate in candidates:
            partner_id = candidate["user_id"]
            other = await self.store.profile(partner_id)
            if (not other or candidate["queued_at"] < time.time() - self.settings.queue_timeout_hours * 3600
                    or await self.store.session(partner_id)):
                await self.store.execute("DELETE FROM private_queue WHERE user_id=?", (partner_id,))
                continue
            if not (other["gender"] == search["gender"] and candidate["wanted_gender"] == profile["gender"]
                    and other["position"] in wanted and profile["position"] in json.loads(candidate["wanted_positions"])):
                continue
            if not await self.member(bot, partner_id):
                await self.store.execute("DELETE FROM private_queue WHERE user_id=?", (partner_id,))
                continue
            await self.store.execute("DELETE FROM private_queue WHERE user_id IN (?,?)", (user_id, partner_id))
            await self.store.execute("DELETE FROM private_searches WHERE user_id IN (?,?)", (user_id, partner_id))
            cursor = await self.store.execute(
                "INSERT INTO role_sessions(user_a,user_b,next_user,updated_at) VALUES(?,?,?,?)",
                (partner_id, user_id, partner_id, time.time()),
            )
            session_id = cursor.lastrowid
            # Identity is sent only in these two private messages. Group posts never reuse these labels.
            for me, them, their_profile in ((user_id, partner_id, other), (partner_id, user_id, profile)):
                chat = await bot.get_chat(them)
                identity = f"@{chat.username}" if chat.username else their_profile["name"]
                first = "نوبت توست؛ متن را همین‌جا بفرست." if me == partner_id else "طرف مقابل اول شروع می‌کند؛ منتظر بمان."
                await self.store.emit(f"matched:{session_id}:{me}", "session_notice", session_id=session_id, chat_id=me,
                                      text=f"نشست #{session_id}: با {identity} مچ شدی.\n{first}\n/end پایان نشست",
                                      reply_markup=InlineKeyboardMarkup([[
                                          InlineKeyboardButton("مشاهده پروفایل طرف مقابل", url=f"tg://user?id={them}"),
                                      ]]).to_dict())
            return
        await self.store.execute(
            "INSERT OR REPLACE INTO private_queue VALUES(?,?,?,?)",
            (user_id, search["gender"], search["positions"], time.time()),
        )
        await self.store.execute("DELETE FROM private_searches WHERE user_id=?", (user_id,))
        await self.say(user_id, "وارد صف ناشناس شدی؛ هویتت در گروه اعلام نمی‌شود.\n/cancel خروج از صف")

    async def end_session(self, session, reason: str) -> None:
        await self.store.execute("UPDATE role_sessions SET status='ended',pending=0 WHERE id=?", (session["id"],))
        for user_id in (session["user_a"], session["user_b"]):
            await self.store.emit(f"ended:{session['id']}:{user_id}", "send_message", chat_id=user_id,
                                  text=f"نشست #{session['id']} پایان یافت. {reason}")

    async def relay(self, user, message, session, bot) -> None:
        partner_id = session["user_b"] if user.id == session["user_a"] else session["user_a"]
        if not await self.member(bot, user.id) or not await self.member(bot, partner_id):
            await self.end_session(session, "یکی از طرفین دیگر عضو گروه نیست.")
            return
        if session["next_user"] != user.id or session["pending"]:
            await self.say(user.id, "الان نوبت تو نیست یا پیام قبلی هنوز در حال ارسال است؛ منتظر بمان.")
            return
        if not message.text or onboarding.units(message.text) > 3500:
            await self.say(user.id, "در نشست فقط متن تا ۳۵۰۰ کاراکتر قابل ارسال است.")
            return
        label = "A" if user.id == session["user_a"] else "B"
        sequence = session["sequence"] + 1
        await self.store.execute("UPDATE role_sessions SET pending=1,updated_at=? WHERE id=?", (time.time(), session["id"]))
        await self.store.emit(f"role:{session['id']}:{sequence}", "role_turn", session_id=session["id"],
                              sequence=sequence, author=user.id, partner=partner_id,
                              text=f"نشست #{session['id']} · {label}\n\n{message.text}")
        await self.say(user.id, "متنت در صف انتشار قرار گرفت؛ بعد از پاسخ طرف مقابل نوبت تو می‌شود.")

    async def private_message(self, update: Update, bot) -> None:
        user, message = update.effective_user, update.message
        command = parse_command(message.text)
        # Persian aliases are matched as plain text because Telegram command entities are ASCII.
        name = command[0] if command else {"/رجیستر": "register", "/فاک": "fuck"}.get(message.text, "")
        if command and command[1] and command[1].lower() != bot.username.lower():
            return
        if name == "start":
            await self.start(update, bot)
        elif name == "report":
            await self.say(user.id, texts.REPORT_USAGE)
        elif name == "discard":
            await self.store.execute("DELETE FROM forms WHERE user_id=?", (user.id,))
            await self.say(user.id, "فرم لغو شد. /start")
        elif name == "register":
            await self.begin_form(user, bot)
        elif name == "cancel":
            await self.store.execute("DELETE FROM private_queue WHERE user_id=?", (user.id,))
            await self.store.execute("DELETE FROM private_searches WHERE user_id=?", (user.id,))
            await self.say(user.id, "از صف خارج شدی. برای پایان نشست فعال /end و برای لغو فرم /discard را بزن.")
        elif name == "end":
            session = await self.store.session(user.id)
            if session:
                await self.end_session(session, "یکی از طرفین نشست را تمام کرد.")
            else:
                await self.say(user.id, "نشست فعالی نداری.")
        elif name == "fuck":
            if await self.store.one("SELECT 1 FROM forms WHERE user_id=?", (user.id,)):
                await self.say(user.id, "اول فرم را کامل کن یا با /discard لغو کن.")
            else:
                await self.start_search(user, bot)
        else:
            form = await self.store.one("SELECT * FROM forms WHERE user_id=?", (user.id,))
            session = await self.store.session(user.id)
            if form:
                if message.media_group_id:
                    await self.say(user.id, "فقط یک عکس بفرست؛ آلبوم پذیرفته نمی‌شود.")
                else:
                    await self.advance_form(user, form, message.text, message.photo[-1].file_id if message.photo else None)
            elif session:
                await self.relay(user, message, session, bot)
            else:
                await self.say(user.id, "برای منوی ربات /start را بزن.")

    async def private_callback(self, query, bot) -> None:
        if not query.data:
            return
        if query.data == "join:begin":
            await self.begin_form(query.from_user, bot)
        elif query.data.startswith("form:"):
            try:
                _, nonce, step, value = query.data.split(":")
                step = int(step)
            except (ValueError, TypeError):
                return
            form = await self.store.one("SELECT * FROM forms WHERE user_id=? AND nonce=? AND step=?",
                                        (query.from_user.id, nonce, step))
            if not form:
                await self.say(query.from_user.id, "این دکمه قدیمی است؛ از آخرین پیام یا /register استفاده کن.")
                return
            if not query.from_user.username:
                await self.say(query.from_user.id, onboarding.NEED_USERNAME)
                return
            if step == len(onboarding.FIELDS):
                if value == "submit":
                    await self.submit_form(query.from_user, form, bot)
                elif value == "edit":
                    await self.store.execute("DELETE FROM forms WHERE user_id=?", (query.from_user.id,))
                    await self.begin_form(query.from_user, bot)
            elif onboarding.FIELDS[step] in onboarding.CHOICES:
                if step == 7 and value == "handle":
                    await self.say(query.from_user.id, "آیدی پارتنر را با @ و فقط در یک خط وارد کن.")
                else:
                    await self.advance_form(query.from_user, form, value)
        elif query.data.startswith("seek:"):
            await self.search_callback(query, bot)

    async def route(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        self.event = f"update:{update.update_id}"
        bot = context.bot
        chat, user = update.effective_chat, update.effective_user
        if update.chat_member and update.chat_member.chat.id == self.settings.allowed_group_id:
            changed = update.chat_member.new_chat_member
            status = changed.status
            if status == "restricted" and not changed.is_member:
                status = "left"
            if not changed.user.is_bot:
                await self.sync_member(changed.user, status, time.time())
            raise ApplicationHandlerStop
        if chat is None or user is None:
            raise ApplicationHandlerStop
        if update.callback_query:
            query = update.callback_query
            if (query.data or "").startswith("admission:"):
                await self.decide(query, bot)
                raise ApplicationHandlerStop
            if chat.type == "private":
                # A stale callback answer must never roll back the actual form transition.
                try:
                    await query.answer()
                except Exception:
                    pass
                await self.private_callback(query, bot)
                raise ApplicationHandlerStop
            if chat.id != self.settings.allowed_group_id or not await self.member(bot, user.id):
                raise ApplicationHandlerStop
            return
        if chat.type == "private" and update.message:
            await self.private_message(update, bot)
            raise ApplicationHandlerStop
        if chat.id != self.settings.allowed_group_id or update.message is None:
            raise ApplicationHandlerStop
        message = update.message
        for joined in message.new_chat_members or ():
            if not joined.is_bot:
                await self.sync_member(joined, "member", time.time())
        if message.left_chat_member and not message.left_chat_member.is_bot:
            await self.sync_member(message.left_chat_member, "left", time.time())
        await self.observe(message, time.time())
        # Legacy group commands stay public; all anonymous flows are intercepted above.
        return

    def last_activity(self, row) -> float:
        cached = self.activity.get(row["user_id"])
        return cached.seen if cached else row["safe_seen"] or row["tracked_since"]

    async def maintain(self, now: float) -> None:
        members = await self.store.all("SELECT * FROM members WHERE status IN ('member','restricted')")
        for row in members:
            seen = self.last_activity(row)
            idle = now - seen
            if (row["warnings"] and row["recovery_since"] is not None
                    and now - row["recovery_since"] >= WEEK and idle < WEEK):
                weeks = int((now - row["recovery_since"]) // WEEK)
                await self.store.execute("UPDATE members SET warnings=MAX(0,warnings-?),recovery_since=? WHERE user_id=?",
                                         (weeks, row["recovery_since"] + weeks * WEEK, row["user_id"]))
            if idle >= 3 * WEEK:
                await self.store.emit(f"ban:{row['user_id']}:{seen}", "inactivity_ban", user_id=row["user_id"])
            elif idle >= WEEK:
                stage = min(2, int(idle // WEEK))
                if stage > row["inactivity_stage"]:
                    await self.store.execute(
                        "UPDATE members SET warnings=MIN(2,warnings+?),inactivity_stage=?,recovery_since=NULL WHERE user_id=?",
                        (stage - row["inactivity_stage"], stage, row["user_id"]),
                    )
                    await self.store.emit(f"warning:{row['user_id']}:{seen}:{stage}", "inactivity_warning",
                                          user_id=row["user_id"], stage=stage)
        for session in await self.store.all("SELECT * FROM role_sessions WHERE status='active' AND updated_at<?",
                                           (now - self.settings.session_timeout_hours * 3600,)):
            await self.end_session(session, "مهلت پاسخ به پایان رسید.")
        for entry in await self.store.all("SELECT user_id FROM private_queue WHERE queued_at<?",
                                         (now - self.settings.queue_timeout_hours * 3600,)):
            await self.store.execute("DELETE FROM private_queue WHERE user_id=?", (entry["user_id"],))
            await self.store.emit(f"queue-expired:{entry['user_id']}:{int(now)}", "send_message",
                                  chat_id=entry["user_id"], text="درخواست جست‌وجو منقضی شد؛ برای جست‌وجوی دوباره /fuck را بزن.")
        await self.store.execute("DELETE FROM forms WHERE updated_at<?", (now - 30 * DAY,))
        await self.store.execute("DELETE FROM inbox WHERE status='done' AND created_at<?", (now - 7 * DAY,))
        await self.store.execute("DELETE FROM outbox WHERE status IN ('done','cancelled') AND created_at<?", (now - 7 * DAY,))


async def route(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    community: Community = context.bot_data["community"]
    await community.route(update, context)
