"""The bridge of a Telegram group to a group chat of the hub (plan chat-bridges, a5): the core plugin telegram as the
bridge's transport, through the API of core plugins 1.5 alone, against the fake Bot API (``fake_telegram.py``) and a
hub of evo-agents at the lock. No call reaches Telegram; the people, groups and files are fictional.

A chat admin's code links a group with ``/link``; the bot removed from the group, or a group admin's ``/unlink``,
takes the bridge off; a group that becomes a supergroup keeps it. A linked member's message comes in as theirs with
its mentions made the hub's and its photo; someone not linked is told once and stays out. A hub message goes out as
HTML within 4096 characters, its table a ``<pre>``, cut with a link to the hub; a run's progress is one message,
edited; its files go as photos and documents, one too large as a link to the hub; the agent's ✅ becomes the
bot's reaction, a person's stays on the hub; and a group gets at most 20 messages a minute."""

from __future__ import annotations

import itertools
from functools import partial
from types import SimpleNamespace

import pytest

from tests.hub import live, pg

if not pg.DSN:
    pytest.skip(pg.SKIP_REASON, allow_module_level=True)

from fastapi.testclient import TestClient
from sqlalchemy import func, insert, select, update

from evo_agents.hub import chat_bridge_events, plugin_events, tables
from evo_agents.hub.server.app import create_app
from evo_core_plugins.telegram import bridge, bridge_model, server
from evo_core_plugins.telegram import model as telegram
from plugin_tests.fake_telegram import BOT, bot_left, group_chat, photo_update, private_chat, text_update
from plugin_tests.test_telegram import (
    OTHER_CHAT,
    OWNER_CHAT,
    bot,  # noqa: F401 (a fixture)
    handled,
    new_link,
    telegram_config,
    unrestricted,
    web,
)
from tests.hub.live import sql
from tests.hub.test_chats import created, page, sent
from tests.hub.test_curator import night  # noqa: F401 (a fixture, on this module's web_client)
from tests.hub.test_runs import OTHER, OWNER, PROJECT

GROUP, NEW_GROUP, STRANGER_ID = -1001234, -1009876, 7999
ORIGIN = "https://hub.test"
CHATS = ["chats:read", "chats:write"]
SINK = {"level": "internal", "location": "any"}
PNG = b"\x89PNG\r\n\x1a\n" + b"fake image bytes" * 8
updates = itertools.count(90_000)


@pytest.fixture
def web_client(hub_db, tmp_path, github, bot, s3):  # noqa: F811
    """The hub the fixture night builds on, with the Telegram channel on and a blob store for the group's files."""
    config = telegram_config(hub_db, tmp_path, github, **s3.config())
    with TestClient(create_app(config), base_url=ORIGIN) as client:
        client.app.state.telegram_inbound = server.InboundLimit(updates=1000)
        yield client


@pytest.fixture
def pace(monkeypatch) -> SimpleNamespace:
    """The groups' pace on a clock the test moves."""
    now = SimpleNamespace(value=1000.0)
    monkeypatch.setattr(bridge, "clock", lambda: now.value)
    monkeypatch.setattr(bridge, "PACE", bridge_model.Pace(lambda: now.value))
    return now


def session(client, db, login: str) -> dict:
    """The headers of a write from a page of the hub, in a new web session of ``login``."""
    return {**web(client, db, login), "Origin": ORIGIN}


def channel_sink(db, clearance=SINK) -> None:
    """The project's sink of kind channel ``telegram``: what of its chats may go out to a Telegram group."""
    sinks, p = tables.project_sinks, tables.projects
    ((project_id,),) = sql(db, select(p.c.id).where(p.c.name == PROJECT))
    row = {"project_id": project_id, "sink_id": "telegram", "kind": "channel", "clearance": clearance}
    sql(db, insert(sinks).values(**row))


def link_private(client, headers, chat_id: int, username: str) -> None:
    chat, sender = private_chat(chat_id, username)
    code = new_link(client, headers)
    assert handled(client, text_update(next(updates), chat, sender, f"/start {code}")) == "linked"


