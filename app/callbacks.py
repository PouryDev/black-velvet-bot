from __future__ import annotations

from app.positions import CODE_TO_GENDER


def parse_owner(query_data: str, prefix: str, expected_kind: str) -> tuple[int, str, str] | None:
    parts = query_data.split(":")
    if len(parts) < 4 or parts[0] != prefix or parts[1] != expected_kind:
        return None
    try:
        owner_id = int(parts[2])
    except ValueError:
        return None
    gender = CODE_TO_GENDER.get(parts[3])
    if gender is None:
        return None
    rest = ":".join(parts[4:]) if len(parts) > 4 else ""
    return owner_id, gender, rest
