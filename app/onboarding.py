from __future__ import annotations

import re
import unicodedata

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.positions import POSITION_ORDER

FIELDS = ("name", "age", "gender", "orientation", "position", "interest", "limits", "status", "photo")
CHOICES = {
    "gender": ("male", "female", "trans"),
    "orientation": ("straight", "gay", "bisexual", "lesbian"),
    "position": POSITION_ORDER,
    "status": ("single", "couple", "handle"),
}
PROMPTS = (
    "نامت را بنویس (حداکثر ۴۸ کاراکتر).",
    "سنت را به عدد وارد کن. استفاده از این بخش فقط برای افراد ۱۸ سال به بالاست.",
    "جنسیتت را انتخاب کن.",
    "گرایشت را انتخاب کن.",
    "پوزیشنت را انتخاب کن.",
    "فانتزی‌ها را فقط در یک خط بنویس (حداکثر ۱۶۰ کاراکتر).",
    "لیمیت‌ها را فقط در یک خط بنویس (حداکثر ۱۶۰ کاراکتر).",
    "وضعیتت را انتخاب کن: single، couple یا وارد کردن آیدی پارتنر.",
    "یک عکس به‌صورت Photo بفرست (فایل، آلبوم یا ویدئو قابل قبول نیست).",
    "پیش‌نمایش پروفایل؛ تأیید یا اصلاح را انتخاب کن.",
)
NEED_USERNAME = (
    "برای ثبت‌نام باید username تلگرام داشته باشی. از Settings → Username یک نام کاربری عمومی تنظیم کن، "
    "بعد /register را بزن یا دکمه «درخواست عضویت» را انتخاب کن. بدون username امکان شروع یا ارسال فرم وجود ندارد."
)
START_WELCOME = "سلام، به ربات Black Velvet خوش آمدی 🖤"
START_JOIN = "برای عضویت در گروه Black Velvet، با دکمه زیر فرم درخواست عضویت را تکمیل کن."
START_MEMBER_GUIDE = (
    "تو عضو گروه Black Velvet هستی.\n\n"
    "راهنمای رول ناشناس در گروه:\n"
    "۱. با /register در پیوی همین ربات پروفایلت را کامل کن.\n"
    "۲. با /fuck مشخصات فرد موردنظرت را انتخاب کن و وارد صف ناشناس شو.\n"
    "۳. بعد از پیدا شدن مچ، ربات در پیوی به هر دو نفر می‌گوید با چه کسی مچ شده‌اند و چه کسی شروع می‌کند.\n"
    "۴. وقتی ربات گفت نوبت توست، متنت را همین‌جا در پیوی بفرست؛ ربات آن را با شناسه ناشناس در گروه "
    "منتشر می‌کند و برای طرف مقابل هم می‌فرستد. پاسخ هر نوبت به پیام قبلی همان نشست در گروه ریپلای می‌شود.\n\n"
    "نام و آیدی شما توسط ربات در گروه نمایش داده نمی‌شود؛ هویت طرف مقابل فقط در پیوی به خودتان گفته می‌شود.\n\n"
    "/cancel خروج از صف جست‌وجو\n"
    "/end پایان نشست برای هر دو نفر"
)
WELCOME = "به Black Velvet خوش آمدی 🖤\nدرخواستت قبول شد؛ تا دقایقی دیگر توسط ادمین‌ها به گروه اضافه می‌شوی."


def units(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


def clean_line(value: str, maximum: int) -> str:
    if any(c in value for c in "\r\n\v\f\x85\u2028\u2029"):
        raise ValueError("متن باید فقط یک خط و بدون Enter باشد.")
    # Strip bidi overrides/control characters so user input cannot disguise card labels.
    bidi_controls = {"RLE", "LRE", "RLO", "LRO", "PDF", "LRI", "RLI", "FSI", "PDI"}
    value = "".join(c for c in value.strip() if unicodedata.bidirectional(c) not in bidi_controls)
    if not value or any(unicodedata.category(c) == "Cc" for c in value):
        raise ValueError("یک متن معتبر و تک‌خطی وارد کن.")
    if units(value) > maximum:
        raise ValueError(f"متن بیش از حد طولانی است؛ حداکثر {maximum} کاراکتر.")
    return value


def validate_value(field: str, value: str) -> str | int:
    if field == "age":
        value = clean_line(value, 3)
        try:
            age = int(value)
        except ValueError:
            raise ValueError("سن را فقط به عدد وارد کن.") from None
        if not 18 <= age <= 100:
            raise ValueError("سن باید بین ۱۸ و ۱۰۰ سال باشد؛ ثبت‌نام زیر ۱۸ سال مجاز نیست.")
        return age
    if field in CHOICES:
        value = clean_line(value, 40).lower()
        if field == "status" and re.fullmatch(r"@[a-zA-Z][a-zA-Z0-9_]{4,31}", value):
            return value
        if value not in CHOICES[field] or value == "handle":
            raise ValueError("یکی از گزینه‌ها را انتخاب کن یا آیدی معتبر با @ وارد کن.")
        return value
    return clean_line(value, 48 if field == "name" else 160)


def card(data: dict) -> str:
    text = (
        "✦ MEMBER ✦\n\n"
        "╭──── ༺✦༻ ────╮\n"
        f"২ NAME:{data['name']}\n"
        f"২ AGE:{data['age']}\n"
        f"২ GENDER:{data['gender'].title()}\n"
        f"২ ORIENTATION:{data['orientation'].title()}\n"
        f"২ POSITION:{data['position'].replace('_', ' ').title()}\n"
        f"২ INTREST:{data['interest']}\n"
        f"২ LIMITS:{data['limits']}\n"
        f"২ STATUS:{data['status']}\n"
        "╰──── ༺✦༻ ────╯\n\n"
        f"USERNAME: @{data['username']}\n\n"
        "SUP BY: 𝖫𝗎𝗌𝗍 𝖢𝗅𝗎𝖻 ."
    )
    if units(text) > 1024:
        raise ValueError("متن پروفایل طولانی است؛ با اصلاح فرم، متن فانتزی‌ها یا لیمیت‌ها را کوتاه کن.")
    return text


def form_keyboard(nonce: str, step: int) -> InlineKeyboardMarkup | None:
    if step == len(FIELDS):
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("تأیید و ارسال", callback_data=f"form:{nonce}:{step}:submit")],
            [InlineKeyboardButton("اصلاح فرم", callback_data=f"form:{nonce}:{step}:edit")],
        ])
    field = FIELDS[step]
    if field not in CHOICES:
        return None
    choices = CHOICES[field]
    buttons = [InlineKeyboardButton(
        "آیدی پارتنر" if choice == "handle" else choice.replace("_", " ").title(),
        callback_data=f"form:{nonce}:{step}:{choice}",
    ) for choice in choices]
    return InlineKeyboardMarkup([buttons[i:i + 2] for i in range(0, len(buttons), 2)])


def decision_keyboard(request_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("قبول", callback_data=f"admission:{request_id}:accept"),
        InlineKeyboardButton("رد", callback_data=f"admission:{request_id}:reject"),
    ]])