def person(user_id: int, username: str | None = None, name: str = "Someone") -> dict:
    found = {"id": user_id, "is_bot": False, "first_name": name}
    return found | ({"username": username} if username else {})


OWNER_TG = person(OWNER_CHAT, "owner_tg", "Owner")
OTHER_TG = person(OTHER_CHAT, "other_tg", "Other")
STRANGER_TG = person(STRANGER_ID, None, "Stranger")


def in_group(client, text: str, sender: dict = OWNER_TG, *, chat: dict | None = None, reply_to: int | None = None):
    update = text_update(next(updates), chat or group_chat(GROUP), sender, text, reply_to=reply_to)
    return handled(client, update), update["message"]["message_id"]


def deliver_events(client) -> dict:
    engine, config = client.app.state.engine, client.app.state.config
    return client.portal.call(partial(plugin_events.deliver, engine, config=config))


def on_hub(client, work):
    async def run(engine):
        async with engine.begin() as conn:
            return await work(conn)

    return client.portal.call(partial(run, client.app.state.engine))


def to_group(fake, chat_id: int = GROUP, method: str = "sendMessage") -> list[dict]:
    return [payload for payload in fake.sent(method) if payload.get("chat_id") == chat_id]


def bridges(db) -> list[tuple]:
    b = tables.chat_bridges
    return sql(db, select(b.c.external_id, b.c.unlinked_via).order_by(b.c.id))


def bridge_code(client, chat_id: int, headers) -> str:
    made = client.post(f"/v1/chats/{chat_id}/bridges/code", json={"kind": "telegram"}, headers=headers)
    assert made.status_code == 201, made.text
    return made.json()["code"]


def hub_bodies(client, headers, chat_id: int) -> list[str]:
    return [message["body"] for message in page(client, headers, chat_id)["messages"]]


@pytest.fixture
def bridged(night, hub_db, bot, pace):  # noqa: F811
    """night's hub with telegram enabled by the project with chats:read and chats:write, its channel sink cleared for
    internal, the owner's and other's Telegram accounts linked (their private chats), and a group chat of the owner and
    the project's agent bridged to the supergroup GROUP with a code the owner made from a web session."""
    client, headers = night.client, night.headers
    enabled = client.post(
        f"/v1/projects/{PROJECT}/plugins/telegram/enable", json={"permissions": CHATS}, headers=headers["owner"]
    )
    assert enabled.status_code == 200, enabled.text
    unrestricted(hub_db)
    channel_sink(hub_db)
    owner_web = session(client, hub_db, OWNER)
    link_private(client, owner_web, OWNER_CHAT, "owner_tg")
    link_private(client, session(client, hub_db, OTHER), OTHER_CHAT, "other_tg")
    chat = created(client, headers["owner"], title="Release team", agents=[PROJECT])
    code = bridge_code(client, chat["id"], owner_web)
    assert in_group(client, f"/link@{BOT} {code}")[0] == "bridged"
    return SimpleNamespace(**vars(night), db=hub_db, fake=bot.fake, waits=bot.waits, chat=chat, web=owner_web)


# Linking


def test_a_code_from_the_chats_page_links_a_group_once_and_a_bad_code_links_nothing(night, hub_db, bot, pace):  # noqa: F811
    client, headers = night.client, night.headers
    path = f"/v1/projects/{PROJECT}/plugins/telegram/enable"
    assert client.post(path, json={"permissions": CHATS}, headers=headers["owner"]).status_code == 200
    channel_sink(hub_db)
    owner_web = session(client, hub_db, OWNER)
    chat = created(client, headers["owner"], title="Release team", agents=[PROJECT])
    code = bridge_code(client, chat["id"], owner_web)
    assert in_group(client, "/link " + "x" * 32)[0] == "bridge_failed"
    assert in_group(client, "/link")[0] == "bridge_failed"
    assert in_group(client, f"/link {code}")[0] == "bridged"
    assert in_group(client, f"/link {code}", chat=group_chat(NEW_GROUP))[0] == "bridge_failed"  # once
    assert bridges(hub_db) == [(str(GROUP), None)]
    said = [payload["text"] for payload in to_group(bot.fake)]
    assert said == [bridge.LINK_FAILED, bridge.LINK_FAILED, bridge.LINKED]
    # A private chat's /start in a group still links nothing, and a group not bridged gets no answer.
    assert in_group(client, f"/start {'y' * 32}", chat=group_chat(NEW_GROUP))[0] == "link_failed"
    assert in_group(client, "hello there", chat=group_chat(NEW_GROUP))[0] == "ignored"
    assert [payload["text"] for payload in to_group(bot.fake, NEW_GROUP)] == [
        bridge.LINK_FAILED,
        server.LINK_FAILED,
    ]


