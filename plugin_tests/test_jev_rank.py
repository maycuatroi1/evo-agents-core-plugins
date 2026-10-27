"""The ranker of the plugin jev (``evo_core_plugins.jev.rank``), against a fake Jev server (no network).

The handler runs with the context and the params the hub gives a ranker. One request carries the query, the hits and
a score question for each hit; the hits come back by score. A failed, late or refused call, a feature that is off or
fewer than two hits leave the hub's order (no order is answered). All names are fictional.
"""

from __future__ import annotations

import asyncio

import pytest

from tests.hub import pg

if not pg.DSN:
    pytest.skip(pg.SKIP_REASON, allow_module_level=True)

from sqlalchemy import select

from evo_agents.hub.plugin_calls import CoreContext
from evo_core_plugins.jev import client as jev_client
from evo_core_plugins.jev import rank, settings
from evo_core_plugins.jev import tables as jev_tables
from plugin_tests.test_jev_plugin import (  # noqa: F401 (fixtures)
    PROJECT,
    client,
    configure,
    count,
    declare_sink,
    enable,
    enabled,
    fake,
    jev,
    members,
    project_id,
    sql,
    tasks_core,
    untouched,
)


def hits(count_: int = 4) -> list[dict]:
    return [{"id": f"note-{i}", "text": f"lantern note {i}", "source": "history"} for i in range(count_)]


def asks(client, hub_db, found: list[dict]) -> dict:
    context = CoreContext(
        "jev", client.app.state.engine, client.app.state.config, PROJECT, project_id(hub_db), sink=settings.SINK
    )
    params = {
        "project": PROJECT,
        "project_id": project_id(hub_db),
        "query": "which lantern",
        "source": "history",
        "sink": settings.SINK,
        "hits": found,
    }
    return client.portal.call(lambda: rank.rank(params, context))


def put_scores(fake, values: list[float], monkeypatch) -> None:
    """Answer score ``values[i]`` to the question ``h<i>``."""
    import json

    import httpx

    def handle(request: httpx.Request) -> httpx.Response:
        fake.requests.append(request)
        asked = json.loads(request.content)["questions"]
        answers = {name: {"type": "score", "score": values[int(name[1:])], "confidence": 0.8} for name in asked}
        body = {"model": fake.model, "answers": answers, "usage": {"input_tokens": fake.tokens, "output_tokens": 7}}
        return httpx.Response(200, json=body)

    monkeypatch.setattr(jev_client, "TRANSPORT", httpx.MockTransport(handle))


def test_jev_rank_puts_the_hits_in_the_order_of_their_scores_with_one_request(client, jev, hub_db, fake, monkeypatch):
    configure(client, jev["owner"], "jev", {"rerank": "on"})
    put_scores(fake, [1, 4, 2, 4], monkeypatch)
    answer = asks(client, hub_db, hits())
    assert answer == {"order": ["note-1", "note-3", "note-2", "note-0"]}  # the tie keeps the hub's order
    assert len(fake.requests) == 1
    body = fake.bodies()[0]
    assert "which lantern" in body["state"] and "lantern note 3" in body["state"]
    assert set(body["questions"]) == {"h0", "h1", "h2", "h3"}
    usage = jev_tables.usage.c
    assert sql(hub_db, select(usage.feature, usage.status)) == [("rerank", "ok")]


def test_jev_rank_sends_at_most_twenty_hits(client, jev, hub_db, fake, monkeypatch):
    configure(client, jev["owner"], "jev", {"rerank": "on"})
    put_scores(fake, list(range(30)), monkeypatch)
    answer = asks(client, hub_db, hits(25))
    assert len(fake.bodies()[0]["questions"]) == 20
    assert answer["order"][0] == "note-19" and len(answer["order"]) == 20


@pytest.mark.parametrize("status", [500, 429])
def test_jev_rank_a_failed_call_leaves_the_old_order(client, jev, hub_db, fake, status):
    configure(client, jev["owner"], "jev", {"rerank": "on"})
    fake.status = status
    assert asks(client, hub_db, hits()) == {}
    assert len(fake.requests) == 1  # nothing is retried


def test_jev_rank_a_late_call_leaves_the_old_order_and_still_books_its_cost(client, jev, hub_db, fake, monkeypatch):
    configure(client, jev["owner"], "jev", {"rerank": "on"})
    put_scores(fake, [1, 2, 3, 4], monkeypatch)
    real = jev_client.ask

    async def slow(*args, **kwargs):
        await asyncio.sleep(0.3)
        return await real(*args, **kwargs)

    monkeypatch.setattr(jev_client, "ask", slow)
    monkeypatch.setattr(rank, "WAIT", 0.05)

    async def late():
        context = CoreContext(
            "jev", client.app.state.engine, client.app.state.config, PROJECT, project_id(hub_db), sink=settings.SINK
        )
        params = {"project": PROJECT, "query": "q", "hits": hits()}
        answer = await rank.rank(params, context)
        await asyncio.gather(*rank._pending)  # the call finishes in the background
        return answer

    assert client.portal.call(late) == {}
    assert count(hub_db, jev_tables.usage) == 1


def test_jev_rank_a_budget_spent_leaves_the_old_order_without_a_request(client, jev, hub_db, fake):
    configure(client, jev["owner"], "jev", {"rerank": "on", "daily_usd": 0.0000001})
    assert asks(client, hub_db, hits()) == {}
    assert fake.requests == []


def test_jev_rank_another_model_than_the_pinned_one_leaves_the_old_order(client, jev, hub_db, fake, monkeypatch):
    configure(client, jev["owner"], "jev", {"rerank": "on"})
    put_scores(fake, [1, 2, 3, 4], monkeypatch)
    fake.model = "jev-9.9.9"
    assert asks(client, hub_db, hits()) == {}


def test_jev_rank_with_the_feature_off_or_one_hit_nothing_is_asked_or_written(client, jev, hub_db, fake):
    assert asks(client, hub_db, hits()) == {}  # rerank is off
    configure(client, jev["owner"], "jev", {"rerank": "on"})
    assert asks(client, hub_db, hits(1)) == {}
    untouched(fake, hub_db)
