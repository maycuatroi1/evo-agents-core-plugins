"""``evo-agents hub editorial posts|show|set|recall|feedback|import|export`` (manifest commands of the core plugin
editorial, ``evo_core_plugins/editorial/cli.json``): the commands and their ``--json`` keys are in the contract (seam
hub-cli-v1), and a member runs them against a hub that serves the plugin: a post set through its stages and gate,
the list of posts with their gates, the notebook's entries added, repeated, listed and recalled, a file imported twice
with no duplicate, and a notebook exported exactly as it was kept. All names are fictional.

The parsing runs without Postgres; everything that needs the hub skips without EVO_HUB_TEST_DSN."""

from __future__ import annotations

import json

import pytest

from evo_agents.hub.contract import commands
from plugin_tests.test_editorial_ledger import VOICE
from tests.hub import pg
from tests.hub.contract_keys import assert_json_keys
from tests.hub.test_hub_task_cli import PROJECT, hub, needs_pg  # noqa: F401 (fixtures)
from tests.hub.test_run_cli import as_json, ok, write_credentials
from tests.hub.test_secrets_cli import run_cli

if pg.DSN:
    import httpx

    from plugin_tests.test_editorial_plugin import CONFIG, DOCUMENT

VERBS = ("posts", "show", "set", "recall", "feedback", "import", "export")


def test_hub_editorial_cli_commands_are_in_the_contract():
    printed = commands()
    assert {f"hub editorial {verb}" for verb in VERBS} <= set(printed)
    posts = printed["hub editorial posts"]["json"]
    assert (posts["kind"], posts["schema"]) == ("array", "EditorialPostSummary")
    assert {"slug", "title", "stage", "waiting_gate", "gates", "rounds", "preview_url", "url"} <= set(posts["keys"])
    assert printed["hub editorial show"]["json"]["schema"] == "EditorialPost"
    assert printed["hub editorial feedback"]["json"]["schema"] == "EditorialEntry"
    assert printed["hub editorial export"]["json"]["schema"] == "EditorialExport"
    for verb in VERBS:
        assert "--json" in {o["flags"][0] for o in printed[f"hub editorial {verb}"]["options"]}
    options = {o["flags"][0]: o for o in printed["hub editorial export"]["options"]}
    assert options["--format"]["choices"] == ["markdown", "json"] and options["--project"]["required"]


def test_hub_editorial_cli_feedback_takes_list_add_or_repeat(monkeypatch, capsys, tmp_path):
    home = write_credentials(tmp_path / "home", "https://hub.example.org", "alice", "evh_unused")
    with pytest.raises(SystemExit) as stopped:
        run_cli(monkeypatch, capsys, home, "hub", "editorial", "feedback", "drop", "--project", PROJECT)
    assert stopped.value.code == 2 and "list" in capsys.readouterr().err


def configured(hub) -> None:
    token = (hub.homes["owner"] / ".evo" / "hub" / "token").read_text(encoding="utf-8").strip()
    headers = {"Authorization": f"Bearer {token}"}
    base = f"{hub.url}/v1/projects/{PROJECT}/plugins/editorial"
    enabled = httpx.post(f"{base}/enable", json={"permissions": []}, headers=headers)
    assert enabled.status_code == 200, enabled.text
    configured = httpx.post(f"{base}/config", json={"values": CONFIG}, headers=headers)
    assert configured.status_code == 200, configured.text


def editorial(hub, monkeypatch, capsys, who: str, *args: str):
    return run_cli(monkeypatch, capsys, hub.homes[who], "hub", "editorial", *args, "--project", PROJECT)


