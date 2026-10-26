"""The core plugin editorial on the hub (``evo_core_plugins.editorial``): the posts of a project through the stages its
config lists, their gates, review rounds and comments, and the feedback notebook.

A writer sets a post's stage, which opens the stage's gate, and answers the gate; ``posts`` lists each post with the
gate that waits, its preview and url and its count of rounds. The notebook takes an entry (``feedback`` add), counts a
repeat with the person's new words, filters by notebook, stage, post and times seen, and recalls what to read before a
stage. Import keeps the ids and a second run adds nothing; export prints a notebook exactly as it was kept. A reader
only reads, a label above the grant hides a post, a project that did not enable the plugin answers 404, the knowledge
graph's source gives one item per entry and per post, and the MCP tools answer what the routes answer. All names are
fictional.
"""

from __future__ import annotations

import json

import pytest

from tests.hub import pg

if not pg.DSN:
    pytest.skip(pg.SKIP_REASON, allow_module_level=True)

from fastapi.testclient import TestClient
from sqlalchemy import select, update

from evo_agents.hub import tables
from evo_agents.hub.plugin_calls import CoreContext
from evo_agents.hub.server import core_plugin_api as hub_api
from evo_agents.hub.server.app import create_app
from evo_core_plugins.editorial import kg as editorial_kg
from evo_core_plugins.editorial import manifest
from evo_core_plugins.editorial import tables as editorial_tables
from plugin_tests.test_editorial_ledger import VOICE
from tests.hub import live
from tests.hub.live import sql
from tests.hub.test_mcp import call
from tests.hub.test_plugin_points import rpc, tool_names
from tests.hub.test_tasks_plugin import (  # noqa: F401 (fixtures)
    PROJECT,
    configure,
    enable,
    members,
    tasks_core,
)

BASE = f"/v1/x/editorial/{PROJECT}"

CONFIG = {
    "stages": [
        {"name": "idea", "title": "Idea", "gate": "choose", "recall": ["voice"]},
        {"name": "draft", "title": "Draft", "recall": ["voice", "facts"]},
        {"name": "review", "title": "Review", "gate": "comments"},
        {"name": "ship", "title": "Ship", "gate": "publish"},
    ],
    "notebooks": [
        {
            "name": "voice",
            "title": "Voice notebook",
            "intro": "What Lumen corrected about the voice of a post.\nRead it before a draft.",
        },
        {"name": "facts", "title": "Facts notebook"},
        {"name": "style", "title": "Style notebook", "always": True},
    ],
    "person": "Lumen",
    "reviewers": ["lumen"],
    "daily_usd": 2,
}

DOCUMENT = {
    "posts": [
        {
            "slug": "northwind-launch",
            "title": "How Northwind ships at night",
            "stage": "review",
            "branch": "post/northwind-launch",
            "preview_url": "https://preview.example.org/northwind-launch",
            "history": [
                {"stage": "idea", "at": "2026-09-10T08:00:00Z"},
                {"stage": "draft", "at": "2026-09-12T08:00:00Z", "evidence": "draft committed"},
                {"stage": "review", "at": "2026-09-14T08:00:00Z"},
            ],
            "gates": [
                {
                    "stage": "idea",
                    "state": "answered",
                    "opened_at": "2026-09-10T08:00:00Z",
                    "answered_at": "2026-09-11T09:00:00Z",
                    "answered_via": "telegram",
                    "answer": {"option": 2},
                },
                {"stage": "review", "opened_at": "2026-09-14T08:00:00Z"},
            ],
            "rounds": [
                {
                    "stage": "review",
                    "number": 1,
                    "at": "2026-09-14T10:00:00Z",
                    "note": "first pass",
                    "feedback": ["PH-0001"],
                    "comments": [
                        {"id": "c-1", "author": "lumen", "quote": "Have you ever wondered", "text": "No question."},
                        {"id": "c-2", "author": "lumen", "text": "Source for 40%?"},
                    ],
                }
            ],
        }
    ],
    "entries": [
        {
            "id": "PH-0001",
            "notebook": "voice",
            "title": "No opening question",
            "date": "2026-09-14",
            "post": "northwind-launch",
            "said": [
                {"text": "Do not open with a rhetorical question."},
                {"text": "Again an opening question.", "date": "2026-09-21", "note": "post northwind-pricing"},
            ],
            "agent_wrote": "Have you ever wondered why stock runs out?",
            "agent_note": "label in the image",
            "agent_after": 1,
            "person_fixed": "Last week the Northwind store ran out of stock at 3 a.m.",
            "fixed_after": 1,
            "rule": "The first sentence is a fact, never a question.",
            "check": "machine: the first sentence does not end with a question mark",
            "seen": 2,
        },
        {
            "id": "PH-0002",
            "notebook": "facts",
            "title": "Dates are absolute",
            "date": "2026-09-15",
            "said": [{"text": "Write the day, not last Tuesday."}],
            "rule": "Write a date as a day.",
            "seen": 1,
        },
        {
            "id": "PH-0003",
            "notebook": "voice",
            "title": "Every figure has a source",
            "date": "2026-09-20",
            "said": [{"text": "Where does this number come from?"}],
            "rule": "Each figure links its source.",
            "seen": 1,
        },
    ],
}

