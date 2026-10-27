"""The core plugin okr on the hub (``evo_core_plugins.okr``): a project's strategy as a tree of business lines,
objectives, key results and deliverables, linked to the hub's tasks, use cases, plans and goals.

The tree takes only its shapes (an objective under at most one business line, a key result under exactly one
objective, a deliverable under one key result or more) and gives codes in order. A link names a target the project
holds, of a kind the item takes. The roll-up counts tasks, use cases and plans up to the business line, and a key
result's goal is met, not met or without a signal from the latest value pushed. An import upserts a source's items by
ref, reports what it would do on a dry run, archives what the source no longer lists with prune, and keeps the fields
of its items to itself. Readers read, writers write, and the MCP tools answer what the routes answer. All names are
fictional.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tests.hub import pg

if not pg.DSN:
    pytest.skip(pg.SKIP_REASON, allow_module_level=True)

from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select, update

from evo_agents.hub import tables
from evo_agents.hub.server import core_plugin_api as hub_api
from evo_agents.hub.server.app import create_app
from evo_core_plugins.okr import manifest, rules
from evo_core_plugins.okr import tables as okr_tables
from tests.hub import live
from tests.hub.live import sql
from tests.hub.test_mcp import call
from tests.hub.test_plugin_points import rpc, tool_names
from tests.hub.test_runs import PLAN
from tests.hub.test_tasks_plugin import (  # noqa: F401 (fixtures)
    PROJECT,
    SAMPLE_SRS,
    enable,
    members,
    tasks_core,
)

BASE = f"/v1/x/okr/{PROJECT}"
TASKS = f"/v1/x/tasks/{PROJECT}"
SOURCE = "northwind-sheet"
REPEAT = "orders.repeat_rate"
METRIC = {"key": REPEAT, "aggregate": "last", "window_days": 30, "comparator": ">=", "target": 0.3}
LONG_AGO = "2020-01-01"


@pytest.fixture
def client(hub_db, tmp_path, github, tasks_core):  # noqa: F811
    """The hub, which answers MCP at its public url."""
    config = live.hub_config(hub_db, tmp_path, github, public_url="https://hub.test")
    with TestClient(create_app(config), base_url="https://hub.test") as client:
        yield client


@pytest.fixture
def okr(client, members):  # noqa: F811
    """``members`` with tasks (plans:read), srs and okr enabled, the sample SRS imported and the plan rollout."""
    enable(client, members["owner"], "tasks", ["plans:read"])
    enable(client, members["owner"], "srs")
    enable(client, members["owner"], "okr")
    body = {"markdown": SAMPLE_SRS.read_text(encoding="utf-8"), "slug": "demo-shop"}
    ok(client.post(f"/v1/x/srs/{PROJECT}/import", json=body, headers=members["alice"]))
    return members


def ok(answer, status: int = 200):
    assert answer.status_code == status, answer.text
    return answer.json()


def refused(answer, status: int) -> str:
    assert answer.status_code == status, answer.text
    return answer.json()["message"]


def add(client, headers, kind: str, title: str, *parents: str, expect: int = 201, **fields) -> dict:
    return ok(
        client.post(
            f"{BASE}/items", json={"kind": kind, "title": title, "parents": list(parents), **fields}, headers=headers
        ),
        expect,
    )


def link(client, headers, item: str, kind: str, target: str, expect: int = 201) -> dict:
    return ok(client.post(f"{BASE}/items/{item}/links", json={"kind": kind, "target": target}, headers=headers), expect)


def task(client, headers, title: str, **body) -> dict:
    return ok(client.post(f"{TASKS}/tasks", json={"title": title, **body}, headers=headers), 201)


def tree(client, headers, **query) -> dict:
    return ok(client.get(f"{BASE}/tree", params=query, headers=headers))


def item(client, headers, ref: str) -> dict:
    return ok(client.get(f"{BASE}/items/{ref}", headers=headers))


def nodes(found: dict) -> dict[str, dict]:
    """code -> node of the tree, the first place each is."""
    every: dict[str, dict] = {}
    stack = list(reversed(found["roots"]))
    while stack:
        node = stack.pop()
        every.setdefault(node["code"], node)
        stack.extend(reversed(node["children"]))
    return every


def shape(found: dict) -> list:
    def one(node):
        return [node["code"], [one(child) for child in node["children"]]] if node["children"] else node["code"]

    return [one(root) for root in found["roots"]]


def gaps(found: dict) -> set[tuple[str, str]]:
    return {(gap["kind"], gap["item"]) for gap in found["gaps"]}


def project_id(db) -> int:
    return sql(db, select(tables.projects.c.id).where(tables.projects.c.name == PROJECT))[0][0]


def goal(client, headers, ref: str = "G-1", metric: dict | None = METRIC) -> dict:
    keys = client.post(f"/v1/projects/{PROJECT}/signal-keys", json={"name": REPEAT, "kind": "number"}, headers=headers)
    assert keys.status_code in (201, 409), keys.text
    body = {"statement": "More customers order again", "metric": metric}
    return ok(client.put(f"/v1/projects/{PROJECT}/goals/{ref}", json=body, headers=headers))


def push(client, headers, value: float, days_ago: int) -> None:
    measured = (datetime.now(UTC) - timedelta(days=days_ago)).isoformat()
    body = {"items": [{"key": REPEAT, "value": value, "measured_at": measured}]}
    assert client.post(f"/v1/signals/{PROJECT}", json=body, headers=headers).status_code == 202


# The manifest and the tables


def test_okr_manifest_asks_for_no_permission_and_contributes_the_tree():
    found = manifest()
    contributes = found["contributes"]
    assert (found["id"], found["version"], found["permissions"]) == ("okr", "1.1.0", [])
    assert [(p["name"], p["entry"]) for p in contributes["pages"]] == [("tree", "pages/tree.html")]
    assert [t["name"] for t in contributes["mcp_tools"]] == ["tree", "item", "link", "unlink"]
    assert [t["name"] for t in contributes["tables"]] == list(okr_tables.NAMES)
    assert {c["name"] for c in contributes["cli"]} == {"tree", "show", "add", "set", "link", "unlink", "import"}
    assert not contributes.get("jobs") and found["schema"]["migrations"] == "evo_core_plugins.okr.migrations"
    assert hub_api.plugin("evo_core_plugins.okr.store").id == "okr"


def test_okr_its_migration_makes_the_tables_its_metadata_holds(client, okr, hub_db):
    with live.engine(hub_db).begin() as conn:
        assert hub_api.adopt_tables(conn, okr_tables.metadata, list(okr_tables.NAMES)) == []


def test_okr_shape_rules_and_cycles_without_a_hub():
    assert rules.shape_problem("business_line", []) is None
    assert rules.shape_problem("objective", []) is None and rules.shape_problem("objective", ["business_line"]) is None
    assert "exactly one objective; 0 given" in rules.shape_problem("key_result", [])
    assert "exactly one objective; 2 given" in rules.shape_problem("key_result", ["objective", "objective"])
    assert "at least one key result" in rules.shape_problem("deliverable", [])
    assert "not an objective" in rules.shape_problem("deliverable", ["objective"])
    assert "at most one business line" in rules.shape_problem("objective", ["business_line", "business_line"])
    assert "under nothing" in rules.shape_problem("business_line", ["objective"])
    assert rules.closes_cycle(1, [2], {2: [3], 3: [1]}) and rules.closes_cycle(1, [1], {})
    assert not rules.closes_cycle(1, [2], {2: [3], 3: []})
    assert rules.parse_code("kr-12") == ("key_result", 12) and rules.parse_code("KR-0") is None
    assert rules.use_case_parts("demo-shop: UC  ORD-1") == ("demo-shop", "UC ORD-1")
    versions = {1: "superseded", 2: "approved", 3: "draft"}
    assert rules.use_case_status(1, None, versions) == "approved"
    assert rules.use_case_status(3, None, versions) == "draft"
    assert rules.use_case_status(1, 2, versions) == "retired"
    assert rules.use_case_status(1, 3, {1: "in_review", 3: "draft"}) == "in_review"
    assert rules.goal_state(METRIC, 0.31) == "met" and rules.goal_state(METRIC, 0.2) == "not_met"
    assert rules.goal_state(METRIC, None) == "no_signal" and rules.goal_state(None, 1.0) == "no_metric"


def test_okr_a_project_that_does_not_enable_it_answers_404(client, members):  # noqa: F811
    assert client.get(f"{BASE}/tree", headers=members["owner"]).status_code == 404
    body = {"kind": "business_line", "title": "Northwind retail"}
    assert client.post(f"{BASE}/items", json=body, headers=members["owner"]).status_code == 404


# The tree


def test_okr_the_tree_takes_only_its_shapes_and_gives_codes_in_order(client, okr):
    alice, eve = okr["alice"], okr["eve"]
    assert tree(client, eve) == {
        "project": PROJECT,
        "today": datetime.now(UTC).date().isoformat(),
        "counts": {"business_line": 0, "objective": 0, "key_result": 0, "deliverable": 0},
        "roots": [],
        "gaps": [],
    }
    line = add(client, alice, "business_line", "Northwind retail", ref="nw-retail")
    assert (line["code"], line["status"], line["created_by"]) == ("BL-1", "active", "alice")
    first = add(client, alice, "objective", "Grow repeat orders", "BL-1", owner="bao", period="2026-Q4")
    alone = add(client, alice, "objective", "Open a second store", status="draft")
    assert (first["code"], alone["code"]) == ("O-1", "O-2")
    assert first["parents"] == [
        {"code": "BL-1", "kind": "business_line", "title": "Northwind retail", "status": "active"}
    ]
    for kind, parents, said in (
        ("key_result", (), "exactly one objective; 0 given"),
        ("key_result", ("BL-1",), "a key result is under an objective, not a business line"),
        ("key_result", ("O-1", "O-2"), "exactly one objective; 2 given"),
        ("deliverable", (), "at least one key result"),
        ("deliverable", ("O-1",), "a deliverable is under a key result, not an objective"),
        ("business_line", ("O-1",), "a business line is under nothing"),
        ("objective", ("nowhere",), "no parent nowhere"),
    ):
        assert said in refused(
            client.post(f"{BASE}/items", json={"kind": kind, "title": "x", "parents": list(parents)}, headers=alice),
            422,
        )
    assert add(client, alice, "key_result", "Repeat orders reach 30 %", "o-1", target="30 %")["code"] == "KR-1"
    assert add(client, alice, "key_result", "Returns answered in a day", "O-1")["code"] == "KR-2"
    both = add(client, alice, "deliverable", "Order history page", "KR-1", "KR-2")
    assert (both["code"], [p["code"] for p in both["parents"]]) == ("D-1", ["KR-1", "KR-2"])
    assert "ref nw-retail is the ref of BL-1" in refused(
        client.post(f"{BASE}/items", json={"kind": "business_line", "title": "x", "ref": "nw-retail"}, headers=alice),
        409,
    )

    found = tree(client, eve)
    assert shape(found) == [["BL-1", [["O-1", [["KR-1", ["D-1"]], ["KR-2", ["D-1"]]]]]], "O-2"]
    assert found["counts"] == {"business_line": 1, "objective": 2, "key_result": 2, "deliverable": 1}
    assert item(client, eve, "nw-retail")["code"] == "BL-1" and item(client, eve, "kr-2")["title"].startswith("Returns")
    assert client.get(f"{BASE}/items/O-9", headers=eve).status_code == 404

    moved = ok(
        client.patch(f"{BASE}/items/O-2", json={"parents": ["BL-1"], "status": "active", "due": ""}, headers=alice)
    )
    assert (
        [p["code"] for p in moved["parents"]] == ["BL-1"]
        and moved["status"] == "active"
        and moved["updated_by"] == "alice"
    )
    assert "exactly one objective; 0 given" in refused(
        client.patch(f"{BASE}/items/KR-1", json={"parents": []}, headers=alice), 422
    )
    assert "always has a title" in refused(client.patch(f"{BASE}/items/KR-1", json={"title": None}, headers=alice), 422)
    cleared = ok(client.patch(f"{BASE}/items/O-1", json={"owner": None, "period": ""}, headers=alice))
    assert (cleared["owner"], cleared["period"], cleared["title"]) == (None, None, "Grow repeat orders")
    assert [root["code"] for root in tree(client, eve)["roots"]] == ["BL-1"]
    only = tree(client, eve, line="BL-1")
    assert [root["code"] for root in only["roots"]] == ["BL-1"]
    assert "O-1 is an objective, not a business line" in refused(
        client.get(f"{BASE}/tree", params={"line": "O-1"}, headers=eve), 422
    )
    ok(client.patch(f"{BASE}/items/KR-2", json={"status": "dropped"}, headers=alice))
    dropped = tree(client, eve, status="dropped")
    assert shape(dropped) == [["BL-1", [["O-1", ["KR-2"]]]]], "a dropped item with the items above it"


def test_okr_a_reader_reads_and_only_a_writer_writes(client, okr, github):
    alice, eve = okr["alice"], okr["eve"]
    add(client, alice, "business_line", "Northwind retail")
    add(client, alice, "objective", "Grow repeat orders", "BL-1")
    assert client.post(f"{BASE}/items", json={"kind": "business_line", "title": "x"}, headers=eve).status_code == 403
    assert client.patch(f"{BASE}/items/BL-1", json={"title": "x"}, headers=eve).status_code == 403
    assert (
        client.post(f"{BASE}/items/BL-1/links", json={"kind": "task", "target": "T-1"}, headers=eve).status_code == 403
    )
    assert client.delete(f"{BASE}/items/BL-1/links/1", headers=eve).status_code == 403
    assert client.post(f"{BASE}/import", json={"source": SOURCE}, headers=eve).status_code == 403
    assert "writer role" in refused(
        client.post(f"{BASE}/items", json={"kind": "business_line", "title": "x"}, headers=eve), 403
    )
    assert [r["code"] for r in tree(client, eve)["roots"]] == ["BL-1"] and tree(client, okr["outsider"])["roots"]
    admin = live.bearer(live.sign_in(client, github, live.ADMIN, 302)["token"])
    assert client.get(f"{BASE}/tree", headers=admin).status_code == 404, "the hub answers a hub admin without a grant"
    assert client.get(f"{BASE}/tree", headers={"Authorization": "Bearer nope"}).status_code in (401, 403)


# Links


def test_okr_links_name_a_target_the_project_holds_of_a_kind_the_item_takes(client, okr, hub_db):
    alice, eve, owner = okr["alice"], okr["eve"], okr["owner"]
    add(client, alice, "business_line", "Northwind retail")
    add(client, alice, "objective", "Grow repeat orders", "BL-1")
    add(client, alice, "key_result", "Repeat orders reach 30 %", "O-1")
    add(client, alice, "deliverable", "Loyalty card", "KR-1")
    task(client, alice, "Card design", status="done")
    task(client, alice, "Card print run")
    goal(client, owner)

    made = link(client, alice, "D-1", "task", "T-1")
    assert (made["made"], made["item"], made["link"]["target"], made["link"]["title"]) == (
        True,
        "D-1",
        "T-1",
        "Card design",
    )
    again = link(client, alice, "d-1", "task", "t-1", expect=200)
    assert (again["made"], again["link"]["id"]) == (False, made["link"]["id"])
    assert "no task T-99" in refused(
        client.post(f"{BASE}/items/D-1/links", json={"kind": "task", "target": "T-99"}, headers=alice), 404
    )
    case = link(client, alice, "D-1", "use_case", "demo-shop:UC ORD-1")["link"]
    assert (case["target"], case["status"], case["done"], case["total"]) == ("demo-shop:UC ORD-1", "draft", 0, 0)
    assert link(client, alice, "D-1", "use_case", "uc  ord-2")["link"]["target"] == "demo-shop:UC ORD-2"
    assert "no use case demo-shop:UC NOPE-9" in refused(
        client.post(
            f"{BASE}/items/D-1/links", json={"kind": "use_case", "target": "demo-shop:UC NOPE-9"}, headers=alice
        ),
        404,
    )
    assert "not a use case" in refused(
        client.post(
            f"{BASE}/items/D-1/links", json={"kind": "use_case", "target": "demo-shop:NFR-SEC-01"}, headers=alice
        ),
        422,
    )
    plan = link(client, alice, "D-1", "plan", PLAN)["link"]
    assert (plan["done"], plan["total"], plan["share"]) == (1, 5, 0.2)
    assert "no plan nowhere" in refused(
        client.post(f"{BASE}/items/D-1/links", json={"kind": "plan", "target": "nowhere"}, headers=alice), 404
    )
    for code, kind, target in (
        ("D-1", "goal", "G-1"),
        ("KR-1", "task", "T-1"),
        ("O-1", "plan", PLAN),
        ("BL-1", "task", "T-2"),
    ):
        assert "which links" in refused(
            client.post(f"{BASE}/items/{code}/links", json={"kind": kind, "target": target}, headers=alice), 422
        )
    measured = link(client, alice, "KR-1", "goal", "g-1")["link"]
    assert (measured["target"], measured["status"], measured["title"]) == (
        "G-1",
        "no_signal",
        "More customers order again",
    )
    goal(client, owner, "G-2", None)
    assert "measured by goal G-1 already" in refused(
        client.post(f"{BASE}/items/KR-1/links", json={"kind": "goal", "target": "G-2"}, headers=alice), 409
    )
    assert "no goal G-9" in refused(
        client.post(f"{BASE}/items/KR-1/links", json={"kind": "goal", "target": "G-9"}, headers=alice), 404
    )

    blind = item(client, okr["outsider"], "D-1")["links"][0]
    assert (blind["target"], blind["visible"], blind["title"], blind["status"]) == ("T-1", False, None, None)
    tasks_items = tables.metadata.tables["tasks_items"]
    sql(hub_db, delete(tasks_items).where(tasks_items.c.project_id == project_id(hub_db), tasks_items.c.number == 1))
    shown = item(client, eve, "D-1")
    assert shown["links"][0]["gone"] and ("gone", "D-1") in {(g["kind"], g["item"]) for g in shown["gaps"]}
    assert "links task T-1, gone" in [g["detail"] for g in shown["gaps"]][0]

    gone = ok(client.delete(f"{BASE}/items/D-1/links/{made['link']['id']}", headers=alice))
    assert (gone["deleted"], gone["item"], gone["link"]["target"]) == (True, "D-1", "T-1")
    assert client.delete(f"{BASE}/items/D-1/links/{made['link']['id']}", headers=alice).status_code == 404
    assert [k["target"] for k in item(client, eve, "D-1")["links"]] == [
        "demo-shop:UC ORD-1",
        "demo-shop:UC ORD-2",
        PLAN,
    ]


# The roll-up


def test_okr_the_roll_up_counts_tasks_use_cases_plans_and_goals_up_to_the_line(client, okr, hub_db):
    alice, eve, owner = okr["alice"], okr["eve"], okr["owner"]
    add(client, alice, "business_line", "Northwind retail")
    add(client, alice, "objective", "Grow repeat orders", "BL-1")
    add(client, alice, "objective", "Open a second store", status="draft")
    add(client, alice, "key_result", "Repeat orders reach 30 %", "O-1")
    add(client, alice, "key_result", "Returns answered in a day", "O-1")
    add(client, alice, "deliverable", "Loyalty card", "KR-1")
    add(client, alice, "deliverable", "Order history page", "KR-1", "KR-2")
    add(client, alice, "deliverable", "Returns form", "KR-2", due=LONG_AGO)
    task(client, alice, "Card design", status="done")  # T-1
    task(client, alice, "Card print run", due_on=LONG_AGO)  # T-2, late
    task(client, alice, "Card stickers", status="cancelled")  # T-3
    task(client, alice, "History list", status="done", links={"use_cases": ["UC ORD-1"]})  # T-4
    task(client, alice, "History filters", status="in_progress", links={"use_cases": ["UC ORD-1"]})  # T-5
    ok(
        client.post(
            f"{TASKS}/tasks/T-2/blockers",
            json={"reason": "waiting for the printer", "waiting_text": "printer"},
            headers=alice,
        ),
        201,
    )
    for target in ("T-1", "T-2", "T-3"):
        link(client, alice, "D-1", "task", target)
    link(client, alice, "D-2", "plan", PLAN)
    link(client, alice, "D-2", "use_case", "demo-shop:UC ORD-1")

    found = tree(client, eve)
    every = nodes(found)
    d1, d2, d3 = (every[code]["rollup"] for code in ("D-1", "D-2", "D-3"))
    assert (d1["progress"], d1["tasks_done"], d1["tasks_total"], d1["tasks_late"], d1["tasks_blocked"]) == (
        0.5,
        1,
        2,
        1,
        1,
    )
    assert (d2["progress"], d2["tasks_total"]) == (0.35, 0) and d3["progress"] is None
    links = {k["target"]: k for k in every["D-1"]["links"]}
    assert (links["T-2"]["late"], links["T-2"]["blocked"], links["T-3"]["total"], links["T-3"]["share"]) == (
        True,
        True,
        0,
        None,
    )
    case = {k["kind"]: k for k in every["D-2"]["links"]}["use_case"]
    assert (case["status"], case["done"], case["total"], case["share"], case["title"]) == (
        "draft",
        1,
        2,
        0.5,
        "Place an order",
    )
    kr1, kr2 = every["KR-1"]["rollup"], every["KR-2"]["rollup"]
    assert (kr1["progress"], kr1["deliverables"], kr1["tasks_total"], kr1["goal"]) == (0.425, 2, 2, None)
    assert (kr2["progress"], kr2["deliverables"]) == (0.35, 2)
    o1, line = every["O-1"]["rollup"], every["BL-1"]["rollup"]
    assert (o1["progress"], o1["deliverables"], o1["krs_met"], o1["krs_total"]) == (0.425, 3, 0, 2)
    assert (line["progress"], line["deliverables"], line["tasks_late"], line["krs_total"]) == (0.425, 3, 1, 2)
    assert gaps(found) == {
        ("no_kr", "O-2"),
        ("no_goal", "KR-1"),
        ("no_goal", "KR-2"),
        ("no_link", "D-3"),
        ("late", "D-3"),
    }

    versions = tables.srs.versions
    sql(hub_db, update(versions).values(state="approved", decided_at=func.now()))
    assert {k["kind"]: k for k in item(client, eve, "D-2")["links"]}["use_case"]["status"] == "approved"

    goal(client, owner)
    link(client, alice, "KR-1", "goal", "G-1")
    assert item(client, eve, "KR-1")["rollup"]["goal"]["state"] == "no_signal"
    push(client, alice, 0.25, 2)
    measured = item(client, eve, "KR-1")["rollup"]["goal"]
    assert (measured["state"], measured["value"], measured["metric"]) == (
        "not_met",
        0.25,
        "orders.repeat_rate last over 30 days >= 0.3",
    )
    push(client, alice, 0.31, 1)
    assert item(client, eve, "KR-1")["rollup"]["goal"]["state"] == "met"
    every = nodes(tree(client, eve))
    assert (every["O-1"]["rollup"]["krs_met"], every["BL-1"]["rollup"]["krs_met"]) == (1, 1)
    assert ("no_goal", "KR-1") not in gaps(tree(client, eve))

    ok(client.patch(f"{BASE}/items/D-1", json={"status": "dropped"}, headers=alice))
    assert nodes(tree(client, eve))["KR-1"]["rollup"]["progress"] == 0.35, "a dropped deliverable counts for nothing"


# Import


def bundle(**changes) -> dict:
    found = {
        "source": SOURCE,
        "items": [
            {
                "ref": "nw-line",
                "kind": "business_line",
                "title": "Northwind wholesale",
                "source_url": "https://sheets.example.org/nw",
                "source_rev": "r1",
            },
            {
                "ref": "nw-o1",
                "kind": "objective",
                "title": "Win ten stores",
                "parents": ["nw-line"],
                "owner": "alice",
                "period": "2026-Q4",
                "due": "2026-12-31",
            },
            {
                "ref": "nw-kr1",
                "kind": "key_result",
                "title": "Ten stores order weekly",
                "parents": ["nw-o1"],
                "baseline": "2",
                "target": "10",
            },
            {"ref": "nw-d1", "kind": "deliverable", "title": "Store portal", "parents": ["nw-kr1"]},
        ],
        "links": [
            {"item": "nw-d1", "kind": "task", "target": "T-1"},
            {"item": "nw-d1", "kind": "task", "target": "T-404"},
            {"item": "nw-kr1", "kind": "goal", "target": "G-1"},
            {"item": "nw-o1", "kind": "task", "target": "T-1"},
        ],
    }
    found.update(changes)
    return found


def imported(client, headers, body: dict, expect: int = 200) -> dict:
    return ok(client.post(f"{BASE}/import", json=body, headers=headers), expect)


def listed(found: dict, word: str) -> list[tuple]:
    return [(entry["ref"], entry["code"]) for entry in found[word]]


def test_okr_import_upserts_by_ref_reports_a_dry_run_and_prunes_to_archived(client, okr, hub_db):
    alice, eve, owner = okr["alice"], okr["eve"], okr["owner"]
    task(client, alice, "Portal login")
    goal(client, owner)

    dry = imported(client, alice, {**bundle(), "dry_run": True})
    assert dry["dry_run"] and listed(dry, "created") == [
        ("nw-line", "BL-1"),
        ("nw-o1", "O-1"),
        ("nw-kr1", "KR-1"),
        ("nw-d1", "D-1"),
    ]
    assert [link["result"] for link in dry["links"]] == ["added", "not_found", "added", "refused"]
    assert "no task T-404" in dry["links"][1]["detail"] and "links nothing" in dry["links"][3]["detail"]
    assert tree(client, eve)["roots"] == [], "a dry run writes nothing"

    first = imported(client, alice, bundle())
    assert listed(first, "created") == listed(dry, "created") and first["updated"] == first["missing"] == []
    assert [link["result"] for link in first["links"]] == ["added", "not_found", "added", "refused"]
    assert all(link["id"] for link in first["links"] if link["result"] == "added")
    portal = item(client, eve, "nw-d1")
    assert (portal["code"], portal["source"], [p["code"] for p in portal["parents"]]) == ("D-1", SOURCE, ["KR-1"])
    assert [k["target"] for k in portal["links"]] == ["T-1"] and item(client, eve, "O-1")["due"] == "2026-12-31"
    assert item(client, eve, "BL-1")["source_rev"] == "r1"

    again = imported(client, alice, bundle())
    assert len(again["unchanged"]) == 4 and again["created"] == again["updated"] == []
    assert [link["result"] for link in again["links"]] == ["exists", "not_found", "exists", "refused"]

    items = bundle()["items"]
    changed = [items[0], items[1], {**items[2], "title": "Twelve stores order weekly"}]
    later = imported(client, alice, bundle(items=changed, links=[]))
    assert [(e["code"], e["fields"]) for e in later["updated"]] == [("KR-1", ["title"])]
    assert [(e["code"], e["archived"]) for e in later["missing"]] == [("D-1", False)]
    assert item(client, eve, "D-1")["status"] == "active", "missing without prune leaves the item"
    pruned = imported(client, alice, bundle(items=changed, links=[], prune=True))
    assert [(e["code"], e["archived"]) for e in pruned["missing"]] == [("D-1", True)]
    assert item(client, eve, "D-1")["status"] == "archived" and "D-1" not in nodes(tree(client, eve))
    assert "D-1" in nodes(tree(client, eve, status="archived"))
    assert imported(client, alice, bundle(items=changed, links=[]))["missing"] == [], (
        "an archived item is missing no more"
    )

    said = refused(client.patch(f"{BASE}/items/KR-1", json={"title": "x"}, headers=alice), 409)
    assert f"comes from source {SOURCE}" in said and "title" in said
    assert refused(client.patch(f"{BASE}/items/O-1", json={"parents": []}, headers=alice), 409)
    measured = item(client, eve, "KR-1")["links"][0]
    assert ok(client.delete(f"{BASE}/items/KR-1/links/{measured['id']}", headers=alice))["deleted"], (
        "links stay editable"
    )
    assert link(client, alice, "KR-1", "goal", "G-1")["made"]

    audit = sql(hub_db, select(tables.audit.c.target).where(tables.audit.c.action == "okr.import"))
    assert len(audit) == 5 and audit[0][0].startswith(f"source {SOURCE}: 4 created")


def test_okr_import_refuses_a_bundle_with_a_problem_and_writes_nothing(client, okr):
    alice, eve = okr["alice"], okr["eve"]
    manual = add(client, alice, "business_line", "Northwind retail", ref="nw-retail")
    items = bundle()["items"]
    for body, said in (
        (bundle(items=[items[0], items[0]]), "ref nw-line is in the bundle twice"),
        (bundle(items=[{**items[2], "parents": []}]), "nw-kr1: a key result is under exactly one objective; 0 given"),
        (bundle(items=[{**items[3], "parents": ["nowhere"]}]), "nw-d1: no parent nowhere in the bundle or the project"),
        (bundle(items=[{**items[1], "parents": ["nw-retail", "nw-line"]}, items[0]]), "at most one business line"),
        (
            bundle(items=[{"ref": "nw-retail", "kind": "objective", "title": "x"}]),
            "nw-retail is BL-1, a business line, not an objective",
        ),
        ({"items": []}, "an import names its source"),
        ({"file": "not json"}, "the file is no JSON"),
    ):
        assert said in refused(client.post(f"{BASE}/import", json=body, headers=alice), 422), said
    assert [r["code"] for r in tree(client, eve)["roots"]] == ["BL-1"]

    adopted = imported(
        client,
        alice,
        bundle(items=[{"ref": "nw-retail", "kind": "business_line", "title": "Northwind retail"}], links=[]),
    )
    assert [(e["code"], e["fields"]) for e in adopted["updated"]] == [("BL-1", ["source"])]
    assert item(client, eve, manual["code"])["source"] == SOURCE
    other = {"source": "lumen-board", "items": [{"ref": "nw-retail", "kind": "business_line", "title": "x"}]}
    assert "which source northwind-sheet writes" in refused(
        client.post(f"{BASE}/import", json=other, headers=alice), 422
    )

    by_file = imported(client, alice, {"file": json.dumps(bundle()), "dry_run": True})
    assert by_file["dry_run"] and by_file["source"] == SOURCE and len(by_file["created"]) == 4
    assert [r["code"] for r in tree(client, eve)["roots"]] == ["BL-1"]


# The tools and the page


def mcp(client, headers, name: str, arguments: dict | None = None) -> tuple:
    result = rpc(client, headers, call(9, name, arguments or {}))
    text = result["content"][0]["text"]
    return (text if result["isError"] else json.loads(text)), result["isError"]


def test_okr_tools_answer_what_the_routes_answer_for_the_caller(client, okr):
    alice, eve = okr["alice"], okr["eve"]
    add(client, alice, "business_line", "Northwind retail")
    add(client, alice, "objective", "Grow repeat orders", "BL-1")
    add(client, alice, "key_result", "Repeat orders reach 30 %", "O-1")
    add(client, alice, "deliverable", "Loyalty card", "KR-1")
    task(client, alice, "Card design", status="done")
    assert {"okr__tree", "okr__item", "okr__link", "okr__unlink"} <= set(tool_names(client, eve))
    found, error = mcp(client, eve, "okr__tree")
    assert not error and found == tree(client, eve)
    one, _ = mcp(client, eve, "okr__item", {"item": "KR-1"})
    assert one == item(client, eve, "KR-1")
    text, error = mcp(client, eve, "okr__link", {"item": "D-1", "kind": "task", "target": "T-1"})
    assert error and "writer" in text
    made, error = mcp(client, alice, "okr__link", {"item": "D-1", "kind": "task", "target": "T-1"})
    assert not error and made["made"] and made["link"]["share"] == 1.0
    text, error = mcp(client, alice, "okr__link", {"item": "D-1", "kind": "task", "target": "T-9"})
    assert error and "no task T-9" in text
    gone, error = mcp(client, alice, "okr__unlink", {"item": "D-1", "link": made["link"]["id"]})
    assert not error and gone["deleted"]
    text, error = mcp(client, alice, "okr__unlink", {"item": "D-1", "link": "one"})
    assert error and "link" in text, "the hub checks the arguments against the tool's schema"


def test_okr_the_page_reads_at_a_narrow_screen_in_english_and_vietnamese():
    import evo_core_plugins.okr as package

    pages = Path(package.__file__).with_name("ui") / "pages"
    html = (pages / "tree.html").read_text(encoding="utf-8")
    assert 'name="viewport" content="width=device-width, initial-scale=1"' in html and "tree.js" in html
    english = (pages / "i18n" / "en.js").read_text(encoding="utf-8")
    vietnamese = (pages / "i18n" / "vi.js").read_text(encoding="utf-8")
    keys = set(json.loads(english[english.index("{") : english.rindex("}") + 1]))
    assert keys == set(json.loads(vietnamese[vietnamese.index("{") : vietnamese.rindex("}") + 1]))
