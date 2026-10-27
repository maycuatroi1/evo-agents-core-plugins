"""The core plugin jev on the hub (``evo_core_plugins.jev``): Jev, the System One model of TypeSafe, as the tools
``jev__decide`` and ``jev__usage``, the routes behind them, a page and ``evo-agents hub jev``, with a ledger of what
each call cost and of what Jev decided.

Against a fake Jev server (``httpx.MockTransport``, no network): one request carries the state and all the questions,
pinned to the checked public address, with the key in the Authorization header alone; the answers come back as the
documented types; a call is refused with a readable reason when Jev is not configured, the project's policy declares
no sink, the daily budget is spent or the model that answered is not the pinned one; a failure is booked without
what the vendor sent, and nothing is retried. The ``optional`` tests are the invariant: with the plugin not enabled,
no key, no sink or every feature off, the fake receives no request and no table gets a row. All names are fictional.
"""

from __future__ import annotations

import json
import re
import secrets
from pathlib import Path

import pytest

from tests.hub import pg

if not pg.DSN:
    pytest.skip(pg.SKIP_REASON, allow_module_level=True)

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import func, insert, select

from evo_agents.hub import tables
from evo_agents.hub.server import core_plugin_api as hub_api
from evo_agents.hub.server.app import create_app
from evo_agents.hub.server.core_plugin_api._types import (
    issue_session,  # a test stands in for the hub that issues a session
)
from evo_core_plugins import PLUGINS
from evo_core_plugins.jev import client as jev_client
from evo_core_plugins.jev import manifest, service, settings, store
from evo_core_plugins.jev import tables as jev_tables
from evo_core_plugins.jev.models import JevAskIn
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

BASE = f"/v1/x/jev/{PROJECT}"
MODEL = "jev-1.2.0"
KEY = "northwind-key-0001"
PUBLIC = "93.184.216.34"
STATE = "Lumen order 42: the customer of Northwind wrote twice about a late delivery and asks for a refund."
QUESTIONS = {
    "urgency": {
        "type": "choice",
        "instructions": "How urgent is the message?",
        "criteria": {"now": "a customer is blocked", "later": "it can wait"},
    },
    "refund": {"type": "noul", "instructions": "Is the customer owed a refund?"},
    "tone": {"type": "score", "criteria": ["rude", "neutral", "warm"]},
}
ASK = {"state": STATE, "questions": QUESTIONS}


class FakeJev:
    """The fake server: it keeps every request it gets and answers what ``status``, ``model`` and ``tokens`` say."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.status = 200
        self.model = MODEL
        self.tokens = 1200
        self.fail: Exception | None = None

    def bodies(self) -> list[dict]:
        return [json.loads(request.content) for request in self.requests]

    def answer(self, question: dict) -> dict:
        if question["type"] == "choice":
            option = next(iter(question["criteria"]))
            return {"type": "choice", "choice": option, "confidence": 0.95, "probabilities": {option: 0.95}}
        if question["type"] == "noul":
            return {"type": "noul", "noul": 0.97}
        return {"type": "score", "score": 3, "confidence": 0.8, "legend": "warm", "probabilities": [0.1, 0.1, 0.8]}

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.fail is not None:
            raise self.fail
        if self.status != 200:
            leak = {"X-Echo": f"Bearer {KEY}"}
            return httpx.Response(self.status, text=f"upstream detail SECRETLEAK {KEY}", headers=leak)
        asked = json.loads(request.content)["questions"]
        body = {
            "model": self.model,
            "answers": {name: self.answer(question) for name, question in asked.items()},
            "usage": {"input_tokens": self.tokens, "output_tokens": 7},
        }
        return httpx.Response(200, json=body)


@pytest.fixture
def fake(monkeypatch) -> FakeJev:
    """The fake Jev behind the client; names resolve to a public address."""
    server = FakeJev()

    async def resolve(host: str, port: int) -> list[str]:
        return [PUBLIC]

    monkeypatch.setattr(jev_client, "TRANSPORT", httpx.MockTransport(server.handle))
    monkeypatch.setattr(jev_client, "RESOLVER", resolve)
    return server


@pytest.fixture
def client(hub_db, tmp_path, github, tasks_core):  # noqa: F811
    config = live.hub_config(
        hub_db, tmp_path, github, public_url="https://hub.test", secrets_key=secrets.token_bytes(32)
    )
    with TestClient(create_app(config), base_url="https://hub.test") as client:
        yield client


def project_id(hub_db) -> int:
    return sql(hub_db, select(tables.projects.c.id).where(tables.projects.c.name == PROJECT))[0][0]


def declare_sink(hub_db) -> None:
    sql(
        hub_db,
        insert(tables.project_sinks).values(
            project_id=project_id(hub_db), sink_id=settings.SINK, kind="llm-backend", clearance={"level": "internal"}
        ),
    )


@pytest.fixture
def enabled(client, members, fake):  # noqa: F811
    """``members`` with jev enabled and nothing else: no key, no model, no sink."""
    enable(client, members["owner"], "jev")
    return members


@pytest.fixture
def jev(client, enabled, hub_db):
    """jev enabled with a key, a pinned model, a budget of 1 USD, and the sink declared in the project's policy."""
    configure(client, enabled["owner"], "jev", {"api_key": KEY, "model": MODEL, "daily_usd": 1})
    declare_sink(hub_db)
    return enabled


