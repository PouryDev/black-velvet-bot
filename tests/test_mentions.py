from app.mentions import mention


def test_mention_always_tags_by_user_id() -> None:
    assert mention(1, "foo", "Bar") == '<a href="tg://user?id=1">Bar</a>'


def test_id_mention_is_html() -> None:
    assert mention(42, None, "Ali") == '<a href="tg://user?id=42">Ali</a>'
