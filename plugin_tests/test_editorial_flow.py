"""The flow of the core plugin editorial on the hub (``evo_core_plugins.editorial.flow``): gates, the writer agent, the
judge, the reviewers' draft comments and the probes of the notebook's rules.

A gate that opens sends its notice to the gatekeepers with the link of the post's page; an answer there is kept with
answered_via hub and hands the agent type writer a task on the post's branch, one at a time; a run that ends short of a
gate is followed by the next, and one that fails or is refused shows on the post and sends a notice. A review round
asks editor-judge, blind, and its scores decide the machine gate of an approval. The comments of the configured
reviewers come from the comment service (faked here) into the round, each once. An entry's probe renders the rule
file with and without its rule. All names are fictional.
"""

from __future__ import annotations

import pytest

from tests.hub import pg

if not pg.DSN:
    pytest.skip(pg.SKIP_REASON, allow_module_level=True)

from sqlalchemy import func, select, update

from evo_agents.hub import tables
from evo_agents.hub.plugin_calls import CoreContext
from evo_core_plugins.editorial import events, flow, judge, marginalia, probes
from plugin_tests.test_editorial_plugin import BASE, CONFIG, client, editorial, ok, project_id  # noqa: F401
from tests.hub import live
from tests.hub.live import sql
from tests.hub.test_chat_runs import chat_worker
from tests.hub.test_tasks_plugin import PROJECT, configure, members, tasks_core  # noqa: F401 (fixtures)

FLOW = {
    **CONFIG,
    "repo": "evo-agents",
    "comments": {"project_id": "lumen-blog", "api_key": "public-web-key-of-lumen", "collection": "marginalia_comments"},
}
CHECKOUTS = {f"{PROJECT}/evo-agents": {"path": "/src/evo-agents", "branch": "main"}}
PAGE = f"/p/{PROJECT}/x/editorial/posts/northwind-notes"


def doc(name: str, author: str, body: str, *, quote: str | None = None, at: str, parent: str | None = None) -> dict:
    """A comment as Firestore's REST API answers it."""
    fields = {
        "postId": {"stringValue": "draft:northwind-notes"},
        "body": {"stringValue": body},
        "status": {"stringValue": "visible"},
        "createdAt": {"timestampValue": at},
        "author": {"mapValue": {"fields": {"name": {"stringValue": author}}}},
    }
    if quote is not None:
        fields["anchor"] = {"mapValue": {"fields": {"exact": {"stringValue": quote}}}}
    if parent is not None:
        fields["parentId"] = {"stringValue": parent}
    return {"name": f"projects/lumen-blog/databases/(default)/documents/marginalia_comments/{name}", "fields": fields}


DOCUMENTS = [
    doc("m-2", "Lumen", "Source for 40%?", quote="Sales rose 40%", at="2026-10-20T09:05:00Z"),
    doc("m-1", "lumen", "No opening question.", quote="Have you ever wondered", at="2026-10-20T09:00:00Z"),
    doc("m-3", "Passerby", "Nice post!", at="2026-10-20T09:10:00Z"),
    doc("m-4", "Lumen", "Thanks, fixed.", at="2026-10-20T09:20:00Z", parent="m-2"),
]


@pytest.fixture
def fetched(monkeypatch) -> list:
    """The comment service, faked: what it was asked, and DOCUMENTS as its answer."""
    asked = []

    async def fake(service, key):
        asked.append((service.project_id, service.api_key, service.collection, key))
        return DOCUMENTS

    monkeypatch.setattr(marginalia, "FETCH", fake)
    return asked


@pytest.fixture
def flowing(client, editorial, fetched):  # noqa: F811
    """The project with the flow on: the repo of posts and the comment service in the config, the writer enabled
    under alice with a $5 cap."""
    configure(client, editorial["owner"], "editorial", FLOW)
    put_type(client, editorial["owner"], flow.WRITER)
    laptop = chat_worker(client, editorial["alice"], "laptop", checkouts=CHECKOUTS)
    return {**editorial, "laptop": laptop}


def put_type(client, headers, name: str, **body) -> dict:  # noqa: F811
    body = {"run_as": "alice", "daily_usd": 5} | body
    return ok(client.put(f"/v1/projects/{PROJECT}/agent-types/editorial/{name}", json=body, headers=headers))


def context(client, db) -> CoreContext:  # noqa: F811
    return CoreContext("editorial", client.app.state.engine, None, PROJECT, project_id(db))


