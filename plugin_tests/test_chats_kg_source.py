"""The history of the hub's group chats in each project's knowledge graph, through the core plugin chats
(``evo_core_plugins.chats``), as criterion a4 of plan chat-history-in-kg names it. Copied from evo-agents'
tests/hub/test_chats_kg_source.py, with its helpers from the checkout of evo-agents (conftest.py).

Checked here, on Postgres with the api and the worker in this process and moto's blob store (``tests.hub.test_kg``):
the items, labels, threads and chats the source gives for a chat of one project and one of two, where the message
goes into the graph of each with a grant on the other in its audience; a message sent while the chat had no agent is
in no graph; a thread and a chat carry the join of their messages; a new message queues a build, which the next joins;
kg_status names the newest message read. The build keeps the graph in the hub's Postgres (``kg_graph_heads`` and the
graph tables, ``evo_agents.hub.kg_graph_rows``) and writes no graph file: the rows read back hash as the build and hold
what a build in memory of the worker's corpus gives (``evo_agents.kg.build.build_rows``), and a build of unchanged
chats, by the hub or in memory, gives the same content hash. On the graph the worker built: a member with a grant on the
project in no chat sees none of it, one who joined after the agent of the other project left sees what was said since
and not the thread it went into, one taken out of the chat loses it at the next read with no build, and the edge from
what a message mentions shows only to who reads the message; the snapshot the api reads it from
(``evo_agents.hub.kg_snapshots.SnapshotCoordinator``) gives a reader in no chat none of its messages and a member those
of their chats.

Projects alpha and beta enable the plugin and grant it chats:read. Chat one (Kiwi rollout) is alice's with dave and the
agents of both; m1 is said there, the agent of beta leaves, bob joins, and dave answers m1 with m2. Chat two (Mango) has
the agent of alpha alone, chat three no agent at all.
"""

from __future__ import annotations

import asyncio
from importlib.metadata import EntryPoint
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.hub import pg

if not pg.DSN:
    pytest.skip(pg.SKIP_REASON, allow_module_level=True)

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from evo_agents.hub import kg_graph_rows, kg_snapshots, kg_sources, plugin_calls, tables
from evo_agents.hub.kg_build import worker_project
from evo_agents.hub.server import chat_graph  # the label rule of chats, which the plugin asks the hub for
from evo_agents.hub.server.chat_access import LabelProject
from evo_agents.kg.build import build_rows, verify_rows
from evo_agents.kg.snapshot_search import SnapshotSearch
from evo_agents.plugins import core
from evo_agents.plugins.core import ENTRY_POINT_GROUP
from evo_core_plugins.chats import kg as chats_kg
from tests.hub import live
from tests.hub.test_kg import (
    LEVELS,
    PROJECT,
    REGISTRATION,
    Machine,
    call_tool,
    doc,
    grant,
    open_hub,
    push,
    query,
    run_jobs,
    tool_ok,
)
from tests.hub.test_kg import build_rows as builds  # the build rows of alpha, newest first, through the api

A, B = PROJECT, "beta"
SOURCE = "plugin.chats"
CHATS = EntryPoint("chats", "evo_core_plugins.chats:manifest", ENTRY_POINT_GROUP)
RUNBOOK = "docs:doc:runbook"
INTERNAL = (1, 0)  # the clearance (level, location) of a reader of internal, the label of every item here
GRANTS = {  # login: [(project, role, max level)], beside those of tests.hub.test_kg.open_hub
    "alice": [(B, "writer", "internal")],  # made every chat and is in each
    "dave": [(B, "reader", "internal")],  # in every chat, until he is taken out of chat one
    "bob": [(A, "reader", "internal")],  # joined chat one once the agent of beta had left
    "erin": [(A, "reader", "internal")],  # in no chat
    "owner": [(A, "admin", "internal"), (B, "admin", "internal")],
}


@pytest.fixture
def plugins_core(monkeypatch):
    """The entry points of the core plugins with chats's, as the package installed declares them."""
    points = [point for point in core.entry_points(group=ENTRY_POINT_GROUP) if point.name != CHATS.name]
    monkeypatch.setattr(core, "entry_points", lambda *, group: [*points, CHATS] if group == ENTRY_POINT_GROUP else [])
    plugin_calls.core_registry.cache_clear()
    yield
    plugin_calls.core_registry.cache_clear()