@needs_pg
def test_hub_editorial_cli_sets_lists_and_shows_posts(hub, monkeypatch, capsys):
    refused = editorial(hub, monkeypatch, capsys, "alice", "posts")
    assert refused.code == 1 and "editorial is not enabled" in refused.err
    configured(hub)
    assert "No posts yet" in ok(editorial(hub, monkeypatch, capsys, "bao", "posts")).out
    made = as_json(editorial(hub, monkeypatch, capsys, "alice", "set", "lumen-notes", "--stage", "idea", "--json"))
    assert_json_keys("hub editorial set", made)
    assert made["waiting_gate"] == "idea"
    answer = ("--gate", "idea", "--gate-state", "answered", "--via", "telegram")
    shown = as_json(editorial(hub, monkeypatch, capsys, "alice", "set", "lumen-notes", *answer, "--json"))
    assert shown["gates"][0]["answered_via"] == "telegram" and shown["waiting_gate"] is None
    for slug, stage in (("lumen-notes", "draft"), ("lumen-notes", "review"), ("northwind-night", "idea")):
        ok(editorial(hub, monkeypatch, capsys, "alice", "set", slug, "--stage", stage))
    ok(editorial(hub, monkeypatch, capsys, "alice", "set", "northwind-day", "--stage", "draft"))
    ok(editorial(hub, monkeypatch, capsys, "alice", "set", "lumen-ship", "--stage", "ship"))

    found = as_json(editorial(hub, monkeypatch, capsys, "bao", "posts", "--json"))
    assert_json_keys("hub editorial posts", found)
    assert len(found) >= 4 and all({"slug", "stage", "gates"} <= set(p) for p in found)
    notes = next(p for p in found if p["slug"] == "lumen-notes")
    assert notes["waiting_gate"] == "review"
    assert [(g["stage"], g["state"], g["answered_via"]) for g in notes["gates"]] == [
        ("idea", "answered", "telegram"),
        ("review", "waiting", None),
    ]
    assert all({"stage", "state", "answered_at", "answered_via"} <= set(g) for p in found for g in p["gates"])
    only = as_json(editorial(hub, monkeypatch, capsys, "bao", "posts", "--stage", "idea", "--json"))
    assert [p["slug"] for p in only] == ["northwind-night"]
    table = ok(editorial(hub, monkeypatch, capsys, "bao", "posts")).out
    assert "waiting gate" in table and "lumen-notes" in table
    one = as_json(editorial(hub, monkeypatch, capsys, "bao", "show", "lumen-notes", "--json"))
    assert_json_keys("hub editorial show", one)
    assert [h["stage"] for h in one["history"]] == ["idea", "draft", "review"]
    assert "Gates:" in ok(editorial(hub, monkeypatch, capsys, "bao", "show", "lumen-notes")).out
    missing = editorial(hub, monkeypatch, capsys, "bao", "show", "nobody")
    assert missing.code == 1 and missing.err.startswith("error:")


@needs_pg
def test_hub_editorial_cli_imports_keeps_the_notebook_and_exports_it_as_kept(hub, monkeypatch, capsys, tmp_path):
    configured(hub)
    path = tmp_path / "editorial.json"
    path.write_text(json.dumps(DOCUMENT), encoding="utf-8")
    denied = editorial(hub, monkeypatch, capsys, "alice", "import", str(path))
    assert denied.code == 1 and "admin" in denied.err
    first = as_json(editorial(hub, monkeypatch, capsys, "owner", "import", str(path), "--json"))
    assert_json_keys("hub editorial import", first)
    assert (first["posts_added"], first["entries_added"]) == (1, 3)
    again = ok(editorial(hub, monkeypatch, capsys, "owner", "import", str(path))).out
    assert "Posts: 0 added, 1 updated. Entries: 0 added, 3 updated." in again

    listed = as_json(editorial(hub, monkeypatch, capsys, "bao", "feedback", "list", "--json"))
    assert_json_keys("hub editorial feedback", listed)
    assert [e["id"] for e in listed] == ["PH-0001", "PH-0002", "PH-0003"]
    add = ("--notebook", "style", "--title", "Short headings", "--said", "Too long.", "--rule", "Six words at most.")
    added = as_json(editorial(hub, monkeypatch, capsys, "alice", "feedback", "add", *add, "--json"))
    assert [(e["id"], e["seen"]) for e in added] == [("PH-0004", 1)]
    repeated = editorial(hub, monkeypatch, capsys, "alice", "feedback", "repeat", "PH-0004", "--said", "Still long.")
    assert "PH-0004" in ok(repeated).out and "Rule: Six words at most." in repeated.out
    seen = as_json(editorial(hub, monkeypatch, capsys, "bao", "feedback", "list", "--seen", "2", "--json"))
    assert [e["id"] for e in seen] == ["PH-0001", "PH-0004"]
    voice = as_json(editorial(hub, monkeypatch, capsys, "bao", "feedback", "list", "--notebook", "voice", "--json"))
    assert [e["id"] for e in voice] == ["PH-0001", "PH-0003"]
    words = ("recall", "--stage", "idea", "--keyword", "question", "--json")
    assert [e["id"] for e in as_json(editorial(hub, monkeypatch, capsys, "bao", *words))] == ["PH-0001"]
    recalled = as_json(editorial(hub, monkeypatch, capsys, "bao", "recall", "--stage", "draft", "--json"))
    assert [e["id"] for e in recalled] == ["PH-0001", "PH-0004", "PH-0002", "PH-0003"]

    printed = ok(editorial(hub, monkeypatch, capsys, "bao", "export", "--notebook", "voice")).out
    assert printed == VOICE
    whole = as_json(editorial(hub, monkeypatch, capsys, "bao", "export", "--format", "json", "--json"))
    assert_json_keys("hub editorial export", whole)
    assert [e["id"] for e in whole["document"]["entries"]] == ["PH-0001", "PH-0002", "PH-0003", "PH-0004"]
