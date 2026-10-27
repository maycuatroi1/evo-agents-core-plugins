"""Corrections that repeat: a daily job reads the corrections people made the day before (the API's
``read_corrections``), keeps for each the earlier corrections of the last 90 days and the project's accepted rules
that share words with it (a test with no call to Jev), and puts one choice question to Jev: which candidate it
repeats, or ``none``.

A match at or above ``corrections_threshold`` is a row of ``jev_matches`` in state ``match`` (the evidence of the
correction, the candidate, the model, the confidence); one below it is a row in state ``suggestion``. In mode
``apply`` the job then pushes the signal ``delivery.repeat_correction_rate`` of the day: the matches over the day's
corrections, left out for a day with no correction. A correction is asked once for each model. A failed or late call
skips the correction and goes on, and the job stops for the project when the budget or the config stops the calls.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime, timedelta

from evo_agents.hub.server import core_plugin_api as hub
from evo_core_plugins.jev import automatic, store

log = logging.getLogger(__name__)
FEATURE = "corrections"
SIGNAL = "delivery.repeat_correction_rate"
LOOKBACK_DAYS = 90
MAX_CANDIDATES = 8  # options a question carries, besides none
MIN_SHARED = 3  # words two texts must share to be candidates of each other
MIN_RATIO = 0.25  # and that share of the shorter text's words
MAX_PER_PASS = 50  # questions a pass puts for one project
NONE = "none"
WORD = re.compile(r"[^\W_]{4,}", re.UNICODE)
STOP = frozenset({"that", "this", "with", "from", "have", "should", "would", "please", "there", "your", "dont"})


def words(text: str) -> frozenset[str]:
    return frozenset(w for w in (m.lower() for m in WORD.findall(text)) if w not in STOP)


def candidates(text: str, pool: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """The ``(id, text)`` of ``pool`` that share enough words with ``text``, the closest first."""
    mine = words(text)
    scored = []
    for ident, other in pool:
        theirs = words(other)
        shared = len(mine & theirs)
        shortest = min(len(mine), len(theirs))
        if shortest and shared >= MIN_SHARED and shared / shortest >= MIN_RATIO:
            scored.append((shared / shortest, shared, ident, other))
    scored.sort(key=lambda s: (-s[0], -s[1], s[2]))
    return [(ident, other) for _, _, ident, other in scored[:MAX_CANDIDATES]]


def question(found: list[tuple[str, str]]) -> dict:
    criteria = {f"c{i}": text[:900] for i, (_, text) in enumerate(found, 1)}
    criteria[NONE] = "the correction repeats none of the candidates"
    return {
        "type": "choice",
        "instructions": "A person corrected an agent. Does the correction repeat one of the candidates: an earlier "
        "correction, or a rule the project accepted? Choose it, or none.",
        "criteria": criteria,
    }


def day_bounds(now: datetime | None = None) -> tuple[datetime, datetime]:
    """The previous UTC day: its start and the start of the day after."""
    end = store.midnight(now)
    return end - timedelta(days=1), end


async def on_job(params: dict, context: hub.Context) -> dict:
    done: dict = {}
    for project in params.get("projects") or []:
        on = await automatic.setup(context, project, FEATURE)
        if on is None:
            continue
        try:
            done[project] = await _project(on)
        except Exception:  # one project's failure does not stop the next
            log.exception("jev corrections failed", extra={"project": project})
            done[project] = {"error": True}
    return done


async def _project(on: automatic.Setup) -> dict:
    start, end = day_bounds()
    async with hub.transaction(on.context) as conn:
        today = await hub.read_corrections(conn, store.handle(), on.project, since=start, until=end)
        if not today.items:
            return {"day": start.date().isoformat(), "corrections": 0, "skipped": today.reason}
        before = await hub.read_corrections(
            conn, store.handle(), on.project, since=start - timedelta(days=LOOKBACK_DAYS), until=start
        )
        rules = await hub.read_accepted_rules(conn, store.handle(), on.project)
    pool = [(c.evidence, c.text) for c in before.items]
    pool += [(f"{r.kind}:{r.id}", f"{r.title}. {r.summary}") for r in rules.items]
    asked = 0
    for item in today.items:
        if asked >= MAX_PER_PASS:
            break
        found = candidates(item.text, pool)
        if not found:
            continue
        sent = await automatic.put(on, item.evidence, item.text, {"match": question(found)})
        if sent.asked is None:
            if sent.stop:
                break
            continue
        asked += 1
        await _record(on, start, item, found, sent.asked.answers["match"])
    return await _signal(on, start, len(today.items), asked)


async def _record(on: automatic.Setup, start: datetime, item, found, answer) -> None:
    index = (answer.choice or NONE)[1:]
    if not (answer.choice or "").startswith("c") or not index.isdigit() or not 1 <= int(index) <= len(found):
        return
    confidence = answer.confidence or 0.0
    state = "match" if confidence >= on.threshold() else "suggestion"
    candidate = found[int(index) - 1][0]
    async with hub.transaction(on.context) as conn:
        await store.record_match(
            conn,
            on.project_id,
            day=start.date(),
            evidence=item.evidence,
            candidate=candidate,
            model=on.model,
            confidence=confidence,
            state=state,
        )
        await automatic.act(conn, on, "match", item.evidence, f"{state}: {candidate}", confidence, False)


async def _signal(on: automatic.Setup, start: datetime, total: int, asked: int) -> dict:
    day = start.date()
    done = {"day": day.isoformat(), "corrections": total, "asked": asked}
    if on.found.modes[FEATURE] != "apply" or total == 0:
        return done
    async with hub.transaction(on.context) as conn:
        matched = await store.matched_on(conn, on.project_id, day)
        try:
            pushed = await hub.push_signal(
                conn,
                store.handle(),
                on.project,
                SIGNAL,
                matched / total,
                measured_at=start.replace(tzinfo=UTC) + timedelta(hours=23, minutes=59),
                external_id=f"jev:{SIGNAL}:{day.isoformat()}",
            )
        except hub.Refused as exc:  # no admin owns an ingest key, or the key is not declared: the matches stay
            done["signal"] = str(exc.detail)
            return done
    done["signal"] = {"stored": pushed.stored, "duplicate": pushed.duplicate, "refused": pushed.refused}
    return done


__all__ = ["SIGNAL", "on_job"]