def done(response, status: int = 200) -> dict | None:
    assert response.status_code == status, response.text
    return response.json() if response.content else None


@pytest.fixture
def hub(hub_db, tmp_path, s3, plugins_core):
    """Projects alpha and beta, each with a knowledge config pushed from a machine and a first build, enabling chats
    with chats:read; the members of GRANTS."""
    client, found = open_hub(hub_db, tmp_path, s3)
    try:
        registration = {**REGISTRATION, "harness": {**REGISTRATION["harness"], "name": B, "path": f"{B}-harness"}}
        done(client.put(f"/v1/projects/{B}", json=registration, headers=found.admin))
        for login, grants in GRANTS.items():
            for project, role, level in grants:
                grant(client, found.admin, login, role, level, project)
            if not hasattr(found, login):
                setattr(found, login, live.bearer(live.insert_token(hub_db, login)))
        for project in (A, B):
            body = {"permissions": ["chats:read"]}
            done(client.post(f"/v1/projects/{project}/plugins/chats/enable", json=body, headers=found.owner))
            machine = Machine(tmp_path, f"laptop-{project}", project)
            machine.sync("docs", {**doc("runbook", "How to roll back."), "path": "docs/runbook.md"})
            assert push(found, machine).ok
        run_jobs(hub_db, s3, found.worker_dir)
        yield found
    finally:
        client.__exit__(None, None, None)


def chat(hub, title: str, agents: list[str]) -> int:
    body = {"title": title, "people": ["dave"], "agents": agents}
    return done(hub.client.post("/v1/chats", json=body, headers=hub.alice), 201)["id"]


def say(hub, chat_id: int, member: str, text: str, reply_to: int | None = None) -> dict:
    body = {"body": text, "reply_to": reply_to}
    return done(hub.client.post(f"/v1/chats/{chat_id}/messages", json=body, headers=getattr(hub, member)), 201)


def converse(hub) -> SimpleNamespace:
    """The chats of the module's docstring, and their messages."""
    one, two, three = chat(hub, "Kiwi rollout", [A, B]), chat(hub, "Mango", [A]), chat(hub, "Lunch", [])
    m1 = say(hub, one, "alice", "The kiwi rollout breaks the search service, see docs/runbook.md")
    done(hub.client.delete(f"/v1/chats/{one}/agents/{B}", headers=hub.alice), 204)
    done(hub.client.put(f"/v1/chats/{one}/people/bob", headers=hub.alice))
    m2 = say(hub, one, "dave", "Fixed after the search service restart, as docs/runbook.md says", reply_to=m1["id"])
    m3 = say(hub, two, "alice", "Mango picks up what the kiwi chat said")
    m0 = say(hub, three, "alice", "Kiwi tart for lunch")
    return SimpleNamespace(one=one, two=two, three=three, m0=m0, m1=m1, m2=m2, m3=m3)


def message(found) -> str:
    return f"{SOURCE}:message:{found['id']}"


def thread(chat_id: int, root: dict) -> str:
    return f"{SOURCE}:thread:{chat_id}/{root['id']}"


def source_items(hub, project: str) -> SimpleNamespace:
    """The items the source gives a build of ``project``'s graph, as the hub finishes them, by id, and its cursor."""

    async def read() -> list:
        engine = create_async_engine(
            hub.db.dsn.replace("postgresql://", "postgresql+psycopg://", 1), poolclass=NullPool
        )
        try:
            async with engine.begin() as conn:
                project_id = await conn.execute(select(tables.projects.c.id).where(tables.projects.c.name == project))
                project_id = project_id.scalar_one()
            knowledge = {"policy": {"levels": LEVELS}}
            return await kg_sources.read_sources(engine, None, project_id, project, knowledge)
        finally:
            await engine.dispose()

    (found,) = [source for source in asyncio.run(read()) if source.id == SOURCE]
    return SimpleNamespace(items={item["id"]: item for item in found.items}, cursor=found.cursor)