def test_the_bot_taken_out_of_the_group_or_a_group_admins_unlink_takes_the_bridge_off(bridged):
    client, db, fake = bridged.client, bridged.db, bridged.fake
    assert in_group(client, "/unlink", OTHER_TG)[0] == "refused"  # not an admin of the group
    assert to_group(fake)[-1]["text"] == bridge.ADMINS_ONLY
    fake.admins.add((GROUP, OWNER_CHAT))
    assert in_group(client, "/unlink")[0] == "unbridged"
    assert in_group(client, "after the unlink")[0] == "ignored"
    assert bridges(db) == [(str(GROUP), "bot")]
    # Bridged again, then the bot removed from the group: the bridge goes.
    code = bridge_code(client, bridged.chat["id"], bridged.web)
    assert in_group(client, f"/link {code}")[0] == "bridged"
    assert handled(client, bot_left(next(updates), group_chat(GROUP), "member")) == "ignored"
    assert handled(client, bot_left(next(updates), group_chat(GROUP), "kicked")) == "unbridged"
    assert handled(client, bot_left(next(updates), group_chat(GROUP), "left")) == "ignored"
    assert bridges(db) == [(str(GROUP), "bot"), (str(GROUP), "bot")]


def test_a_group_that_becomes_a_supergroup_keeps_its_bridge_from_the_update_or_the_400(bridged):
    client, db, fake, chat, headers = bridged.client, bridged.db, bridged.fake, bridged.chat, bridged.headers
    old = {"id": GROUP, "type": "group", "title": "Release team"}
    update = text_update(next(updates), old, OWNER_TG, "")
    del update["message"]["text"]
    update["message"]["migrate_to_chat_id"] = NEW_GROUP
    assert handled(client, update) == "moved"
    assert bridges(db) == [(str(NEW_GROUP), None)]
    assert in_group(client, "on the new id", chat=group_chat(NEW_GROUP))[0] == "bridged_in"
    # A message out that Telegram answers with the group's new id goes there, and the bridge follows.
    fake.fail_next(400, "Bad Request: group chat was upgraded to a supergroup chat", migrate_to=GROUP)
    sent(client, headers["owner"], chat["id"], "where are we")
    deliver_events(client)
    assert [payload["chat_id"] for payload in fake.sent()][-1] == GROUP
    assert bridges(db) == [(str(GROUP), None)]


# In from the group


def test_a_linked_members_message_comes_in_with_its_mentions_made_the_hubs(bridged):
    client, db, fake, chat, headers = bridged.client, bridged.db, bridged.fake, bridged.chat, bridged.headers
    outcome, first = in_group(client, f"@{BOT} ship the release with @other_tg and @nobody_tg")
    assert outcome == "bridged_in"
    assert in_group(client, "a second word", reply_to=first)[0] == "bridged_in"
    messages = page(client, headers["owner"], chat["id"])["messages"]
    came = {message["body"]: message for message in messages}
    shipped = came[f"@{PROJECT} ship the release with @{OTHER} and @nobody_tg"]
    assert shipped["via"] == "telegram" and shipped["author"]["login"] == OWNER, shipped
    second = came["a second word"]
    assert second["thread_root_id"] == shipped["id"] or second["reply_to"] == shipped["id"], second
    deliver_events(client)
    went = [payload["text"] for payload in to_group(fake)]
    assert not [text for text in went if "ship the release" in text or "a second word" in text], went
    m = tables.chat_messages
    assert sql(db, select(func.count()).where(m.c.chat_id == chat["id"], m.c.via == "telegram")) == [(2,)]


