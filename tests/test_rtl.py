from app.rtl import ensure_rtl


def test_keeps_persian_start() -> None:
    assert ensure_rtl("سلام خوبی") == "سلام خوبی"


def test_prefixes_english_and_mentions() -> None:
    text = ensure_rtl("@one و @two\nhello")
    lines = text.split("\n")
    assert lines[0].startswith("خب ")
    assert lines[1].startswith("خب ")
    assert "@one" in lines[0]