def make_engine(db):
    return create_async_engine(db.dsn.replace("postgresql://", "postgresql+psycopg://", 1), poolclass=NullPool)


def project_id(hub, project: str = A) -> int:
    projects = tables.projects
    return query(hub.db, select(projects.c.id).where(projects.c.name == project))[0][0]


def kept_graph(hub, project: str = A):
    """The rows of ``project``'s graph as the hub's tables keep them (``kg_graph_rows.read_graph``)."""

    async def read():
        engine = make_engine(hub.db)
        try:
            async with engine.connect() as conn:
                return await kg_graph_rows.read_graph(conn, project_id(hub, project))
        finally:
            await engine.dispose()

    return asyncio.run(read())


def head(hub, project: str = A) -> list[tuple]:
    heads = tables.kg_graph_heads
    found = select(heads.c.build_id, heads.c.content_hash).where(heads.c.project_id == project_id(hub, project))
    return query(hub.db, found)


def queued(hub) -> int:
    b = tables.kg_builds
    return query(hub.db, select(func.count()).select_from(b).where(b.c.status == "queued"))[0][0]


def node(hub, node_id: str, member: str = "alice", project: str = A):
    """kg_node of ``node_id`` in ``project`` as ``member``: the node, or None when it shows them none."""
    response = hub.client.post(
        f"/v1/kg/{project}/tools/kg_node",
        json={"arguments": {"id": node_id}, "sink": "claude-code@anthropic"},
        headers=getattr(hub, member),
    )
    result = done(response)
    return None if result.get("isError") else result["structuredContent"]["node"]


def neighbours(hub, node_id: str, member: str) -> set[str]:
    """The ids of the nodes kg_context around ``node_id`` shows ``member`` in alpha."""
    found = tool_ok(hub, "kg_context", {"ids": [node_id], "depth": 1}, member=member)["structuredContent"]
    return {n["id"] for n in found["nodes"]}


def searched(hub, text: str, member: str) -> set[str]:
    found = tool_ok(hub, "kg_search", {"query": text, "limit": 25}, member=member)["structuredContent"]
    return {n["id"] for n in found["results"]}


# The source's answer


def test_chats_source_gives_each_message_with_its_projects_part_and_the_chats_audience(hub):
    said = converse(hub)
    alpha = source_items(hub, A)
    first = alpha.items[message(said.m1)]
    assert first["kind"] == "message" and first["parent"] == thread(said.one, said.m1)
    assert first["title"].startswith(f"#{said.m1['id']} alice 20") and first["title"].endswith("Z")  # as tools call it
    assert first["body"]["text"] == said.m1["body"]  # indexed for search only: no tool returns it
    assert first["props"]["chat"] == said.one and first["props"]["thread"] == said.m1["id"]
    assert first["props"]["author_kind"] == "person" and first["props"]["author"] == "alice"
    # sent while the agent of beta was in chat one: a reader there must hold a grant on beta too
    assert first["label"] == {
        "level": "internal",
        "location": "any",
        "integrity": "U",
        "audience": [f"chat:{said.one}", f"grant:{B}:internal"],
    }
    answer = alpha.items[message(said.m2)]
    assert answer["label"]["audience"] == [f"chat:{said.one}"] and answer["parent"] == thread(said.one, said.m1)
    assert alpha.items[message(said.m3)]["label"]["audience"] == [f"chat:{said.two}"]

    # the thread and the chat carry the join of their messages in this graph
    kiwi = alpha.items[thread(said.one, said.m1)]
    assert kiwi["kind"] == "thread" and kiwi["parent"] == f"{SOURCE}:chat:{said.one}"
    assert kiwi["title"] == f"Kiwi rollout (thread {said.m1['id']})"
    assert kiwi["label"]["audience"] == [f"chat:{said.one}", f"grant:{B}:internal"]
    room = alpha.items[f"{SOURCE}:chat:{said.one}"]
    assert room["kind"] == "chat" and room["title"] == "Kiwi rollout" and room["label"] == kiwi["label"]

    # the message of two projects is in beta's graph too, with a grant on alpha in its audience; m2 and m3 are not
    beta = source_items(hub, B)
    assert beta.items[message(said.m1)]["label"]["audience"] == [f"chat:{said.one}", f"grant:{A}:internal"]
    assert message(said.m2) not in beta.items and message(said.m3) not in beta.items
    # a message sent while its chat had no agent is in no graph
    assert all(message(said.m0) not in found.items for found in (alpha, beta))
    assert not any(item_id.startswith(f"{SOURCE}:chat:{said.three}") for item_id in alpha.items)
    assert alpha.cursor == {"item": message(said.m3), "at": alpha.items[message(said.m3)]["rev_time"]}


