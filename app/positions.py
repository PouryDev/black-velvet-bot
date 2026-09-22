from __future__ import annotations

import json

POSITION_ORDER = ("top", "bottom", "vers", "vers_top", "vers_bottom")
POSITION_CODES = {
    "top": "t",
    "bottom": "b",
    "vers": "v",
    "vers_top": "vt",
    "vers_bottom": "vb",
}
CODE_TO_POSITION = {code: name for name, code in POSITION_CODES.items()}
GENDER_CODES = {"male": "m", "female": "f", "trans": "x"}
CODE_TO_GENDER = {code: name for name, code in GENDER_CODES.items()}
MAX_POSITIONS = 3
MIN_POSITIONS = 1


def encode_positions(positions: list[str] | tuple[str, ...]) -> str:
    unique: list[str] = []
    seen: set[str] = set()
    for name in positions:
        if name not in POSITION_CODES or name in seen:
            continue
        seen.add(name)
        unique.append(name)
        if len(unique) == MAX_POSITIONS:
            break
    return "+".join(POSITION_CODES[name] for name in unique)


def decode_positions(payload: str | None) -> list[str]:
    if not payload:
        return []
    names: list[str] = []
    seen: set[str] = set()
    for code in payload.split("+"):
        name = CODE_TO_POSITION.get(code)
        if name is None or name in seen:
            continue
        seen.add(name)
        names.append(name)
        if len(names) == MAX_POSITIONS:
            break
    return names


def toggle_position(selected: list[str], position: str) -> list[str]:
    if position not in POSITION_CODES:
        return selected[:]
    if position in selected:
        return [item for item in selected if item != position]
    if len(selected) >= MAX_POSITIONS:
        return selected[:]
    return [*selected, position]


def positions_to_json(positions: list[str] | tuple[str, ...]) -> str:
    return json.dumps(decode_positions(encode_positions(list(positions))), ensure_ascii=False)


def positions_from_storage(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return tuple(decode_positions(encode_positions([str(item) for item in parsed])))
    except json.JSONDecodeError:
        pass
    if raw in POSITION_CODES:
        return (raw,)
    return tuple(decode_positions(raw))
