from __future__ import annotations

import sqlite3
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.config import Settings

SECRET = "test-secret-123456"
HEADERS = {"X-Telegram-Bot-Api-Secret-Token": SECRET}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr("app.main.load_settings", lambda: Settings(
        bot_token="123:test-token", webhook_secret=SECRET, db_path=str(tmp_path / "bot.db"),
    ))
    with (
        patch("telegram.ext.Application.initialize", new_callable=AsyncMock),
        patch("telegram.ext.Application.start", new_callable=AsyncMock),
        patch("telegram.ext.Application.stop", new_callable=AsyncMock),
        patch("telegram.ext.Application.shutdown", new_callable=AsyncMock),
        patch("app.delivery.Delivery.start"),
    ):
        from app.main import create_app
        with TestClient(create_app()) as test_client:
            yield test_client


def test_health(client: TestClient) -> None:
    assert client.get("/health").json() == {"ok": True}


def test_webhook_without_secret_is_rejected(client: TestClient) -> None:
    assert client.post("/webhook", json={"update_id": 1}).status_code == 403
    assert client.post("/webhook", json={"update_id": 1}, headers={
        "X-Telegram-Bot-Api-Secret-Token": "wrong-secret",
    }).status_code == 403


@pytest.mark.parametrize("body", [b"not-json", b"[]", b'{}', b'{"update_id":true}'])
def test_webhook_invalid_body(client: TestClient, body) -> None:
    assert client.post("/webhook", content=body, headers=HEADERS).status_code == 400


def test_webhook_deduplicates_and_persists_before_ack(client: TestClient) -> None:
    for _ in range(2):
        assert client.post("/webhook", json={"update_id": 1}, headers=HEADERS).status_code == 200
    with sqlite3.connect(client.app.state.community.settings.db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM inbox").fetchone()[0] == 1
        assert db.execute("SELECT status FROM inbox").fetchone()[0] == "pending"


def test_plain_group_activity_does_not_store_messages_or_write_per_message(client: TestClient) -> None:
    c = client.app.state.community
    payload = {"update_id": 10, "message": {
        "message_id": 1, "date": 1700000000, "chat": {"id": c.settings.allowed_group_id, "type": "supergroup"},
        "from": {"id": 42, "first_name": "A", "is_bot": False}, "text": "ordinary group message",
    }}
    assert client.post("/webhook", json=payload, headers=HEADERS).status_code == 200
    changes = c.db.raw.total_changes
    payload["message"]["date"] += 10
    payload["update_id"] += 1
    assert client.post("/webhook", json=payload, headers=HEADERS).status_code == 200
    assert c.db.raw.total_changes == changes
    with sqlite3.connect(c.settings.db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM inbox").fetchone()[0] == 0
        assert db.execute("SELECT user_id FROM members").fetchone()[0] == 42


def test_missing_secret_fails_startup(monkeypatch) -> None:
    from app.main import create_app
    monkeypatch.setattr("app.main.load_settings", lambda: Settings(bot_token="123:test-token"))
    with pytest.raises(ValueError, match="WEBHOOK_SECRET"):
        create_app()