def deliver(client, db, handler, kind: str, payload: dict) -> dict:  # noqa: F811
    params = {"event": kind, "kind": kind, "project": PROJECT, "payload": {"project": PROJECT, **payload}}
    return client.portal.call(lambda: handler(params, context(client, db)))


def ended(client, db, run_id: int, state: str = "done", **more) -> dict:  # noqa: F811
    """The run is over, as the hub keeps it, and its task.result reaches the plugin."""
    with live.engine(db).begin() as conn:
        worker = sql(db, select(tables.workers.c.id).where(tables.workers.c.name == "laptop"))[0][0]
        over = {"state": state, "finished_at": func.now(), "worker_id": worker, "runtime": "claude-code"}
        over |= {"leased_at": func.now(), "started_at": func.now()}
        if state == "failed":
            over |= {"failure_cause": more.get("failure_cause", "agent_error"), "error": "the agent stopped"}
        conn.execute(update(tables.runs).where(tables.runs.c.id == run_id).values(**over))
    payload = {"task_id": run_id, "run_id": run_id, "agent_type": flow.WRITER, "state": state, **more}
    return deliver(client, db, events.on_task_result, events.RESULT_EVENT, payload)


def run_row(db, run_id: int) -> dict:
    r = tables.runs
    found = sql(db, select(r.c.kind, r.c.state, r.c.repos, r.c.title, r.c.request).where(r.c.id == run_id))
    return dict(zip(("kind", "state", "repos", "title", "request"), found[0], strict=True))


def notices(db, kind: str) -> list[tuple]:
    n, u = tables.notifications, tables.users
    query = (
        select(u.c.login, n.c.title, n.c.link, n.c.details)
        .join(u, u.c.id == n.c.user_id)
        .where(n.c.notice_kind == kind)
        .order_by(n.c.id)
    )
    return sql(db, query)


def post(client, headers, slug: str = "northwind-notes", **body) -> dict:  # noqa: F811
    return ok(client.post(f"{BASE}/posts/{slug}", json=body, headers=headers))


def test_editorial_flow_gate_notice_answer_on_the_page_and_the_writer_runs_to_the_next_gate(client, flowing, hub_db):
    alice, owner = flowing["alice"], flowing["owner"]
    made = post(client, alice, stage="idea", title="Northwind notes", ask={"options": ["Night shifts", "Pricing"]})
    assert made["waiting_gate"] == "idea" and made["run"] is None
    assert made["gates"][0]["ask"] == {"options": ["Night shifts", "Pricing"]}
    sent = notices(hub_db, flow.NOTICE_GATE)
    assert [(login, link) for login, _, link, _ in sent] == [("owner", PAGE)]  # the admins, when no gatekeeper is set
    assert sent[0][3] == {"post": "northwind-notes", "stage": "idea"}
    # the person answers on the page: kept with answered_via hub, and the writer gets the task on post/<slug>
    answered = post(client, owner, gate="idea", gate_state="answered", answer={"option": 1})
    gate = answered["gates"][0]
    assert gate["state"] == "answered" and gate["answered_via"] == "hub" and gate["answered_by"] == "owner"
    run = answered["run"]
    assert run["state"] == "running" and run["stage"] == "idea" and answered["branch"] == "post/northwind-notes"
    row = run_row(hub_db, run["run_id"])
    assert row["kind"] == "task" and {"repo": "evo-agents", "branch": "post/northwind-notes"} in row["repos"]
    assert row["title"] == "editorial northwind-notes: idea"
    # one task per post at a time
    busy = client.post(f"{BASE}/posts/northwind-notes/run", headers=alice)
    assert busy.status_code == 409 and "one task at a time" in busy.text
    # the writer moves the post on and its run ends short of a gate: the next task goes out
    post(client, alice, stage="draft", evidence="draft pushed")
    assert ended(client, hub_db, run["run_id"]) == {"post": "handed"}
    again = ok(client.get(f"{BASE}/posts/northwind-notes", headers=alice))["run"]
    assert again["run_id"] != run["run_id"] and again["state"] == "running" and again["stage"] == "draft"
    assert ended(client, hub_db, run["run_id"]) == {"post": "not a running post"}  # a second delivery does nothing
    # the next run reaches the review gate: the post waits for the person there
    post(client, alice, stage="review", preview_url="https://preview.example.org/northwind-notes")
    assert ended(client, hub_db, again["run_id"]) == {"post": "at a gate"}
    shown = ok(client.get(f"{BASE}/posts/northwind-notes", headers=alice))
    assert shown["waiting_gate"] == "review" and shown["run"]["state"] == "done"
    assert [details["stage"] for *_, details in notices(hub_db, flow.NOTICE_GATE)] == ["idea", "review"]


