from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "123456:TESTTOKEN")
    monkeypatch.setenv("ALLOWED_GROUP_ID", "-1001")
    monkeypatch.setenv("WEBHOOK_URL", "https://example.com/webhook")
    monkeypatch.setenv("WEBHOOK_SECRET", "s3cret")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "bot.db"))
    monkeypatch.setenv(
        "TELEGRAM_API_BASE",
        "https://snowy-tree-5c79.pk74ever.workers.dev",
    )

    with (
        patch("telegram.ext.Application.initialize", new_callable=AsyncMock),
        patch("telegram.ext.Application.start", new_callable=AsyncMock),
        patch("telegram.ext.Application.stop", new_callable=AsyncMock),
        patch("telegram.ext.Application.shutdown", new_callable=AsyncMock),
        patch("telegram.Bot.set_webhook", new_callable=AsyncMock),
        patch("telegram.ext.Application.process_update", new_callable=AsyncMock),
    ):
        from app.main import create_app

        with TestClient(create_app()) as test_client:
            yield test_client


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_webhook_rejects_bad_secret(client: TestClient) -> None:
    response = client.post("/webhook", json={"update_id": 1})
    assert response.status_code == 403


def test_webhook_accepts_secret(client: TestClient) -> None:
    response = client.post(
        "/webhook",
        json={"update_id": 1},
        headers={"X-Telegram-Bot-Api-Secret-Token": "s3cret"},
    )
    assert response.status_code == 204
