"""The files of a notification on the Telegram channel (``evo_core_plugins.telegram.server``, plan run-outputs: a4,
a6), the channel alone: notifications made here as the hub's prepare gives them, a fake Bot API and a fake store of
files. No database; ``test_telegram_outputs.py`` runs the same through a hub.

A notice of a run's files goes as one message or one group, its text the caption with the run's link; a decision's
files go first, each with its caption, and then its message with its buttons as a reply to them. The bytes come from
the presigned GET the hub gave, whose URL is never logged; a file that does not come is counted on the hub; Telegram
refusing photos sends them as documents, then the text alone; a 429, a blocked bot and a message that failed after its
files went keep the delivery's retry as it was. A restricted project's message, and a decision that no longer waits,
go without any file. The people, projects and files are fictional.
"""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest

from evo_agents.hub.server import core_plugin_api as hub
from evo_core_plugins.telegram import server as server_telegram
from plugin_tests.fake_telegram import SECRET, TOKEN, FakeTelegram

CHAT = 7001
PROJECT = "lumen"
SHOT = b"\x89PNG\r\n\x1a\n" + b"lumen settings page" * 20
CHART = b"\x89PNG\r\n\x1a\n" + b"lumen latency chart" * 20
REPORT = b"# Report\n\nThe flaky wait test passes now.\n"
STORE = "http://store.test"
RUN_URL = f"https://hub.test/p/{PROJECT}/runs/7"
OPTIONS = [{"key": "yes", "label": "Ship it"}, {"key": "no", "label": "Not yet"}]


