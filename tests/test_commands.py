from app.commands import command_filter, parse_command


def test_plain_command() -> None:
    assert parse_command("/register") == ("register", None)


def test_command_with_bot_username() -> None:
    assert parse_command("/register@BlackVelvetDatingBot") == (
        "register",
        "BlackVelvetDatingBot",
    )


def test_command_with_args() -> None:
    assert parse_command("/fuck@BlackVelvetDatingBot extra") == (
        "fuck",
        "BlackVelvetDatingBot",
    )


def test_non_command() -> None:
    assert parse_command("!ping") is None


def test_command_filter_accepts_bot_mention() -> None:
    pattern = command_filter("register").pattern
    assert pattern.search("/register")
    assert pattern.search("/register@BlackVelvetDatingBot")
    assert not pattern.search("please /register later")
