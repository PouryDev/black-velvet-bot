from __future__ import annotations

import pytest

from app.community_store import CommunityStore
from app.db import Database


@pytest.mark.asyncio
async def test_adding_community_tables_keeps_existing_profiles_and_public_queue(tmp_path):
    path = str(tmp_path / "bot.db")
    original = Database(path)
    await original.init()
    await original.upsert_user(user_id=101, username="member_101", first_name="Member",
                               gender="male", positions=["top", "vers"])
    await original.enqueue(user_id=101, wanted_gender="female", wanted_positions=["bottom"])
    await original.close()
    migrated = Database(path)
    await migrated.init()
    store = CommunityStore(migrated)
    try:
        await store.init()
        await store.init()  # repeatable on every container start
        assert (await migrated.get_user(101)).positions == ("top", "vers")
        assert await migrated.is_in_queue(101)
        assert (await store.one("PRAGMA integrity_check"))[0] == "ok"
    finally:
        await migrated.close()


@pytest.mark.asyncio
async def test_inbox_lane_migration_preserves_pending_work(tmp_path):
    db = Database(str(tmp_path / "bot.db"))
    await db.init()
    await db.raw.execute("""CREATE TABLE inbox(update_id INTEGER PRIMARY KEY,payload TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
        next_attempt REAL NOT NULL DEFAULT 0,created_at REAL NOT NULL)""")
    await db.raw.execute("INSERT INTO inbox(update_id,payload,created_at) VALUES(1,'{}',0)")
    await db.raw.commit()
    try:
        store = CommunityStore(db)
        await store.init()
        row = await store.one("SELECT * FROM inbox WHERE update_id=1")
        assert row["lane"] == "unknown"
        assert row["status"] == "pending"
    finally:
        await db.close()