def test_editorial_flow_only_an_answer_through_the_hub_hands_the_writer_a_task(client, flowing, hub_db):
    alice, owner = flowing["alice"], flowing["owner"]
    post(client, alice, stage="idea", title="Lumen notes", slug="lumen-notes")
    in_session = post(client, owner, slug="lumen-notes", gate="idea", gate_state="answered", via="claude-code")
    gate = in_session["gates"][0]
    assert gate["state"] == "answered" and gate["answered_via"] == "claude-code" and in_session["run"] is None
    post(client, alice, stage="idea", title="Northwind lumen", slug="northwind-lumen")
    from_codex = post(client, owner, slug="northwind-lumen", gate="idea", gate_state="skipped", via="codex")
    assert from_codex["gates"][0]["state"] == "skipped" and from_codex["run"] is None
    on_the_page = post(client, owner, slug="lumen-notes", gate="idea", gate_state="answered", via="hub")
    assert on_the_page["gates"][0]["answered_via"] == "hub" and on_the_page["run"]["state"] == "running"
    assert run_row(hub_db, on_the_page["run"]["run_id"])["title"] == "editorial lumen-notes: idea"


def test_editorial_flow_a_failed_run_or_a_refused_task_shows_on_the_post_and_sends_a_notice(client, flowing, hub_db):
    alice, owner = flowing["alice"], flowing["owner"]
    post(client, alice, stage="idea", title="Northwind notes")
    run_id = post(client, owner, gate="idea", gate_state="answered", answer={"topic": "Night shifts"})["run"]["run_id"]
    assert ended(client, hub_db, run_id, "failed", failure_cause="no_worker") == {"post": "failed"}
    shown = ok(client.get(f"{BASE}/posts/northwind-notes", headers=alice))
    assert shown["run"]["state"] == "failed" and "no_worker" in shown["run"]["error"]
    failures = notices(hub_db, flow.NOTICE_FAILED)
    assert [(login, link) for login, _, link, _ in failures] == [("owner", PAGE)] and "failed" in failures[0][1]
    # with the writer turned off, the retry is refused by the hub: the error state and one more notice, no 5xx
    off = client.delete(f"/v1/projects/{PROJECT}/agent-types/editorial/writer", headers=owner)
    assert off.status_code == 200, off.text
    retried = ok(client.post(f"{BASE}/posts/northwind-notes/run", headers=alice))
    assert retried["run"]["state"] == "refused" and retried["run"]["error"]
    assert len(notices(hub_db, flow.NOTICE_FAILED)) == 2


def test_editorial_flow_is_off_without_a_repo_and_stops_after_max_runs_without_an_answer(client, flowing, hub_db):
    alice, owner = flowing["alice"], flowing["owner"]
    post(client, alice, stage="idea", title="Northwind notes")
    run_id = post(client, owner, gate="idea", gate_state="answered", answer={"option": 2})["run"]["run_id"]
    post(client, alice, stage="draft")
    for _ in range(flow.MAX_RUNS - 1):
        assert ended(client, hub_db, run_id) == {"post": "handed"}
        run_id = ok(client.get(f"{BASE}/posts/northwind-notes", headers=alice))["run"]["run_id"]
    assert ended(client, hub_db, run_id)["post"].startswith("not handed")
    shown = ok(client.get(f"{BASE}/posts/northwind-notes", headers=alice))
    assert shown["run"]["state"] == "failed" and f"{flow.MAX_RUNS} runs" in shown["run"]["error"]
    unset = {"values": {}, "unset": ["repo"]}  # no repo: the plugin is a tracker again
    ok(client.post(f"/v1/projects/{PROJECT}/plugins/editorial/config", json=unset, headers=owner))
    refused = client.post(f"{BASE}/posts/northwind-notes/run", headers=alice)
    assert refused.status_code == 422 and "repo" in refused.text


