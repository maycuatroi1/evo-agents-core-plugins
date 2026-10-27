"""Graph review of the plugin jev: the hourly job reads the open items of the rules possible_duplicate and
ambiguous_match through the API, asks Jev about each once and merges, dismisses, proposes or only suggests
(``evo_core_plugins.jev.review``), against a fake Jev server. The graph is a small fixed queue (as the API's own
tests have it); the decisions, the dismissals and the plugin's tables are real. All names are fictional.
"""

from __future__ import annotations

import pytest

from tests.hub import pg

if not pg.DSN:
    pytest.skip(pg.SKIP_REASON, allow_module_level=True)

from sqlalchemy import select

from evo_agents.hub import tables
from evo_agents.hub.plugin_calls import CoreContext
from evo_agents.hub.server.core_plugin_api import _decision as decision
from evo_core_plugins.jev import review
from plugin_tests.test_jev_plugin import (  # noqa: F401 (fixtures)
    BASE,
    MODEL,
    PROJECT,
    client,
    configure,
    count,
    enabled,
    fake,
    jev,
    jev_tables,
    members,
    ok,
    project_id,
    sql,
    tasks_core,
    untouched,
)

DUP, DUP2, MATCH, MENTION = "r:dup0000000000001", "r:dup0000000000002", "r:match00000000001", "r:mention000000001"


def node(ident: str, kind: str, name: str) -> dict:
    return {"id": ident, "kind": kind, "name": name}


def item(fingerprint: str, rule: str, nodes: list[dict], samples: list[str] | None = None) -> dict:
    return {
        "fingerprint": fingerprint,
        "rule": rule,
        "action": "merge",
        "cluster": None,
        "cluster_label": None,
        "nodes": nodes,
        "detail": {"samples": samples or []},
        "weight": 1,
    }


QUEUE = {
    "computed": True,
    "reason": None,
    "items": [
        item(
            DUP,
            "possible_duplicate",
            [node("northwind:doc:a", "Document", "Lumen guide"), node("northwind:doc:b", "Document", "lumen guide")],
            ["the Lumen guide of Northwind"],
        ),
        item(
            DUP2,
            "possible_duplicate",
            [node("northwind:doc:c", "Document", "Pricing"), node("northwind:doc:d", "Document", "pricing")],
        ),
        item(
            MATCH,
            "ambiguous_match",
            [
                node("northwind:doc:a", "Document", "Lumen guide"),
                node("northwind:file:x", "File", "docs/guide.md"),
                node("northwind:file:y", "File", "docs/guide.md"),
            ],
        ),
        item(MENTION, "ambiguous_match", [node("northwind:doc:a", "Document", "Lumen guide")]),
    ],
    "props": {},
}


@pytest.fixture
def graph(monkeypatch):
    """The newest graph of the project: ``QUEUE`` for the review, every node visible for a decision."""
    seen = {"reads": 0, "queue": QUEUE}

    async def fake_graph(conn, config, project_id, project, rules, sink, reader):
        if reader is decision._queue:
            seen["reads"] += 1
            return seen["queue"], None
        return {
            **{f"northwind:doc:{x}": "visible" for x in "abcd"},
            **{f"northwind:file:{x}": "visible" for x in "xy"},
        }, None

    monkeypatch.setattr(decision, "_graph", fake_graph)
    return seen


def only(graph, *fingerprints: str) -> None:
    graph["queue"] = {**QUEUE, "items": [i for i in QUEUE["items"] if i["fingerprint"] in fingerprints]}


def says(fake, *, noul: float | None = None, choice: str | None = None, confidence: float = 0.95) -> None:
    def answer(question: dict) -> dict:
        if question["type"] == "noul":
            return {"type": "noul", "noul": noul}
        return {"type": "choice", "choice": choice, "confidence": confidence, "probabilities": {choice: confidence}}

    fake.answer = answer


def run(client, hub_db) -> dict:
    context = CoreContext("jev", client.app.state.engine, client.app.state.config, PROJECT, project_id(hub_db))
    return client.portal.call(lambda: review.on_job({"projects": [PROJECT]}, context))


def decisions(hub_db) -> list:
    d, e = tables.kg_decisions, tables.kg_decision_events
    query = (
        select(d.c.number, d.c.kind, d.c.state, d.c.src, d.c.dst, e.c.actor_plugin, e.c.reason)
        .select_from(d.join(e, e.c.decision_id == d.c.id))
        .order_by(d.c.number)
    )
    return sql(hub_db, query)


def dismissals(hub_db) -> list:
    d = tables.kg_review_dismissals
    return sql(hub_db, select(d.c.fingerprint, d.c.reason, d.c.dismissed_by_plugin).order_by(d.c.fingerprint))


def acts(hub_db) -> list:
    a = jev_tables.acts.c
    return sql(hub_db, select(a.kind, a.target, a.applied, a.confidence).order_by(a.id))


