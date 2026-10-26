"""The plugin editorial's reads and writes of its own tables (SQLAlchemy Core), and who may read and write them.

A post is one row of editorial_posts for each slug of a project, with its stage history, its gates (one for each stage
that has one), its review rounds and their comments, which go with it. A feedback entry is one row of
editorial_feedback for each number of a project: what the person said grows by one item and its count of times seen by
one at each repeat. Import writes by slug, by number, by stage and by the ids a source gave, so the same file twice
changes nothing the first run did not.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from evo_agents.hub.server import core_plugin_api as hub
from evo_core_plugins.editorial import ledger
from evo_core_plugins.editorial import tables as t
from evo_core_plugins.editorial.settings import handle

PLUGIN = "editorial"
RUNNING = "running"
SINK_HEADER = "X-Evo-Sink"  # evo_agents.hub.server.plans.SINK_HEADER
NUMBER_TRIES = 5


# Who may do what


def reader(access: hub.ProjectRef) -> None:
    if access.role is None:
        raise hub.Refused(403, f"reading the posts of project {access.name} needs a grant on it")


def writer(access: hub.ProjectRef, what: str) -> None:
    reader(access)
    if not hub.has_role(access.role, "writer"):
        raise hub.Refused(403, f"{what} in project {access.name} needs the writer role; you are {access.role}")


def admin(access: hub.ProjectRef, what: str) -> None:
    reader(access)
    if not hub.has_role(access.role, "admin"):
        raise hub.Refused(403, f"{what} in project {access.name} needs the admin role; you are {access.role}")


# Posts


@dataclass(frozen=True)
class Post:
    id: int
    slug: str
    title: str
    stage: str
    branch: str | None
    preview_url: str | None
    url: str | None
    published_at: datetime | None
    d7: dict | None
    d28: dict | None
    label: dict
    created_at: datetime
    updated_at: datetime
    comment_id: str | None = None
    run_id: int | None = None
    run_state: str | None = None  # running, done, failed, refused
    run_stage: str | None = None
    run_error: str | None = None
    run_at: datetime | None = None
    run_count: int = 0

    @property
    def running(self) -> bool:
        return self.run_state == RUNNING


@dataclass(frozen=True)
class Gate:
    post_id: int
    stage: str
    kind: str
    state: str
    opened_at: datetime
    answered_at: datetime | None
    answered_via: str | None
    answered_by: str | None  # the login of the member who answered
    answer: Any
    ask: Any = None  # what the agent put to the person


@dataclass(frozen=True)
class Comment:
    external_id: str
    author: str | None
    quote: str | None
    text: str
    at: datetime | None


@dataclass(frozen=True)
class Round:
    id: int
    stage: str
    number: int
    at: datetime
    note: str | None
    feedback: list
    scores: dict | None
    comments: list[Comment] = field(default_factory=list)
    question_id: int | None = None
    judge_state: str | None = None
    judge_note: str | None = None


@dataclass(frozen=True)
class Entered:
    stage: str
    at: datetime
    evidence: str | None


def _post(row) -> Post:
    return Post(
        row.id,
        row.slug,
        row.title,
        row.stage,
        row.branch,
        row.preview_url,
        row.url,
        row.published_at,
        row.d7,
        row.d28,
        row.label,
        row.created_at,
        row.updated_at,
        row.comment_id,
        row.run_id,
        row.run_state,
        row.run_stage,
        row.run_error,
        row.run_at,
        row.run_count,
    )


async def posts(conn: AsyncConnection, project_id: int) -> list[Post]:
    """The posts of a project, the one changed last first."""
    p = t.posts.c
    query = select(t.posts).where(p.project_id == project_id).order_by(p.updated_at.desc(), p.id.desc())
    return [_post(row) for row in await conn.execute(query)]


async def post(conn: AsyncConnection, project_id: int, slug: str, *, lock: bool = False) -> Post | None:
    p = t.posts.c
    query = select(t.posts).where(p.project_id == project_id, p.slug == slug)
    row = (await conn.execute(query.with_for_update() if lock else query)).first()
    return _post(row) if row else None


async def post_by_id(conn: AsyncConnection, post_id: int, *, lock: bool = False) -> Post | None:
    query = select(t.posts).where(t.posts.c.id == post_id)
    row = (await conn.execute(query.with_for_update() if lock else query)).first()
    return _post(row) if row else None


async def post_of_run(conn: AsyncConnection, project_id: int, run_id: int) -> Post | None:
    """The post whose task run is ``run_id`` (the task's id), locked."""
    p = t.posts.c
    query = select(t.posts).where(p.project_id == project_id, p.run_id == run_id).with_for_update()
    row = (await conn.execute(query)).first()
    return _post(row) if row else None


async def set_post_values(conn: AsyncConnection, post_id: int, values: Mapping) -> None:
    """Write ``values`` (columns of editorial_posts) on the post."""
    await conn.execute(update(t.posts).where(t.posts.c.id == post_id).values(**values, updated_at=func.now()))


async def gates(conn: AsyncConnection, post_ids: Iterable[int]) -> dict[int, list[Gate]]:
    """post id -> its gates, in the order they opened."""
    ids = list(post_ids)
    if not ids:
        return {}
    g = t.gates.c
    rows = list(await conn.execute(select(t.gates).where(g.post_id.in_(ids)).order_by(g.opened_at, g.id)))
    who = {row.answered_by for row in rows if row.answered_by is not None}
    logins = {user.id: user.login for user in await hub.read_users(conn, handle(), ids=who)} if who else {}
    found: dict[int, list[Gate]] = {}
    for row in rows:
        found.setdefault(row.post_id, []).append(
            Gate(
                row.post_id,
                row.stage,
                row.kind,
                row.state,
                row.opened_at,
                row.answered_at,
                row.answered_via,
                logins.get(row.answered_by),
                row.answer,
                row.ask,
            )
        )
    return found


async def round_counts(conn: AsyncConnection, post_ids: Iterable[int]) -> dict[int, int]:
    ids = list(post_ids)
    if not ids:
        return {}
    r = t.rounds.c
    found = await conn.execute(select(r.post_id, func.count()).where(r.post_id.in_(ids)).group_by(r.post_id))
    return {post_id: n for post_id, n in found}


async def rounds(conn: AsyncConnection, post_id: int) -> list[Round]:
    """The review rounds of a post, by stage and number, each with its comments in time order."""
    r, c = t.rounds.c, t.comments.c
    rows = list(await conn.execute(select(t.rounds).where(r.post_id == post_id).order_by(r.at, r.number, r.id)))
    said: dict[int, list[Comment]] = {}
    if rows:
        query = select(t.comments).where(c.round_id.in_([row.id for row in rows])).order_by(c.at, c.id)
        for row in await conn.execute(query):
            said.setdefault(row.round_id, []).append(Comment(row.external_id, row.author, row.quote, row.text, row.at))
    return [
        Round(
            row.id,
            row.stage,
            row.number,
            row.at,
            row.note,
            row.feedback or [],
            row.scores,
            said.get(row.id, []),
            row.question_id,
            row.judge_state,
            row.judge_note,
        )
        for row in rows
    ]


async def last_round(conn: AsyncConnection, post_id: int, stage: str) -> Round | None:
    """The post's round of the highest number at ``stage``."""
    found = [item for item in await rounds(conn, post_id) if item.stage == stage]
    return max(found, key=lambda item: item.number) if found else None


async def new_round(conn: AsyncConnection, post_id: int, stage: str, note: str | None) -> int:
    """The post's next round at ``stage``, from now; its id."""
    r = t.rounds
    number = (await conn.scalar(select(func.max(r.c.number)).where(r.c.post_id == post_id, r.c.stage == stage))) or 0
    return await put_round(
        conn, post_id, {"stage": stage, "number": number + 1, "at": func.now(), "note": note, "feedback": []}
    )


async def round_of_question(conn: AsyncConnection, question_id: int) -> tuple[int, int] | None:
    """(round id, post id) of the round whose judge's question is ``question_id``."""
    r = t.rounds.c
    row = (await conn.execute(select(r.id, r.post_id).where(r.question_id == question_id))).first()
    return (row.id, row.post_id) if row else None


async def set_round(conn: AsyncConnection, round_id: int, values: Mapping) -> None:
    await conn.execute(update(t.rounds).where(t.rounds.c.id == round_id).values(**values))


async def history(conn: AsyncConnection, post_id: int) -> list[Entered]:
    h = t.stage_history.c
    found = await conn.execute(select(h.stage, h.at, h.evidence).where(h.post_id == post_id).order_by(h.at, h.id))
    return [Entered(row.stage, row.at, row.evidence) for row in found]


async def put_post(conn: AsyncConnection, project_id: int, slug: str, values: Mapping, label: dict) -> tuple[int, bool]:
    """Write post ``slug`` with ``values`` (columns of editorial_posts), making it when it is not there; (its id, whether
    this call made it)."""
    p = t.posts
    made = (
        await conn.execute(
            pg_insert(p)
            .values(project_id=project_id, slug=slug, label=label, **values)
            .on_conflict_do_nothing(constraint="editorial_posts_slug_key")
            .returning(p.c.id)
        )
    ).scalar()
    if made is not None:
        return made, True
    found = await conn.scalar(
        update(p)
        .where(p.c.project_id == project_id, p.c.slug == slug)
        .values(**values, updated_at=func.now())
        .returning(p.c.id)
    )
    return found, False


async def entered(conn: AsyncConnection, post_id: int, stage: str, at: datetime, evidence: str | None) -> None:
    """Keep that the post entered ``stage`` at ``at``; the same entry twice is kept once."""
    await conn.execute(
        pg_insert(t.stage_history)
        .values(post_id=post_id, stage=stage, at=at, evidence=evidence)
        .on_conflict_do_nothing(constraint="editorial_stage_history_once_key")
    )


async def open_gate(conn: AsyncConnection, post_id: int, stage: str, kind: str) -> None:
    """The gate of the post at ``stage`` waits again, from now, with no answer."""
    g = t.gates
    statement = pg_insert(g).values(post_id=post_id, stage=stage, kind=kind, state="waiting")
    await conn.execute(
        statement.on_conflict_do_update(
            constraint="editorial_gates_stage_key",
            set_={
                "kind": kind,
                "state": "waiting",
                "opened_at": func.now(),
                "answered_at": None,
                "answered_via": None,
                "answered_by": None,
                "answer": None,
                "ask": None,
            },
        )
    )


async def answer_gate(
    conn: AsyncConnection, post_id: int, stage: str, state: str, via: str | None, by: int | None, answer: Any
) -> bool:
    """Set the state of the post's gate at ``stage``: answered or skipped with when, through what and by whom, or
    waiting again; whether the post has that gate."""
    g = t.gates
    values: dict = {"state": state}
    if state == "waiting":
        values |= {"answered_at": None, "answered_via": None, "answered_by": None, "answer": None}
    else:
        values |= {"answered_at": func.now(), "answered_via": via, "answered_by": by}
        if answer is not None:
            values["answer"] = answer
    found = await conn.scalar(
        update(g).where(g.c.post_id == post_id, g.c.stage == stage).values(**values).returning(g.c.id)
    )
    return found is not None


async def ask_at_gate(conn: AsyncConnection, post_id: int, stage: str, ask: Any) -> bool:
    """Keep what the agent puts to the person at the post's gate at ``stage``; whether the post has that gate."""
    g = t.gates
    found = await conn.scalar(
        update(g).where(g.c.post_id == post_id, g.c.stage == stage).values(ask=ask).returning(g.c.id)
    )
    return found is not None


async def put_gate(conn: AsyncConnection, post_id: int, values: Mapping) -> None:
    """Write the post's gate at ``values['stage']`` as given (import)."""
    g = t.gates
    statement = pg_insert(g).values(post_id=post_id, **values)
    await conn.execute(
        statement.on_conflict_do_update(
            constraint="editorial_gates_stage_key", set_={k: v for k, v in values.items() if k != "stage"}
        )
    )


async def put_round(conn: AsyncConnection, post_id: int, values: Mapping) -> int:
    """Write the post's round ``values['number']`` at ``values['stage']`` as given; its id."""
    r = t.rounds
    statement = pg_insert(r).values(post_id=post_id, **values)
    return (
        await conn.execute(
            statement.on_conflict_do_update(
                constraint="editorial_rounds_number_key",
                set_={k: v for k, v in values.items() if k not in ("stage", "number")},
            ).returning(r.c.id)
        )
    ).scalar_one()


async def put_comment(conn: AsyncConnection, round_id: int, values: Mapping) -> None:
    c = t.comments
    statement = pg_insert(c).values(round_id=round_id, **values)
    await conn.execute(
        statement.on_conflict_do_update(
            constraint="editorial_comments_once_key",
            set_={k: v for k, v in values.items() if k != "external_id"},
        )
    )


# The feedback notebook


@dataclass(frozen=True)
class Entry:
    number: int
    notebook: str
    title: str
    date: date
    post: str | None
    said: list
    agent_wrote: str | None
    agent_note: str | None
    agent_after: int | None
    person_fixed: str | None
    fixed_note: str | None
    fixed_after: int | None
    rule: str
    check: str | None
    seen: int
    probe_id: int | None
    label: dict
    updated_at: datetime
    probe_task: str | None = None
    probe_verify: str | None = None

    @property
    def id(self) -> str:
        return ledger.entry_id(self.number)

    def as_ledger(self) -> dict:
        """The entry as ``ledger`` prints it."""
        return {
            "number": self.number,
            "title": self.title,
            "date": self.date.isoformat(),
            "post": self.post,
            "said": self.said,
            "agent_wrote": self.agent_wrote,
            "agent_note": self.agent_note,
            "agent_after": self.agent_after,
            "person_fixed": self.person_fixed,
            "fixed_note": self.fixed_note,
            "fixed_after": self.fixed_after,
            "rule": self.rule,
            "check": self.check,
            "seen": self.seen,
        }

    def words(self) -> str:
        """Everything the entry says, lower case, for a keyword."""
        parts = [self.id, self.title, self.post or "", self.rule, self.check or "", self.agent_wrote or ""]
        parts += [self.person_fixed or "", *(item.get("text") or "" for item in self.said)]
        return "\n".join(parts).lower()


def _entry(row) -> Entry:
    return Entry(
        row.number,
        row.notebook,
        row.title,
        row.date,
        row.post,
        list(row.said or []),
        row.agent_wrote,
        row.agent_note,
        row.agent_after,
        row.person_fixed,
        row.fixed_note,
        row.fixed_after,
        row.rule,
        row.check_line,
        row.seen,
        row.probe_id,
        row.label,
        row.updated_at,
        row.probe_task,
        row.probe_verify,
    )


async def entries(conn: AsyncConnection, project_id: int) -> list[Entry]:
    """The entries of a project's notebook, by number."""
    f = t.feedback.c
    found = await conn.execute(select(t.feedback).where(f.project_id == project_id).order_by(f.number))
    return [_entry(row) for row in found]


async def entry(conn: AsyncConnection, project_id: int, number: int, *, lock: bool = False) -> Entry | None:
    f = t.feedback.c
    query = select(t.feedback).where(f.project_id == project_id, f.number == number)
    row = (await conn.execute(query.with_for_update() if lock else query)).first()
    return _entry(row) if row else None


def placed(after: int | None, said: list) -> int | None:
    """Where a line among the said lines is kept: None once it stands after all of them, so a repeat keeps it last."""
    return None if after is None or after >= len(said) else max(after, 0)


async def add_entry(conn: AsyncConnection, project_id: int, values: Mapping, label: dict) -> Entry:
    """A new entry with the next number of the project and ``values`` (columns of editorial_feedback)."""
    f = t.feedback
    for _ in range(NUMBER_TRIES):
        number = (await conn.scalar(select(func.max(f.c.number)).where(f.c.project_id == project_id)) or 0) + 1
        made = await conn.scalar(
            pg_insert(f)
            .values(project_id=project_id, number=number, label=label, **values)
            .on_conflict_do_nothing(constraint="editorial_feedback_number_key")
            .returning(f.c.id)
        )
        if made is not None:
            found = await entry(conn, project_id, number)
            assert found is not None
            return found
    raise hub.Refused(409, "another entry took the next number at the same time: try again")


async def repeat(conn: AsyncConnection, project_id: int, number: int, said: dict | None) -> Entry | None:
    """Entry ``number`` was seen again: one more time seen, and what the person said this time after their other
    words; None when there is no such entry."""
    found = await entry(conn, project_id, number, lock=True)
    if found is None:
        return None
    f = t.feedback
    values: dict = {"seen": f.c.seen + 1, "updated_at": func.now()}
    if said is not None:
        values["said"] = [*found.said, said]
    await conn.execute(update(f).where(f.c.project_id == project_id, f.c.number == number).values(**values))
    return await entry(conn, project_id, number)


async def put_entry(conn: AsyncConnection, project_id: int, number: int, values: Mapping, label: dict) -> bool:
    """Write entry ``number`` as given (import), keeping its number; whether this call made it."""
    f = t.feedback
    statement = pg_insert(f).values(project_id=project_id, number=number, label=label, **values)
    made = await conn.scalar(
        statement.on_conflict_do_update(
            constraint="editorial_feedback_number_key", set_={**values, "updated_at": func.now()}
        ).returning(f.c.created_at == f.c.updated_at)
    )
    return bool(made)


async def set_entry(conn: AsyncConnection, project_id: int, number: int, values: Mapping) -> None:
    """Write ``values`` (columns of editorial_feedback) on entry ``number``."""
    f = t.feedback
    await conn.execute(
        update(f).where(f.c.project_id == project_id, f.c.number == number).values(**values, updated_at=func.now())
    )