def count(hub_db, table) -> int:
    return sql(hub_db, select(func.count()).select_from(table))[0][0]


def untouched(fake: FakeJev, hub_db) -> None:
    """The invariant: nothing was sent, and no table of the plugin got a row."""
    assert fake.requests == []
    assert (count(hub_db, jev_tables.usage), count(hub_db, jev_tables.acts)) == (0, 0)


def ok(answer, status: int = 200):
    assert answer.status_code == status, answer.text
    return answer.json()


def refused(answer, status: int) -> str:
    assert answer.status_code == status, answer.text
    return answer.json()["message"]


def mcp(client, headers, name: str, arguments: dict | None = None) -> tuple:
    result = rpc(client, headers, call(9, name, arguments or {}))
    text = result["content"][0]["text"]
    return (text if result["isError"] else json.loads(text)), result["isError"]


def on_hub(client, work):
    async def run():
        async with client.app.state.engine.begin() as conn:
            return await work(conn)

    return client.portal.call(run)


# The manifest, the config and the tables


def test_jev_manifest_declares_the_sink_the_config_the_tools_and_the_ledger():
    found = manifest()
    contributes = found["contributes"]
    assert (found["id"], found["version"], found["permissions"]) == ("jev", "1.1.0", [])
    assert found["egress"] == [{"id": "jev@typesafe", "kind": "llm-backend", "host": "api.typesafe.ai"}]
    assert [t["name"] for t in contributes["mcp_tools"]] == ["decide", "usage"]
    assert [(p["name"], p["entry"]) for p in contributes["pages"]] == [("jev", "pages/jev.html")]
    assert [t["name"] for t in contributes["tables"]] == list(jev_tables.NAMES)
    assert {c["name"] for c in contributes["cli"]} == {"status", "ask", "usage", "acts"}
    assert found["schema"]["migrations"] == "evo_core_plugins.jev.migrations"
    assert hub_api.plugin("evo_core_plugins.jev.store").egress == (
        hub_api.EgressSink("jev@typesafe", "llm-backend", "api.typesafe.ai"),
    )


def test_jev_config_is_flat_with_every_feature_off_and_the_starting_thresholds():
    props = settings.CONFIG["properties"]
    assert props["api_key"]["x-secret"] is True and "default" not in props["model"]
    assert props["base_url"]["default"] == "https://api.typesafe.ai"
    for feature in ("triage", "kg_review", "corrections"):
        assert props[f"{feature}_mode"]["default"] == "off" and props[f"{feature}_mode"]["enum"] == [
            "off",
            "suggest",
            "apply",
        ]
        assert props[f"{feature}_threshold"]["default"] == 0.9 and props[f"{feature}_cap"]["default"] == 50
    assert (props["kg_review_noul_yes"]["default"], props["kg_review_noul_no"]["default"]) == (0.9, 0.1)
    assert props["rerank"]["default"] == "off" and props["rerank"]["enum"] == ["off", "on"]
    assert all(settings.read({}).modes[name] == "off" for name in settings.FEATURES)
    model = re.compile(props["model"]["pattern"])
    assert model.match("jev-1.2.0") and model.match("jev-10.0.31")
    assert not any(model.match(alias) for alias in ("jev-latest", "jev", "jev-1.2", "jev-1.2.0-beta", "xjev-1.2.0"))


