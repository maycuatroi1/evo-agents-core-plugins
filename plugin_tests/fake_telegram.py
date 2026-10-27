"""A fake Telegram Bot API for the hub's tests: what the hub's bot calls, recorded, and answered as Telegram would.

The Python tests put ``transport()`` in ``evo_core_plugins.telegram.server.TRANSPORT``; evo-agents' Playwright
stack serves its copy of this fake over HTTP (``serve``) and points EVO_HUB_TELEGRAM_API_URL at it. ``fail_next`` makes
the next call of a method (sendMessage unless it names another) answer an error, such as Telegram's 429 with
retry_after or the 403 of a blocked bot. A call that uploads files (sendPhoto, sendDocument, sendMediaGroup) comes as
multipart/form-data: its payload holds its fields, and ``files`` what it uploaded under each field, by name, type and
bytes. Nothing here reaches Telegram.

For the bridge of a group: ``files`` holds what getFile and the download of a file (GET /file/bot<token>/<path>)
give, by file_id; ``admins`` the users getChatMember says are admins of a group; ``group_chat``, ``photo_update`` and
``bot_left`` build a group's updates, and ``fail_next`` with ``migrate_to`` answers the 400 of a group that became a
supergroup.

The bot token and the webhook secret are built from pieces, so no scanner reads them as real ones.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from email.parser import BytesParser
from email.policy import HTTP
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BOT = "evo_test_bot"
TOKEN = "".join(("1234567", "89:", "AAfake", "-test-", "token", "-for-the-hub"))  # <bot id>:<secret>, a fake
SECRET = "".join(("webhook", "-secret-", "for-tests"))
SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"
MEDIA_METHODS = ("sendPhoto", "sendDocument", "sendMediaGroup")
JSON_FIELDS = frozenset({"chat_id", "media", "reply_markup", "reply_parameters", "link_preview_options"})


def payload_of(content_type: str | None, body: bytes) -> dict:
    """A call's payload: its JSON, or the fields of its multipart/form-data with ``files`` of what it uploaded."""
    if not (content_type or "").startswith("multipart/form-data"):
        try:
            return json.loads(body or b"{}")
        except ValueError:
            return {}
    form = BytesParser(policy=HTTP).parsebytes(f"Content-Type: {content_type}\r\n\r\n".encode() + body)
    payload: dict = {"files": {}}
    for part in form.iter_parts():
        name = part.get_param("name", header="content-disposition")
        content = part.get_payload(decode=True) or b""
        if part.get_filename() is not None:
            payload["files"][name] = {"name": part.get_filename(), "type": part.get_content_type(), "content": content}
        else:
            text = content.decode()
            payload[name] = json.loads(text) if name in JSON_FIELDS else text
    return payload


@dataclass
class FakeTelegram:
    calls: list = field(default_factory=list)  # (method, payload), in order
    failures: list = field(default_factory=list)  # (method, status, body) the next calls of a method answer, in turn
    webhook: dict = field(default_factory=lambda: {"url": "", "pending_update_count": 0})
    message_id: int = 1000
    token: str = TOKEN
    files: dict = field(default_factory=dict)  # file_id: bytes, what a group's message carries
    admins: set = field(default_factory=set)  # (chat id, user id) of a group's admins
    lock: threading.Lock = field(default_factory=threading.Lock)

    def download(self, path: str) -> tuple[int, bytes]:
        """GET /file/bot<token>/<path>: the bytes getFile pointed at."""
        prefix = f"/file/bot{self.token}/files/"
        with self.lock:
            self.calls.append(("download", {"path": path}))
            found = self.files.get(path[len(prefix) :]) if path.startswith(prefix) else None
        return (200, found) if found is not None else (404, b"Not Found")

    def answer(self, path: str, payload: dict) -> tuple[int, dict]:
        prefix = f"/bot{self.token}/"
        if not path.startswith(prefix):
            return 404, {"ok": False, "error_code": 404, "description": "Not Found"}
        method = path[len(prefix) :]
        with self.lock:
            self.calls.append((method, payload))
            if method == "getMe":
                return 200, ok({"id": 123456789, "is_bot": True, "first_name": "evo hub", "username": BOT})
            failed = next((index for index, failure in enumerate(self.failures) if failure[0] == method), None)
            if failed is not None:
                return self.failures.pop(failed)[1:]
            if method in ("sendMessage", "sendPhoto", "sendDocument"):
                self.message_id += 1
                payload["message_id"] = self.message_id  # what the test presses a button of, or replies to
                return 200, ok({"message_id": self.message_id, "chat": {"id": payload.get("chat_id")}})
            if method == "sendMediaGroup":
                sent = []
                for _ in payload.get("media") or []:
                    self.message_id += 1
                    sent.append({"message_id": self.message_id, "chat": {"id": payload.get("chat_id")}})
                payload["message_ids"] = [message["message_id"] for message in sent]
                return 200, ok(sent)
            if method in ("answerCallbackQuery", "editMessageText", "setMessageReaction"):
                return 200, ok(True)
            if method == "getFile":
                found = self.files.get(payload.get("file_id"))
                if found is None:
                    return 400, {"ok": False, "error_code": 400, "description": "Bad Request: invalid file_id"}
                file_id = payload["file_id"]
                return 200, ok({"file_id": file_id, "file_size": len(found), "file_path": f"files/{file_id}"})
            if method == "getChatMember":
                admin = (payload.get("chat_id"), payload.get("user_id")) in self.admins
                user = {"id": payload.get("user_id"), "is_bot": False, "first_name": "Someone"}
                return 200, ok({"status": "administrator" if admin else "member", "user": user})
            if method == "getWebhookInfo":
                return 200, ok(dict(self.webhook))
            if method == "setWebhook":
                self.webhook = {"url": payload.get("url", ""), "pending_update_count": 0}
                return 200, ok(True)
        return 404, {"ok": False, "error_code": 404, "description": "Not Found: method not found"}

    def transport(self):
        import httpx

        def handle(request: httpx.Request) -> httpx.Response:
            if request.method == "GET" and request.url.path.startswith("/file/"):
                status, content = self.download(request.url.path)
                return httpx.Response(status, content=content)
            payload = payload_of(request.headers.get("content-type"), request.content)
            status, body = self.answer(request.url.path, payload)
            return httpx.Response(status, json=body)

        return httpx.MockTransport(handle)

    def fail_next(
        self,
        status: int,
        description: str,
        retry_after: int | None = None,
        method: str = "sendMessage",
        migrate_to: int | None = None,
    ) -> None:
        body = {"ok": False, "error_code": status, "description": description}
        if retry_after is not None:
            body["parameters"] = {"retry_after": retry_after}
        if migrate_to is not None:
            body["parameters"] = {"migrate_to_chat_id": migrate_to}
        self.failures.append((method, status, body))

    def sent(self, method: str = "sendMessage") -> list[dict]:
        with self.lock:
            return [payload for name, payload in self.calls if name == method]

    def media(self) -> list[tuple[str, dict]]:
        """The calls that uploaded files, (method, payload) in order."""
        with self.lock:
            return [(name, payload) for name, payload in self.calls if name in MEDIA_METHODS]

    def serve(self, port: int = 0) -> ThreadingHTTPServer:
        """This fake over HTTP on 127.0.0.1:``port`` (a free one by default), in a thread; shut it down when done."""
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # the name http.server calls
                length = int(self.headers.get("content-length") or 0)
                payload = payload_of(self.headers.get("content-type"), self.rfile.read(length))
                status, body = fake.answer(self.path, payload)
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, format, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return server