def test_someone_not_linked_is_told_once_how_to_link_and_stays_out_of_the_hub(bridged):
    client, fake, chat, headers = bridged.client, bridged.fake, bridged.chat, bridged.headers
    assert in_group(client, "can I join?", STRANGER_TG)[0] == "not_linked"
    assert in_group(client, "hello?", STRANGER_TG)[0] == "not_linked"
    told = [payload["text"] for payload in to_group(fake) if payload["text"] != bridge.LINKED]
    assert told == [bridge.HOW_TO_LINK.format(name="Stranger", bot=BOT)]
    assert "can I join?" not in hub_bodies(client, headers["owner"], chat["id"])
    assert "hello?" not in hub_bodies(client, headers["owner"], chat["id"])


def test_a_photo_of_the_group_comes_in_as_a_file_of_the_message(bridged):
    client, db, fake, chat, headers = bridged.client, bridged.db, bridged.fake, bridged.chat, bridged.headers
    fake.files["photo-1"] = PNG
    update = photo_update(next(updates), group_chat(GROUP), OWNER_TG, "photo-1", len(PNG), caption="the new screen")
    assert handled(client, update) == "bridged_in"
    (message,) = [item for item in page(client, headers["owner"], chat["id"])["messages"] if item["body"]]
    assert message["body"] == "the new screen"
    a = tables.attachments
    rows = sql(db, select(a.c.name, a.c.size))
    assert rows == [(f"photo-{update['message']['message_id']}.jpg", len(PNG))], rows
    # A file above what a bot may fetch from Telegram is refused with a word, and a text with it still comes in.
    big = photo_update(next(updates), group_chat(GROUP), OWNER_TG, "photo-2", bridge_model.TELEGRAM_DOWNLOAD_BYTES + 1)
    assert handled(client, big) == "refused"
    assert to_group(fake)[-1]["text"] == bridge.TOO_LARGE


# Out to the group


def test_a_hub_message_goes_out_once_as_html_with_its_table_in_pre_and_a_long_one_cut_with_a_link(bridged):
    client, fake, chat, headers = bridged.client, bridged.fake, bridged.chat, bridged.headers
    _, first = in_group(client, "what is left?")
    m = tables.chat_messages
    ((started,),) = sql(bridged.db, select(m.c.id).where(m.c.body == "what is left?"))
    body = "**Left**\n| step | state |\n|---|---|\n| build | done |\n| deploy | <waiting> |"
    answer = sent(client, headers["owner"], chat["id"], body, reply_to=started)
    deliver_events(client)
    deliver_events(client)
    (out,) = [payload for payload in to_group(fake) if payload["text"] != bridge.LINKED]
    assert out["parse_mode"] == "HTML" and out["reply_parameters"]["message_id"] == first, out
    assert out["text"].startswith(f"<b>{OWNER}</b>\n<b>Left</b>\n<pre>step   | state")
    assert "deploy | &lt;waiting&gt;</pre>" in out["text"]
    shown = page(client, headers["owner"], chat["id"])["messages"]
    (mine,) = [item for item in shown if item["id"] == answer["id"]]
    assert [bridged_to["kind"] for bridged_to in mine["bridged_to"]] == ["telegram"]
    # A reply in the group to what went out threads under it on the hub.
    assert in_group(client, "thanks", reply_to=out["message_id"])[0] == "bridged_in"
    # A long message is cut within 4096 characters and links to itself on the hub.
    long = sent(client, headers["owner"], chat["id"], "word " * 2000)
    deliver_events(client)
    cut = to_group(fake)[-1]["text"]
    assert len(cut) <= 4096, len(cut)
    assert cut.endswith(f'/chats/{chat["id"]}?message={long["id"]}">Read the rest on the hub</a>'), cut[-200:]