POST_KEYS = {"slug", "title", "stage", "waiting_gate", "run", "gates", "rounds", "preview_url", "url"}
GATE_KEYS = {"stage", "kind", "state", "answered_at", "answered_via"}


@pytest.fixture
def client(hub_db, tmp_path, github, tasks_core):  # noqa: F811
    """The hub, which answers MCP at its public url."""
    config = live.hub_config(hub_db, tmp_path, github, public_url="https://hub.test")
    with TestClient(create_app(config), base_url="https://hub.test") as client:
        yield client


@pytest.fixture
def editorial(client, members):  # noqa: F811
    enable(client, members["owner"], "editorial")
    configure(client, members["owner"], "editorial", CONFIG)
    return members


def ok(answer, status: int = 200):
    assert answer.status_code == status, answer.text
    return answer.json()


def imported(client, headers) -> dict:
    return ok(client.post(f"{BASE}/import", json={"file": json.dumps(DOCUMENT)}, headers=headers))


def project_id(db) -> int:
    return sql(db, select(tables.projects.c.id).where(tables.projects.c.name == PROJECT))[0][0]


def test_editorial_manifest_runs_no_job_and_asks_for_api_1_4():
    found = manifest()
    contributes = found["contributes"]
    assert not contributes.get("jobs") and found["permissions"] == [] and found["version"] == "1.1.0"
    assert [p["name"] for p in contributes["pages"]] == ["posts", "feedback"]
    assert [t["name"] for t in contributes["mcp_tools"]] == ["state", "recall", "feedback", "comments"]
    types = {t["name"]: t for t in contributes["agent_types"]}
    assert set(types) == {"writer", "editor-judge"} and all(t["mentioned_by"] == "admin" for t in types.values())
    assert "next gate, then stop" in types["writer"]["profile"]["instructions"]
    assert types["writer"]["events"] == ["results"] and types["editor-judge"]["events"] == ["answers"]
    assert {e["name"]: e["on"] for e in contributes["events"]} == {
        "results": ["task.result"],
        "answers": ["agent.answer"],
    }
    assert [k["name"] for k in contributes["notice_kinds"]] == ["editorial_gate", "editorial_failed"]
    assert [k["name"] for k in contributes["kg_sources"]] == ["notebook"]
    assert [t["name"] for t in contributes["tables"]] == list(editorial_tables.NAMES)
    assert {c["name"] for c in contributes["cli"]} == {"posts", "show", "set", "recall", "feedback", "import", "export"}
    assert hub_api.plugin("evo_core_plugins.editorial.settings").id == "editorial"


def test_editorial_its_migration_makes_the_tables_its_metadata_holds(client, editorial, hub_db):
    with live.engine(hub_db).begin() as conn:
        assert hub_api.adopt_tables(conn, editorial_tables.metadata, list(editorial_tables.NAMES)) == []


def test_editorial_a_project_that_does_not_enable_it_answers_404(client, members):
    assert client.get(f"{BASE}/posts", headers=members["owner"]).status_code == 404
    assert client.post(f"{BASE}/posts/x", json={"stage": "idea"}, headers=members["owner"]).status_code == 404


