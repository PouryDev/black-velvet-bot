from app.positions import MAX_POSITIONS, encode_positions, toggle_position


def test_toggle_adds_and_rejects_duplicates() -> None:
    selected: list[str] = []
    selected = toggle_position(selected, "top")
    selected = toggle_position(selected, "bottom")
    selected = toggle_position(selected, "top")
    assert selected == ["bottom"]


def test_toggle_caps_at_three() -> None:
    selected = ["top", "bottom", "vers"]
    assert toggle_position(selected, "vers_bottom") == selected
    assert len(selected) == MAX_POSITIONS


def test_encode_unique_order() -> None:
    assert encode_positions(["top", "top", "vers_bottom", "bottom"]) == "t+vb+b"