def test_chats_message_label_reads_other_projects_as_label_reader_does():
    ladder = {name: LabelProject(1, name, LEVELS, ["any"], {"level": "internal"}, None) for name in ("alpha", "beta")}
    part = {"level": "internal", "projects": ["alpha"]}
    off_ladder = [part, {"level": "top-secret", "projects": ["beta"]}]
    assert chat_graph.message_label(off_ladder, 4, "alpha", ladder)["audience"] == ["chat:4", "grant:beta:secret"]
    assert chat_graph.message_label([part, {"level": "public", "projects": ["gone"]}], 4, "alpha", ladder) is None
    assert chat_graph.message_label([{"level": "public", "projects": ["beta"]}], 4, "alpha", ladder) is None
    assert chat_graph.message_label([], 4, "alpha", ladder) is None
    joined = chat_graph.join(
        [
            {"level": "internal", "integrity": "T", "audience": ["chat:4"]},
            {"level": "customer", "location": "any", "integrity": "U", "audience": ["chat:4", "grant:beta:public"]},
        ],
        ladder["alpha"],
    )
    assert joined == {
        "level": "customer",
        "integrity": "U",
        "location": "any",
        "projects": ["alpha"],
        "audience": ["chat:4", "grant:beta:public"],
    }


def test_chats_kg_label_carries_the_audience_and_still_drops_another_projects_label():
    levels, locations = LEVELS, ["any"]
    label = {"level": "internal", "projects": [A], "audience": ["chat:3"]}
    assert kg_sources.kg_label(label, A, levels, locations) == {
        "level": "internal",
        "integrity": "U",
        "audience": ["chat:3"],
    }
    assert kg_sources.kg_label({**label, "projects": [A, B]}, A, levels, locations) is None
    assert "audience" not in kg_sources.kg_label({"level": "internal"}, A, levels, locations)


def test_chats_kg_sources_takes_a_cursor_of_the_sources_own_item_and_a_time():
    knowledge, at = {"policy": {"levels": LEVELS}}, "2026-10-19T00:00:00Z"
    cursor = {"item": f"{SOURCE}:message:1", "at": at}
    assert kg_sources.checked(SOURCE, "chats", {"items": [], "cursor": cursor}, knowledge, A).cursor == cursor
    assert kg_sources.checked(SOURCE, "chats", {"items": []}, knowledge, A).cursor is None
    for bad in ({"item": "docs:doc:x", "at": at}, {"item": cursor["item"]}, {**cursor, "at": "now"}, "x", 5):
        with pytest.raises(kg_sources.SourceFailure):
            kg_sources.checked(SOURCE, "chats", {"items": [], "cursor": bad}, knowledge, A)


# Building


