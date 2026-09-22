from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def gender_keyboard(prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("مرد", callback_data=f"{prefix}:gender:male"),
                InlineKeyboardButton("زن", callback_data=f"{prefix}:gender:female"),
                InlineKeyboardButton("ترنس", callback_data=f"{prefix}:gender:trans"),
            ]
        ]
    )


def position_keyboard(prefix: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("تاپ", callback_data=f"{prefix}:pos:top"),
                InlineKeyboardButton("باتم", callback_data=f"{prefix}:pos:bottom"),
                InlineKeyboardButton("ورس", callback_data=f"{prefix}:pos:vers"),
            ],
            [
                InlineKeyboardButton("ورس‌تاپ", callback_data=f"{prefix}:pos:vers_top"),
                InlineKeyboardButton("ورس‌باتم", callback_data=f"{prefix}:pos:vers_bottom"),
            ],
        ]
    )
