"""Run with docker run -i --network none ... python - < tests/container_smoke.py.

Uses a loopback fake Telegram API. Never contacts Telegram or sends real messages.
"""
from __future__ import annotations

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs

from fastapi.testclient import TestClient

os.environ.update(BOT_TOKEN="123:container-test-token", WEBHOOK_SECRET="container-test-secret-123456",
                  TELEGRAM_API_BASE="http://127.0.0.1:8123")
received = []


class TelegramStub(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        method = self.path.rsplit("/", 1)[-1]
        if method == "getMe":
            result = {"id": 999, "first_name": "Test bot", "is_bot": True, "username": "TestBot"}
        elif method == "getChatMember":
            result = {"status": "left", "user": {"id": 101, "is_bot": False, "first_name": "Member"}}
        elif method == "sendMessage":
            parameters = {key: values[0] for key, values in parse_qs(body.decode()).items()}
            received.append(parameters)
            chat_id = int(parameters["chat_id"])
            result = {"message_id": len(received), "date": int(time.time()),
                      "chat": {"id": chat_id, "type": "private" if chat_id > 0 else "supergroup"}, "text": "ok"}
        else:
            result = True
        encoded = json.dumps({"ok": True, "result": result}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, *_):
        pass


server = HTTPServer(("127.0.0.1", 8123), TelegramStub)
threading.Thread(target=server.serve_forever, daemon=True).start()
from app.main import create_app

with TestClient(create_app()) as client:
    assert client.get("/health").json() == {"ok": True}
    assert client.post("/webhook", json={"update_id": 1}).status_code == 403
    result = client.post("/webhook", headers={"X-Telegram-Bot-Api-Secret-Token": os.environ["WEBHOOK_SECRET"]}, json={
        "update_id": 1, "message": {"message_id": 1, "date": int(time.time()),
                                   "from": {"id": 101, "is_bot": False, "first_name": "Member"},
                                   "chat": {"id": 101, "type": "private"}, "text": "/start"},
    })
    assert result.status_code == 200
    for _ in range(40):
        if received:
            break
        time.sleep(0.1)
    assert len(received) == 1
    settings = client.app.state.community.settings
    report_date = int(time.time())
    for command_id in (2, 3):
        result = client.post("/webhook", headers={"X-Telegram-Bot-Api-Secret-Token": os.environ["WEBHOOK_SECRET"]}, json={
            "update_id": command_id, "message": {
                "message_id": command_id, "date": report_date,
                "from": {"id": 101, "is_bot": False, "first_name": "Reporter"},
                "chat": {"id": settings.allowed_group_id, "type": "supergroup"}, "text": "/report",
                "reply_to_message": {"message_id": 42, "date": int(time.time()),
                                     "chat": {"id": settings.allowed_group_id, "type": "supergroup"},
                                     "from": {"id": 202, "is_bot": False, "first_name": "Target"}, "text": "Reported message"},
            },
        })
        assert result.status_code == 200
        for _ in range(60):
            if len(received) >= command_id + 1:
                break
            time.sleep(0.1)
    assert len(received) == 4
    reports = [item for item in received if int(item["chat_id"]) == settings.admin_group_id]
    assert len(reports) == 1
    assert "گزارش جدید" in reports[0]["text"]
    assert json.loads(reports[0]["reply_markup"])["inline_keyboard"][0][0]["url"].endswith("/42")
    assert json.loads(received[2]["reply_parameters"])["message_id"] == 2
    assert "سهمیه" in received[3]["text"]
server.shutdown()
print("Smoke passed: startup, health, webhook auth, inbox/outbox, reports, daily limit, graceful shutdown")
