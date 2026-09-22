from __future__ import annotations

import html

from telegram import User

from app.db import Profile, QueueEntry


def mention_user(user: User) -> str:
    return mention(user.id, user.username, user.first_name)


def mention(user_id: int, username: str | None, first_name: str | None) -> str:
    if first_name:
        label = html.escape(first_name)
    elif username:
        label = html.escape("@" + username)
    else:
        label = str(user_id)
    return f'<a href="tg://user?id={user_id}">{label}</a>'


def mention_profile(profile: Profile) -> str:
    return mention(profile.user_id, profile.username, profile.first_name)


def mention_queue(entry: QueueEntry) -> str:
    return mention(entry.user_id, entry.username, entry.first_name)
