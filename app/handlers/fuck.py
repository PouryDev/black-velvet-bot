from __future__ import annotations

import random

from telegram import Update
from telegram.ext import CallbackQueryHandler, ContextTypes, MessageHandler

from app import texts
from app.commands import command_filter
from app.db import Database
from app.group import send_to_group
from app.keyboards import gender_keyboard, position_keyboard
from app.mentions import mention_queue, mention_user

PREFIX = "fuck"


async def start_fuck(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_user is None:
        return
    db: Database = context.bot_data["db"]
    user = update.effective_user
    if not await db.is_registered(user.id):
        await send_to_group(
            context,
            f"{mention_user(user)}\n{texts.FUCK_NEED_REGISTER}",
            parse_mode="HTML",
        )
        return
    await db.touch_identity(user.id, user.username, user.first_name)
    await send_to_group(
        context,
        f"{mention_user(user)}\n{texts.FUCK_PICK_GENDER}",
        parse_mode="HTML",
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
        await query.answer(texts.FUCK_WRONG_USER, show_alert=True)
        return
    await query.answer()
    await query.edit_message_text(
        texts.FUCK_PICK_POSITION,
        reply_markup=position_keyboard(PREFIX, owner_id_int, gender),
    )


async def pick_position(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.from_user is None or query.data is None or query.message is None:
        return
    try:
        _, _, owner_id, wanted_gender, wanted_position = query.data.split(":", 4)
        owner_id_int = int(owner_id)
    except ValueError:
        await query.answer()
        return
    if query.from_user.id != owner_id_int:
        await query.answer(texts.FUCK_WRONG_USER, show_alert=True)
        return
    await query.answer()

    db: Database = context.bot_data["db"]
    user = query.from_user
    profile = await db.get_user(user.id)
    if profile is None:
        await query.edit_message_text(texts.FUCK_NEED_REGISTER)
        return

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
        return

    line = random.choice(texts.MATCH_LINES)
    caption = texts.match_caption(mention_user(user), mention_queue(partner), line)
    await query.edit_message_text("مچ پیدا شد 🔥")
    await send_to_group(context, caption, parse_mode="HTML")


def add_handlers(application) -> None:
    application.add_handler(MessageHandler(command_filter("fuck"), start_fuck))
    application.add_handler(CallbackQueryHandler(pick_gender, pattern=rf"^{PREFIX}:gender:"))
    application.add_handler(CallbackQueryHandler(pick_position, pattern=rf"^{PREFIX}:pos:"))