def test_chats_a_new_message_queues_a_build_whose_graph_the_hub_keeps_in_its_tables(hub):
    assert queued(hub) == 0
    said = converse(hub)
    assert queued(hub) == 2  # one build of alpha, which every later message joined, and one of beta (m1)
    run_jobs(hub.db, hub.s3, hub.worker_dir)
    built = builds(hub)[0]
    assert built["status"] == "succeeded" and built["graph_kept"]
    assert built["nodes"] is None and built["edges"] is None  # totals counting chats would tell erin they exist
    assert node(hub, message(said.m3))["kind"] == "ChatMessage"
    assert node(hub, message(said.m1), project=B)["label"]["audience"] == [f"chat:{said.one}", f"grant:{A}:internal"]

    status = tool_ok(hub, "kg_status")
    assert f"read {message(said.m3)} at " in status["content"][0]["text"]  # the newest message the build read

    # the graph is in the hub's Postgres, under the head of the build, and in no file of the worker
    assert head(hub) == [(built["id"], built["content_hash"])]
    rows = kept_graph(hub)
    assert rows.content_hash == built["content_hash"]
    ids = {row[0] for row in rows.nodes}
    chats = {message(said.m1), message(said.m2), message(said.m3), thread(said.one, said.m1)}
    assert chats | {f"{SOURCE}:chat:{said.one}", f"{SOURCE}:chat:{said.two}", RUNBOOK} <= ids
    assert message(said.m0) not in ids
    assert not list(hub.worker_dir.rglob("*.sqlite")), "the hub writes no graph file"
    assert f"chat:{said.one}" in rows.top[1] and f"chat:{said.two}" in rows.top[1]

    # a build in memory of the corpus the worker built from gives the rows the tables hold
    report, own = build_rows(worker_project(hub.worker_dir, A))
    assert report.ok and own.content_hash == rows.summary["content_hash"] == built["content_hash"]
    assert sorted(own.nodes) == sorted(rows.nodes) and sorted(own.edges) == sorted(rows.edges)
    assert own.keyed == rows.keyed and own.top == rows.top

    say(hub, said.two, "alice", "One more mango")
    assert queued(hub) == 1


def test_chats_unchanged_build_the_same_content_hash_on_the_hub_and_in_memory(hub, caplog):
    converse(hub)
    run_jobs(hub.db, hub.s3, hub.worker_dir)
    built = builds(hub)[0]
    assert built["status"] == "succeeded"

    done(hub.client.post(f"/v1/kg/{A}/builds", headers=hub.alice), 202)  # nothing changed since
    with caplog.at_level("INFO", logger="evo_agents.hub.kg_build"):
        run_jobs(hub.db, hub.s3, hub.worker_dir)
    same = builds(hub)[0]
    assert same["id"] != built["id"] and same["status"] == "succeeded" and same["graph_kept"]
    assert same["content_hash"] == built["content_hash"]
    (finished,) = [r for r in caplog.records if r.getMessage() == "kg build succeeded" and r.project == A]
    assert finished.skipped is True  # the same corpus and inputs: the rows the tables hold, built again by no one
    assert kept_graph(hub).content_hash == built["content_hash"]

    # two builds in memory of the same corpus, the second with an empty memo, hash as the hub's
    project = worker_project(hub.worker_dir, A)
    first, _ = build_rows(project)
    assert first.ok and first.content_hash == built["content_hash"]
    checked = verify_rows(project, built["content_hash"], cold=True)
    assert checked["match"], checked


# Reading the built graph


def test_chats_in_the_built_graph_show_only_to_who_reads_each_chat_now(hub):
    said = converse(hub)
    run_jobs(hub.db, hub.s3, hub.worker_dir)
    m1, m2, m3 = message(said.m1), message(said.m2), message(said.m3)
    kiwi, room = thread(said.one, said.m1), f"{SOURCE}:chat:{said.one}"

    # alice and dave are in both chats and hold grants on both projects: they read every message, thread and chat
    for member in ("alice", "dave"):
        assert all(node(hub, found, member) for found in (m1, m2, m3, kiwi, room)), member
    assert {m1, m2} <= neighbours(hub, RUNBOOK, "alice")  # what the messages mention
    assert {m1, m2} <= searched(hub, "search service", "alice")

    # erin holds a grant on alpha and is in no chat: nothing of them, by id, by search or by what they mention
    assert not any(node(hub, found, "erin") for found in (m1, m2, m3, kiwi, room))
    assert not searched(hub, "kiwi", "erin") & {m1, m2, m3, kiwi, room}
    assert not neighbours(hub, RUNBOOK, "erin") & {m1, m2}
    assert node(hub, RUNBOOK, "erin") is not None
    status = tool_ok(hub, "kg_status", member="erin")["content"][0]["text"]
    assert f"{SOURCE}" in status and "items you can read" in status and f"read {m3}" not in status

    # bob joined chat one once the agent of beta had left: he reads m2, said since, and not m1, which needs a grant
    # on beta, nor the thread and the chat, which carry m1's label too, nor the edge from what m1 mentions
    assert node(hub, m2, "bob") is not None
    assert not any(node(hub, found, "bob") for found in (m1, m3, kiwi, room))
    near = neighbours(hub, RUNBOOK, "bob")
    assert m2 in near and m1 not in near

    # dave, taken out of chat one, loses it at his next read, with no build
    done(hub.client.delete(f"/v1/chats/{said.one}/people/dave", headers=hub.alice), 204)
    assert not any(node(hub, found, "dave") for found in (m1, m2, kiwi, room))
    assert node(hub, m3, "dave") is not None
    assert call_tool(hub, "kg_node", {"id": m3}, member="carol").json()["isError"]  # carol's grant stops at public


