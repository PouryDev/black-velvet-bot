from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.positions import (
    GENDER_CODES,
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


def position_keyboard(prefix: str, user_id: int, gender: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("تاپ", callback_data=f"{prefix}:pos:{user_id}:{gender}:top"),
                InlineKeyboardButton("باتم", callback_data=f"{prefix}:pos:{user_id}:{gender}:bottom"),
                InlineKeyboardButton("ورس", callback_data=f"{prefix}:pos:{user_id}:{gender}:vers"),
            ],
            [
                InlineKeyboardButton(
                    "ورس‌تاپ",
                    callback_data=f"{prefix}:pos:{user_id}:{gender}:vers_top",
                ),
                InlineKeyboardButton(
                    "ورس‌باتم",
                    callback_data=f"{prefix}:pos:{user_id}:{gender}:vers_bottom",
                ),
            ],
        ]
    )


def fuck_position_keyboard(user_id: int, gender: str, selected: list[str]) -> InlineKeyboardMarkup:
    gender_code = GENDER_CODES[gender]
    encoded = encode_positions(selected) or "-"
    rows: list[list[InlineKeyboardButton]] = []
    current: list[InlineKeyboardButton] = []
    for name in POSITION_ORDER:
        mark = " ✅" if name in selected else ""
        current.append(
            InlineKeyboardButton(
                f"{POSITION_LABELS[name]}{mark}",
                callback_data=f"fuck:tgl:{user_id}:{gender_code}:{POSITION_CODES[name]}:{encoded}",
            )
        )
        if len(current) == 3:
            rows.append(current)
            current = []
    if current:
        rows.append(current)
    confirm_label = f"ثبت انتخاب‌ها ({len(selected)}/2)"
    rows.append(
        [
            InlineKeyboardButton(
                confirm_label,
                callback_data=f"fuck:ok:{user_id}:{gender_code}:{encoded}",
            )
        ]
    )
    return InlineKeyboardMarkup(rows)


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