def test_jev_config_refuses_an_alias_as_the_pinned_model(client, enabled):
    body = {"values": {"model": "jev-latest"}}
    answer = client.post(f"/v1/projects/{PROJECT}/plugins/jev/config", json=body, headers=enabled["owner"])
    assert 400 <= answer.status_code < 500, answer.text
    configure(client, enabled["owner"], "jev", {"model": MODEL})


def test_jev_its_migration_makes_the_tables_its_metadata_holds(client, enabled, hub_db):
    with live.engine(hub_db).begin() as conn:
        assert hub_api.adopt_tables(conn, jev_tables.metadata, list(jev_tables.NAMES)) == []


def test_jev_cost_is_the_vendors_price_for_the_input_tokens():
    assert float(store.cost_of(1_000_000)) == pytest.approx(0.042)
    assert float(store.cost_of(1200)) == pytest.approx(0.0000504)
    assert 0 < jev_client.TIMEOUT.read < 30 and jev_client.TIMEOUT.connect < jev_client.TIMEOUT.read


# The call


def test_jev_decide_sends_one_pinned_request_and_books_usage_and_acts(client, jev, fake, hub_db):
    found, error = mcp(client, jev["alice"], "jev__decide", ASK)
    assert not error, found
    assert (found["model"], found["input_tokens"]) == (MODEL, 1200)
    assert found["cost_usd"] == pytest.approx(0.0000504)
    assert found["answers"]["urgency"]["choice"] == "now" and found["answers"]["urgency"]["confidence"] == 0.95
    assert found["answers"]["refund"]["noul"] == 0.97 and found["answers"]["tone"]["score"] == 3
    [request] = fake.requests
    assert request.method == "POST" and request.url.path == "/v1/systemone"
    assert request.url.host == PUBLIC, "the call goes to the address that was checked"
    assert request.headers["host"] == "api.typesafe.ai"
    assert request.extensions["sni_hostname"] == "api.typesafe.ai"
    assert request.headers["authorization"] == f"Bearer {KEY}"
    assert KEY not in request.content.decode() and KEY not in str(request.url)
    [sent] = fake.bodies()
    assert sent["model"] == MODEL and sent["state"] == STATE and set(sent["questions"]) == set(QUESTIONS)
    assert sent["questions"]["urgency"]["criteria"] == QUESTIONS["urgency"]["criteria"]
    [row] = sql(hub_db, select(jev_tables.usage.c.feature, jev_tables.usage.c.model, jev_tables.usage.c.input_tokens))
    assert row == ("tool", MODEL, 1200)
    spent = sql(hub_db, select(func.sum(jev_tables.usage.c.cost_usd)))[0][0]
    assert float(spent) == pytest.approx(0.0000504)
    acts = sql(
        hub_db,
        select(jev_tables.acts.c.kind, jev_tables.acts.c.target, jev_tables.acts.c.outcome, jev_tables.acts.c.applied),
    )
    assert sorted(acts) == [
        ("choice", "urgency", "now", False),
        ("noul", "refund", "0.970", False),
        ("score", "tone", "3", False),
    ]


def test_jev_the_route_and_the_tool_answer_alike_and_the_route_has_words_for_the_cli(client, jev, fake):
    found = ok(client.post(f"{BASE}/ask", json=ASK, headers=jev["alice"]))
    via_tool, _ = mcp(client, jev["alice"], "jev__decide", ASK)
    assert found == via_tool and len(fake.requests) == 2
    said = ok(client.post(f"{BASE}/ask", params={"render": "text"}, json=ASK, headers=jev["alice"]))["text"]
    assert MODEL in said and "urgency [choice]: now" in said and "1200 input tokens" in said


