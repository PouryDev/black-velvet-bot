from __future__ import annotations

from dataclasses import replace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.config import load_settings


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.main.load_settings",
        lambda: replace(load_settings(), db_path=str(tmp_path / "bot.db")),
    )

    with (
        patch("telegram.ext.Application.initialize", new_callable=AsyncMock),
        patch("telegram.ext.Application.start", new_callable=AsyncMock),
        patch("telegram.ext.Application.stop", new_callable=AsyncMock),
        patch("telegram.ext.Application.shutdown", new_callable=AsyncMock),
        patch("telegram.ext.Application.process_update", new_callable=AsyncMock),
    ):
        from app.main import create_app

        with TestClient(create_app()) as test_client:
            yield test_client


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_webhook_without_secret_header_is_200(client: TestClient) -> None:
    response = client.post("/webhook", json={"update_id": 1})
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_webhook_invalid_body_still_200(client: TestClient) -> None:
    response = client.post(
        "/webhook",
        content=b"not-json",
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 200
    assert response.json() == {"ok": True}