def test_the_channel_sink_keeps_a_message_above_its_clearance_in_the_hub(bridged):
    client, db, fake, chat, headers = bridged.client, bridged.db, bridged.fake, bridged.chat, bridged.headers
    sinks = tables.project_sinks
    sql(db, update(sinks).values(clearance={"level": "public", "location": "any"}).where(sinks.c.sink_id == "telegram"))
    sent(client, headers["owner"], chat["id"], "kept in the hub")
    deliver_events(client)
    assert [payload["text"] for payload in to_group(fake)] == [bridge.LINKED]


def attached(client, headers, chat_id: int, body: str, *files: tuple[str, str, bytes]) -> dict:
    """A message of ``body`` with ``files`` (name, media type, bytes) attached, as a member posts it from the hub."""
    ids = []
    for name, media_type, content in files:
        target = f"/v1/chats/{chat_id}/attachments"
        up = client.post(
            target, params={"name": name}, content=content, headers={**headers, "Content-Type": media_type}
        )
        assert up.status_code == 201, up.text
        ids.append(up.json()["id"])
    posted = client.post(f"/v1/chats/{chat_id}/messages", json={"body": body, "attachment_ids": ids}, headers=headers)
    assert posted.status_code == 201, posted.text
    return posted.json()


def uploads(fake, method: str, field: str) -> list[tuple[str, bytes, int | None, str | None]]:
    """What went to the group with ``method``: the file's name and bytes, the message it replies to, its caption."""
    return [
        (
            payload["files"][field]["name"],
            payload["files"][field]["content"],
            (payload.get("reply_parameters") or {}).get("message_id"),
            payload.get("caption"),
        )
        for payload in to_group(fake, method=method)
    ]


def test_the_files_of_a_hub_message_go_out_as_a_photo_and_a_document_and_one_too_large_as_a_link(bridged, monkeypatch):
    client, fake, chat, headers = bridged.client, bridged.fake, bridged.chat, bridged.headers
    monkeypatch.setattr(telegram, "MAX_DOCUMENT_BYTES", 200)  # what a bot uploads, small enough for a test's file
    notes = b"step one, then step two\n" * 4
    large = b"z" * 300
    files = [
        ("screen.png", "image/png", PNG),
        ("notes.txt", "text/plain", notes),
        ("all.zip", "application/zip", large),
    ]
    message = attached(client, headers["owner"], chat["id"], "the release, in files", *files)
    deliver_events(client)
    (text,) = [payload for payload in to_group(fake) if payload["text"] != bridge.LINKED]
    assert text["text"].startswith(
        f"<b>{OWNER}</b>\nthe release, in files\nToo large for Telegram, on the hub: all.zip"
    )
    assert text["text"].endswith(f'/chats/{chat["id"]}?message={message["id"]}">Open it on the hub</a>'), text
    head = text["message_id"]
    assert uploads(fake, "sendPhoto", "photo") == [("screen.png", PNG, head, None)]
    assert uploads(fake, "sendDocument", "document") == [("notes.txt", notes, head, None)]
    # Once: the event delivered again sends nothing more.
    deliver_events(client)
    assert len(fake.media()) == 2
    # A message that is files alone goes as its first file, its author the caption, the rest replies to it.
    alone = attached(
        client, headers["owner"], chat["id"], "", ("shot.png", "image/png", PNG), ("more.txt", "text/plain", notes)
    )
    deliver_events(client)
    assert [payload["text"] for payload in to_group(fake)][-1] == text["text"], "no text for files alone"
    (photo, caption) = [(payload["message_id"], payload) for payload in to_group(fake, method="sendPhoto")][-1]
    assert caption["caption"] == f"<b>{OWNER}</b>" and caption["parse_mode"] == "HTML"
    assert uploads(fake, "sendDocument", "document")[-1] == ("more.txt", notes, photo, None)
    shown = page(client, headers["owner"], chat["id"])["messages"]
    (mine,) = [item for item in shown if item["id"] == alone["id"]]
    assert [bridged_to["kind"] for bridged_to in mine["bridged_to"]] == ["telegram"]


