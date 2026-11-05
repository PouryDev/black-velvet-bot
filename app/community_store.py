from __future__ import annotations

import json
import time
from typing import Any

from app.db import Database

DAY = 86400
WEEK = 7 * DAY

SCHEMA = """
CREATE TABLE IF NOT EXISTS members (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    first_name TEXT,
    status TEXT NOT NULL,
    tracked_since REAL NOT NULL,
    last_seen REAL,
    safe_seen REAL,
    warnings INTEGER NOT NULL DEFAULT 0,
    inactivity_stage INTEGER NOT NULL DEFAULT 0,
    recovery_since REAL
);
CREATE TABLE IF NOT EXISTS member_profiles (
    user_id INTEGER PRIMARY KEY,
    data TEXT NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS forms (
    user_id INTEGER PRIMARY KEY,
    nonce TEXT NOT NULL,
    purpose TEXT NOT NULL,
    step INTEGER NOT NULL,
    data TEXT NOT NULL,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    data TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at REAL NOT NULL,
    decided_by INTEGER,
    decided_at REAL
);
CREATE UNIQUE INDEX IF NOT EXISTS one_pending_application
    ON applications(user_id) WHERE status = 'pending';
CREATE TABLE IF NOT EXISTS bot_admins (
    user_id INTEGER PRIMARY KEY,
    added_by INTEGER NOT NULL,
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS admission_access (
    application_id INTEGER PRIMARY KEY,
    invite_link TEXT,
    joined_at REAL
);
CREATE TABLE IF NOT EXISTS admission_join_requests (
    user_id INTEGER PRIMARY KEY,
    requested_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS private_searches (
    user_id INTEGER PRIMARY KEY,
    nonce TEXT NOT NULL,
    gender TEXT,
    positions TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS private_queue (
    user_id INTEGER PRIMARY KEY,
    wanted_gender TEXT NOT NULL,
    wanted_positions TEXT NOT NULL,
    queued_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS role_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_a INTEGER NOT NULL,
    user_b INTEGER NOT NULL,
    next_user INTEGER NOT NULL,
    sequence INTEGER NOT NULL DEFAULT 0,
    pending INTEGER NOT NULL DEFAULT 0,
    last_message_id INTEGER,
    status TEXT NOT NULL DEFAULT 'active',
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS active_sessions ON role_sessions(status, user_a, user_b);
CREATE TABLE IF NOT EXISTS daily_reports (
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    report_day TEXT NOT NULL,
    report_message_id INTEGER NOT NULL,
    target_message_id INTEGER NOT NULL,
    PRIMARY KEY(chat_id, user_id)
);
CREATE TABLE IF NOT EXISTS outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dedupe_key TEXT NOT NULL UNIQUE,
    method TEXT NOT NULL,
    payload TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt REAL NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS pending_outbox ON outbox(status, next_attempt, id);
CREATE TABLE IF NOT EXISTS inbox (
    update_id INTEGER PRIMARY KEY,
    lane TEXT NOT NULL DEFAULT 'unknown',
    payload TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt REAL NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
);
"""


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


class CommunityStore:
    """Use the existing SQLite connection. Runtime.lock owns transaction boundaries."""

    def __init__(self, db: Database):
        self.db = db

    async def init(self) -> None:
        await self.db.raw.executescript(SCHEMA)
        columns = {row["name"] for row in await self.all("PRAGMA table_info(inbox)")}
        if "lane" not in columns:
            await self.execute("ALTER TABLE inbox ADD COLUMN lane TEXT NOT NULL DEFAULT 'unknown'")
        await self.execute("CREATE INDEX IF NOT EXISTS inbox_lanes ON inbox(lane,status,update_id)")
        await self.db.raw.commit()

    async def one(self, sql: str, args: tuple = ()):
        async with self.db.raw.execute(sql, args) as cursor:
            return await cursor.fetchone()

    async def all(self, sql: str, args: tuple = ()):
        async with self.db.raw.execute(sql, args) as cursor:
            return await cursor.fetchall()

    async def execute(self, sql: str, args: tuple = ()):
        return await self.db.raw.execute(sql, args)

    async def emit(self, key: str, method: str, **payload) -> None:
        await self.execute(
            "INSERT OR IGNORE INTO outbox(dedupe_key,method,payload,created_at) VALUES(?,?,?,?)",
            (key, method, dumps(payload), time.time()),
        )

    async def profile(self, user_id: int) -> dict | None:
        row = await self.one("SELECT data FROM member_profiles WHERE user_id=?", (user_id,))
        return json.loads(row["data"]) if row else None

    async def claim_report(self, chat_id: int, user_id: int, report_day: str,
                           report_message_id: int, target_message_id: int) -> bool:
        cursor = await self.execute(
            """INSERT INTO daily_reports(chat_id,user_id,report_day,report_message_id,target_message_id)
               VALUES(?,?,?,?,?) ON CONFLICT(chat_id,user_id) DO UPDATE SET
               report_day=excluded.report_day,report_message_id=excluded.report_message_id,
               target_message_id=excluded.target_message_id
               WHERE daily_reports.report_day < excluded.report_day""",
            (chat_id, user_id, report_day, report_message_id, target_message_id),
        )
        return cursor.rowcount == 1

    async def session(self, user_id: int):
        return await self.one(
            "SELECT * FROM role_sessions WHERE status='active' AND (user_a=? OR user_b=?)",
            (user_id, user_id),
        )