def test_editorial_a_writer_moves_a_post_through_the_stages_and_answers_its_gates(client, editorial):
    alice, eve = editorial["alice"], editorial["eve"]
    assert ok(client.get(f"{BASE}/posts", headers=eve)) == []
    assert client.post(f"{BASE}/posts/lumen-notes", json={"stage": "idea"}, headers=eve).status_code == 403
    assert client.post(f"{BASE}/posts/lumen-notes", json={"stage": "nowhere"}, headers=alice).status_code == 422
    assert client.post(f"{BASE}/posts/lumen-notes", json={"title": "x"}, headers=alice).status_code == 422
    made = ok(client.post(f"{BASE}/posts/lumen-notes", json={"stage": "idea", "title": "Notes"}, headers=alice))
    assert made["waiting_gate"] == "idea" and [(g["stage"], g["kind"], g["state"]) for g in made["gates"]] == [
        ("idea", "choose", "waiting")
    ]
    answered = {"gate": "idea", "gate_state": "answered", "via": "telegram", "answer": {"option": 1}}
    shown = ok(client.post(f"{BASE}/posts/lumen-notes", json=answered, headers=alice))
    gate = shown["gates"][0]
    assert shown["waiting_gate"] is None and gate["answered_via"] == "telegram" and gate["answered_by"] == "alice"
    assert gate["answer"] == {"option": 1} and gate["answered_at"]
    assert (
        client.post(
            f"{BASE}/posts/lumen-notes", json={"gate": "ship", "gate_state": "answered"}, headers=alice
        ).status_code
        == 404
    )
    ok(client.post(f"{BASE}/posts/lumen-notes", json={"stage": "draft", "evidence": "draft pushed"}, headers=alice))
    moved = ok(
        client.post(
            f"{BASE}/posts/lumen-notes",
            json={"stage": "review", "preview_url": "https://preview.example.org/lumen-notes", "d7": '{"views": 12}'},
            headers=alice,
        )
    )
    assert [h["stage"] for h in moved["history"]] == ["idea", "draft", "review"]
    assert moved["history"][1]["evidence"] == "draft pushed" and moved["d7"] == {"views": 12}
    listed = ok(client.get(f"{BASE}/posts", headers=eve))
    assert [set(p) for p in listed] == [POST_KEYS] and all(set(g) == GATE_KEYS for g in listed[0]["gates"])
    assert listed[0]["waiting_gate"] == "review" and listed[0]["preview_url"].endswith("lumen-notes")
    assert listed[0]["rounds"] == 0 and [g["stage"] for g in listed[0]["gates"]] == ["idea", "review"]
    assert ok(client.get(f"{BASE}/posts", params={"stage": "idea"}, headers=eve)) == []
    text = ok(client.get(f"{BASE}/posts", params={"render": "text"}, headers=eve))["text"]
    assert "lumen-notes" in text and "review" in text


def test_editorial_import_keeps_the_ids_and_a_second_run_adds_nothing(client, editorial):
    owner, alice, eve = editorial["owner"], editorial["alice"], editorial["eve"]
    assert client.post(f"{BASE}/import", json={"file": json.dumps(DOCUMENT)}, headers=alice).status_code == 403
    first = imported(client, owner)
    assert first == {"posts_added": 1, "posts_updated": 0, "entries_added": 3, "entries_updated": 0}
    again = imported(client, owner)
    assert again == {"posts_added": 0, "posts_updated": 1, "entries_added": 0, "entries_updated": 3}
    entries = ok(client.get(f"{BASE}/feedback", headers=eve))
    assert [e["id"] for e in entries] == ["PH-0001", "PH-0002", "PH-0003"]
    post = ok(client.get(f"{BASE}/posts/northwind-launch", headers=eve))
    assert [(g["stage"], g["state"], g["answered_via"]) for g in post["gates"]] == [
        ("idea", "answered", "telegram"),
        ("review", "waiting", None),
    ]
    assert len(post["rounds"]) == 1 and [c["id"] for c in post["rounds"][0]["comments"]] == ["c-1", "c-2"]
    assert post["rounds"][0]["feedback"] == ["PH-0001"] and post["feedback"] == ["PH-0001"]
    assert [h["stage"] for h in post["history"]] == ["idea", "draft", "review"]
    listed = ok(client.get(f"{BASE}/posts", headers=eve))
    assert listed[0]["rounds"] == 1 and listed[0]["waiting_gate"] == "review"
    wrong = {**DOCUMENT, "entries": [{**DOCUMENT["entries"][0], "notebook": "elsewhere"}]}
    refused = client.post(f"{BASE}/import", json={"document": wrong}, headers=owner)
    assert refused.status_code == 422 and "elsewhere" in refused.text
    assert client.post(f"{BASE}/import", json={"file": "{"}, headers=owner).status_code == 422