def test_a_photo_telegram_refuses_goes_as_a_document_and_the_files_of_one_try_stay_within_its_bytes(
    bridged, monkeypatch
):
    client, db, fake, chat, headers = bridged.client, bridged.db, bridged.fake, bridged.chat, bridged.headers
    fake.fail_next(400, "Bad Request: PHOTO_INVALID_DIMENSIONS", method="sendPhoto")
    attached(client, headers["owner"], chat["id"], "a wide one", ("wide.png", "image/png", PNG))
    deliver_events(client)
    assert [upload[0] for upload in uploads(fake, "sendPhoto", "photo")] == ["wide.png"]  # refused
    assert [upload[:2] for upload in uploads(fake, "sendDocument", "document")] == [("wide.png", PNG)]
    # A try uploads one file and what fits in MAX_MEDIA_BYTES after it; the hub sends the event again for the rest.
    monkeypatch.setattr(telegram, "MAX_MEDIA_BYTES", len(PNG) + 1)
    two = [("first.png", "image/png", PNG), ("second.png", "image/png", PNG)]
    attached(client, headers["owner"], chat["id"], "two of them", *two)
    deliver_events(client)
    assert [upload[0] for upload in uploads(fake, "sendPhoto", "photo")[1:]] == ["first.png"]
    d = tables.plugin_deliveries
    sql(db, update(d).values(next_at=func.now()).where(d.c.state == "pending"))
    deliver_events(client)
    assert [upload[0] for upload in uploads(fake, "sendPhoto", "photo")[1:]] == ["first.png", "second.png"]
    heads = [payload["message_id"] for payload in to_group(fake) if payload["text"].endswith("two of them")]
    assert len(heads) == 1 and {upload[2] for upload in uploads(fake, "sendPhoto", "photo")[1:]} == set(heads)


def test_a_runs_progress_is_one_message_edited_and_the_agents_check_is_a_reaction(bridged):
    client, db, fake, chat = bridged.client, bridged.db, bridged.fake, bridged.chat
    _, first = in_group(client, f"@{BOT} run the checks")
    m = tables.chat_messages
    ((started,),) = sql(db, select(m.c.id).where(m.c.chat_id == chat["id"], m.c.via == "telegram"))

    def moved(state: str):
        async def emit(conn):
            return await chat_bridge_events.progress(conn, chat["id"], started, 41, state)

        assert on_hub(client, emit) == 1

    moved("leased")
    deliver_events(client)
    moved("running")
    deliver_events(client)
    moved("done")

    async def checked(conn):
        return await chat_bridge_events.reaction(
            conn, chat["id"], started, "✅", added=True, count=1, by_kind="agent", by=PROJECT
        )

    async def eyes(conn):
        return await chat_bridge_events.reaction(
            conn, chat["id"], started, "\U0001f440", added=True, count=1, by_kind="agent", by=PROJECT
        )

    async def a_persons(conn):
        return await chat_bridge_events.reaction(
            conn, chat["id"], started, "❌", added=True, count=1, by_kind="person", by=OWNER
        )

    assert on_hub(client, checked) == 1 and on_hub(client, eyes) == 1 and on_hub(client, a_persons) == 1
    deliver_events(client)
    progress = [payload for payload in to_group(fake) if payload["text"].startswith("Run #41")]
    assert len(progress) == 1 and progress[0]["reply_parameters"]["message_id"] == first, progress
    assert progress[0]["text"] == "Run #41: picked up"
    edits = [payload["text"] for payload in to_group(fake, method="editMessageText")]
    assert edits == ["Run #41: working", "Run #41: done"]
    assert {payload["message_id"] for payload in to_group(fake, method="editMessageText")} == {
        progress[0]["message_id"]
    }
    (reacted,) = to_group(fake, method="setMessageReaction")  # neither the 👀 nor a person's ❌ goes out
    assert reacted["message_id"] == first and reacted["reaction"] == [{"type": "emoji", "emoji": "\U0001f44d"}]


