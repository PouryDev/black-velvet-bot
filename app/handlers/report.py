from __future__ import annotations

import html
from zoneinfo import ZoneInfo

from telegram import Chat, InlineKeyboardButton, InlineKeyboardMarkup, Message, ReplyParameters, Update
from telegram.ext import ContextTypes, MessageHandler

from app import texts
from app.commands import command_filter, parse_command
from app.mentions import mention_user

TEHRAN = ZoneInfo("Asia/Tehran")


def message_link(message: Message) -> str | None:
    if message.chat.type not in {Chat.SUPERGROUP, Chat.CHANNEL} or message.message_id <= 0:
        return None
    if message.chat.username:
        peer = message.chat.username
    elif str(message.chat.id).startswith("-100"):
        peer = f"c/{str(message.chat.id)[4:]}"
    else:
        return None
    link = f"https://t.me/{peer}/{message.message_id}"
    if message.is_topic_message and message.message_thread_id:
        link += f"?thread={message.message_thread_id}"
    return link


async def report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message, user = update.message, update.effective_user
    community = context.bot_data["community"]
    if message is None or user is None or message.chat.id != community.settings.allowed_group_id:
        return
    command = parse_command(message.text)
    if not command or command[0] != "report":
        return
    if command[1] and command[1].lower() != context.bot.username.lower():
        return

    async def respond(text: str) -> None:
        await community.store.emit(
            f"report-reply:{message.chat.id}:{message.message_id}", "send_message",
            chat_id=message.chat.id, text=text,
            reply_parameters=ReplyParameters(message_id=message.message_id, allow_sending_without_reply=True).to_dict(),
        )

    if user.is_bot or message.sender_chat is not None:
        await respond(texts.REPORT_IDENTIFIED_USER)
        return
    target = message.reply_to_message
    if target is None or target.chat.id != message.chat.id:
        await respond(texts.REPORT_USAGE)
        return
    link = message_link(target)
    if not link:
        await respond(texts.REPORT_LINK_UNAVAILABLE)
        return
    report_day = message.date.astimezone(TEHRAN).date().isoformat()
    claimed = await community.store.claim_report(
        message.chat.id, user.id, report_day, message.message_id, target.message_id,
    )
    if not claimed:
        previous = await community.store.one(
            "SELECT report_message_id FROM daily_reports WHERE chat_id=? AND user_id=?",
            (message.chat.id, user.id),
        )
        if previous["report_message_id"] == message.message_id:
            await respond(texts.REPORT_RECEIVED)
        else:
            await respond(texts.REPORT_DAILY_LIMIT)
        return

    if target.sender_chat:
        sender = html.escape(target.sender_chat.title or "فرستنده ناشناس")
    elif target.from_user:
        sender = mention_user(target.from_user)
    else:
        sender = "فرستنده ناشناس"
    await community.store.emit(
        f"report:{message.chat.id}:{message.message_id}", "send_message",
        chat_id=community.settings.admin_group_id,
        text=texts.REPORT_ADMIN_NEW.format(reporter=mention_user(user), sender=sender, link=html.escape(link)),
        parse_mode="HTML", disable_web_page_preview=True,
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("مشاهده پیام گزارش‌شده", url=link),
        ]]).to_dict(),
    )
    await respond(texts.REPORT_RECEIVED)


def add_handlers(application) -> None:
    application.add_handler(MessageHandler(command_filter("report"), report))