def test_editorial_export_prints_a_notebook_exactly_as_it_was_kept(client, editorial):
    imported(client, editorial["owner"])
    found = ok(client.get(f"{BASE}/export", params={"notebook": "voice"}, headers=editorial["eve"]))
    assert found["format"] == "markdown" and [b["file"] for b in found["notebooks"]] == ["voice.md"]
    assert found["notebooks"][0]["markdown"] == VOICE
    every = ok(client.get(f"{BASE}/export", headers=editorial["eve"]))
    assert [b["name"] for b in every["notebooks"]] == ["voice", "facts", "style"]
    data = ok(client.get(f"{BASE}/export", params={"format": "json"}, headers=editorial["eve"]))["document"]
    assert [e["id"] for e in data["entries"]] == ["PH-0001", "PH-0002", "PH-0003"]
    assert data["posts"][0]["slug"] == "northwind-launch"
    again = ok(client.post(f"{BASE}/import", json={"document": data}, headers=editorial["owner"]))
    assert again["entries_added"] == 0 and again["posts_added"] == 0
    after = ok(client.get(f"{BASE}/export", params={"notebook": "voice"}, headers=editorial["eve"]))
    assert after["notebooks"][0]["markdown"] == VOICE


def test_editorial_feedback_adds_counts_repeats_filters_and_recalls(client, editorial):
    imported(client, editorial["owner"])
    alice, eve = editorial["alice"], editorial["eve"]
    new = {"title": "Short headings", "said": "Headings over six words are too long.", "rule": "Six words at most."}
    assert client.post(f"{BASE}/feedback", params={"notebook": "style"}, json=new, headers=eve).status_code == 403
    assert client.post(f"{BASE}/feedback", params={"notebook": "nowhere"}, json=new, headers=alice).status_code == 422
    assert (
        client.post(f"{BASE}/feedback", params={"notebook": "style"}, json={"said": "x"}, headers=alice).status_code
        == 422
    )
    added = ok(
        client.post(f"{BASE}/feedback", params={"notebook": "style", "action": "add"}, json=new, headers=alice), 201
    )
    assert [(e["id"], e["notebook"], e["seen"]) for e in added] == [("PH-0004", "style", 1)]
    repeated = ok(
        client.post(f"{BASE}/feedback/PH-4/repeat", json={"said": "Still long.", "date": "2026-10-01"}, headers=alice)
    )
    assert repeated[0]["seen"] == 2 and repeated[0]["said"][-1] == {
        "text": "Still long.",
        "date": "2026-10-01",
        "note": None,
    }
    assert ok(client.post(f"{BASE}/feedback/PH-0002/repeat", json={}, headers=alice))[0]["seen"] == 2
    assert client.post(f"{BASE}/feedback/PH-0099/repeat", json={}, headers=alice).status_code == 404
    assert client.get(f"{BASE}/feedback", params={"action": "add"}, headers=eve).status_code == 422

    def ids(path: str, **query) -> list[str]:
        return [e["id"] for e in ok(client.get(f"{BASE}/{path}", params=query, headers=eve))]

    assert ids("feedback", notebook="voice") == ["PH-0001", "PH-0003"]
    assert ids("feedback", stage="idea") == ["PH-0001", "PH-0003", "PH-0004"]
    assert ids("feedback", post="northwind-launch") == ["PH-0001"]
    assert ids("feedback", seen=2) == ["PH-0001", "PH-0002", "PH-0004"]
    assert ids("feedback", q="SOURCE figure") == ["PH-0003"]
    assert ids("recall", stage="draft") == ["PH-0001", "PH-0002", "PH-0004", "PH-0003"]
    assert ids("recall", stage="review", post="northwind-launch") == ["PH-0001", "PH-0004"]
    assert ids("recall", stage="idea", q="question") == ["PH-0001"]
    assert client.get(f"{BASE}/recall", params={"stage": "nowhere"}, headers=eve).status_code == 422


