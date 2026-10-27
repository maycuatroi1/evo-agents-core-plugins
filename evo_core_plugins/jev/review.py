"""Graph review: an hourly job reads the open items of two rules of a project's review queue and asks Jev about each
once (a fingerprint is asked once for each model).

- ``possible_duplicate``: a noul question, "are these two nodes one". At or above ``kg_review_noul_yes`` the two are
  merged; at or below ``kg_review_noul_no`` the item is dismissed with the reason; between the two it is proposed;
- ``ambiguous_match``: a choice among the files an edge may point to. When Jev confirms the target the edge has, the
  item is dismissed. Another target is only booked as a suggestion: the API's text of an item does not name the
  edge's relation, so the plugin cannot take a link decision. An item of one node (a mention) is not asked.

Mode ``apply`` takes a decision active at once only for a merge over the noul threshold, and a dismissal for a clear
no, each within ``kg_review_cap`` a day; everything else is proposed (``propose``) for a writer to accept, or booked as
a suggestion. Mode ``suggest`` only proposes. A decision is undone with ``evo-agents hub kg decisions undo``, a
dismissal with ``evo-agents hub kg review undismiss``; every reason names the model and the confidence.
"""

from __future__ import annotations

import logging

from evo_agents.hub.server import core_plugin_api as hub
from evo_core_plugins.jev import automatic, store

log = logging.getLogger(__name__)
FEATURE = "kg_review"
RULES = ("possible_duplicate", "ambiguous_match")
MAX_PER_PASS = 20  # questions a pass puts for one project: the queue is long, Jev is paid by the call
READ_LIMIT = 100
UNSURE = "unsure"
SAME = {
    "type": "noul",
    "instructions": "Are the two nodes the same thing, written twice? 1 is certain they are, 0 certain they are not.",
    "criteria": {"true": "the two nodes are the same thing", "false": "the two nodes are different things"},
}


def _node(node) -> str:
    return f"{node.kind} {node.name or node.id} (id {node.id})"


def duplicate_state(item) -> str:
    return "\n".join(
        ["Two nodes of a knowledge graph have the same normalised name."]
        + [f"node {i}: {_node(n)}" for i, n in enumerate(item.nodes[:2], 1)]
        + [f"text: {item.snippet}"]
    )


def match_question(item) -> dict:
    """The choice among the files an edge may point to: the node ids are the options, ``unsure`` a way out."""
    criteria = {n.id: _node(n) for n in item.nodes[1:]}
    criteria[UNSURE] = "none of these can be told from the text given"
    return {
        "type": "choice",
        "instructions": "An edge of the graph resolved to one of several files with the same path. Which file does "
        "the source node mean? Choose its id, or unsure.",
        "criteria": criteria,
    }


def match_state(item) -> str:
    source, current = item.nodes[0], item.nodes[1]
    return "\n".join(
        [
            "The source node mentions a path that several files have.",
            f"source: {_node(source)}",
            f"the target the edge has now: {_node(current)}",
            f"text: {item.snippet}",
        ]
    )


async def on_job(params: dict, context: hub.Context) -> dict:
    """The job: each project of the run, in turn. A project that did not turn the feature on is not touched."""
    done: dict = {}
    for project in params.get("projects") or []:
        on = await automatic.setup(context, project, FEATURE)
        if on is None:
            continue
        try:
            done[project] = await _project(on)
        except Exception:  # one project's failure does not stop the next
            log.exception("jev review failed", extra={"project": project})
            done[project] = {"error": True}
    return done


async def _project(on: automatic.Setup) -> dict:
    async with hub.transaction(on.context) as conn:
        found = await hub.read_review_queue(conn, store.handle(), on.project, on.context.config, limit=READ_LIMIT)
    if not found.items:
        return {"skipped": found.reason}
    seen = {"asked": 0, "applied": 0, "proposed": 0}
    for item in found.items:
        if item.rule not in RULES or seen["asked"] >= MAX_PER_PASS:
            continue
        if item.rule == "possible_duplicate" and len(item.nodes) < 2:
            continue
        if item.rule == "ambiguous_match" and len(item.nodes) < 3:
            continue
        stop = await (_duplicate if item.rule == "possible_duplicate" else _match)(on, item, seen)
        if stop:
            break
    return seen


