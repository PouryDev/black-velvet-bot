from __future__ import annotations

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

ASK_GENDER, ASK_POSITION = range(2)
PREFIX = "reg"


def _owner_id(context: ContextTypes.DEFAULT_TYPE) -> int | None:
    return context.user_data.get("flow_user_id")


async def start_register(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message is None or update.effective_user is None:
        return ConversationHandler.END
    user = update.effective_user
    context.user_data.clear()
    context.user_data["flow_user_id"] = user.id
    await update.message.reply_text(
        texts.REGISTER_PICK_GENDER,
        reply_markup=gender_keyboard(PREFIX),
    )
    return ASK_GENDER


async def pick_gender(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query is None or query.from_user is None or query.data is None:
        return ConversationHandler.END
    if query.from_user.id != _owner_id(context):
        await query.answer(texts.REGISTER_WRONG_USER, show_alert=True)
        return ASK_GENDER
    await query.answer()
    _, _, gender = query.data.split(":", 2)
    context.user_data["gender"] = gender
    await query.edit_message_text(
        texts.REGISTER_PICK_POSITION,
        reply_markup=position_keyboard(PREFIX),
    )
    return ASK_POSITION


async def pick_position(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query is None or query.from_user is None or query.data is None:
        return ConversationHandler.END
    if query.from_user.id != _owner_id(context):
        await query.answer(texts.REGISTER_WRONG_USER, show_alert=True)
        return ASK_POSITION
    await query.answer()
    _, _, position = query.data.split(":", 2)
    gender = context.user_data.get("gender")
    if not gender:
        await query.edit_message_text("یه بار دیگه /register بزن.")
        return ConversationHandler.END

    db: Database = context.bot_data["db"]
    user = query.from_user
    await db.upsert_user(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        gender=gender,
        position=position,
    )
    await query.edit_message_text(
        texts.REGISTER_DONE.format(
            gender=texts.GENDER_LABELS[gender],
            position=texts.POSITION_LABELS[position],
        )
    )
    context.user_data.clear()
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    if update.message:
        await update.message.reply_text(texts.CANCELLED)
    return ConversationHandler.END


def build_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("register", start_register)],
        states={
            ASK_GENDER: [CallbackQueryHandler(pick_gender, pattern=rf"^{PREFIX}:gender:")],
            ASK_POSITION: [CallbackQueryHandler(pick_position, pattern=rf"^{PREFIX}:pos:")],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_chat=True,
        per_user=True,
        name="register",
    )