@pytest.fixture
def bot(monkeypatch):
    """The fake Bot API in place of Telegram's, a fake store the files' URLs point at, the bot's variables, and the
    channel's pacing recorded instead of slept."""
    fake = FakeTelegram()
    monkeypatch.setenv(server_telegram.TOKEN_VARIABLE, TOKEN)
    monkeypatch.setenv(server_telegram.SECRET_VARIABLE, SECRET)
    monkeypatch.delenv(server_telegram.API_URL_VARIABLE, raising=False)
    monkeypatch.setattr(server_telegram, "TRANSPORT", fake.transport())
    store: dict[str, bytes] = {}
    fetched: list[str] = []

    def serve(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        fetched.append(url)
        if "unreachable" in url:
            raise httpx.ConnectError(f"cannot connect to {url}")
        return httpx.Response(200, content=store[url]) if url in store else httpx.Response(403)

    monkeypatch.setattr(server_telegram, "FETCH_TRANSPORT", httpx.MockTransport(serve))
    monkeypatch.setattr(server_telegram, "_FILES_SENT", OrderedDict())
    waits: list[float] = []

    async def pause(seconds: float) -> None:
        waits.append(seconds)

    monkeypatch.setattr(server_telegram, "pause", pause)
    return SimpleNamespace(fake=fake, store=store, fetched=fetched, waits=waits)


def stored(bot, file_id: int, name: str, data: bytes, media_type: str = "image/png", **changes) -> dict:
    """A file the fake store holds, as one of ``extra.outputs``: its url a presigned GET of it."""
    url = f"{STORE}/blobs/{file_id:064x}?X-Amz-Signature=sig{file_id}"
    bot.store[url] = data
    found = {"id": file_id, "name": name, "media_type": media_type, "viewer": "image", "size": len(data)}
    return {**found, "caption": None, "url": url, **changes}


def notice(outputs: list[dict], count: int | None = None, **extra) -> hub.Outgoing:
    names = ", ".join(output["name"] for output in outputs)
    return hub.Outgoing(
        id=41,
        user_id=1,
        login="owner",
        kind="notice",
        notice_kind="run_outputs",
        project=PROJECT,
        run_id=7,
        decision_id=None,
        title=f"Local run #7 sent {len(outputs)} files" if len(outputs) != 1 else f"Local run #7 sent {names}",
        body=f"- {names}\n\nFiles of local run #7 in project {PROJECT}.",
        details={"outputs": [output["id"] for output in outputs]},
        link=f"/p/{PROJECT}/runs/7",
        created_at=datetime(2026, 10, 21, 9, 0, tzinfo=UTC),
        extra={"restricted": False, "outputs": outputs, "outputs_count": count or len(outputs), **extra},
    )


def decision(outputs: list[dict], count: int | None = None, state: str = "open") -> hub.Outgoing:
    asked = {
        "question": "Ship the settings page?",
        "category": "product",
        "plan_id": None,
        "step_key": None,
        "options": OPTIONS,
        "state": state,
        "run_kind": "local",
        "run_title": "Settings page",
    }
    return hub.Outgoing(
        id=42,
        user_id=1,
        login="owner",
        kind="decision",
        notice_kind=None,
        project=PROJECT,
        run_id=7,
        decision_id=9,
        title="Ship the settings page?",
        body=None,
        details=None,
        link="/inbox?decision=9",
        created_at=datetime(2026, 10, 21, 9, 1, tzinfo=UTC),
        extra={"restricted": False, "decision": asked, "outputs": outputs, "outputs_count": count or len(outputs)},
    )


def send(notification: hub.Outgoing) -> str | None:
    channel = server_telegram.TelegramChannel(SimpleNamespace(public_url="https://hub.test"))
    return asyncio.run(channel.send(notification, {"chat_id": CHAT}))


def uploaded(payload: dict) -> list[tuple[str, str, bytes]]:
    return [(field, file["name"], file["content"]) for field, file in payload["files"].items()]


# A notice of a run's files


def test_a_notices_photos_go_as_one_group_whose_caption_is_the_notice_with_the_runs_link(bot):
    shot, chart = stored(bot, 1, "settings.png", SHOT), stored(bot, 2, "out/latency.png", CHART)
    ref = send(notice([shot, chart]))
    ((method, group),) = bot.fake.media()
    assert method == "sendMediaGroup" and group["chat_id"] == CHAT
    first, second = group["media"]
    assert (first["type"], first["media"], second) == (
        "photo",
        "attach://file0",
        {"type": "photo", "media": "attach://file1"},
    )
    assert first["parse_mode"] == "HTML" and first["caption"].startswith(
        f"<b>Files from a run</b> in {PROJECT}\nLocal run #7 sent 2 files\n\n- settings.png, out/latency.png"
    )
    assert first["caption"].endswith(f"\n\n{RUN_URL}")
    assert uploaded(group) == [("file0", "settings.png", SHOT), ("file1", "latency.png", CHART)]
    assert bot.fake.sent() == [], "one group a notification: no message besides"
    assert ref == f"{CHAT}:{group['message_ids'][0]}"


def test_one_file_goes_as_one_message_with_the_web_button(bot):
    report = stored(bot, 3, "report.md", REPORT, "text/markdown")
    ref = send(notice([report]))
    ((method, sent),) = bot.fake.media()
    assert method == "sendDocument" and uploaded(sent) == [("document", "report.md", REPORT)]
    assert sent["files"]["document"]["type"] == "text/markdown"
    assert sent["caption"].startswith(f"<b>Files from a run</b> in {PROJECT}\nLocal run #7 sent report.md")
    assert sent["reply_markup"] == {"inline_keyboard": [[{"text": "Open on the hub", "url": RUN_URL}]]}
    assert ref == f"{CHAT}:{sent['message_id']}"
    shot = stored(bot, 1, "settings.png", SHOT)
    send(notice([shot]))
    method, sent = bot.fake.media()[-1]
    assert method == "sendPhoto" and uploaded(sent) == [("photo", "settings.png", SHOT)]


def test_an_image_with_another_file_goes_as_documents_since_telegram_groups_documents_alone(bot):
    files = [stored(bot, 1, "settings.png", SHOT), stored(bot, 3, "report.md", REPORT, "text/markdown")]
    send(notice(files))
    ((method, group),) = bot.fake.media()
    assert method == "sendMediaGroup" and [item["type"] for item in group["media"]] == ["document", "document"]
    assert uploaded(group) == [("file0", "settings.png", SHOT), ("file1", "report.md", REPORT)]


def test_files_that_do_not_come_are_counted_on_the_hub_and_their_urls_are_never_logged(bot, caplog):
    caplog.set_level(logging.DEBUG)
    shot = stored(bot, 1, "settings.png", SHOT)
    refused = stored(bot, 2, "gone.png", CHART)
    refused["url"] = refused["url"].replace("/blobs/", "/expired/")
    unreachable = {**stored(bot, 3, "far.png", CHART), "url": f"{STORE}/unreachable/3?X-Amz-Signature=sig3"}
    short = {**stored(bot, 4, "short.png", CHART), "size": len(CHART) + 1}  # fewer bytes than the hub said
    send(notice([shot, refused, unreachable, short], count=6))
    ((method, sent),) = bot.fake.media()
    assert method == "sendPhoto" and uploaded(sent) == [("photo", "settings.png", SHOT)]
    assert sent["caption"].endswith(f"\n\n5 more files on the hub.\n\n{RUN_URL}")
    assert len(bot.fetched) == 4
    logged = [record for record in caplog.records if record.name.startswith("evo_core_plugins")]
    assert len(logged) == 3, "each file that did not come, by its id"  # the hub keeps httpx's own lines at WARNING
    assert all("X-Amz-Signature" not in str(vars(record)) and STORE not in str(vars(record)) for record in logged)

    bot.store.clear()
    send(notice([refused]))
    (text,) = bot.fake.sent()
    assert len(bot.fake.media()) == 1, "none of them came: the notice goes as text, which names them"
    assert "- gone.png" in text["text"] and text["reply_markup"]["inline_keyboard"][0][0]["url"] == RUN_URL


def test_telegram_refusing_photos_gets_them_as_documents_then_the_text_alone(bot):
    files = [stored(bot, 1, "tall.png", SHOT), stored(bot, 2, "wide.png", CHART)]
    bot.fake.fail_next(400, "Bad Request: PHOTO_INVALID_DIMENSIONS", method="sendMediaGroup")
    ref = send(notice(files))
    photos, documents = bot.fake.media()
    assert [item["type"] for item in photos[1]["media"]] == ["photo", "photo"]
    assert [item["type"] for item in documents[1]["media"]] == ["document", "document"]
    assert ref == f"{CHAT}:{documents[1]['message_ids'][0]}" and bot.fake.sent() == []

    for _ in range(2):
        bot.fake.fail_next(400, "Bad Request: failed to send", method="sendMediaGroup")
    ref = send(notice(files))
    (text,) = bot.fake.sent()
    assert text["text"].startswith(f"<b>Files from a run</b> in {PROJECT}") and ref == f"{CHAT}:{text['message_id']}"


def test_a_429_on_the_files_waits_its_retry_after_and_a_blocked_bot_turns_the_channel_off(bot):
    shot = stored(bot, 1, "settings.png", SHOT)
    bot.fake.fail_next(429, "Too Many Requests: retry after 7", retry_after=7, method="sendPhoto")
    with pytest.raises(hub.RetryAfter) as waited:
        send(notice([shot]))
    assert waited.value.seconds == 7 and bot.fake.sent() == []
    for status, description in ((403, "Forbidden: bot was blocked by the user"), (400, "Bad Request: chat not found")):
        bot.fake.fail_next(status, description, method="sendPhoto")
        with pytest.raises(hub.ChannelGone, match=description):
            send(notice([shot]))
    bot.fake.fail_next(500, "Internal Server Error", method="sendPhoto")
    with pytest.raises(server_telegram.BotApiError, match="500"):  # a failed try, tried again after its backoff
        send(notice([shot]))
    assert bot.fake.sent() == []


# A decision's files


def test_a_decisions_files_go_first_and_its_message_with_its_buttons_replies_to_them(bot):
    shot = stored(bot, 1, "settings.png", SHOT, caption="After the fix")
    ref = send(decision([shot], count=2))
    ((method, photo),) = bot.fake.media()
    assert method == "sendPhoto" and uploaded(photo) == [("photo", "settings.png", SHOT)]
    assert photo["caption"] == "After the fix\n\n1 more file on the hub." and "reply_markup" not in photo
    (question,) = bot.fake.sent()
    assert "Ship the settings page?" in question["text"]
    assert question["reply_markup"]["inline_keyboard"][0] == [{"text": "Ship it", "callback_data": "d:9:yes"}]
    assert question["reply_parameters"] == {"message_id": photo["message_id"], "allow_sending_without_reply": True}
    assert ref == f"{CHAT}:{question['message_id']}", "a reply to the question finds its decision"
    assert len(bot.waits) <= 1, "the question waits its second after the photo"


def test_a_decisions_message_that_failed_after_its_files_went_goes_alone_the_next_try(bot):
    files = [stored(bot, 1, "settings.png", SHOT), stored(bot, 2, "latency.png", CHART)]
    bot.fake.fail_next(500, "Internal Server Error")
    with pytest.raises(server_telegram.BotApiError):
        send(decision(files))
    ((_, group),) = bot.fake.media()
    ref = send(decision(files))
    assert len(bot.fake.media()) == 1, "its files went once"
    failed, question = bot.fake.sent()
    assert failed["reply_parameters"] == question["reply_parameters"]
    assert question["reply_parameters"]["message_id"] == group["message_ids"][0]
    assert ref == f"{CHAT}:{question['message_id']}" and server_telegram._FILES_SENT == {}


def test_a_restricted_projects_message_or_a_closed_decision_goes_without_any_file(bot):
    shot = stored(bot, 1, "northwind-contract.png", SHOT)
    kept = notice([shot])
    kept = hub.Outgoing(**{**kept.__dict__, "extra": {"restricted": True, "outputs": [shot], "outputs_count": 1}})
    send(kept)
    (text,) = bot.fake.sent()
    assert text["text"] == f"<b>{PROJECT}</b>: Files from a run.\n\n{RUN_URL}"
    send(decision([shot], state="answered"))
    closed = bot.fake.sent()[-1]["text"]
    assert (
        closed == f"<b>{PROJECT}</b>: Decision #9 no longer waits for your answer.\n\nhttps://hub.test/inbox?decision=9"
    )
    send(notice([{**shot, "url": None}]))  # the hub's pass had no store to sign with
    assert bot.fake.media() == [] and bot.fetched == []
    assert all("northwind" not in payload["text"] for payload in bot.fake.sent()[:2])