def test_editorial_a_label_above_the_grant_hides_a_post_and_an_entry(client, editorial, hub_db):
    imported(client, editorial["owner"])
    p, f = editorial_tables.posts, editorial_tables.feedback
    secret = {"level": "restricted", "location": "any"}
    sql(hub_db, update(p).where(p.c.slug == "northwind-launch").values(label=secret))
    sql(hub_db, update(f).where(f.c.number == 3).values(label=secret))
    eve = editorial["eve"]
    assert ok(client.get(f"{BASE}/posts", headers=eve)) == []
    assert client.get(f"{BASE}/posts/northwind-launch", headers=eve).status_code == 404
    assert [e["id"] for e in ok(client.get(f"{BASE}/feedback", headers=eve))] == ["PH-0001", "PH-0002"]
    assert ok(client.get(f"{BASE}/feedback", headers=editorial["outsider"])) == []  # the default label is internal


def test_editorial_the_graph_source_gives_one_item_per_entry_and_per_post(client, editorial, hub_db):
    imported(client, editorial["owner"])
    context = CoreContext("editorial", client.app.state.engine, None, PROJECT, project_id(hub_db))
    answered = client.portal.call(lambda: editorial_kg.kg_source({"source": "plugin.editorial"}, context))
    items = {item["id"]: item for item in answered["items"]}
    assert set(items) == {
        "plugin.editorial:feedback:PH-0001",
        "plugin.editorial:feedback:PH-0002",
        "plugin.editorial:feedback:PH-0003",
        "plugin.editorial:post:northwind-launch",
    }
    entry = items["plugin.editorial:feedback:PH-0001"]
    assert entry["title"] == "PH-0001 No opening question" and entry["props"]["notebook"] == "voice"
    assert entry["fragments"][0]["text"] in VOICE and entry["label"]["level"]
    assert "gate review (comments): waiting" in items["plugin.editorial:post:northwind-launch"]["fragments"][0]["text"]


def mcp(client, headers, name: str, arguments: dict | None = None) -> tuple:
    result = rpc(client, headers, call(9, name, arguments or {}))
    text = result["content"][0]["text"]
    return (text if result["isError"] else json.loads(text)), result["isError"]


def test_editorial_tools_answer_what_the_routes_answer_for_the_caller(client, editorial):
    imported(client, editorial["owner"])
    alice, eve = editorial["alice"], editorial["eve"]
    assert {"editorial__state", "editorial__recall", "editorial__feedback"} <= set(tool_names(client, eve))
    listed, error = mcp(client, eve, "editorial__state")
    assert not error and listed == ok(client.get(f"{BASE}/posts", headers=eve))
    one, _ = mcp(client, eve, "editorial__state", {"slug": "northwind-launch"})
    assert one == ok(client.get(f"{BASE}/posts/northwind-launch", headers=eve))
    text, error = mcp(client, eve, "editorial__state", {"slug": "northwind-launch", "set": {"stage": "ship"}})
    assert error and "writer" in text
    moved, error = mcp(client, alice, "editorial__state", {"slug": "northwind-launch", "set": {"stage": "ship"}})
    assert not error and moved["stage"] == "ship" and moved["waiting_gate"] == "ship"
    recalled, _ = mcp(client, eve, "editorial__recall", {"stage": "draft", "keyword": "date"})
    assert [e["id"] for e in recalled] == ["PH-0002"]
    added, error = mcp(
        client,
        alice,
        "editorial__feedback",
        {"action": "add", "notebook": "facts", "title": "Units", "said": "Say km.", "rule": "Write units."},
    )
    assert not error and added["id"] == "PH-0004"
    again, _ = mcp(client, alice, "editorial__feedback", {"action": "repeat", "entry": "PH-0004", "said": "km!"})
    assert again["seen"] == 2 and again["said"][-1]["text"] == "km!"
    text, error = mcp(client, alice, "editorial__feedback", {"action": "repeat"})
    assert error and "PH-<n>" in text


def test_editorial_pages_read_at_a_narrow_screen():
    from pathlib import Path

    import evo_core_plugins.editorial as package

    pages = Path(package.__file__).with_name("ui") / "pages"
    for name in ("posts", "feedback"):
        html = (pages / f"{name}.html").read_text(encoding="utf-8")
        assert 'name="viewport" content="width=device-width, initial-scale=1"' in html and f"{name}.js" in html
    assert (pages / "i18n" / "en.js").exists() and (pages / "i18n" / "vi.js").exists()