def test_jev_a_reader_reads_usage_and_acts_and_does_not_ask(client, jev, fake):
    assert refused(client.post(f"{BASE}/ask", json=ASK, headers=jev["eve"]), 403).count("writer")
    text, error = mcp(client, jev["eve"], "jev__decide", ASK)
    assert error and "writer" in text and fake.requests == []
    assert {"jev__decide", "jev__usage"} <= set(tool_names(client, jev["eve"]))
    ok(client.get(f"{BASE}/usage", headers=jev["eve"]))
    ok(client.get(f"{BASE}/acts", headers=jev["eve"]))
    assert ok(client.get(f"{BASE}/status", headers=jev["eve"]))["configured"] is True


def test_jev_questions_are_checked_before_anything_is_sent(client, jev, fake):
    bad = {
        "state": STATE,
        "questions": {"urgency": {"type": "choice", "criteria": {"now": "only one option"}}},
    }
    assert client.post(f"{BASE}/ask", json=bad, headers=jev["alice"]).status_code == 422
    text, error = mcp(client, jev["alice"], "jev__decide", bad)
    assert error and "criteria" in text
    for questions in (
        {},
        {"1bad": {"type": "noul"}},
        {"x": {"type": "rank"}},
        {"x": {"type": "score", "criteria": ["a"]}},
    ):
        answer = client.post(f"{BASE}/ask", json={"state": STATE, "questions": questions}, headers=jev["alice"])
        assert answer.status_code == 422, questions
    text, error = mcp(
        client, jev["alice"], "jev__decide", {"state": STATE, "questions": {"x": {"type": "noul"}, "y": {}}}
    )
    assert error
    big = {"state": "northwind " * 20_000, "questions": {"x": {"type": "noul"}}}
    assert "at most" in refused(client.post(f"{BASE}/ask", json=big, headers=jev["alice"]), 422)
    assert fake.requests == []


# The refusals


def test_jev_refuses_with_a_reason_when_it_is_not_configured(client, enabled, hub_db, fake):
    declare_sink(hub_db)
    assert "no api_key" in refused(client.post(f"{BASE}/ask", json=ASK, headers=enabled["alice"]), 409)
    configure(client, enabled["owner"], "jev", {"api_key": KEY})
    assert "no pinned model" in refused(client.post(f"{BASE}/ask", json=ASK, headers=enabled["alice"]), 409)
    text, error = mcp(client, enabled["alice"], "jev__decide", ASK)
    assert error and text.startswith("refused:") and "no pinned model" in text
    status = ok(client.get(f"{BASE}/status", headers=enabled["alice"]))
    assert status["configured"] is False and status["key_set"] is True and status["problems"]
    untouched(fake, hub_db)


def test_jev_refuses_when_the_policy_declares_no_sink(client, enabled, hub_db, fake):
    configure(client, enabled["owner"], "jev", {"api_key": KEY, "model": MODEL})
    said = refused(client.post(f"{BASE}/ask", json=ASK, headers=enabled["alice"]), 409)
    assert "declares no sink jev@typesafe" in said
    text, error = mcp(client, enabled["alice"], "jev__usage", {})
    assert not error, "reading the ledger needs no sink"
    assert ok(client.get(f"{BASE}/status", headers=enabled["alice"]))["sink_declared"] is False
    untouched(fake, hub_db)


def test_jev_refuses_over_the_daily_budget_and_counts_what_was_spent(client, jev, hub_db, fake):
    sql(
        hub_db,
        insert(jev_tables.usage).values(
            project_id=project_id(hub_db), feature="tool", model=MODEL, input_tokens=0, cost_usd=1.0
        ),
    )
    said = refused(client.post(f"{BASE}/ask", json=ASK, headers=jev["alice"]), 409)
    assert "spent" in said and "1 USD a day" in said
    text, error = mcp(client, jev["alice"], "jev__decide", ASK)
    assert error and "a day" in text and fake.requests == []
    assert ok(client.get(f"{BASE}/usage", headers=jev["eve"]))["spent_today_usd"] == pytest.approx(1.0)
    configure(client, jev["owner"], "jev", {"daily_usd": 2})
    ok(client.post(f"{BASE}/ask", json=ASK, headers=jev["alice"]))
    assert len(fake.requests) == 1


