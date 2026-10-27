"""``evo-agents hub okr tree|show|add|set|link|unlink|import`` (manifest commands of the core plugin okr,
``evo_core_plugins/okr/cli.json``): the commands and their ``--json`` keys are in the contract (seam hub-cli-v1), and a
member runs them against a hub that serves the plugin: a tree built item by item, its deliverable linked to a task, a
use case and a plan, an item changed and shown, a link taken off, and a source's bundle imported after a dry run and
pruned. All names are fictional.

The parsing runs without Postgres; everything that needs the hub skips without EVO_HUB_TEST_DSN."""

from __future__ import annotations

import json

import pytest

from evo_agents.hub.contract import commands
from tests.hub import pg
from tests.hub.contract_keys import assert_json_keys
from tests.hub.test_hub_task_cli import PROJECT, hub, needs_pg  # noqa: F401 (fixtures)
from tests.hub.test_run_cli import as_json, ok, write_credentials
from tests.hub.test_secrets_cli import run_cli

if pg.DSN:
    import httpx

VERBS = ("tree", "show", "add", "set", "link", "unlink", "import")
SOURCE = "northwind-sheet"


def test_hub_okr_cli_commands_are_in_the_contract():
    printed = commands()
    assert {f"hub okr {verb}" for verb in VERBS} <= set(printed)
    tree = printed["hub okr tree"]["json"]
    assert (tree["kind"], tree["schema"], set(tree["keys"])) == (
        "object",
        "OkrTree",
        {"project", "today", "counts", "roots", "gaps"},
    )
    for verb in ("show", "add", "set"):
        assert printed[f"hub okr {verb}"]["json"]["schema"] == "OkrItem"
    assert printed["hub okr link"]["json"]["schema"] == "OkrLinkMade"
    assert printed["hub okr unlink"]["json"]["schema"] == "OkrUnlinked"
    assert printed["hub okr import"]["json"]["schema"] == "OkrImported"
    for verb in VERBS:
        assert "--json" in {o["flags"][0] for o in printed[f"hub okr {verb}"]["options"]}
    options = {o["flags"][0]: o for o in printed["hub okr tree"]["options"]}
    assert options["--status"]["choices"] == ["draft", "active", "done", "dropped", "archived"]
    assert options["--project"]["required"] and not options["--line"]["required"]
    added = {o["flags"][0]: o for o in printed["hub okr add"]["options"]}
    assert added["--title"]["required"] and "--parent" in added and "--body" in added
    imported = {o["flags"][0]: o for o in printed["hub okr import"]["options"]}
    assert imported["--file"]["required"] and {"--dry-run", "--prune"} <= set(imported)


def test_hub_okr_cli_link_takes_a_kind_the_plugin_knows(monkeypatch, capsys, tmp_path):
    home = write_credentials(tmp_path / "home", "https://hub.example.org", "alice", "evh_unused")
    with pytest.raises(SystemExit) as stopped:
        run_cli(monkeypatch, capsys, home, "hub", "okr", "link", "D-1", "epic", "X-1", "--project", PROJECT)
    assert stopped.value.code == 2 and "invalid choice" in capsys.readouterr().err
    with pytest.raises(SystemExit) as stopped:
        run_cli(monkeypatch, capsys, home, "hub", "okr", "import", "--project", PROJECT)
    assert stopped.value.code == 2 and "--file" in capsys.readouterr().err