def test_editorial_judge_scores_a_round_blind_and_the_machine_gate_takes_four_on_every_axis(client, flowing, hub_db):
    alice, owner = flowing["alice"], flowing["owner"]
    put_type(client, owner, judge.AGENT_TYPE)
    post(client, alice, stage="draft", title="Northwind notes", comment_id="northwind-notes")
    entered = post(client, alice, stage="review", preview_url="https://preview.example.org/northwind-notes")
    (first,) = entered["rounds"]
    assert first["judge"] == {"state": "pending", "note": None, "passed": False}
    q = tables.agent_questions
    ((ref, question_id),) = sql(hub_db, select(q.c.ref, q.c.id))
    assert ref.startswith(judge.REF) and ref[len(judge.REF) :].isdigit()
    asked = judge.question("https://preview.example.org/northwind-notes", "evo-agents", "post/northwind-notes")
    assert "alice" not in asked and "Lumen" not in asked and "preview.example.org" in asked
    # an approval before the judge passed the round is refused, saying why
    early = client.post(
        f"{BASE}/posts/northwind-notes",
        json={"gate": "review", "gate_state": "answered", "answer": {"approve": True}},
        headers=owner,
    )
    assert early.status_code == 409 and "machine gate" in early.text
    below = {"question_id": question_id, "agent_type": judge.AGENT_TYPE, "state": "done"}
    text = 'Scores: {"slop": 4, "giong": 5, "nguon": 3, "hinh": 4, "why": "one figure has no source"}'
    assert deliver(client, hub_db, events.on_agent_answer, "agent.answer", {**below, "text": text}) == {
        "round": "below"
    }
    scored = ok(client.get(f"{BASE}/posts/northwind-notes", headers=alice))["rounds"][0]
    assert scored["scores"] == {"slop": 4, "giong": 5, "nguon": 3, "hinh": 4}
    assert scored["judge"]["state"] == "below" and "nguon" in scored["judge"]["note"] and not scored["judge"]["passed"]
    refused = client.post(
        f"{BASE}/posts/northwind-notes",
        json={"gate": "review", "gate_state": "answered", "answer": {"approve": True}},
        headers=owner,
    )
    assert refused.status_code == 409
    good = '{"slop": 5, "giong": 4, "nguon": 4, "hinh": 4}'
    assert deliver(client, hub_db, events.on_agent_answer, "agent.answer", {**below, "text": good}) == {
        "round": "passed"
    }
    approved = post(client, owner, gate="review", gate_state="answered", answer={"approve": True})
    assert [g["state"] for g in approved["gates"] if g["stage"] == "review"] == ["answered"]
    # an answer that reads as no score passes nothing
    assert (
        judge.parse("looks fine to me").ok is False
        and judge.parse('{"slop": 6, "giong": 4, "nguon": 4, "hinh": 4}').ok is False
    )


def test_editorial_judge_refused_without_its_type_leaves_a_note_on_the_round(client, flowing, hub_db):
    alice = flowing["alice"]
    post(client, alice, stage="draft", title="Northwind notes")
    (round_,) = post(client, alice, stage="review")["rounds"]
    assert round_["judge"]["state"] == "refused" and round_["judge"]["note"]


def test_editorial_marginalia_pulls_the_reviewers_comments_by_key_into_the_round_once(client, flowing, hub_db, fetched):
    alice, eve = flowing["alice"], flowing["eve"]
    post(client, alice, stage="draft", title="Northwind notes", comment_id="northwind-notes")
    entered = post(client, alice, stage="review")  # entering the stage pulls them
    assert fetched == [("lumen-blog", "public-web-key-of-lumen", "marginalia_comments", "draft:northwind-notes")]
    comments = entered["rounds"][0]["comments"]
    assert [(c["id"], c["author"], c["quote"], c["text"]) for c in comments] == [
        ("m-1", "lumen", "Have you ever wondered", "No opening question."),
        ("m-2", "Lumen", "Sales rose 40%", "Source for 40%?"),
        ("m-4", "Lumen", None, "(reply) Thanks, fixed."),
    ]  # the passerby's comment is left out
    pulled = ok(client.post(f"{BASE}/posts/northwind-notes/comments", headers=alice))  # the button: each once
    assert len(fetched) == 2 and [c["id"] for c in pulled["rounds"][0]["comments"]] == ["m-1", "m-2", "m-4"]
    assert client.post(f"{BASE}/posts/northwind-notes/comments", headers=eve).status_code == 403


