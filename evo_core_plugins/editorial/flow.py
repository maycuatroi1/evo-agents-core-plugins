"""The flow of a post between the agents and the person (``docs/editorial-plugin.md``, The flow).

When a post enters a stage with a gate, the gate waits and its notice (``editorial_gate``) goes to the gatekeepers:
the Inbox, and each channel of theirs that is on, with the link of the post's page, where they answer it. At a stage
with a comments gate the plugin also opens the next review round, reads the reviewers' comments into it
(``marginalia``) and asks the judge to score the draft (``judge``).

An answer through the page is kept with ``answered_via`` hub, and hands the agent type ``writer`` a task on the post's
branch (``post/<slug>`` of the config's ``repo``): follow the project's writing skill from the stage the post is at to
the next gate, then stop. A post has one task at a time: while its run runs, the plugin hands no other and a person's
answer waits (409). When the run ends (the event ``task.result``, ``events``) and the post reached no gate, the next task
goes out, within the type's daily cap; at most ``MAX_RUNS`` runs follow one another without a person's answer. A run
that fails, or a task the hub refuses (its cap, a branch another run works on), puts the post in the error state and
sends ``editorial_failed`` to the gatekeepers: nothing fails without a word.

The approval of a draft at a comments gate passes only once the judge scored its latest round 4 or more on every axis
(the machine gate); ``done`` on a round hands the writer the comments to work in, and the run's end opens the next round.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncConnection

from evo_agents.hub.server import core_plugin_api as hub
from evo_core_plugins.editorial import judge, marginalia, store
from evo_core_plugins.editorial.settings import Config, Stage, handle

log = logging.getLogger(__name__)

WRITER = "writer"
NOTICE_GATE = "editorial_gate"
NOTICE_FAILED = "editorial_failed"
NOTICE_KINDS = (
    (NOTICE_GATE, "A post waits for you at a gate"),
    (NOTICE_FAILED, "A post's agent run failed or was refused"),
)
MAX_RUNS = 6  # runs of a post one after another without a person's answer
BRANCH = "post/"
DONE, FAILED, REFUSED = "done", "failed", "refused"


def branch_of(post: store.Post) -> str:
    return post.branch or f"{BRANCH}{post.slug}"


def page_link(project: str, slug: str) -> str:
    """The post's page on the hub's web."""
    return f"/p/{project}/x/editorial/posts/{slug}"


async def gatekeepers(conn: AsyncConnection, project: str, cfg: Config) -> list[int]:
    """The members a gate's notice goes to: those the config lists, else the project's admins."""
    grants = await hub.read_grants(conn, handle(), project)
    if cfg.gatekeepers:
        wanted = set(cfg.gatekeepers)
        return [grant.user_id for grant in grants if grant.login in wanted]
    return [grant.user_id for grant in grants if hub.has_role(grant.role, "admin")]


async def _notify(conn: AsyncConnection, project: str, cfg: Config, kind: str, post: store.Post, title: str, body: str):
    users = await gatekeepers(conn, project, cfg)
    if not users:
        log.warning("editorial notice without a gatekeeper", extra={"project": project, "post": post.slug})
        return ()
    return await hub.notify(
        conn,
        handle(),
        project,
        kind,
        users=users,
        title=title,
        body=body,
        link=page_link(project, post.slug),
        details={"post": post.slug, "stage": post.stage},
    )


async def _guarded(conn: AsyncConnection, work, what: str):
    """``work()`` in a savepoint: (its result, None), or (None, why) when the hub refused it; nothing it wrote stays."""
    try:
        async with conn.begin_nested():
            return await work(), None
    except (hub.Refused, ValueError) as exc:
        why = exc.detail if isinstance(exc, hub.Refused) else str(exc)
        log.info("editorial %s refused", what, extra={"why": why})
        return None, str(why)


# Gates


async def gate_opened(
    conn: AsyncConnection, project: str, project_id: int, cfg: Config, post_id: int, stage: Stage
) -> None:
    """The post's gate at ``stage`` just opened: at a comments gate the next round, its comments and the judge's
    question, once the flow is on (the config names the repo of posts or the comment service); then the notice to
    the gatekeepers."""
    post = await store.post_by_id(conn, post_id)
    assert post is not None
    if stage.gate == "comments" and (cfg.repo is not None or cfg.comments is not None):
        await open_round(conn, project, project_id, cfg, post, stage)
    title = f"{post.title or post.slug}: {stage.title} waits for you"
    body = {
        "choose": "Pick one of the proposals, or write another topic.",
        "interview": "Answer the questions, then approve the brief.",
        "comments": "Comment on the draft, then press done, or approve the draft.",
        "publish": "Publish the post, then say it is out.",
    }.get(stage.gate or "", "Answer the gate.")
    await _guarded(conn, lambda: _notify(conn, project, cfg, NOTICE_GATE, post, title, body), "gate notice")


async def open_round(
    conn: AsyncConnection, project: str, project_id: int, cfg: Config, post: store.Post, stage: Stage
) -> int:
    """The post's next round at ``stage``, with the reviewers' comments read into it and the judge asked; its id."""
    round_id = await store.new_round(conn, post.id, stage.name, None)
    if cfg.comments is not None and post.comment_id:
        _, why = await _guarded(conn, lambda: pull_comments(conn, cfg, post, stage.name), "comments")
        if why is not None:
            await store.set_round(conn, round_id, {"note": f"comments not read: {why}"[:2000]})
    await ask_judge(conn, project, cfg, post, round_id)
    return round_id


async def ask_judge(conn: AsyncConnection, project: str, cfg: Config, post: store.Post, round_id: int) -> None:
    asked, why = await _guarded(
        conn, lambda: judge.ask(conn, project, round_id, post.preview_url, cfg.repo, branch_of(post)), "judge"
    )
    values = {"question_id": asked, "judge_state": "pending"} if asked else {"judge_state": REFUSED, "judge_note": why}
    await store.set_round(conn, round_id, values)


async def pull_comments(conn: AsyncConnection, cfg: Config, post: store.Post, stage: str) -> int:
    """Read the reviewers' comments on the post's draft into its latest round at ``stage`` (made when there is none);
    how many it holds of them. Refused (422) without the comment service or the post's comment key, 502 when the
    service does not answer."""
    if cfg.comments is None:
        raise hub.Refused(422, "set comments (the Firebase project and its web API key) in the config of editorial")
    if not post.comment_id:
        raise hub.Refused(422, f"post {post.slug} has no comment_id: set it to the id its draft comments are kept by")
    try:
        documents = await marginalia.FETCH(cfg.comments, marginalia.key(post.comment_id))
    except Exception as exc:  # the service's answer, whatever it is, is no reason to lose the round
        log.warning("editorial comments not read", extra={"post": post.slug, "error": type(exc).__name__})
        raise hub.Refused(502, f"the comment service did not answer: {type(exc).__name__}") from None
    found = marginalia.of_reviewers(documents, cfg.reviewers)
    latest = await store.last_round(conn, post.id, stage)
    round_id = latest.id if latest is not None else await store.new_round(conn, post.id, stage, None)
    for item in found:
        text = item.text if item.parent is None else f"(reply) {item.text}"
        values = {"external_id": item.id, "author": item.author, "quote": item.quote, "text": text, "at": item.at}
        await store.put_comment(conn, round_id, values)
    return len(found)


def comments_stage(cfg: Config, post: store.Post) -> Stage | None:
    """The stage with a comments gate the post is at, else the last one before it."""
    here = cfg.stage(post.stage)
    if here is not None and here.gate == "comments":
        return here
    before = [
        stage for stage in cfg.stages if stage.gate == "comments" and cfg.order(stage.name) <= cfg.order(post.stage)
    ]
    return before[-1] if before else None


async def approval_refusal(conn: AsyncConnection, post: store.Post, stage: Stage, answer: Any) -> str | None:
    """Why an answer at a comments gate may not pass: an approval before the judge passed the latest round."""
    if stage.gate != "comments" or not (isinstance(answer, dict) and answer.get("approve") is True):
        return None
    latest = await store.last_round(conn, post.id, stage.name)
    if latest is None or not judge.passes(latest.scores):
        shown = json.dumps(latest.scores) if latest is not None and latest.scores else "no scores yet"
        return f"the machine gate of {stage.name} has not passed: every axis of the judge at 4 or more ({shown})"
    return None


# Tasks


def task_text(cfg: Config, project: str, post: store.Post, gates: list[store.Gate]) -> str:
    """The writer's task: the post, where it stands, what the person answered, and where to stop."""
    answered = [gate for gate in gates if gate.state in ("answered", "skipped")]
    last = max(answered, key=lambda gate: gate.answered_at or gate.opened_at) if answered else None
    lines = [
        f"Post {post.slug} ({post.title or 'no title yet'}) of project {project} is at stage {post.stage}.",
        f"Follow the project's writing skill {cfg.skill} from this stage to the next gate, then stop.",
        f"Work on the branch {branch_of(post)}. Read editorial__recall for each stage before writing it, and set the "
        "post's stage with editorial__state as you go: entering a stage with a gate hands the post to the person, "
        "with what you ask them in ask (the proposals to choose from, the questions of an interview).",
    ]
    if last is not None:
        said = json.dumps(last.answer, ensure_ascii=False) if last.answer is not None else "no words"
        lines.append(f"The person answered the gate at {last.stage} ({last.kind}, {last.state}): {said}.")
        if last.kind == "comments":
            lines.append("Read the round's comments with editorial__state and work each one in.")
    return "\n".join(lines)


