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


def _rtl_line(line: str) -> str:
    stripped = line.lstrip()
    if not stripped:
        return line
    if _is_persian_letter(stripped[0]):
        return line
    leading = line[: len(line) - len(stripped)]
    return f"{leading}خب {stripped}"


def ensure_rtl(text: str) -> str:
    return "\n".join(_rtl_line(part) for part in text.split("\n"))
