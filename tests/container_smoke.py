"""Run with docker run -i --network none ... python - < tests/container_smoke.py.

Uses a loopback fake Telegram API. Never contacts Telegram or sends real messages.
"""
from __future__ import annotations

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

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
            received.append(body)
            result = {"message_id": 1, "date": int(time.time()), "chat": {"id": 101, "type": "private"}, "text": "ok"}
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
server.shutdown()
print("Container smoke passed: startup, health, webhook auth, durable inbox, routing, outbox, graceful shutdown")