async def _duplicate(on: automatic.Setup, item, seen: dict) -> bool:
    sent = await automatic.put(on, f"review:{item.fingerprint}", duplicate_state(item), {"same": SAME})
    if sent.asked is None:
        return sent.stop
    seen["asked"] += 1
    value = sent.asked.answers["same"].noul
    if value is None:
        return False
    yes, no = float(on.values.get("kg_review_noul_yes", 0.9)), float(on.values.get("kg_review_noul_no", 0.1))
    keep, drop = item.nodes[0], item.nodes[1]
    names = f"{_node(keep)} and {_node(drop)}"
    target = f"review:{item.fingerprint}"
    apply = on.found.modes[FEATURE] == "apply"
    async with hub.transaction(on.context) as conn:
        if value <= no:
            if apply and await automatic.room(conn, on):
                reason = automatic.reason(on, f"not the same thing: {names}", value)
                await _dismiss(conn, on, item.fingerprint, reason, value, seen)
            else:
                await automatic.act(conn, on, "suggest", target, f"not the same thing: {names}", value, False)
            return False
        active = apply and value >= yes and await automatic.room(conn, on)
        words = f"the same thing: {names}" if value >= yes else f"may be the same thing: {names}"
        reason = automatic.reason(on, words, value)
        await _decide(conn, on, "merge", (drop.id, keep.id), target, reason, value, active, seen)
    return False


async def _match(on: automatic.Setup, item, seen: dict) -> bool:
    sent = await automatic.put(on, f"review:{item.fingerprint}", match_state(item), {"target": match_question(item)})
    if sent.asked is None:
        return sent.stop
    seen["asked"] += 1
    answer = sent.asked.answers["target"]
    choice, confidence = answer.choice or UNSURE, answer.confidence or 0.0
    current, target = item.nodes[1], f"review:{item.fingerprint}"
    async with hub.transaction(on.context) as conn:
        confirmed = choice == current.id
        if (
            confirmed
            and on.found.modes[FEATURE] == "apply"
            and confidence >= on.threshold()
            and await automatic.room(conn, on)
        ):
            reason = automatic.reason(on, f"the target {_node(current)} is the right one", confidence)
            await _dismiss(conn, on, item.fingerprint, reason, confidence, seen)
        else:
            outcome = "the edge's target is right" if confirmed else f"another target: {choice}"
            await automatic.act(conn, on, "suggest", target, outcome, confidence, False)
    return False


async def _dismiss(conn, on: automatic.Setup, fingerprint: str, reason: str, confidence: float, seen: dict) -> None:
    target = f"review:{fingerprint}"
    try:
        await hub.dismiss_review_item(conn, store.handle(), on.project, on.context.config, fingerprint, reason)
    except (hub.Refused, ValueError) as exc:
        await automatic.act(conn, on, "skipped", target, f"dismissal refused: {_why(exc)}", confidence, False)
        return
    await automatic.act(conn, on, "dismiss", target, reason, confidence, True)
    seen["applied"] += 1


async def _decide(
    conn, on, kind: str, nodes: tuple[str, str], target: str, reason: str, confidence: float, active: bool, seen
) -> None:
    src, dst = nodes
    try:
        taken = await hub.decide_graph(
            conn, store.handle(), on.project, on.context.config, kind, src, dst=dst, reason=reason, propose=not active
        )
    except (hub.Refused, ValueError) as exc:
        await automatic.act(conn, on, "skipped", target, f"{kind} refused: {_why(exc)}", confidence, False)
        return
    await automatic.act(conn, on, kind, f"decision:{taken.number}", reason, confidence, active)
    seen["applied" if active else "proposed"] += 1


def _why(exc: Exception) -> str:
    return str(getattr(exc, "detail", None) or exc)


__all__ = ["RULES", "on_job"]
