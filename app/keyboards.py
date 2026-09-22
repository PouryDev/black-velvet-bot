from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.positions import (
    GENDER_CODES,
    MAX_PROFILE_POSITIONS,
    MAX_WANTED_POSITIONS,
    POSITION_CODES,
    POSITION_ORDER,
    encode_positions,
)
from app.texts import POSITION_LABELS


def gender_keyboard(prefix: str, user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("مرد", callback_data=f"{prefix}:gender:{user_id}:male"),
                InlineKeyboardButton("زن", callback_data=f"{prefix}:gender:{user_id}:female"),
                InlineKeyboardButton("ترنس", callback_data=f"{prefix}:gender:{user_id}:trans"),
            ]
        ]
    )


def multi_position_keyboard(
    prefix: str,
    user_id: int,
    gender: str,
    selected: list[str],
    max_count: int,
) -> InlineKeyboardMarkup:
    gender_code = GENDER_CODES[gender]
    encoded = encode_positions(selected, max_count=max_count) or "-"
    rows: list[list[InlineKeyboardButton]] = []
    current: list[InlineKeyboardButton] = []
    for name in POSITION_ORDER:
        mark = " ✅" if name in selected else ""
        current.append(
            InlineKeyboardButton(
                f"{POSITION_LABELS[name]}{mark}",
                callback_data=f"{prefix}:tgl:{user_id}:{gender_code}:{POSITION_CODES[name]}:{encoded}",
            )
        )
        if len(current) == 3:
            rows.append(current)
            current = []
    if current:
        rows.append(current)
    rows.append(
        [
            InlineKeyboardButton(
                f"ثبت انتخاب‌ها ({len(selected)}/{max_count})",
                callback_data=f"{prefix}:ok:{user_id}:{gender_code}:{encoded}",
            )
        ]
    )
    return InlineKeyboardMarkup(rows)


def register_position_keyboard(user_id: int, gender: str, selected: list[str]) -> InlineKeyboardMarkup:
    return multi_position_keyboard("reg", user_id, gender, selected, MAX_PROFILE_POSITIONS)


def fuck_position_keyboard(user_id: int, gender: str, selected: list[str]) -> InlineKeyboardMarkup:
    return multi_position_keyboard("fuck", user_id, gender, selected, MAX_WANTED_POSITIONS)


def position_keyboard(prefix: str, user_id: int, gender: str) -> InlineKeyboardMarkup:
    return multi_position_keyboard(prefix, user_id, gender, [], MAX_PROFILE_POSITIONS)


def fuck_queue_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("لغو درخواست", callback_data=f"fuck:cx:{user_id}")]]
    )


def fuck_cancel_confirm_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("بله، لغو کن", callback_data=f"fuck:cy:{user_id}"),
                InlineKeyboardButton("نه، بمونه", callback_data=f"fuck:cn:{user_id}"),
            ]
        ]
    )