async def hand_next(
    conn: AsyncConnection, project: str, cfg: Config, post_id: int, *, answered: bool
) -> tuple[int | None, str | None]:
    """Hand the writer the post's next task: (its run, None), or (None, why not). Nothing without the config's repo,
    while the post's run runs, or after ``MAX_RUNS`` runs without a person's answer (``answered`` counts from 0
    again). A refusal of the hub puts the post in the error state and tells the gatekeepers."""
    if cfg.repo is None:
        return None, "no repo of posts in the config: the plugin hands no task"
    post = await store.post_by_id(conn, post_id, lock=True)
    assert post is not None
    if post.running:
        return None, f"the post's run #{post.run_id} still runs"
    if cfg.order(post.stage) >= len(cfg.stages) - 1:
        return None, f"post {post.slug} is at the last stage, {post.stage}: nothing is left for the writer"
    count = 0 if answered else post.run_count
    if count >= MAX_RUNS:
        why = f"{MAX_RUNS} runs reached no gate: a person looks at the post before the next"
        await failed(conn, project, cfg, post, why)
        return None, why
    gates = (await store.gates(conn, [post.id])).get(post.id, [])
    handed, why = await _guarded(
        conn,
        lambda: hub.hand_task(
            conn,
            handle(),
            project,
            WRITER,
            task_text(cfg, project, post, gates),
            title=f"editorial {post.slug}: {post.stage}",
            repo=cfg.repo,
            branch=branch_of(post),
            minutes=cfg.minutes,
        ),
        "task",
    )
    if handed is not None and handed.run_id is not None:
        values = {
            "run_id": handed.run_id,
            "run_state": store.RUNNING,
            "run_stage": post.stage,
            "run_error": None,
            "run_at": func.now(),
            "run_count": count + 1,
            "branch": branch_of(post),
        }
        await store.set_post_values(conn, post.id, values)
        return handed.run_id, None
    why = (handed.refused if handed is not None else why) or "the hub queued no task"
    await failed(conn, project, cfg, post, why, state=REFUSED)
    return None, why