def test_a_group_gets_at_most_twenty_messages_a_minute_and_the_rest_later(bridged, pace):
    client, db, fake, chat, headers = bridged.client, bridged.db, bridged.fake, bridged.chat, bridged.headers
    for index in range(25):
        sent(client, headers["owner"], chat["id"], f"line {index}")
    deliver_events(client)
    out = [payload["text"] for payload in to_group(fake) if payload["text"] != bridge.LINKED]
    assert len(out) == bridge_model.GROUP_MESSAGES, out
    assert all(wait <= bridge.MAX_WAIT_SECONDS for wait in bridged.waits)
    d = tables.plugin_deliveries
    held = sql(db, select(func.count()).where(d.c.state == "pending", d.c.attempts > 0))
    assert held == [(5,)]
    pace.value += bridge_model.GROUP_SECONDS + 1
    sql(db, update(d).values(next_at=func.now()).where(d.c.state == "pending"))
    deliver_events(client)
    out = [payload["text"] for payload in to_group(fake) if payload["text"] != bridge.LINKED]
    assert out == [f"<b>{OWNER}</b>\nline {index}" for index in range(25)]


# The pace and the model


def test_the_pace_holds_a_group_to_twenty_messages_a_minute_and_a_chat_to_one_a_second():
    now = SimpleNamespace(value=0.0)
    pace = bridge_model.Pace(lambda: now.value)
    for _ in range(bridge_model.GROUP_MESSAGES):
        assert pace.wait(GROUP) <= 1.0
        pace.took(GROUP)
        now.value += 1.0
    assert pace.wait(GROUP) == pytest.approx(bridge_model.GROUP_SECONDS - bridge_model.GROUP_MESSAGES)
    assert pace.wait(NEW_GROUP) == 0.0
    now.value += bridge_model.GROUP_SECONDS
    assert pace.wait(GROUP) == 0.0


def test_inbound_mentions_and_outbound_html_as_the_model_makes_them():
    logins = {"other_tg": OTHER}
    said = bridge_model.inbound_text(f"@{BOT.upper()} ask @other_tg", BOT, PROJECT, logins)
    assert said == f"@{PROJECT} ask @{OTHER}"
    assert bridge_model.inbound_text(f"@{BOT} hi", BOT, None, {}) == "hi"
    html = bridge_model.outbound("agent", PROJECT, "```\na < b\n```\nsee `x` and [docs](https://docs.test/a)", None)
    assert html == (
        f'<b>{PROJECT}</b> (agent)\n<pre>a &lt; b</pre>\nsee <code>x</code> and <a href="https://docs.test/a">docs</a>'
    )
    assert bridge_model.outbound("person", OWNER, "", "https://hub.test/chats/1#m2").endswith(
        '<a href="https://hub.test/chats/1#m2">Open it on the hub</a>'
    )
    assert bridge_model.reaction("✅") == "\U0001f44d" and bridge_model.reaction("❌") == "\U0001f44e"
    assert bridge_model.reaction("\U0001f440") is None
    mib = 1024 * 1024
    assert bridge_model.file_method("image/png", 10 * mib) == "sendPhoto"
    assert bridge_model.file_method("image/png", 10 * mib + 1) == "sendDocument"
    assert bridge_model.file_method("image/gif", 1) == "sendDocument"
    assert bridge_model.file_method("application/pdf", 50 * mib) == "sendDocument"
    assert bridge_model.file_method("application/pdf", 50 * mib + 1) is None
    assert bridge_model.caption("agent", PROJECT, "https://hub.test/c", ["big.mov"]) == (
        f"<b>{PROJECT}</b> (agent)\nToo large for Telegram, on the hub: big.mov"
        '\n<a href="https://hub.test/c">Open it on the hub</a>'
    )
    assert live  # the module of evo-agents' test helpers this module reads its hub from
