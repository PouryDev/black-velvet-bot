from __future__ import annotations

from telegram import Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

from app import texts
from app.db import Database
from app.keyboards import gender_keyboard, position_keyboard

PREFIX = "reg"


async def start_register(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_user is None:
        return
    user = update.effective_user
    await update.message.reply_text(
        texts.REGISTER_PICK_GENDER,
        reply_markup=gender_keyboard(PREFIX, user.id),
    )


async def pick_gender(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.from_user is None or query.data is None:
        return
    try:
        _, _, owner_id, gender = query.data.split(":", 3)
        owner_id_int = int(owner_id)
    except ValueError:
        await query.answer()
        return
    if query.from_user.id != owner_id_int:
        await query.answer(texts.REGISTER_WRONG_USER, show_alert=True)
        return
    await query.answer()
    await query.edit_message_text(
        texts.REGISTER_PICK_POSITION,
        reply_markup=position_keyboard(PREFIX, owner_id_int, gender),
    )


async def pick_position(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.from_user is None or query.data is None:
        return
    try:
        _, _, owner_id, gender, position = query.data.split(":", 4)
        owner_id_int = int(owner_id)
    except ValueError:
        await query.answer()
        return
    if query.from_user.id != owner_id_int:
        await query.answer(texts.REGISTER_WRONG_USER, show_alert=True)
        return
    await query.answer()

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


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message:
        await update.message.reply_text(texts.CANCELLED)


def add_handlers(application) -> None:
    application.add_handler(CommandHandler("register", start_register))
    application.add_handler(CallbackQueryHandler(pick_gender, pattern=rf"^{PREFIX}:gender:"))
    application.add_handler(CallbackQueryHandler(pick_position, pattern=rf"^{PREFIX}:pos:"))
    application.add_handler(CommandHandler("cancel", cancel))
