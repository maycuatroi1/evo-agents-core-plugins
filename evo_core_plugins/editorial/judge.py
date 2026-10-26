"""The judge of a review round: the agent type ``editor-judge`` scores the draft of a round in a fresh context, without
knowing who wrote it, on four axes from 0 to 5 (``docs/editorial-plugin.md``, The judge).

The axes are ``slop`` (no filler, no stock phrases), ``giong`` (the voice of the blog), ``nguon`` (every claim and
figure has its source) and ``hinh`` (the images and their captions). The machine gate of a review stage passes when
every axis is 4 or more. The agent answers one JSON object; an answer that does not read as one passes nothing.

The judge is asked through the hub's question dispatch (``hub.ask_agent_type``): a question run is read-only, starts
in a fresh context and answers in text, which is what a judge does, where a task run would push to a branch and answer
nothing. The question names the draft's preview and its branch, never the writer, and its ref is the round
(``round:<id>``), so a round is asked once. The answer comes back as the event ``agent.answer`` (``events``).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncConnection

from evo_agents.hub.server import core_plugin_api as hub
from evo_core_plugins.editorial.settings import handle

AGENT_TYPE = "editor-judge"
AXES = ("slop", "giong", "nguon", "hinh")
PASS_AT = 4
ASKER = "editorial"
CLEARED = hub.Clearance("internal")  # the answer stays in the hub
REF = "round:"


@dataclass(frozen=True)
class Verdict:
    ok: bool
    scores: dict
    detail: str


def parse(text: str | None) -> Verdict:
    """The verdict an answer holds: the first JSON object with the four axes as numbers from 0 to 5."""
    scores = None
    for match in re.finditer(r"\{.*?\}", text or "", re.DOTALL):
        try:
            found = json.loads(match.group(0))
        except ValueError:
            continue
        if isinstance(found, dict) and all(
            isinstance(found.get(axis), int | float) and not isinstance(found.get(axis), bool) for axis in AXES
        ):
            scores = {axis: found[axis] for axis in AXES}
            break
    if scores is None or any(not 0 <= value <= 5 for value in scores.values()):
        return Verdict(False, scores or {}, "the judge's answer is no score of slop, giong, nguon and hinh from 0 to 5")
    return Verdict(passes(scores), scores, describe(scores))


def passes(scores: dict | None) -> bool:
    """Whether the machine gate passes on ``scores``: every axis at 4 or more."""
    if not isinstance(scores, dict):
        return False
    values = [scores.get(axis) for axis in AXES]
    return all(isinstance(v, int | float) and not isinstance(v, bool) and v >= PASS_AT for v in values)


def describe(scores: dict) -> str:
    low = [axis for axis in AXES if not (isinstance(scores.get(axis), int | float) and scores[axis] >= PASS_AT)]
    if low:
        return f"the judge scored {', '.join(low)} below {PASS_AT}"
    return "the judge passed it"


def question(preview_url: str | None, repo: str | None, branch: str | None) -> str:
    """What the judge is asked: where the draft is, nothing of who wrote it."""
    where = []
    if preview_url:
        where.append(f"its preview: {preview_url}")
    if repo and branch:
        where.append(f"the branch {branch} of the repo {repo} (git fetch origin {branch}, then read it there)")
    return (
        "Score the draft of a blog post on four axes from 0 to 5: slop (no filler, no stock phrases, no padding), "
        "giong (it keeps the voice of the blog), nguon (every claim and figure has its source) and hinh (the images "
        "and their captions serve the text). Read the draft at "
        + ("; or ".join(where) or "the link the round names")
        + ". Change nothing. Answer with one JSON object only, like "
        '{"slop": 4, "giong": 5, "nguon": 3, "hinh": 4, "why": "one line"}.'
    )


async def ask(
    conn: AsyncConnection, project: str, round_id: int, preview_url: str | None, repo: str | None, branch: str | None
) -> int:
    """Ask the project's editor-judge about the round's draft; the id of the question. A round is asked once."""
    made = await hub.ask_agent_type(
        conn,
        handle(),
        project,
        AGENT_TYPE,
        question(preview_url, repo, branch),
        asker=ASKER,
        ref=f"{REF}{round_id}",
        cleared=CLEARED,
    )
    return made.question_id


__all__ = ["AGENT_TYPE", "AXES", "PASS_AT", "Verdict", "ask", "parse", "passes", "question"]
