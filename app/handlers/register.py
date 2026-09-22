from __future__ import annotations

from telegram import Update
from telegram.ext import CallbackQueryHandler, ContextTypes, MessageHandler

from app import texts
from app.callbacks import parse_owner
from app.commands import command_filter
from app.db import Database
from app.group import send_to_group
from app.keyboards import gender_keyboard, register_position_keyboard
from app.mentions import mention_user
from app.positions import (
    CODE_TO_POSITION,
    MAX_PROFILE_POSITIONS,
    MIN_POSITIONS,
    decode_positions,
    toggle_position,
)
from app.rtl import ensure_rtl

PREFIX = "reg"


def _format_positions(positions: list[str] | tuple[str, ...]) -> str:
    return "، ".join(texts.POSITION_LABELS[name] for name in positions)


async def start_register(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_user is None:
        return
    user = update.effective_user
    await send_to_group(
        context,
        f"{mention_user(user)}\n{texts.REGISTER_PICK_GENDER}",
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
        await query.answer(texts.REGISTER_WRONG_USER, show_alert=True)
        return
    await query.answer()
    await query.edit_message_text(
        ensure_rtl(texts.REGISTER_PICK_POSITION),
        reply_markup=register_position_keyboard(owner_id_int, gender, []),
    )


async def toggle_profile_position(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.from_user is None or query.data is None:
        return
    parsed = parse_owner(query.data, PREFIX, "tgl")
    if parsed is None:
        await query.answer()
        return
    owner_id, gender, rest = parsed
    if query.from_user.id != owner_id:
        await query.answer(texts.REGISTER_WRONG_USER, show_alert=True)
        return
    try:
        code, encoded = rest.split(":", 1)
    except ValueError:
        await query.answer()
        return
    position = CODE_TO_POSITION.get(code)
    if position is None:
        await query.answer()
        return
    selected = decode_positions("" if encoded == "-" else encoded, max_count=MAX_PROFILE_POSITIONS)
    if position not in selected and len(selected) >= MAX_PROFILE_POSITIONS:
        await query.answer(texts.REGISTER_POSITION_MAX, show_alert=True)
        return
    updated = toggle_position(selected, position, MAX_PROFILE_POSITIONS)
    await query.answer()
    await query.edit_message_text(
        ensure_rtl(texts.REGISTER_PICK_POSITION),
        reply_markup=register_position_keyboard(owner_id, gender, updated),
    )


async def confirm_profile_positions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.from_user is None or query.data is None:
        return
    parsed = parse_owner(query.data, PREFIX, "ok")
    if parsed is None:
        await query.answer()
        return
    owner_id, gender, encoded = parsed
    if query.from_user.id != owner_id:
        await query.answer(texts.REGISTER_WRONG_USER, show_alert=True)
        return
    positions = decode_positions("" if encoded == "-" else encoded, max_count=MAX_PROFILE_POSITIONS)
    if len(positions) < MIN_POSITIONS:
        await query.answer(texts.REGISTER_POSITION_MIN, show_alert=True)
        return
    await query.answer()
    db: Database = context.bot_data["db"]
    user = query.from_user
    await db.upsert_user(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        gender=gender,
        positions=positions,
    )
    await query.edit_message_text(
        ensure_rtl(
            texts.REGISTER_DONE.format(
                gender=texts.GENDER_LABELS[gender],
                position=_format_positions(positions),
            )
        )
    )


def add_handlers(application) -> None:
    application.add_handler(MessageHandler(command_filter("register"), start_register))
    application.add_handler(CallbackQueryHandler(pick_gender, pattern=rf"^{PREFIX}:gender:"))
    application.add_handler(CallbackQueryHandler(toggle_profile_position, pattern=rf"^{PREFIX}:tgl:"))
    application.add_handler(CallbackQueryHandler(confirm_profile_positions, pattern=rf"^{PREFIX}:ok:"))