def test_jev_review_merges_two_nodes_over_the_noul_threshold_and_a_writer_can_undo_it(client, jev, hub_db, fake, graph):
    configure(client, jev["owner"], "jev", {"kg_review_mode": "apply"})
    only(graph, DUP)
    says(fake, noul=0.97)
    assert run(client, hub_db) == {PROJECT: {"asked": 1, "applied": 1, "proposed": 0}}
    ((number, kind, state, src, dst, plugin, reason),) = decisions(hub_db)
    assert (number, kind, state, plugin) == (1, "merge", "active", "jev")
    assert {src, dst} == {"northwind:doc:a", "northwind:doc:b"}
    assert MODEL in reason and "0.97" in reason
    (body,) = fake.bodies()
    assert body["questions"]["same"]["type"] == "noul" and "Lumen guide" in body["state"]
    assert acts(hub_db) == [("merge", "decision:1", True, 0.97)]
    undo = ok(client.get(f"{BASE}/acts", headers=jev["alice"]))["acts"][0]["undo"]
    assert undo["path"] == f"/v1/kg/{PROJECT}/decisions/1/undo" and "decisions undo 1" in undo["command"]


def test_jev_review_dismisses_a_clear_no_and_proposes_what_lies_between(client, jev, hub_db, fake, graph):
    configure(client, jev["owner"], "jev", {"kg_review_mode": "apply"})
    only(graph, DUP, DUP2)
    answers = iter([0.05, 0.5])
    fake.answer = lambda question: {"type": "noul", "noul": next(answers)}
    assert run(client, hub_db) == {PROJECT: {"asked": 2, "applied": 1, "proposed": 1}}
    ((fingerprint, reason, plugin),) = dismissals(hub_db)
    assert (fingerprint, plugin) == (DUP, "jev") and MODEL in reason and "0.05" in reason
    ((number, kind, state, *_),) = decisions(hub_db)
    assert (kind, state) == ("merge", "proposed")
    assert [(a[0], a[2]) for a in acts(hub_db)] == [("dismiss", True), ("merge", False)]
    undo = ok(client.get(f"{BASE}/acts", headers=jev["alice"]))["acts"]
    assert {a["kind"]: a["undo"] and a["undo"]["path"] for a in undo} == {
        "dismiss": f"/v1/kg/{PROJECT}/review/{DUP}/dismiss",
        "merge": None,
    }


def test_jev_review_suggest_mode_only_proposes(client, jev, hub_db, fake, graph):
    configure(client, jev["owner"], "jev", {"kg_review_mode": "suggest"})
    only(graph, DUP, DUP2)
    answers = iter([0.99, 0.01])
    fake.answer = lambda question: {"type": "noul", "noul": next(answers)}
    run(client, hub_db)
    assert [(d[2]) for d in decisions(hub_db)] == ["proposed"]
    assert dismissals(hub_db) == []
    assert [a[2] for a in acts(hub_db)] == [False, False]


def test_jev_review_asks_a_fingerprint_once_for_each_model(client, jev, hub_db, fake, graph):
    configure(client, jev["owner"], "jev", {"kg_review_mode": "suggest"})
    only(graph, DUP)
    says(fake, noul=0.5)
    run(client, hub_db)
    run(client, hub_db)
    assert len(fake.requests) == 1 and count(hub_db, jev_tables.asked) == 1
    sql(hub_db, jev_tables.asked.update().values(model="jev-0.9.0"))
    run(client, hub_db)  # the decision is there: the second ask is refused by the hub, and booked as skipped
    assert len(fake.requests) == 2
    assert [a[0] for a in acts(hub_db)] == ["merge", "skipped"]


def test_jev_review_stops_applying_at_the_daily_cap(client, jev, hub_db, fake, graph):
    configure(client, jev["owner"], "jev", {"kg_review_mode": "apply", "kg_review_cap": 1})
    only(graph, DUP, DUP2)
    says(fake, noul=0.99)
    assert run(client, hub_db) == {PROJECT: {"asked": 2, "applied": 1, "proposed": 1}}
    assert [d[2] for d in decisions(hub_db)] == ["active", "proposed"]


def test_jev_review_an_ambiguous_match_is_dismissed_only_when_jev_confirms_the_target_the_edge_has(
    client, jev, hub_db, fake, graph
):
    configure(client, jev["owner"], "jev", {"kg_review_mode": "apply"})
    only(graph, MATCH, MENTION)
    says(fake, choice="northwind:file:y")  # another target: no link can be taken, so a suggestion
    assert run(client, hub_db) == {PROJECT: {"asked": 1, "applied": 0, "proposed": 0}}
    assert dismissals(hub_db) == [] and decisions(hub_db) == []
    (body,) = fake.bodies()
    options = body["questions"]["target"]["criteria"]
    assert set(options) == {"northwind:file:x", "northwind:file:y", "unsure"}, "the mention of one node is not asked"
    sql(hub_db, jev_tables.asked.delete())
    says(fake, choice="northwind:file:x")
    run(client, hub_db)
    ((fingerprint, reason, _),) = dismissals(hub_db)
    assert fingerprint == MATCH and "0.95" in reason


def test_jev_review_a_failed_call_skips_the_item_and_is_not_repeated(client, jev, hub_db, fake, graph):
    configure(client, jev["owner"], "jev", {"kg_review_mode": "apply"})
    only(graph, DUP)
    fake.status = 502
    run(client, hub_db)
    fake.status = 200
    run(client, hub_db)
    assert len(fake.requests) == 1 and decisions(hub_db) == [] and dismissals(hub_db) == []
    assert [(a[0], a[2]) for a in acts(hub_db)] == [("skipped", False)]


def test_jev_review_does_nothing_while_the_feature_is_off(client, jev, hub_db, fake, graph):
    assert run(client, hub_db) == {}
    assert graph["reads"] == 0
    untouched(fake, hub_db)
