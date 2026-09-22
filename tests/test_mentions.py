from __future__ import annotations

from app.mentions import mention


def test_username_mention() -> None:
    assert mention(1, "foo", "Bar") == "@foo"


def test_id_mention_is_html() -> None:
    assert mention(42, None, "Ali") == '<a href="tg://user?id=42">Ali</a>'
