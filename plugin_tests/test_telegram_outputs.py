"""The files of a run and of a question on Telegram through a hub (plan run-outputs: a4, a6), with a fake Bot API and
the fake S3 of evo-agents' tests: what the hub's prepare gives the channel (``extra.outputs``, presigned GETs of the
store) goes to the chat as photos or documents, a question's files before the question; a restricted project's chat
gets no file and no file's name, and an image taken out of a tool's result never goes. The notice of a run's files
(run_outputs) only reports: the hub keeps it on the web and gives it to no channel (evo-agents'
runs.REPORT_NOTICE_KINDS, docs/notifications.md), so it never reaches a chat, with the store or without.

These need a hub that gives channels a notification's files: evo-agents with the notice run_outputs (plan
run-outputs, step 4). The hub at an earlier commit of evo-agents.lock gives none, and the module skips; the channel's
own tests (``test_telegram_files.py``) run either way. The people, projects and files are fictional.
"""

from __future__ import annotations

from functools import partial

import pytest

from tests.hub import pg

if not pg.DSN:
    pytest.skip(pg.SKIP_REASON, allow_module_level=True)

from evo_agents.hub import runs

if getattr(runs, "OUTPUT_NOTICE", None) != "run_outputs":
    pytest.skip(
        "the evo-agents of this checkout gives channels no files of a notification (plan run-outputs, step 4)",
        allow_module_level=True,
    )

from fastapi.testclient import TestClient

from evo_agents.hub.server import notifications
from evo_agents.hub.server.app import create_app
from plugin_tests.test_telegram import (
    OWNER_CHAT,
    bot,  # noqa: F401 (a fixture)
    linked,
    telegram_config,
    telegram_deliveries,
    unrestricted,
    web,
)
from tests.hub.test_notifications import due_now
from tests.hub.test_output_notices import SHOT, TOOL_SHOT, ask_local, local_run
from tests.hub.test_run_outputs import REPORT, item, sent
from tests.hub.test_runs import OWNER, PROJECT, members


@pytest.fixture
def client(hub_db, tmp_path, github, bot, s3):  # noqa: F811
    config = telegram_config(hub_db, tmp_path, github, **s3.config())
    with TestClient(create_app(config), base_url="https://hub.test") as client:
        yield client


@pytest.fixture
def hub(client, github, hub_db) -> dict:
    """test_runs' members, the project's hub sink below Telegram's clearance, and the owner's chat linked."""
    headers = members(client, github)
    unrestricted(hub_db)
    linked(client, web(client, hub_db, OWNER))
    return headers


def deliver(client, *, blobs: bool = True) -> dict:
    """One pass of the job hub.deliver_notifications, with the store the hub signs the files' GETs with."""
    engine, config = client.app.state.engine, client.app.state.config
    store = client.app.state.blobs if blobs else None
    return client.portal.call(partial(notifications.deliver_notifications, engine, config=config, blobs=store))


def uploaded(payload: dict) -> list[tuple[str, bytes]]:
    return [(file["name"], file["content"]) for file in payload["files"].values()]


@pytest.mark.parametrize("blobs", [True, False], ids=["with-the-store", "without-the-store"])
def test_a_runs_files_stay_on_the_hub_and_reach_no_chat(client, hub, hub_db, bot, blobs):  # noqa: F811
    _, prefix = local_run(client, hub)
    sent(
        client,
        prefix,
        hub["owner"],
        [
            (SHOT, item(SHOT, "settings.png", "image/png", caption="After the fix")),
            (REPORT, item(REPORT, "report.md", "text/markdown")),
            (TOOL_SHOT, item(TOOL_SHOT, "browser.png", "image/png", "tool")),
        ],
    )
    assert deliver(client, blobs=blobs)["failed"] == 0
    due_now(hub_db)
    assert deliver(client, blobs=blobs)["failed"] == 0
    sent(client, prefix, hub["owner"], [(SHOT[::-1], item(SHOT[::-1], "after.png", "image/png"))])
    due_now(hub_db)
    assert deliver(client, blobs=blobs)["failed"] == 0
    assert bot.fake.media() == [], "a notice that only reports goes to no channel"
    assert [payload["text"] for payload in bot.fake.sent()][1:] == [], "no message besides the link's"
    assert telegram_deliveries(hub_db) == []
    for name in ("settings.png", "report.md", "browser.png", "after.png"):
        assert name not in str(bot.fake.calls)


def test_a_question_with_a_file_sends_the_image_and_then_the_question_as_a_reply_to_it(client, hub, hub_db, bot):  # noqa: F811
    _, prefix = local_run(client, hub)
    shot, tool_shot = sent(
        client,
        prefix,
        hub["owner"],
        [
            (SHOT, item(SHOT, "settings.png", "image/png", caption="After the fix")),
            (TOOL_SHOT, item(TOOL_SHOT, "browser.png", "image/png", "tool")),
        ],
    )["outputs"]
    asked = ask_local(client, hub, prefix, [shot["id"], tool_shot["id"]])
    assert deliver(client)["failed"] == 0
    ((method, photo),) = bot.fake.media()
    assert method == "sendPhoto" and uploaded(photo) == [("settings.png", SHOT)], "the tool's image stays on the hub"
    assert photo["caption"] == "After the fix"
    question = bot.fake.sent()[-1]
    assert "Ship the settings page?" in question["text"]
    assert question["reply_markup"]["inline_keyboard"][0] == [{"text": "Yes", "callback_data": f"d:{asked['id']}:yes"}]
    assert question["reply_parameters"]["message_id"] == photo["message_id"]
    assert telegram_deliveries(hub_db) == [("delivered", 1, f"{OWNER_CHAT}:{question['message_id']}", None)]
    due_now(hub_db)
    deliver(client)
    assert len(bot.fake.media()) == 1, "the file went with the question: no notice of it besides"


def test_a_restricted_projects_chat_gets_neither_files_nor_their_names(client, hub, hub_db, bot):  # noqa: F811
    unrestricted(hub_db, {"level": "customer", "location": "any"})  # at Telegram's level: restricted
    _, prefix = local_run(client, hub)
    (shot,) = sent(client, prefix, hub["owner"], [(SHOT, item(SHOT, "northwind-contract.png", "image/png"))])["outputs"]
    asked = ask_local(client, hub, prefix, [shot["id"]])
    sent(client, prefix, hub["owner"], [(REPORT, item(REPORT, "northwind-terms.md", "text/markdown"))])
    due_now(hub_db)
    assert deliver(client)["failed"] == 0
    assert bot.fake.media() == []
    texts = [payload["text"] for payload in bot.fake.sent()][1:]
    assert texts == [  # the question alone: the notice of the run's files stays on the hub
        f"<b>{PROJECT}</b>: A decision waits for your answer.\n\nhttps://hub.test/inbox?decision={asked['id']}",
    ]
    assert "northwind" not in str(bot.fake.calls)
