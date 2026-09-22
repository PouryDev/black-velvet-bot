from __future__ import annotations

import random

from telegram import Update
from telegram.ext import CallbackQueryHandler, ContextTypes, MessageHandler

from app import texts
from app.callbacks import parse_owner
from app.commands import command_filter
from app.db import Database
from app.group import send_to_group
from app.keyboards import (
    fuck_cancel_confirm_keyboard,
    fuck_position_keyboard,
    fuck_queue_keyboard,
    gender_keyboard,
)
from app.mentions import mention_queue, mention_user
from app.positions import (
    CODE_TO_POSITION,
    MAX_WANTED_POSITIONS,
    MIN_POSITIONS,
    decode_positions,
    toggle_position,
)
from app.rtl import ensure_rtl

PREFIX = "fuck"


def _format_positions(positions: list[str] | tuple[str, ...]) -> str:
    return "، ".join(texts.POSITION_LABELS[name] for name in positions)


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
        ensure_rtl(texts.FUCK_PICK_POSITION),
        reply_markup=fuck_position_keyboard(owner_id_int, gender, []),
    )


async def toggle_wanted_position(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.from_user is None or query.data is None:
        return
    parsed = parse_owner(query.data, PREFIX, "tgl")
    if parsed is None:
        await query.answer()
        return
    owner_id, gender, rest = parsed
    if query.from_user.id != owner_id:
        await query.answer(texts.FUCK_WRONG_USER, show_alert=True)
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
    selected = decode_positions("" if encoded == "-" else encoded, max_count=MAX_WANTED_POSITIONS)
    if position not in selected and len(selected) >= MAX_WANTED_POSITIONS:
        await query.answer(texts.FUCK_POSITION_MAX, show_alert=True)
        return
    updated = toggle_position(selected, position, MAX_WANTED_POSITIONS)
    await query.answer()
    await query.edit_message_text(
        ensure_rtl(texts.FUCK_PICK_POSITION),
        reply_markup=fuck_position_keyboard(owner_id, gender, updated),
    )


async def confirm_positions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.from_user is None or query.data is None or query.message is None:
        return
    parsed = parse_owner(query.data, PREFIX, "ok")
    if parsed is None:
        await query.answer()
        return
    owner_id, wanted_gender, encoded = parsed
    if query.from_user.id != owner_id:
        await query.answer(texts.FUCK_WRONG_USER, show_alert=True)
        return
    wanted_positions = decode_positions("" if encoded == "-" else encoded, max_count=MAX_WANTED_POSITIONS)
    if len(wanted_positions) < MIN_POSITIONS:
        await query.answer(texts.FUCK_POSITION_MIN, show_alert=True)
        return
    await query.answer()

    db: Database = context.bot_data["db"]
    user = query.from_user
    profile = await db.get_user(user.id)
    if profile is None:
        await query.edit_message_text(ensure_rtl(texts.FUCK_NEED_REGISTER))
        return

    partner = await db.match_or_enqueue(
        user_id=user.id,
        gender=profile.gender,
        positions=profile.positions,
        wanted_gender=wanted_gender,
        wanted_positions=wanted_positions,
    )
    if partner is None:
        await query.edit_message_text(
            ensure_rtl(
                texts.FUCK_QUEUED.format(
                    gender=texts.GENDER_LABELS[wanted_gender],
                    position=_format_positions(wanted_positions),
                )
            ),
            reply_markup=fuck_queue_keyboard(user.id),
        )
        return

    line = random.choice(texts.MATCH_LINES)
    caption = texts.match_caption(mention_user(user), mention_queue(partner), line)
    await send_to_group(context, caption, parse_mode="HTML")
    await query.edit_message_text(ensure_rtl(texts.FUCK_MATCHED))


def _owner_from_simple(query_data: str, kind: str) -> int | None:
    parts = query_data.split(":")
    if len(parts) != 3 or parts[0] != PREFIX or parts[1] != kind:
        return None
    try:
        return int(parts[2])
    except ValueError:
        return None


async def start_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_user is None:
        return
    db: Database = context.bot_data["db"]
    user = update.effective_user
    if not await db.is_in_queue(user.id):
        await send_to_group(
            context,
            f"{mention_user(user)}\n{texts.FUCK_CANCEL_NONE}",
            parse_mode="HTML",
        )
        return
    await send_to_group(
        context,
        f"{mention_user(user)}\n{texts.FUCK_CANCEL_ASK}",
        parse_mode="HTML",
        reply_markup=fuck_cancel_confirm_keyboard(user.id),
    )


async def ask_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.from_user is None or query.data is None:
        return
    owner_id = _owner_from_simple(query.data, "cx")
    if owner_id is None:
        await query.answer()
        return
    if query.from_user.id != owner_id:
        await query.answer(texts.FUCK_WRONG_USER, show_alert=True)
        return
    db: Database = context.bot_data["db"]
    if not await db.is_in_queue(owner_id):
        await query.answer(texts.FUCK_CANCEL_NONE, show_alert=True)
        await query.edit_message_text(ensure_rtl(texts.FUCK_CANCEL_NONE))
        return
    await query.answer()
    await query.edit_message_text(
        ensure_rtl(texts.FUCK_CANCEL_ASK),
        reply_markup=fuck_cancel_confirm_keyboard(owner_id),
    )


async def confirm_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.from_user is None or query.data is None:
        return
    owner_id = _owner_from_simple(query.data, "cy")
    if owner_id is None:
        await query.answer()
        return
    if query.from_user.id != owner_id:
        await query.answer(texts.FUCK_WRONG_USER, show_alert=True)
        return
    db: Database = context.bot_data["db"]
    if not await db.is_in_queue(owner_id):
        await query.answer(texts.FUCK_CANCEL_NONE, show_alert=True)
        await query.edit_message_text(ensure_rtl(texts.FUCK_CANCEL_NONE))
        return
    await db.dequeue_users(owner_id)
    await query.answer()
    await query.edit_message_text(ensure_rtl(texts.FUCK_CANCEL_DONE))


async def keep_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query is None or query.from_user is None or query.data is None:
        return
    owner_id = _owner_from_simple(query.data, "cn")
    if owner_id is None:
        await query.answer()
        return
    if query.from_user.id != owner_id:
        await query.answer(texts.FUCK_WRONG_USER, show_alert=True)
        return
    await query.answer()
    await query.edit_message_text(ensure_rtl(texts.FUCK_CANCEL_KEEP))


def add_handlers(application) -> None:
    application.add_handler(MessageHandler(command_filter("fuck"), start_fuck))
    application.add_handler(MessageHandler(command_filter("cancel"), start_cancel))
    application.add_handler(CallbackQueryHandler(pick_gender, pattern=rf"^{PREFIX}:gender:"))
    application.add_handler(CallbackQueryHandler(toggle_wanted_position, pattern=rf"^{PREFIX}:tgl:"))
    application.add_handler(CallbackQueryHandler(confirm_positions, pattern=rf"^{PREFIX}:ok:"))
    application.add_handler(CallbackQueryHandler(ask_cancel, pattern=rf"^{PREFIX}:cx:"))
    application.add_handler(CallbackQueryHandler(confirm_cancel, pattern=rf"^{PREFIX}:cy:"))
    application.add_handler(CallbackQueryHandler(keep_request, pattern=rf"^{PREFIX}:cn:"))