async def failed(
    conn: AsyncConnection, project: str, cfg: Config, post: store.Post, why: str, *, state: str = FAILED
) -> None:
    """The post's error state, and the notice of it to the gatekeepers."""
    await store.set_post_values(conn, post.id, {"run_state": state, "run_error": why[:2000], "run_at": func.now()})
    title = f"{post.title or post.slug}: the writer's run {'was refused' if state == REFUSED else 'failed'}"
    await _guarded(conn, lambda: _notify(conn, project, cfg, NOTICE_FAILED, post, title, why[:1000]), "failure notice")


async def run_ended(conn: AsyncConnection, project: str, project_id: int, cfg: Config, payload: dict) -> str:
    """The post's task run ended (``task.result``): what the plugin did. A delivery of an end it already took does
    nothing."""
    task_id = payload.get("task_id")
    if not isinstance(task_id, int):
        return "no task"
    post = await store.post_of_run(conn, project_id, task_id)
    if post is None or not post.running:
        return "not a running post"
    state = payload.get("state")
    if state != DONE:
        why = payload.get("failure_cause") or f"the run was {state}"
        await failed(conn, project, cfg, post, f"run #{payload.get('run_id') or task_id} {state}: {why}")
        return FAILED
    await store.set_post_values(conn, post.id, {"run_state": DONE, "run_error": None, "run_at": func.now()})
    post = await store.post_by_id(conn, post.id)
    assert post is not None
    gates = (await store.gates(conn, [post.id])).get(post.id, [])
    here = cfg.stage(post.stage)
    gate = next((item for item in gates if here is not None and item.stage == here.name), None)
    if gate is not None and gate.state == "waiting":
        return "at a gate"
    if here is not None and here.gate == "comments" and gate is not None and _round_done(gate.answer):
        await store.open_gate(conn, post.id, here.name, here.gate)  # the comments are in: the next round
        await gate_opened(conn, project, project_id, cfg, post.id, here)
        return "next round"
    if here is not None and here.gate is not None and gate is None:
        await store.open_gate(conn, post.id, here.name, here.gate)
        await gate_opened(conn, project, project_id, cfg, post.id, here)
        return "at a gate"
    if cfg.order(post.stage) >= len(cfg.stages) - 1:
        return "at the end"
    run_id, why = await hand_next(conn, project, cfg, post.id, answered=False)
    return "handed" if run_id else f"not handed: {why}"


def _round_done(answer: Any) -> bool:
    return isinstance(answer, dict) and answer.get("done") is True and answer.get("approve") is not True


async def answer_ended(conn: AsyncConnection, payload: dict) -> str:
    """The judge answered (``agent.answer``): its scores kept in the round."""
    question_id = payload.get("question_id")
    if not isinstance(question_id, int):
        return "no question"
    found = await store.round_of_question(conn, question_id)
    if found is None:
        return "no round"
    round_id, _ = found
    state = payload.get("state")
    if state != DONE:
        why = payload.get("failure_cause") or state
        await store.set_round(conn, round_id, {"judge_state": FAILED, "judge_note": f"the judge gave no answer: {why}"})
        return FAILED
    verdict = judge.parse(payload.get("text"))
    values = {
        "scores": verdict.scores or None,
        "judge_state": "passed" if verdict.ok else "below",
        "judge_note": verdict.detail,
    }
    await store.set_round(conn, round_id, values)
    return values["judge_state"]


__all__ = [
    "NOTICE_KINDS",
    "WRITER",
    "answer_ended",
    "approval_refusal",
    "gate_opened",
    "hand_next",
    "pull_comments",
    "run_ended",
    "task_text",
]