def test_editorial_marginalia_query_and_read_take_only_visible_comments_of_the_key():
    from evo_core_plugins.editorial.settings import Comments

    body = marginalia.query(Comments("lumen-blog", "k"), "draft:northwind-notes")["structuredQuery"]
    assert body["from"] == [{"collectionId": "marginalia_comments"}]
    filters = {
        f["fieldFilter"]["field"]["fieldPath"]: f["fieldFilter"]["value"]
        for f in body["where"]["compositeFilter"]["filters"]
    }
    assert filters == {"postId": {"stringValue": "draft:northwind-notes"}, "status": {"stringValue": "visible"}}
    hidden = doc("m-9", "Lumen", "gone", at="2026-10-20T10:00:00Z")
    hidden["fields"]["status"] = {"stringValue": "hidden"}
    assert marginalia.read(hidden) is None and marginalia.key("abc") == "draft:abc"


def test_editorial_marginalia_without_a_comment_id_or_a_service_is_refused(client, flowing, hub_db):
    alice = flowing["alice"]
    post(client, alice, stage="draft", title="Northwind notes")
    assert client.post(f"{BASE}/posts/northwind-notes/comments", headers=alice).status_code == 422  # not at review
    entered = post(client, alice, stage="review")
    assert entered["rounds"][0]["comments"] == []
    refused = client.post(f"{BASE}/posts/northwind-notes/comments", headers=alice)
    assert refused.status_code == 422 and "comment_id" in refused.text


def test_editorial_probe_of_an_entry_renders_the_rule_file_with_and_without_its_rule(client, flowing, hub_db):
    alice, owner = flowing["alice"], flowing["owner"]
    first = {
        "notebook": "voice",
        "title": "No opening question",
        "said": "Do not open with a question.",
        "rule": "The first sentence is a fact.",
    }
    ok(client.post(f"{BASE}/feedback", json=first, headers=alice), 201)
    probe = {
        "probe_task": "Write the opening of a post about Northwind's night shifts in drafts/n.md.",
        "probe_verify": "! head -1 drafts/n.md | grep -q '?$'",
    }
    second = {
        "notebook": "voice",
        "title": "Figures have sources",
        "said": "Source?",
        "rule": "Each figure links its source.",
    }
    assert client.post(f"{BASE}/feedback", json={**second, **probe}, headers=alice).status_code == 403  # admins alone
    made = ok(client.post(f"{BASE}/feedback", json={**second, **probe}, headers=owner), 201)
    (entry,) = made if isinstance(made, list) else [made]
    assert entry["probe_id"] and entry["probe_task"] == probe["probe_task"] and "probe_verify" not in entry
    p = tables.curator_probes
    rows = sql(
        hub_db, select(p.c.ref, p.c.repo, p.c.verify, p.c.arms, p.c.retired_at).where(p.c.id == entry["probe_id"])
    )
    ref, repo, verify, arms, retired = rows[0]
    path = probes.path("voice")
    assert (
        ref == f"editorial:{entry['id']}"
        and repo == "evo-agents"
        and verify == probe["probe_verify"]
        and retired is None
    )
    assert "The first sentence is a fact." in arms["on"][path] and "Each figure links its source." in arms["on"][path]
    assert (
        "The first sentence is a fact." in arms["off"][path]
        and "Each figure links its source." not in arms["off"][path]
    )
    # given again: the active probe replaced; removed: retired, the entry without it
    first_id = ok(client.get(f"{BASE}/feedback", headers=owner))[0]["id"]
    again = ok(
        client.post(
            f"{BASE}/feedback/{first_id}/probe",
            json={"task": "Open a post.", "verify": "grep -q Northwind drafts/n.md"},
            headers=owner,
        )
    )
    assert again["probe_id"] and again["probe_task"] == "Open a post."
    assert client.post(f"{BASE}/feedback/{first_id}/probe", json={"remove": True}, headers=alice).status_code == 403
    removed = ok(client.post(f"{BASE}/feedback/{first_id}/probe", json={"remove": True}, headers=owner))
    assert removed["probe_id"] is None and removed["probe_task"] is None
    assert sql(hub_db, select(p.c.retired_at).where(p.c.id == again["probe_id"]))[0][0] is not None
    bad = client.post(f"{BASE}/feedback/{first_id}/probe", json={"task": "x"}, headers=owner)
    assert bad.status_code == 422 and "verify" in bad.text


def test_editorial_events_take_only_their_own_agent_type(client, flowing, hub_db):
    other = {"task_id": 999, "agent_type": "someone-else", "state": "done"}
    assert deliver(client, hub_db, events.on_task_result, events.RESULT_EVENT, other) == {}
    assert (
        deliver(client, hub_db, events.on_agent_answer, "agent.answer", {"question_id": 1, "agent_type": "writer"})
        == {}
    )
    assert ended(client, hub_db, 999) == {"post": "not a running post"}