def test_chats_the_snapshot_coordinator_shows_a_chat_only_to_a_reader_in_it(hub):
    said = converse(hub)
    run_jobs(hub.db, hub.s3, hub.worker_dir)
    built = builds(hub)[0]
    m1, m2, m3 = message(said.m1), message(said.m2), message(said.m3)
    kiwi, room = thread(said.one, said.m1), f"{SOURCE}:chat:{said.one}"
    one, two, beta = f"chat:{said.one}", f"chat:{said.two}", f"grant:{B}:internal"

    async def read() -> tuple:
        engine = make_engine(hub.db)
        coordinator = kg_snapshots.SnapshotCoordinator(engine)
        try:
            held = await coordinator.get(project_id(hub))
            readers = (frozenset(), frozenset({one}), frozenset({one, beta}), frozenset({one, two, beta}))
            views = [await coordinator.view(project_id(hub), reader) for reader in readers]
            return held, readers, views
        finally:
            await coordinator.close()
            await engine.dispose()

    held, readers, views = asyncio.run(read())
    assert held.build_id == built["id"] and held.snapshot.content_hash == built["content_hash"]
    items = (m1, m2, m3, kiwi, room)
    # the audiences of erin (no chat), bob (chat one, joined after the agent of beta left), and members of chat one,
    # then of both chats, who hold a grant on beta: as the hub computes them for each read (kg_audience)
    sees = [set(), {m2}, {m1, m2, kiwi, room}, set(items)]
    for reader, view, seen in zip(readers, views, sees, strict=True):
        assert {n for n in items if view.node(n) is not None} == seen, reader
        assert view.node(RUNBOOK) is not None, reader  # the docs carry no audience
        assert all(view.degree(n) == 0 for n in items if n not in seen), reader

    def searched_by(audience: frozenset[str], text: str) -> set[str]:
        results, _ = SnapshotSearch(held.snapshot, INTERNAL, audience).search(text, limit=25)
        return {n["id"] for n in results}

    assert not searched_by(frozenset(), "kiwi rollout") & set(items)  # a reader in no chat
    assert m2 in searched_by(frozenset({one}), "search service restart")
    assert m1 not in searched_by(frozenset({one}), "kiwi rollout")  # m1 also needs a grant on beta
    assert m1 in searched_by(frozenset({one, beta}), "kiwi rollout")
    assert m3 not in searched_by(frozenset({one, beta}), "mango")  # of chat two
    assert m3 in searched_by(frozenset({two, beta}), "mango")


def test_chats_source_gives_nothing_and_queues_nothing_without_chats_read(hub):
    # enabling grants what the plugin asks for; a grant that lacks it, as after an upgrade that asks for more, reads
    # no chat
    pp, projects = tables.project_plugins, tables.projects
    alpha = select(projects.c.id).where(projects.c.name == A).scalar_subquery()
    live.sql(hub.db, update(pp).values(permissions=[]).where(pp.c.project_id == alpha))
    converse(hub)
    assert source_items(hub, A).items == {}
    assert queued(hub) == 1  # beta's, from m1: no message queued a build of alpha


def test_chats_node_kinds_are_hub_kinds():
    from evo_agents.kg.schema import HUB_KINDS, ITEM_KIND_TO_NODE

    assert {ITEM_KIND_TO_NODE[k] for k in ("chat", "thread", "message")} == {"Chat", "ChatThread", "ChatMessage"}
    assert {"Chat", "ChatThread", "ChatMessage"} <= set(HUB_KINDS)
    assert Path(chats_kg.__file__).parent.name == "chats"
