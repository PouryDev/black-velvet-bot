"""Run with docker run -i --network none ... python - < tests/container_smoke.py.

Uses a loopback fake Telegram API. Never contacts Telegram or sends real messages.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs

from fastapi.testclient import TestClient

os.environ.update(BOT_TOKEN="123:container-test-token", WEBHOOK_SECRET="container-test-secret-123456",
                  TELEGRAM_API_BASE="http://127.0.0.1:8123")
received = []
photos = []
approved = []
invites = []


class TelegramStub(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        method = self.path.rsplit("/", 1)[-1]
        parameters = {key: values[0] for key, values in parse_qs(body.decode()).items()}
        bot_user = {"id": 999, "first_name": "Test bot", "is_bot": True, "username": "TestBot"}
        if method == "getMe":
            result = bot_user
        elif method == "getChatMember":
            user_id = int(parameters["user_id"])
            result = {"status": "member" if user_id in approved or int(parameters["chat_id"]) == -1004357571815 else "left",
                      "user": {"id": user_id, "is_bot": False, "first_name": "Member"}}
        elif method == "getChat":
            result = {"id": int(parameters["chat_id"]), "type": "private", "first_name": "Member", "username": "member_one",
                      "accent_color_id": 1, "max_reaction_count": 1}
        elif method == "createChatInviteLink":
            invites.append(parameters)
            result = {"invite_link": "https://t.me/+smoke-link", "creator": bot_user,
                      "creates_join_request": True, "is_primary": False, "is_revoked": False}
        elif method == "approveChatJoinRequest":
            approved.append(int(parameters["user_id"]))
            result = True
        elif method in {"sendMessage", "sendPhoto", "editMessageCaption"}:
            if method == "sendMessage":
                received.append(parameters)
            elif method == "sendPhoto":
                photos.append(parameters)
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

    def post(update):
        assert client.post("/webhook", headers={"X-Telegram-Bot-Api-Secret-Token": os.environ["WEBHOOK_SECRET"]},
                           json=update).status_code == 200

    def wait_for(predicate):
        for _ in range(150):
            if predicate():
                return
            time.sleep(0.1)
        raise AssertionError("Timed out waiting for Telegram delivery")

    post({"update_id": 10, "message": {
        "message_id": 10, "date": int(time.time()), "from": {"id": settings.owner_user_id, "first_name": "Owner", "is_bot": False},
        "chat": {"id": settings.admin_group_id, "type": "supergroup"}, "text": "/addadmin 903",
    }})
    wait_for(lambda: len(received) == 5)
    with sqlite3.connect(settings.db_path) as db:
        assert db.execute("SELECT user_id FROM bot_admins").fetchone()[0] == 903
        profile = dict(name="Member", age=24, gender="male", orientation="straight", position="top", interest="One line",
                       limits="One line", status="single", photo="photo-file-id", username="member_one", first_name="Member")
        request_id = db.execute("INSERT INTO applications(user_id,data,created_at) VALUES(?,?,?)",
                                (101, json.dumps(profile), time.time())).lastrowid
    post({"update_id": 11, "callback_query": {
        "id": "accept-smoke", "chat_instance": "smoke", "data": f"admission:{request_id}:accept",
        "from": {"id": 903, "first_name": "Granted admin", "is_bot": False},
        "message": {"message_id": 50, "date": int(time.time()), "chat": {"id": settings.admin_group_id, "type": "supergroup"}},
    }})
    wait_for(lambda: any("https://t.me/+smoke-link" in item.get("text", "") for item in received))
    assert len(photos) == 1 and int(photos[0]["chat_id"]) == 101
    assert photos[0]["show_caption_above_media"] == "true"
    assert len(invites) == 1 and invites[0]["creates_join_request"] == "true"
    post({"update_id": 12, "chat_join_request": {
        "chat": {"id": settings.allowed_group_id, "type": "supergroup"}, "user_chat_id": 101,
        "from": {"id": 101, "first_name": "Member", "is_bot": False}, "date": int(time.time()),
    }})
    wait_for(lambda: any("tg://user?id=101" in item.get("text", "") and "خوش اومدی🖤" in item.get("text", "") for item in received))
    assert approved == [101]
server.shutdown()
print("Smoke passed: startup, health, webhook auth, reports, daily limit, bot admin grant, acceptance, profile, invite, autoapproval, welcome, shutdown")
