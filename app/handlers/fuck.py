from __future__ import annotations

import random

from telegram import Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
)

from app import texts
from app.db import Database
from app.keyboards import gender_keyboard, position_keyboard
from app.mentions import mention_queue, mention_user

ASK_GENDER, ASK_POSITION = range(2)
PREFIX = "fuck"


def _owner_id(context: ContextTypes.DEFAULT_TYPE) -> int | None:
    return context.user_data.get("flow_user_id")


async def start_fuck(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message is None or update.effective_user is None:
        return ConversationHandler.END
    db: Database = context.bot_data["db"]
    user = update.effective_user
    if not await db.is_registered(user.id):
        await update.message.reply_text(texts.FUCK_NEED_REGISTER)
        return ConversationHandler.END
    await db.touch_identity(user.id, user.username, user.first_name)
    context.user_data.clear()
    context.user_data["flow_user_id"] = user.id
    await update.message.reply_text(
        texts.FUCK_PICK_GENDER,
        reply_markup=gender_keyboard(PREFIX),
    )
    return ASK_GENDER


async def pick_gender(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query is None or query.from_user is None or query.data is None:
        return ConversationHandler.END
    if query.from_user.id != _owner_id(context):
        await query.answer(texts.FUCK_WRONG_USER, show_alert=True)
        return ASK_GENDER
    await query.answer()
    _, _, gender = query.data.split(":", 2)
    context.user_data["wanted_gender"] = gender
    await query.edit_message_text(
        texts.FUCK_PICK_POSITION,
        reply_markup=position_keyboard(PREFIX),
    )
    return ASK_POSITION


async def pick_position(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query is None or query.from_user is None or query.data is None or query.message is None:
        return ConversationHandler.END
    if query.from_user.id != _owner_id(context):
        await query.answer(texts.FUCK_WRONG_USER, show_alert=True)
        return ASK_POSITION
    await query.answer()
    _, _, wanted_position = query.data.split(":", 2)
    wanted_gender = context.user_data.get("wanted_gender")
    if not wanted_gender:
        await query.edit_message_text("یه بار دیگه /fuck بزن.")
        return ConversationHandler.END

    db: Database = context.bot_data["db"]
    user = query.from_user
    profile = await db.get_user(user.id)
    if profile is None:
        await query.edit_message_text(texts.FUCK_NEED_REGISTER)
        return ConversationHandler.END

    partner = await db.match_or_enqueue(
        user_id=user.id,
        gender=profile.gender,
        position=profile.position,
        wanted_gender=wanted_gender,
        wanted_position=wanted_position,
    )
    if partner is None:
        await query.edit_message_text(
            texts.FUCK_QUEUED.format(
                gender=texts.GENDER_LABELS[wanted_gender],
                position=texts.POSITION_LABELS[wanted_position],
            )
        )
        context.user_data.clear()
        return ConversationHandler.END

    line = random.choice(texts.MATCH_LINES)
    caption = texts.match_caption(mention_user(user), mention_queue(partner), line)
    await query.edit_message_text("مچ پیدا شد 🔥")
    await query.message.chat.send_message(caption, parse_mode="HTML")
    context.user_data.clear()
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    if update.message:
        await update.message.reply_text(texts.CANCELLED)
    return ConversationHandler.END


def build_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("fuck", start_fuck)],
        states={
            ASK_GENDER: [CallbackQueryHandler(pick_gender, pattern=rf"^{PREFIX}:gender:")],
            ASK_POSITION: [CallbackQueryHandler(pick_position, pattern=rf"^{PREFIX}:pos:")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_chat=True,
        per_user=True,
        name="fuck",
    )
