from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


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