def enable_okr(hub) -> None:
    token = (hub.homes["owner"] / ".evo" / "hub" / "token").read_text(encoding="utf-8").strip()
    enabled = httpx.post(
        f"{hub.url}/v1/projects/{PROJECT}/plugins/okr/enable",
        json={"permissions": []},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert enabled.status_code == 200, enabled.text


def okr(hub, monkeypatch, capsys, who: str, *args: str):
    return run_cli(monkeypatch, capsys, hub.homes[who], "hub", "okr", *args, "--project", PROJECT)


@needs_pg
def test_hub_okr_cli_builds_links_shows_and_changes_the_tree(hub, monkeypatch, capsys):
    refused = okr(hub, monkeypatch, capsys, "alice", "tree")
    assert refused.code == 1 and "okr is not enabled" in refused.err
    enable_okr(hub)
    assert "No item in the OKR tree" in ok(okr(hub, monkeypatch, capsys, "bao", "tree")).out

    line = as_json(
        okr(hub, monkeypatch, capsys, "alice", "add", "business_line", "--title", "Northwind wholesale", "--json")
    )
    assert_json_keys("hub okr add", line)
    assert (line["code"], line["status"]) == ("BL-1", "active")
    ok(okr(hub, monkeypatch, capsys, "alice", "add", "objective", "--title", "Win ten stores", "--parent", "BL-1"))
    words = ("--title", "Ten stores order weekly", "--parent", "O-1", "--baseline", "2", "--target", "10 stores")
    ok(okr(hub, monkeypatch, capsys, "alice", "add", "key_result", *words))
    ok(okr(hub, monkeypatch, capsys, "alice", "add", "deliverable", "--title", "Store portal", "--parent", "KR-1"))
    wrong = okr(hub, monkeypatch, capsys, "alice", "add", "deliverable", "--title", "x", "--parent", "O-1")
    assert wrong.code == 1 and "under a key result, not an objective" in wrong.err

    ok(
        run_cli(
            monkeypatch,
            capsys,
            hub.homes["alice"],
            "hub",
            "task",
            "create",
            "--title",
            "Portal login",
            "--project",
            PROJECT,
        )
    )
    made = as_json(okr(hub, monkeypatch, capsys, "alice", "link", "D-1", "task", "T-1", "--json"))
    assert_json_keys("hub okr link", made)
    assert (made["made"], made["link"]["target"], made["link"]["status"]) == (True, "T-1", "backlog")
    case = ok(okr(hub, monkeypatch, capsys, "alice", "link", "D-1", "use_case", "UC ORD-1")).out
    assert "D-1 links use_case demo-shop:UC ORD-1" in case
    ok(okr(hub, monkeypatch, capsys, "alice", "link", "D-1", "plan", "rollout"))
    missing = okr(hub, monkeypatch, capsys, "alice", "link", "D-1", "task", "T-9")
    assert missing.code == 1 and "no task T-9" in missing.err

    found = as_json(okr(hub, monkeypatch, capsys, "bao", "tree", "--json"))
    assert_json_keys("hub okr tree", found)
    assert [root["code"] for root in found["roots"]] == ["BL-1"]
    printed = ok(okr(hub, monkeypatch, capsys, "bao", "tree")).out
    assert "BL-1  Northwind wholesale  [active]" in printed and "    KR-1  Ten stores order weekly" in printed
    assert "no goal" in printed and "Gaps:" in printed and "no_goal  KR-1" in printed

    shown = as_json(okr(hub, monkeypatch, capsys, "bao", "show", "D-1", "--json"))
    assert_json_keys("hub okr show", shown)
    assert [k["target"] for k in shown["links"]] == ["T-1", "demo-shop:UC ORD-1", "rollout"]
    text = ok(okr(hub, monkeypatch, capsys, "bao", "show", "D-1")).out
    assert "Under: KR-1 Ten stores order weekly" in text and "rollout" in text and "1/5" in text

    changed = as_json(
        okr(hub, monkeypatch, capsys, "alice", "set", "KR-1", "--due", "2026-12-31", "--owner", "bao", "--json")
    )
    assert_json_keys("hub okr set", changed)
    assert (changed["due"], changed["owner"], changed["target"]) == ("2026-12-31", "bao", "10 stores")
    cleared = as_json(okr(hub, monkeypatch, capsys, "alice", "set", "KR-1", "--due", "", "--json"))
    assert (cleared["due"], cleared["owner"]) == (None, "bao")

    gone = as_json(okr(hub, monkeypatch, capsys, "alice", "unlink", "D-1", str(made["link"]["id"]), "--json"))
    assert_json_keys("hub okr unlink", gone)
    assert gone["deleted"] and gone["link"]["target"] == "T-1"
    said = ok(okr(hub, monkeypatch, capsys, "alice", "unlink", "D-1", str(shown["links"][2]["id"]))).out
    assert said.strip() == f"Took link {shown['links'][2]['id']} (plan rollout) off D-1"


@needs_pg
def test_hub_okr_cli_imports_a_bundle_after_a_dry_run_and_prunes(hub, monkeypatch, capsys, tmp_path):
    enable_okr(hub)
    ok(
        run_cli(
            monkeypatch,
            capsys,
            hub.homes["alice"],
            "hub",
            "task",
            "create",
            "--title",
            "Portal login",
            "--project",
            PROJECT,
        )
    )
    items = [
        {"ref": "nw-line", "kind": "business_line", "title": "Northwind wholesale"},
        {"ref": "nw-o1", "kind": "objective", "title": "Win ten stores", "parents": ["nw-line"], "period": "2026-Q4"},
        {"ref": "nw-kr1", "kind": "key_result", "title": "Ten stores order weekly", "parents": ["nw-o1"]},
        {"ref": "nw-d1", "kind": "deliverable", "title": "Store portal", "parents": ["nw-kr1"]},
    ]
    links = [{"item": "nw-d1", "kind": "task", "target": "T-1"}, {"item": "nw-d1", "kind": "plan", "target": "nowhere"}]
    path = tmp_path / "bundle.json"
    path.write_text(json.dumps({"source": SOURCE, "items": items, "links": links}), encoding="utf-8")

    dry = as_json(okr(hub, monkeypatch, capsys, "alice", "import", "--file", str(path), "--dry-run", "--json"))
    assert_json_keys("hub okr import", dry)
    assert dry["dry_run"] and [e["code"] for e in dry["created"]] == ["BL-1", "O-1", "KR-1", "D-1"]
    assert [link["result"] for link in dry["links"]] == ["added", "not_found"]
    assert "No item in the OKR tree" in ok(okr(hub, monkeypatch, capsys, "bao", "tree")).out

    printed = ok(okr(hub, monkeypatch, capsys, "alice", "import", "--file", str(path))).out
    assert f"Source {SOURCE}: 4 created, 0 updated, 0 unchanged, 0 missing" in printed
    assert "Links: 1 added, 0 exists, 1 not_found, 0 refused" in printed and "no plan nowhere" in printed
    assert as_json(okr(hub, monkeypatch, capsys, "bao", "show", "nw-d1", "--json"))["source"] == SOURCE
    refused = okr(hub, monkeypatch, capsys, "alice", "set", "nw-kr1", "--title", "x")
    assert refused.code == 1 and f"comes from source {SOURCE}" in refused.err

    path.write_text(json.dumps({"source": SOURCE, "items": items[:3]}), encoding="utf-8")
    pruned = as_json(okr(hub, monkeypatch, capsys, "alice", "import", "--file", str(path), "--prune", "--json"))
    assert [(e["code"], e["archived"]) for e in pruned["missing"]] == [("D-1", True)] and len(pruned["unchanged"]) == 3
    assert "D-1" not in ok(okr(hub, monkeypatch, capsys, "bao", "tree")).out
    archived = ok(okr(hub, monkeypatch, capsys, "bao", "tree", "--status", "archived")).out
    assert "D-1  Store portal  [archived]" in archived
