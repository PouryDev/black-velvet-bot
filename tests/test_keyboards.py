from app.keyboards import fuck_position_keyboard, gender_keyboard, position_keyboard


def test_callback_data_stays_under_telegram_limit() -> None:
    user_id = 999999999999
    for prefix in ("reg", "fuck"):
        for row in gender_keyboard(prefix, user_id).inline_keyboard:
            for button in row:
                assert button.callback_data
                assert len(button.callback_data.encode()) <= 64
        for row in position_keyboard(prefix, user_id, "female").inline_keyboard:
            for button in row:
                assert button.callback_data
                assert len(button.callback_data.encode()) <= 64
    selected = ["top", "bottom", "vers_bottom"]
    for row in fuck_position_keyboard(user_id, "female", selected).inline_keyboard:
        for button in row:
            assert button.callback_data
            assert len(button.callback_data.encode()) <= 64
