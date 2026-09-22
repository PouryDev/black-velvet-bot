from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class Profile:
    user_id: int
    username: str | None
    first_name: str | None
    gender: str
    position: str


@dataclass(frozen=True)
class QueueEntry:
    user_id: int
    wanted_gender: str
    wanted_position: str
    queued_at: str
    username: str | None
    first_name: str | None
    gender: str
    position: str


class Database:
    def __init__(self, path: str) -> None:
        self._path = path
        self._db: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    @property
    def raw(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("Database is not initialized")
        return self._db

    async def init(self) -> None:
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA foreign_keys = ON")
        await self._db.execute("PRAGMA journal_mode = WAL")
        await self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                gender TEXT NOT NULL,
                position TEXT NOT NULL,
                registered_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS queue (
                user_id INTEGER PRIMARY KEY,
                wanted_gender TEXT NOT NULL,
                wanted_position TEXT NOT NULL,
                queued_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            );
            """
        )
        await self._db.commit()

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    async def get_user(self, user_id: int) -> Profile | None:
        cur = await self.raw.execute(
            "SELECT user_id, username, first_name, gender, position FROM users WHERE user_id = ?",
            (user_id,),
        )
        row = await cur.fetchone()
        if row is None:
            return None
        return Profile(
            user_id=row["user_id"],
            username=row["username"],
            first_name=row["first_name"],
            gender=row["gender"],
            position=row["position"],
        )

    async def is_registered(self, user_id: int) -> bool:
        return await self.get_user(user_id) is not None

    async def upsert_user(
        self,
        *,
        user_id: int,
        username: str | None,
        first_name: str | None,
        gender: str,
        position: str,
    ) -> None:
        await self.raw.execute(
            """
            INSERT INTO users (user_id, username, first_name, gender, position, registered_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username,
                first_name = excluded.first_name,
                gender = excluded.gender,
                position = excluded.position
            """,
            (user_id, username, first_name, gender, position, _utc_now()),
        )
        await self.raw.commit()

    async def touch_identity(self, user_id: int, username: str | None, first_name: str | None) -> None:
        await self.raw.execute(
            "UPDATE users SET username = ?, first_name = ? WHERE user_id = ?",
            (username, first_name, user_id),
        )
        await self.raw.commit()

    async def find_match(
        self,
        *,
        user_id: int,
        gender: str,
        position: str,
        wanted_gender: str,
        wanted_position: str,
    ) -> QueueEntry | None:
        cur = await self.raw.execute(
            """
            SELECT
                q.user_id,
                q.wanted_gender,
                q.wanted_position,
                q.queued_at,
                u.username,
                u.first_name,
                u.gender,
                u.position
            FROM queue AS q
            INNER JOIN users AS u ON u.user_id = q.user_id
            WHERE q.user_id != ?
              AND u.gender = ?
              AND u.position = ?
              AND q.wanted_gender = ?
              AND q.wanted_position = ?
            ORDER BY q.queued_at ASC
            LIMIT 1
            """,
            (user_id, wanted_gender, wanted_position, gender, position),
        )
        row = await cur.fetchone()
        if row is None:
            return None
        return QueueEntry(
            user_id=row["user_id"],
            wanted_gender=row["wanted_gender"],
            wanted_position=row["wanted_position"],
            queued_at=row["queued_at"],
            username=row["username"],
            first_name=row["first_name"],
            gender=row["gender"],
            position=row["position"],
        )

    async def enqueue(
        self,
        *,
        user_id: int,
        wanted_gender: str,
        wanted_position: str,
    ) -> None:
        await self.raw.execute(
            """
            INSERT INTO queue (user_id, wanted_gender, wanted_position, queued_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                wanted_gender = excluded.wanted_gender,
                wanted_position = excluded.wanted_position,
                queued_at = excluded.queued_at
            """,
            (user_id, wanted_gender, wanted_position, _utc_now()),
        )
        await self.raw.commit()

    async def dequeue_users(self, *user_ids: int) -> None:
        if not user_ids:
            return
        placeholders = ",".join("?" * len(user_ids))
        await self.raw.execute(f"DELETE FROM queue WHERE user_id IN ({placeholders})", user_ids)
        await self.raw.commit()

    async def match_or_enqueue(
        self,
        *,
        user_id: int,
        gender: str,
        position: str,
        wanted_gender: str,
        wanted_position: str,
    ) -> QueueEntry | None:
        async with self._lock:
            partner = await self.find_match(
                user_id=user_id,
                gender=gender,
                position=position,
                wanted_gender=wanted_gender,
                wanted_position=wanted_position,
            )
            if partner is not None:
                await self.dequeue_users(user_id, partner.user_id)
                return partner
            await self.enqueue(
                user_id=user_id,
                wanted_gender=wanted_gender,
                wanted_position=wanted_position,
            )
            return None