def test_jev_refuses_an_answer_from_another_model_and_books_what_it_cost(client, jev, fake, hub_db):
    fake.model = "jev-1.2.1"
    said = refused(client.post(f"{BASE}/ask", json=ASK, headers=jev["alice"]), 502)
    assert "jev-1.2.1" in said and f"pinned {MODEL}" in said
    [row] = sql(hub_db, select(jev_tables.usage.c.status, jev_tables.usage.c.input_tokens))
    assert row == ("error", 1200), "the tokens were spent"
    assert count(hub_db, jev_tables.acts) == 0, "nothing the wrong model said is kept"
    text, error = mcp(client, jev["alice"], "jev__decide", ASK)
    assert error and "pinned" in text and len(fake.requests) == 2, "no automatic retry"


@pytest.mark.parametrize("status", [401, 429, 500])
def test_jev_a_failed_call_is_booked_once_and_says_nothing_the_vendor_sent(client, jev, fake, hub_db, status):
    fake.status = status
    answer = client.post(f"{BASE}/ask", json=ASK, headers=jev["alice"])
    assert answer.status_code == 502 and answer.json()["message"] == f"Jev answered HTTP {status}"
    assert "SECRETLEAK" not in answer.text and KEY not in answer.text
    assert len(fake.requests) == 1, "no retry"
    [row] = sql(hub_db, select(jev_tables.usage.c.status, jev_tables.usage.c.input_tokens))
    assert row == ("error", 0)
    stored = json.dumps(sql(hub_db, select(tables.audit)), default=str)
    assert "SECRETLEAK" not in stored and KEY not in stored


def test_jev_a_timeout_and_a_redirect_are_failures_and_a_redirect_is_not_followed(client, jev, fake, hub_db):
    fake.fail = httpx.ReadTimeout("slow")
    assert "in time" in refused(client.post(f"{BASE}/ask", json=ASK, headers=jev["alice"]), 502)
    fake.fail = None
    assert len(fake.requests) == 1

    def redirect(request: httpx.Request) -> httpx.Response:
        fake.requests.append(request)
        return httpx.Response(302, headers={"Location": "https://elsewhere.example.org/v1/systemone"})

    jev_client.TRANSPORT = httpx.MockTransport(redirect)
    assert refused(client.post(f"{BASE}/ask", json=ASK, headers=jev["alice"]), 502) == "Jev answered HTTP 302"
    assert len(fake.requests) == 2 and fake.requests[-1].url.host == PUBLIC


@pytest.mark.parametrize(
    "resolved", [["10.0.0.5"], [PUBLIC, "127.0.0.1"], ["::ffff:10.0.0.5"], ["100.64.0.9"], ["fd00::1"]]
)
def test_jev_a_host_that_resolves_to_a_private_address_is_never_called(
    client, jev, fake, hub_db, monkeypatch, resolved
):
    async def resolve(host: str, port: int) -> list[str]:
        return resolved

    monkeypatch.setattr(jev_client, "RESOLVER", resolve)
    assert "not public" in refused(client.post(f"{BASE}/ask", json=ASK, headers=jev["alice"]), 502)
    untouched(fake, hub_db)


def test_jev_the_base_url_is_https_without_credentials_and_public_addresses_are_told_apart(client, jev, fake, hub_db):
    for base in (
        "http://api.typesafe.ai",
        "https://key:pass@api.typesafe.ai",
        "https://api.typesafe.ai/?q=1",
        "ftp://x",
    ):
        configure(client, jev["owner"], "jev", {"base_url": base})
        assert refused(client.post(f"{BASE}/ask", json=ASK, headers=jev["alice"]), 502)
    untouched(fake, hub_db)
    assert [jev_client.public(a) for a in (PUBLIC, "8.8.8.8", "2606:4700::1111")] == [True] * 3
    private = ("127.0.0.1", "10.1.2.3", "172.16.0.1", "192.168.1.1", "169.254.169.254", "100.64.0.1", "224.0.0.1")
    assert not any(jev_client.public(a) for a in (*private, "::1", "fe80::1", "::ffff:127.0.0.1", "ff02::1", "junk"))


