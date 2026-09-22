from __future__ import annotations

from pathlib import Path

import pytest

from app import texts
from app.db import Database


@pytest.mark.asyncio
async def test_two_way_match_and_dequeue(tmp_path: Path) -> None:
    db = Database(str(tmp_path / "bot.db"))
    await db.init()
    await db.upsert_user(user_id=1, username="top_guy", first_name="A", gender="male", position="top")
    await db.upsert_user(user_id=2, username="btm_guy", first_name="B", gender="male", position="bottom")

    waiting = await db.match_or_enqueue(
        user_id=1,
        gender="male",
        position="top",
        wanted_gender="male",
        wanted_positions=["bottom", "vers_bottom"],
    )
    assert waiting is None

    partner = await db.match_or_enqueue(
        user_id=2,
        gender="male",
        position="bottom",
        wanted_gender="male",
        wanted_positions=["top", "vers"],
    )
    assert partner is not None
    assert partner.user_id == 1

    leftover = await db.raw.execute("SELECT COUNT(*) AS c FROM queue")
    row = await leftover.fetchone()
    assert row["c"] == 0
    await db.close()


@pytest.mark.asyncio
async def test_no_match_when_wanted_position_differs(tmp_path: Path) -> None:
    db = Database(str(tmp_path / "bot.db"))
    await db.init()
    await db.upsert_user(user_id=1, username="a", first_name="A", gender="female", position="top")
    await db.upsert_user(user_id=2, username="b", first_name="B", gender="female", position="bottom")
    await db.match_or_enqueue(
        user_id=1,
        gender="female",
        position="top",
        wanted_gender="female",
        wanted_positions=["vers"],
    )
    partner = await db.match_or_enqueue(
        user_id=2,
        gender="female",
        position="bottom",
        wanted_gender="female",
        wanted_positions=["top"],
    )
    assert partner is None
    leftover = await db.raw.execute("SELECT COUNT(*) AS c FROM queue")
    row = await leftover.fetchone()
    assert row["c"] == 2
    await db.close()


@pytest.mark.asyncio
async def test_fifo_picks_first_compatible(tmp_path: Path) -> None:
    db = Database(str(tmp_path / "bot.db"))
    await db.init()
    await db.upsert_user(user_id=10, username="first", first_name="F", gender="trans", position="vers")
    await db.upsert_user(user_id=11, username="second", first_name="S", gender="trans", position="vers")
    await db.upsert_user(user_id=12, username="seeker", first_name="K", gender="male", position="top")
    await db.match_or_enqueue(
        user_id=10,
        gender="trans",
        position="vers",
        wanted_gender="male",
        wanted_positions=["top"],
    )
    await db.match_or_enqueue(
        user_id=11,
        gender="trans",
        position="vers",
        wanted_gender="male",
        wanted_positions=["top"],
    )
    partner = await db.match_or_enqueue(
        user_id=12,
        gender="male",
        position="top",
        wanted_gender="trans",
        wanted_positions=["vers", "vers_bottom"],
    )
    assert partner is not None
    assert partner.user_id == 10
    leftover = await db.raw.execute("SELECT user_id FROM queue ORDER BY queued_at")
    rows = await leftover.fetchall()
    assert [r["user_id"] for r in rows] == [11]
    await db.close()


@pytest.mark.asyncio
async def test_match_uses_any_of_three_positions(tmp_path: Path) -> None:
    db = Database(str(tmp_path / "bot.db"))
    await db.init()
    await db.upsert_user(user_id=1, username="a", first_name="A", gender="male", position="vers_bottom")
    await db.upsert_user(user_id=2, username="b", first_name="B", gender="male", position="top")
    await db.match_or_enqueue(
        user_id=1,
        gender="male",
        position="vers_bottom",
        wanted_gender="male",
        wanted_positions=["top", "bottom"],
    )
    partner = await db.match_or_enqueue(
        user_id=2,
        gender="male",
        position="top",
        wanted_gender="male",
        wanted_positions=["vers", "vers_bottom", "bottom"],
    )
    assert partner is not None
    assert partner.user_id == 1
    await db.close()


def test_twenty_match_lines() -> None:
    assert len(texts.MATCH_LINES) == 20
    assert len(set(texts.MATCH_LINES)) == 20
    for line in texts.MATCH_LINES:
        rendered = texts.match_caption("@one", "@two", line)
        assert "@one" in rendered and "@two" in rendered
        assert "fuck" in rendered.lower()