def ok(result) -> dict:
    return {"ok": True, "result": result}


def private_chat(chat_id: int, username: str | None = "owner_tg") -> tuple[dict, dict]:
    """(chat, from) of a member's private chat with the bot: in Telegram they share the id."""
    sender = {"id": chat_id, "is_bot": False, "first_name": "Owner"}
    if username:
        sender["username"] = username
    return {"id": chat_id, "type": "private"}, sender


def text_update(update_id: int, chat: dict, sender: dict, text: str, *, reply_to: int | None = None) -> dict:
    message = {"message_id": update_id + 50_000, "date": 1_760_000_000, "chat": chat, "from": sender, "text": text}
    if reply_to is not None:
        message["reply_to_message"] = {"message_id": reply_to, "chat": chat, "date": 1_760_000_000, "text": "..."}
    return {"update_id": update_id, "message": message}


def button_update(update_id: int, chat: dict, sender: dict, data: str, message: dict) -> dict:
    """A press of the button ``data`` under ``message``, a message the bot sent (as sendMessage took it)."""
    shown = {
        "message_id": message["message_id"],
        "date": 1_760_000_000,
        "chat": chat,
        "text": message.get("text", ""),
        "reply_markup": message.get("reply_markup"),
    }
    return {
        "update_id": update_id,
        "callback_query": {
            "id": f"cb{update_id}",
            "from": sender,
            "chat_instance": "1",
            "data": data,
            "message": shown,
        },
    }


def group_chat(chat_id: int, kind: str = "supergroup") -> dict:
    """A group the bot is a member of: a group, or a supergroup, whose id starts -100."""
    return {"id": chat_id, "type": kind, "title": "Release team"}


def photo_update(update_id: int, chat: dict, sender: dict, file_id: str, size: int, caption: str = "") -> dict:
    """A photo sent to ``chat``, in the sizes Telegram gives, the largest last."""
    sizes = [
        {"file_id": f"{file_id}-small", "file_unique_id": "s", "width": 90, "height": 90, "file_size": 1000},
        {"file_id": file_id, "file_unique_id": "l", "width": 1280, "height": 960, "file_size": size},
    ]
    message = {"message_id": update_id + 50_000, "date": 1_760_000_000, "chat": chat, "from": sender, "photo": sizes}
    if caption:
        message["caption"] = caption
    return {"update_id": update_id, "message": message}


def bot_left(update_id: int, chat: dict, status: str = "kicked") -> dict:
    """The bot's membership of ``chat`` changed to ``status`` (my_chat_member)."""
    bot = {"id": 123456789, "is_bot": True, "first_name": "evo hub", "username": BOT}
    return {
        "update_id": update_id,
        "my_chat_member": {
            "chat": chat,
            "from": {"id": 9, "is_bot": False, "first_name": "Admin"},
            "date": 1_760_000_000,
            "old_chat_member": {"user": bot, "status": "member"},
            "new_chat_member": {"user": bot, "status": status},
        },
    }