def test_jev_a_base_url_with_a_path_keeps_it_and_the_pin_holds_the_port(client, jev, fake):
    configure(client, jev["owner"], "jev", {"base_url": "https://api.typesafe.ai:8443/gateway/"})
    ok(client.post(f"{BASE}/ask", json=ASK, headers=jev["alice"]))
    [request] = fake.requests
    assert (request.url.host, request.url.port, request.url.path) == (PUBLIC, 8443, "/gateway/v1/systemone")
    assert request.headers["host"] == "api.typesafe.ai:8443"


# The ledger


def test_jev_usage_sums_the_last_day_and_week_by_feature(client, jev, fake, hub_db):
    ok(client.post(f"{BASE}/ask", json=ASK, headers=jev["alice"]))
    ok(client.post(f"{BASE}/ask", json=ASK, headers=jev["alice"]))
    pid = project_id(hub_db)
    from datetime import UTC, datetime, timedelta

    sql(
        hub_db,
        insert(jev_tables.usage).values(
            project_id=pid,
            feature="triage",
            model=MODEL,
            input_tokens=5000,
            cost_usd=0.0002,
            created_at=datetime.now(UTC) - timedelta(days=3),
        ),
    )
    usage = ok(client.get(f"{BASE}/usage", headers=jev["eve"]))
    assert usage["last_24h"]["calls"] == 2 and usage["last_24h"]["input_tokens"] == 2400
    assert usage["last_7d"]["calls"] == 3 and usage["last_7d"]["input_tokens"] == 7400
    assert usage["last_7d"]["cost_usd"] == pytest.approx(0.0000504 * 2 + 0.0002)
    assert [row["feature"] for row in usage["last_7d"]["by_feature"]] == ["tool", "triage"]
    found, error = mcp(client, jev["eve"], "jev__usage")
    assert not error and found["last_24h"]["calls"] == 2
    text = ok(client.get(f"{BASE}/usage", params={"render": "text"}, headers=jev["eve"]))["text"]
    assert "24 hours: 2 calls" in text and "tool: 2 calls" in text


def test_jev_acts_list_newest_first_with_the_hubs_undo_for_an_applied_one(client, jev, hub_db):
    pid = project_id(hub_db)
    rows = [
        {"kind": "choice", "feature": "triage", "target": "run:41", "outcome": "environment", "applied": True},
        {"kind": "noul", "feature": "kg_review", "target": "review:ab12:cd", "outcome": "0.970", "applied": True},
        {"kind": "choice", "feature": "triage", "target": "run:42", "outcome": "runtime", "applied": False},
    ]
    for row in rows:
        sql(hub_db, insert(jev_tables.acts).values(project_id=pid, model=MODEL, confidence=0.95, **row))
    found = ok(client.get(f"{BASE}/acts", headers=jev["eve"]))["acts"]
    assert [act["target"] for act in found] == ["run:42", "review:ab12:cd", "run:41"]
    assert found[0]["undo"] is None and found[0]["applied"] is False
    assert found[2]["undo"] == {
        "command": f"evo-agents hub run-cause restore 41 --project {PROJECT}",
        "method": "POST",
        "path": f"/v1/projects/{PROJECT}/runs/41/cause/restore",
    }
    assert found[1]["undo"]["command"] == f"evo-agents hub kg review undismiss ab12:cd --project {PROJECT}"
    assert found[1]["undo"]["path"] == f"/v1/kg/{PROJECT}/review/ab12:cd/dismiss"
    assert on_hub(client, lambda conn: store.mark_undone(conn, pid, found[2]["id"])) is True
    assert on_hub(client, lambda conn: store.mark_undone(conn, pid, found[2]["id"])) is False
    after = ok(client.get(f"{BASE}/acts", params={"limit": 1}, headers=jev["eve"]))["acts"]
    assert len(after) == 1
    again = {act["target"]: act for act in ok(client.get(f"{BASE}/acts", headers=jev["eve"]))["acts"]}
    assert again["run:41"]["undone"] is True and again["run:41"]["undo"] is None
    text = ok(client.get(f"{BASE}/acts", params={"render": "text"}, headers=jev["eve"]))["text"]
    assert "evo-agents hub kg review undismiss ab12:cd" in text and "undone" in text


