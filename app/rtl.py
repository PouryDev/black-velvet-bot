from __future__ import annotations


def _is_persian_letter(char: str) -> bool:
    code = ord(char)
    return (
        0x0600 <= code <= 0x06FF
        or 0x0750 <= code <= 0x077F
        or 0x08A0 <= code <= 0x08FF
        or 0xFB50 <= code <= 0xFDFF
        or 0xFE70 <= code <= 0xFEFF
    )


def ensure_rtl(text: str) -> str:
    """Keep Telegram RTL without rewriting every line (that breaks wrapping)."""
    stripped = text.lstrip()
    if not stripped:
        return text
    if _is_persian_letter(stripped[0]):
        return text
    leading = text[: len(text) - len(stripped)]
    return f"{leading}یالا {stripped}"
