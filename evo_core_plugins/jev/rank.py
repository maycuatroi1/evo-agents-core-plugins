"""Rerank: the ranker of the plugin (extension point ``rankers``), which puts the first hits of ``history_search`` and
``kg_search`` in the order Jev scores them.

The hub hands the handler the query and the hits the project's policy lets the sink read, at most 20 (``params``). One
request goes to Jev with the query and the hits as the state and one ``score`` question for each hit, on four
ordered levels; the hits come back by score, highest first, and a tie keeps the order the hub gave. The hub gives the
whole search 2 seconds: the handler waits less than that for Jev, and on a failed, late or refused call (a budget
spent, a model that is not the pinned one) it answers no order, so the old one stays. A call that is late still
finishes in the background so its cost is booked. Nothing is asked unless the project enabled the plugin, the
feature ``rerank`` is on, a key and a model are set and the sink is declared (``automatic.setup``).
"""

from __future__ import annotations

import asyncio
import logging

from evo_agents.hub.server import core_plugin_api as hub
from evo_core_plugins.jev import automatic, service

log = logging.getLogger(__name__)
FEATURE = "rerank"
MAX_HITS = 20
WAIT = 1.7  # seconds the handler waits for Jev, under the hub's 2 for the whole search
HIT_CHARS = 1500
LEVELS = ["unrelated", "mentions the topic", "partly answers", "answers the query"]
_pending: set[asyncio.Task] = set()  # calls that outlived their wait, kept until they finish


def question(name: str) -> dict:
    return {
        "type": "score",
        "instructions": f"How well does hit {name} answer the query?",
        "criteria": LEVELS,
    }


def state_of(query: str, hits: list[dict]) -> str:
    parts = [f"Query: {query}"]
    parts += [f"Hit {name}: {text}" for name, text in hits]
    return "\n\n".join(parts)


def order_by(ids: list[str], scores: list[float]) -> list[str]:
    """``ids`` by score, highest first; equal scores keep their place."""
    ranked = sorted(range(len(ids)), key=lambda i: (-scores[i], i))
    return [ids[i] for i in ranked]


async def rank(params: dict, context: hub.Context) -> dict:
    """The ranker: ``{"order": [ids]}``, or ``{}`` (the hub keeps its order) when Jev is not to be asked or did not
    answer in time."""
    hits = [hit for hit in params.get("hits") or [] if isinstance(hit, dict) and isinstance(hit.get("id"), str)]
    hits = hits[:MAX_HITS]
    if len(hits) < 2:
        return {}
    on = await automatic.setup(context, params.get("project"), FEATURE)
    if on is None:
        return {}
    names = [f"h{i}" for i in range(len(hits))]
    shown = [(name, str(hit.get("text") or "")[:HIT_CHARS]) for name, hit in zip(names, hits, strict=True)]
    try:
        asked = service.parse(state_of(str(params.get("query") or ""), shown), {name: question(name) for name in names})
    except hub.Refused as exc:
        log.info("jev rerank skipped", extra={"project": on.project, "why": exc.detail})
        return {}
    task = asyncio.ensure_future(
        service.automatic(lambda: hub.transaction(context), context.config, on.project, asked, feature=FEATURE)
    )
    _pending.add(task)
    task.add_done_callback(_pending.discard)
    done, _ = await asyncio.wait({task}, timeout=WAIT)
    if not done:
        log.info("jev rerank late", extra={"project": on.project})
        return {}
    try:
        sent = task.result()
    except Exception:
        log.exception("jev rerank failed", extra={"project": on.project})
        return {}
    if sent.asked is None:
        log.info("jev rerank skipped", extra={"project": on.project, "why": sent.failure})
        return {}
    scores = [sent.asked.answers[name].score for name in names]
    if any(score is None for score in scores):
        return {}
    return {"order": order_by([hit["id"] for hit in hits], scores)}


__all__ = ["rank"]