def test_jev_the_status_never_holds_the_key_and_lists_every_feature_off(client, jev):
    found = ok(client.get(f"{BASE}/status", headers=jev["alice"]))
    assert KEY not in json.dumps(found)
    assert found["configured"] and found["sink_declared"] and not found["problems"]
    assert {f["name"]: f["mode"] for f in found["features"]} == {
        "triage": "off",
        "kg_review": "off",
        "corrections": "off",
        "rerank": "off",
    }
    review = next(f for f in found["features"] if f["name"] == "kg_review")
    assert (review["threshold"], review["noul_yes"], review["noul_no"], review["cap"]) == (0.9, 0.9, 0.1, 50)
    assert "Jev in" in ok(client.get(f"{BASE}/status", params={"render": "text"}, headers=jev["alice"]))["text"]


def test_jev_a_feature_applies_only_in_apply_mode_over_its_threshold_and_under_its_cap(client, jev, hub_db):
    configure(client, jev["owner"], "jev", {"triage_mode": "apply", "triage_cap": 1, "kg_review_mode": "suggest"})
    pid = project_id(hub_db)

    async def decide(conn, feature, confidence):
        config = await hub_api.plugin_config(conn, store.handle(), client.app.state.config, project=PROJECT)
        return await service.can_apply(
            conn, pid, settings.read(config.values), dict(config.values), feature, confidence
        )

    assert on_hub(client, lambda conn: decide(conn, "triage", 0.95)) == "apply"
    assert on_hub(client, lambda conn: decide(conn, "triage", 0.5)) == "suggest"
    assert on_hub(client, lambda conn: decide(conn, "kg_review", 0.99)) == "suggest"
    assert on_hub(client, lambda conn: decide(conn, "corrections", 0.99)) == "off"
    sql(
        hub_db,
        insert(jev_tables.acts).values(
            project_id=pid,
            kind="choice",
            feature="triage",
            target="run:1",
            outcome="runtime",
            model=MODEL,
            applied=True,
        ),
    )
    assert on_hub(client, lambda conn: decide(conn, "triage", 0.95)) == "suggest", "the cap of 1 a day is reached"


# The invariant: optional


def test_jev_optional_a_project_that_did_not_enable_it_gets_nothing(client, members, hub_db, fake):  # noqa: F811
    for answer in (
        client.post(f"{BASE}/ask", json=ASK, headers=members["alice"]),
        client.get(f"{BASE}/status", headers=members["alice"]),
        client.get(f"{BASE}/usage", headers=members["alice"]),
    ):
        assert answer.status_code == 404, answer.text
    declare_sink(hub_db)
    untouched(fake, hub_db)
    assert "jev__decide" not in tool_names(client, members["alice"])


def test_jev_optional_without_an_api_key_nothing_is_sent_or_written(client, enabled, hub_db, fake):
    declare_sink(hub_db)
    configure(client, enabled["owner"], "jev", {"model": MODEL, "triage_mode": "apply", "rerank": "on"})
    assert refused(client.post(f"{BASE}/ask", json=ASK, headers=enabled["alice"]), 409)
    text, error = mcp(client, enabled["alice"], "jev__decide", ASK)
    assert error and "api_key" in text
    untouched(fake, hub_db)


def test_jev_optional_without_the_sink_in_the_policy_nothing_is_sent_or_written(client, enabled, hub_db, fake):
    configure(client, enabled["owner"], "jev", {"api_key": KEY, "model": MODEL, "triage_mode": "apply"})
    text, error = mcp(client, enabled["alice"], "jev__decide", ASK)
    assert error and "declares no sink" in text
    untouched(fake, hub_db)


def test_jev_optional_with_every_feature_off_a_feature_applies_nothing(client, jev, hub_db, fake):
    pid = project_id(hub_db)

    async def run(feature):
        async with client.app.state.engine.begin() as conn:
            config = await hub_api.plugin_config(conn, store.handle(), client.app.state.config, project=PROJECT)
            found = settings.read(config.values)
            assert found.modes[feature] == "off" and not found.any_feature
            return await service.can_apply(conn, pid, found, dict(config.values), feature, 1.0)

    for feature in ("triage", "kg_review", "corrections", "rerank"):
        assert client.portal.call(run, feature) == "off"
    untouched(fake, hub_db)


