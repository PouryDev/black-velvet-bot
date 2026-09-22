from app.positions import (
    MAX_PROFILE_POSITIONS,
    MAX_WANTED_POSITIONS,
    encode_positions,
    toggle_position,
)


def test_toggle_adds_and_rejects_duplicates() -> None:
    selected: list[str] = []
    selected = toggle_position(selected, "top", MAX_WANTED_POSITIONS)
    selected = toggle_position(selected, "bottom", MAX_WANTED_POSITIONS)
    selected = toggle_position(selected, "top", MAX_WANTED_POSITIONS)
    assert selected == ["bottom"]


def test_profile_caps_at_two() -> None:
    selected = ["top", "bottom"]
    assert toggle_position(selected, "vers_bottom", MAX_PROFILE_POSITIONS) == selected


def test_wanted_caps_at_three() -> None:
    selected = ["top", "bottom", "vers"]
    assert toggle_position(selected, "vers_bottom", MAX_WANTED_POSITIONS) == selected
    assert len(selected) == MAX_WANTED_POSITIONS


def test_encode_unique_order() -> None:
    assert encode_positions(["top", "top", "vers_bottom", "bottom"], max_count=3) == "t+vb+b"