def test_jev_optional_a_feature_that_is_off_refuses_its_own_call_before_anything_is_sent(client, jev, hub_db, fake):
    asked = JevAskIn.model_validate(ASK)

    async def run():
        async with client.app.state.engine.begin() as conn:
            u = tables.users
            user_id = (await conn.execute(select(u.c.id).where(u.c.login == "alice"))).scalar_one()
        session = issue_session(user_id, "alice", 0, False)
        with pytest.raises(hub_api.Refused) as stopped:
            await service.ask(
                lambda: client.app.state.engine.begin(),
                client.app.state.config,
                session,
                PROJECT,
                asked,
                feature="triage",
            )
        return stopped.value.detail

    assert "feature triage is off" in client.portal.call(run)
    untouched(fake, hub_db)


def test_jev_optional_every_plugin_of_the_distribution_requires_the_same_api():
    import importlib

    versions = {name: importlib.import_module(f"evo_core_plugins.{name}").API for name in PLUGINS}
    assert "jev" in versions and set(versions.values()) == {
        hub_api.API_VERSION == (1, 6) and (1, 6) or hub_api.API_VERSION
    }
    assert versions["jev"] == (1, 6)


def test_jev_optional_the_code_the_tests_and_the_docs_use_fictional_names():
    root = Path(__file__).resolve().parent.parent
    banned = re.compile("|".join(("ome" + "let", "soc" + "rat", "meri" + "dai", "bi" + "nh")), re.IGNORECASE)
    files = [
        *(root / "evo_core_plugins" / "jev").rglob("*"),
        *Path(__file__).parent.glob("*jev*"),
        root / "docs" / "jev-plugin.md",
    ]
    for path in files:
        if path.is_file() and path.suffix in {".py", ".json", ".js", ".css", ".html", ".md"}:
            assert not banned.search(path.read_text(encoding="utf-8")), path


# The page and the commands


def test_jev_the_page_reads_at_a_narrow_screen_in_light_and_dark_in_english_and_vietnamese():
    import evo_core_plugins.jev as package

    pages = Path(package.__file__).with_name("ui") / "pages"
    html = (pages / "jev.html").read_text(encoding="utf-8")
    assert 'name="viewport" content="width=device-width, initial-scale=1"' in html and "jev.js" in html
    css = (pages / "jev.css").read_text(encoding="utf-8") + (pages / "common.css").read_text(encoding="utf-8")
    assert "minmax(9rem, 1fr)" in css and "overflow-wrap" in css, "the figures wrap at 375 px"
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", (pages / "jev.css").read_text(encoding="utf-8")), (
        "colours come from the kit"
    )
    script = (pages / "jev.js").read_text(encoding="utf-8")
    assert all(f'page.call("{route}"' in script for route in ("status", "usage", "acts")) and "undo.command" in script
    english = (pages / "i18n" / "en.js").read_text(encoding="utf-8")
    vietnamese = (pages / "i18n" / "vi.js").read_text(encoding="utf-8")
    keys = set(json.loads(english[english.index("{") : english.rindex("}") + 1]))
    assert keys == set(json.loads(vietnamese[vietnamese.index("{") : vietnamese.rindex("}") + 1]))


def test_jev_cli_commands_are_in_the_contract_each_with_json():
    from evo_agents.hub.contract import commands

    printed = commands()
    verbs = ("status", "ask", "usage", "acts")
    assert {f"hub jev {verb}" for verb in verbs} <= set(printed)
    schemas = {"status": "JevStatus", "ask": "JevAsked", "usage": "JevUsage", "acts": "JevActs"}
    for verb in verbs:
        found = printed[f"hub jev {verb}"]
        assert found["json"]["schema"] == schemas[verb] and found["json"]["kind"] == "object"
        assert "--json" in {o["flags"][0] for o in found["options"]}
    assert {o["flags"][0]: o for o in printed["hub jev ask"]["options"]}["--file"]["required"]
    assert {o["flags"][0]: o for o in printed["hub jev status"]["options"]}["--project"]["required"]
