"""What the routes (``server``) and the MCP tools (``tools``) of editorial do, for a caller whose access to the project
is known (``Viewer``): list and show posts, set a post's state, read the notebook by notebook, stage, post, times seen
and keyword, recall what to read before a stage, add an entry, record a repeat, import and export.

What the caller may not read (a label above their grant, through the sink they read with) is not there for them. A
stage, a notebook and a gate's kind are the ones the project's config lists (``settings``).
"""

from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncConnection

from evo_agents.hub.server import core_plugin_api as hub
from evo_core_plugins.editorial import document, flow, judge, ledger, probes, settings, store
from evo_core_plugins.editorial.models import (
    EditorialComment,
    EditorialEntry,
    EditorialExport,
    EditorialFeedbackIn,
    EditorialGate,
    EditorialGateSummary,
    EditorialImported,
    EditorialJudge,
    EditorialNotebookFile,
    EditorialPost,
    EditorialPostSummary,
    EditorialProbeIn,
    EditorialRepeatIn,
    EditorialRound,
    EditorialRun,
    EditorialSaid,
    EditorialSetIn,
    EditorialStageEntered,
)
from evo_core_plugins.editorial.tables import GATE_STATES, SLUG

DEFAULT_VIA = "hub"


@dataclass(frozen=True)
class Viewer:
    """A caller in a project: their access, their read rule, the sink they read through and the project's config."""

    session: hub.Session
    access: hub.ProjectRef
    rule: hub.LabelReader
    sink: str | None
    cfg: settings.Config

    def sees(self, label) -> bool:
        return self.rule.visible(label, self.sink)


async def viewer(conn: AsyncConnection, session: hub.Session, project: str, sink: str | None) -> Viewer:
    """The caller's access to ``project``, which enables the plugin, and what they read there."""
    access = await hub.project_access(conn, session, project)
    store.reader(access)
    rule = await hub.label_reader(conn, settings.handle(), access)
    return Viewer(session, access, rule, sink, await settings.config(conn, project))


def _unprocessable(message: str) -> hub.Refused:
    return hub.Refused(422, message)


# Posts


def _waiting(cfg: settings.Config, stage: str, gates: list[store.Gate]) -> str | None:
    """The stage of the gate that waits: the one at the post's stage, else the first by the order of stages."""
    waiting = sorted((gate.stage for gate in gates if gate.state == "waiting"), key=cfg.order)
    if stage in waiting:
        return stage
    return waiting[0] if waiting else None


def _ordered(cfg: settings.Config, gates: list[store.Gate]) -> list[store.Gate]:
    return sorted(gates, key=lambda gate: (cfg.order(gate.stage), gate.opened_at))


def _run(row: store.Post) -> EditorialRun | None:
    if row.run_state is None:
        return None
    return EditorialRun(run_id=row.run_id, state=row.run_state, stage=row.run_stage, error=row.run_error, at=row.run_at)


def _judge(item: store.Round) -> EditorialJudge | None:
    if item.judge_state is None and item.scores is None:
        return None
    return EditorialJudge(state=item.judge_state, note=item.judge_note, passed=judge.passes(item.scores))


def _summary_gate(gate: store.Gate) -> EditorialGateSummary:
    return EditorialGateSummary(
        stage=gate.stage, kind=gate.kind, state=gate.state, answered_at=gate.answered_at, answered_via=gate.answered_via
    )


async def list_posts(conn: AsyncConnection, who: Viewer, stage: str | None = None) -> list[EditorialPostSummary]:
    """The posts the caller sees, by the order of their stages, then the one changed last first."""
    rows = [row for row in await store.posts(conn, who.access.id) if who.sees(row.label)]
    if stage:
        rows = [row for row in rows if row.stage == stage]
    ids = [row.id for row in rows]
    gates, counts = await store.gates(conn, ids), await store.round_counts(conn, ids)
    rows.sort(key=lambda row: who.cfg.order(row.stage))
    return [
        EditorialPostSummary(
            slug=row.slug,
            title=row.title,
            stage=row.stage,
            waiting_gate=_waiting(who.cfg, row.stage, gates.get(row.id, [])),
            gates=[_summary_gate(gate) for gate in _ordered(who.cfg, gates.get(row.id, []))],
            rounds=counts.get(row.id, 0),
            preview_url=row.preview_url,
            url=row.url,
            run=_run(row),
        )
        for row in rows
    ]


def _missing(who: Viewer, slug: str) -> hub.Refused:
    return hub.Refused(
        404, f"no post {slug} in project {who.access.name} that you can see: see `evo-agents hub editorial posts`"
    )


async def _seen_post(conn: AsyncConnection, who: Viewer, slug: str, *, lock: bool = False) -> store.Post:
    found = await store.post(conn, who.access.id, slug, lock=lock)
    if found is None or not who.sees(found.label):
        raise _missing(who, slug)
    return found


async def show_post(conn: AsyncConnection, who: Viewer, slug: str) -> EditorialPost:
    """One post with its gates, rounds and comments, the stages it entered and the entries about it."""
    row = await _seen_post(conn, who, slug)
    gates = (await store.gates(conn, [row.id])).get(row.id, [])
    rounds = await store.rounds(conn, row.id)
    about = [entry.id for entry in await store.entries(conn, who.access.id) if entry.post == slug]
    return EditorialPost(
        slug=row.slug,
        title=row.title,
        stage=row.stage,
        branch=row.branch,
        preview_url=row.preview_url,
        url=row.url,
        comment_id=row.comment_id,
        published_at=row.published_at,
        run=_run(row),
        d7=row.d7,
        d28=row.d28,
        waiting_gate=_waiting(who.cfg, row.stage, gates),
        gates=[
            EditorialGate(
                stage=gate.stage,
                kind=gate.kind,
                state=gate.state,
                opened_at=gate.opened_at,
                answered_at=gate.answered_at,
                answered_via=gate.answered_via,
                answered_by=gate.answered_by,
                answer=gate.answer,
                ask=gate.ask,
            )
            for gate in _ordered(who.cfg, gates)
        ],
        rounds=[
            EditorialRound(
                stage=item.stage,
                number=item.number,
                at=item.at,
                note=item.note,
                feedback=list(item.feedback),
                scores=item.scores,
                judge=_judge(item),
                comments=[
                    EditorialComment(id=c.external_id, author=c.author, quote=c.quote, text=c.text, at=c.at)
                    for c in item.comments
                ],
            )
            for item in rounds
        ],
        history=[
            EditorialStageEntered(stage=step.stage, at=step.at, evidence=step.evidence)
            for step in await store.history(conn, row.id)
        ],
        feedback=about,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _figures(value: dict | str | None, name: str) -> dict | None:
    if value is None or isinstance(value, dict):
        return value
    try:
        found = json.loads(value)
    except json.JSONDecodeError:
        found = None
    if not isinstance(found, dict):
        raise _unprocessable(f'{name} is an object of figures, such as {{"views": 120}}, as JSON')
    return found


def _known_stage(cfg: settings.Config, stage: str) -> settings.Stage:
    found = cfg.stage(stage)
    if found is None:
        listed = ", ".join(cfg.stage_names)
        if not listed:
            raise _unprocessable("the project lists no stages yet: set stages in the config of plugin editorial")
        raise _unprocessable(f"stage {stage!r} is not one of the project's stages: {listed}")
    return found


async def set_post(conn: AsyncConnection, who: Viewer, slug: str, body: EditorialSetIn) -> EditorialPost:
    """Change a post, or make it when it is not there (which needs a stage). Entering a stage keeps it in the
    history and opens the stage's gate, when the config gives it one, which tells the gatekeepers (``flow``); a gate's
    state is set with ``gate``, and an answer hands the writer the post's next task."""
    store.writer(who.access, "setting the state of a post")
    if not re.fullmatch(SLUG, slug):
        raise _unprocessable(f"{slug!r} is no slug: lower case letters, digits and -")
    found = await store.post(conn, who.access.id, slug, lock=True)
    if found is not None and not who.sees(found.label):
        raise _missing(who, slug)
    values: dict[str, Any] = {}
    for name in ("title", "branch", "preview_url", "url", "published_at", "comment_id"):
        if getattr(body, name) is not None:
            values[name] = getattr(body, name)
    for name in ("d7", "d28"):
        if getattr(body, name) is not None:
            values[name] = _figures(getattr(body, name), name)
    stage = None
    if body.stage is not None:
        stage = _known_stage(who.cfg, body.stage)
        values["stage"] = stage.name
    if found is None and stage is None:
        raise _unprocessable(f"there is no post {slug} yet: give its stage to make it")
    moved = stage is not None and (found is None or found.stage != stage.name)
    if body.gate is None and (body.gate_state is not None or body.via is not None or body.answer is not None):
        raise _unprocessable("gate_state, via and answer go with gate, the stage of the gate to set")
    if body.gate is not None and body.gate_state not in GATE_STATES:
        raise _unprocessable(f"give the state of the gate at {body.gate}: {', '.join(GATE_STATES)}")
    if not values and body.gate is None and body.ask is None:
        raise _unprocessable("give something to set: a stage, a title, links, figures or a gate")
    answering = body.gate is not None and body.gate_state in ("answered", "skipped")
    if answering and found is not None:
        if found.running:
            raise hub.Refused(409, f"post {slug} has run #{found.run_id} running: answer once it stops at the gate")
        gate_stage = who.cfg.stage(body.gate)
        if gate_stage is not None and body.gate_state == "answered":
            why = await flow.approval_refusal(conn, found, gate_stage, body.answer)
            if why is not None:
                raise hub.Refused(409, why)
    project = await hub.read_project(conn, settings.handle(), who.access.name)
    post_id = found.id if found is not None else None
    if values or post_id is None:
        post_id, _ = await store.put_post(conn, who.access.id, slug, values, dict(project.default_label))
    opened = None
    if moved and stage is not None:
        await store.entered(conn, post_id, stage.name, dt.datetime.now(dt.UTC), body.evidence)
        if stage.gate is not None:
            await store.open_gate(conn, post_id, stage.name, stage.gate)
            opened = stage
    asked_at = body.gate if body.gate is not None else (opened.name if opened is not None else None)
    if body.ask is not None:
        if asked_at is None or not await store.ask_at_gate(conn, post_id, asked_at, body.ask):
            raise _unprocessable("ask goes with the stage of a gate: enter it, or name it with gate")
    if opened is not None:
        await flow.gate_opened(conn, who.access.name, who.access.id, who.cfg, post_id, opened)
    if body.gate is not None and body.gate_state is not None:
        changed = await store.answer_gate(
            conn, post_id, body.gate, body.gate_state, body.via or DEFAULT_VIA, who.session.user_id, body.answer
        )
        if not changed:
            raise hub.Refused(404, f"post {slug} has no gate at stage {body.gate}")
        if answering:
            await flow.hand_next(conn, who.access.name, who.cfg, post_id, answered=True)
    return await show_post(conn, who, slug)


async def pull_comments(conn: AsyncConnection, who: Viewer, slug: str) -> EditorialPost:
    """Read the reviewers' comments on the post's draft into its latest round at its comments stage."""
    store.writer(who.access, "reading the comments of a post")
    post = await _seen_post(conn, who, slug, lock=True)
    stage = flow.comments_stage(who.cfg, post)
    if stage is None:
        raise _unprocessable(f"post {slug} is at no stage with a comments gate, nor past one")
    await flow.pull_comments(conn, who.cfg, post, stage.name)
    return await show_post(conn, who, slug)


async def run_post(conn: AsyncConnection, who: Viewer, slug: str) -> EditorialPost:
    """Hand the writer the post's next task now, as after an answer (again after an error, say)."""
    store.writer(who.access, "handing the writer a post")
    post = await _seen_post(conn, who, slug, lock=True)
    if who.cfg.repo is None:
        raise _unprocessable("set repo, the repo of the posts, in the config of plugin editorial")
    if post.running:
        raise hub.Refused(409, f"post {slug} has run #{post.run_id} running: one task at a time")
    await flow.hand_next(conn, who.access.name, who.cfg, post.id, answered=True)  # a refusal shows on the post
    return await show_post(conn, who, slug)


# The feedback notebook


def entry_model(entry: store.Entry) -> EditorialEntry:
    return EditorialEntry(
        id=entry.id,
        notebook=entry.notebook,
        title=entry.title,
        date=entry.date,
        post=entry.post,
        said=[EditorialSaid(**item) for item in entry.said],
        agent_wrote=entry.agent_wrote,
        agent_note=entry.agent_note,
        agent_after=entry.agent_after,
        person_fixed=entry.person_fixed,
        fixed_note=entry.fixed_note,
        fixed_after=entry.fixed_after,
        rule=entry.rule,
        check=entry.check,
        seen=entry.seen,
        probe_id=entry.probe_id,
        probe_task=entry.probe_task,
    )


async def _visible_entries(conn: AsyncConnection, who: Viewer) -> list[store.Entry]:
    return [entry for entry in await store.entries(conn, who.access.id) if who.sees(entry.label)]


def _keyword(entries: list[store.Entry], keyword: str | None) -> list[store.Entry]:
    words = [word for word in (keyword or "").lower().split() if word]
    return [entry for entry in entries if all(word in entry.words() for word in words)]


async def list_feedback(
    conn: AsyncConnection,
    who: Viewer,
    *,
    notebook: str | None = None,
    stage: str | None = None,
    post: str | None = None,
    seen: int | None = None,
    keyword: str | None = None,
) -> list[store.Entry]:
    """The entries the caller sees, by number: of one notebook, of the notebooks read before ``stage``, about one
    post, seen at least ``seen`` times, with every word of ``keyword``."""
    found = await _visible_entries(conn, who)
    if notebook:
        found = [entry for entry in found if entry.notebook == notebook]
    if stage:
        books = who.cfg.recall(_known_stage(who.cfg, stage).name)
        found = [entry for entry in found if entry.notebook in books]
    if post:
        found = [entry for entry in found if entry.post == post]
    if seen is not None:
        found = [entry for entry in found if entry.seen >= seen]
    return _keyword(found, keyword)


async def recall(
    conn: AsyncConnection, who: Viewer, *, stage: str | None, post: str | None, keyword: str | None
) -> list[store.Entry]:
    """What to read before ``stage``: the entries of the notebooks it reads and of those read before every stage,
    with those about ``post`` from any notebook, then narrowed to every word of ``keyword``; the ones seen most first."""
    found = await _visible_entries(conn, who)
    if stage:
        books = who.cfg.recall(_known_stage(who.cfg, stage).name)
        found = [entry for entry in found if entry.notebook in books or (post and entry.post == post)]
    elif post:
        found = [entry for entry in found if entry.post == post]
    found = _keyword(found, keyword)
    return sorted(found, key=lambda entry: (-entry.seen, entry.number))


def _known_notebook(cfg: settings.Config, name: str | None) -> str:
    if not name:
        raise _unprocessable(f"give the entry's notebook: {', '.join(cfg.notebook_names) or 'none is listed yet'}")
    if cfg.notebook(name) is None:
        listed = ", ".join(cfg.notebook_names)
        if not listed:
            raise _unprocessable("the project lists no notebooks yet: set notebooks in the config of plugin editorial")
        raise _unprocessable(f"notebook {name!r} is not one of the project's notebooks: {listed}")
    return name


async def add_feedback(conn: AsyncConnection, who: Viewer, body: EditorialFeedbackIn) -> store.Entry:
    """A new entry, numbered after the last one: what the person said, the rule, and how it is checked."""
    store.writer(who.access, "adding to the feedback notebook")
    notebook = _known_notebook(who.cfg, body.notebook)
    missing = [name for name in ("title", "said", "rule") if not (getattr(body, name) or "").strip()]
    if missing:
        raise _unprocessable(f"a new entry needs {', '.join(missing)}")
    probing = bool(body.probe_task or body.probe_verify)
    if probing:
        store.admin(who.access, "giving an entry its probe")
    values = {
        "notebook": notebook,
        "title": body.title.strip(),
        "date": body.date or dt.datetime.now(dt.UTC).date(),
        "post": body.post or None,
        "said": [{"text": body.said.strip(), "date": None, "note": body.note or None}],
        "agent_wrote": body.agent_wrote or None,
        "person_fixed": body.person_fixed or None,
        "rule": body.rule.strip(),
        "check_line": body.check or None,
        "seen": 1,
        "probe_id": body.probe_id,
    }
    project = await hub.read_project(conn, settings.handle(), who.access.name)
    made = await store.add_entry(conn, who.access.id, values, dict(project.default_label))
    if not probing:
        return made
    await probes.put(
        conn, who.access.name, who.access.id, who.cfg, made, body.probe_task or "", body.probe_verify or ""
    )
    found = await store.entry(conn, who.access.id, made.number)
    assert found is not None
    return found


async def probe_feedback(conn: AsyncConnection, who: Viewer, entry: str, body: EditorialProbeIn) -> store.Entry:
    """Give entry ``entry`` its probe (task and verify), in place of the one it has, or retire it with ``remove``."""
    store.admin(who.access, "the probe of an entry")
    number = entry_number(entry)
    found = await store.entry(conn, who.access.id, number, lock=True)
    if found is None or not who.sees(found.label):
        raise hub.Refused(404, f"no entry {ledger.entry_id(number)} in project {who.access.name} that you can see")
    if body.remove:
        await probes.remove(conn, who.access.name, who.access.id, found)
    else:
        await probes.put(conn, who.access.name, who.access.id, who.cfg, found, body.task or "", body.verify or "")
    changed = await store.entry(conn, who.access.id, number)
    assert changed is not None
    return changed


def entry_number(text: str) -> int:
    number = ledger.entry_number(text)
    if number is None:
        raise _unprocessable(f"{text!r} is no entry id: write PH-<number>")
    return number


async def repeat_feedback(conn: AsyncConnection, who: Viewer, entry: str, body: EditorialRepeatIn) -> store.Entry:
    """Entry ``entry`` came back: seen once more, with what the person said this time when given."""
    store.writer(who.access, "recording a repeat in the feedback notebook")
    number = entry_number(entry)
    found = await store.entry(conn, who.access.id, number)
    if found is None or not who.sees(found.label):
        raise hub.Refused(404, f"no entry {ledger.entry_id(number)} in project {who.access.name} that you can see")
    said = None
    if body.said and body.said.strip():
        said = {
            "text": body.said.strip(),
            "date": body.date or dt.datetime.now(dt.UTC).date().isoformat(),
            "note": body.note or None,
        }
    repeated = await store.repeat(conn, who.access.id, number, said)
    assert repeated is not None
    return repeated


# Import and export


def _entry_values(item: document.DocEntry) -> dict:
    said = [said.model_dump() for said in item.said]
    return {
        "notebook": item.notebook,
        "title": item.title,
        "date": item.date,
        "post": item.post,
        "said": said,
        "agent_wrote": item.agent_wrote,
        "agent_note": item.agent_note,
        "agent_after": store.placed(item.agent_after, said),
        "person_fixed": item.person_fixed,
        "fixed_note": item.fixed_note,
        "fixed_after": store.placed(item.fixed_after, said),
        "rule": item.rule,
        "check_line": item.check,
        "seen": item.seen,
        "probe_id": item.probe_id,
    }


async def _import_post(conn: AsyncConnection, who: Viewer, item: document.DocPost, label: dict) -> bool:
    values = {
        "title": item.title,
        "stage": item.stage,
        "branch": item.branch,
        "preview_url": item.preview_url,
        "url": item.url,
        "published_at": item.published_at,
        "d7": item.d7,
        "d28": item.d28,
    }
    post_id, made = await store.put_post(conn, who.access.id, item.slug, values, label)
    for step in item.history:
        await store.entered(conn, post_id, step.stage, step.at, step.evidence)
    for gate in item.gates:
        kind = gate.kind or who.cfg.stage(gate.stage).gate  # document.problems checked there is one
        gate_values = {
            "stage": gate.stage,
            "kind": kind,
            "state": gate.state,
            "answered_at": gate.answered_at,
            "answered_via": gate.answered_via,
            "answer": gate.answer,
        }
        if gate.opened_at is not None:
            gate_values["opened_at"] = gate.opened_at
        await store.put_gate(conn, post_id, gate_values)
    for item_round in item.rounds:
        round_id = await store.put_round(
            conn,
            post_id,
            {
                "stage": item_round.stage,
                "number": item_round.number,
                "at": item_round.at,
                "note": item_round.note,
                "feedback": [ledger.entry_id(entry_number(ph)) for ph in item_round.feedback],
                "scores": item_round.scores,
            },
        )
        for comment in item_round.comments:
            await store.put_comment(
                conn,
                round_id,
                {
                    "external_id": comment.id,
                    "author": comment.author,
                    "quote": comment.quote,
                    "text": comment.text,
                    "at": comment.at,
                },
            )
    return made


async def import_document(conn: AsyncConnection, who: Viewer, text: str | None, data: dict | None) -> EditorialImported:
    """Write the posts and entries of the file, keeping their ids: what is there is written over, nothing is there
    twice. Nothing is written when anything in the file does not fit the project's config."""
    store.admin(who.access, "importing posts and the feedback notebook")
    try:
        doc = document.parse(text, data)
    except ValueError as exc:
        raise _unprocessable(str(exc)) from None
    wrong = document.problems(who.cfg, doc)
    if wrong:
        more = f" (and {len(wrong) - document.MAX_PROBLEMS} more)" if len(wrong) > document.MAX_PROBLEMS else ""
        raise _unprocessable("; ".join(wrong[: document.MAX_PROBLEMS]) + more)
    project = await hub.read_project(conn, settings.handle(), who.access.name)
    label = dict(project.default_label)
    for item in doc.posts:
        found = await store.post(conn, who.access.id, item.slug)
        if found is not None and not who.sees(found.label):
            raise _unprocessable(f"post {item.slug} is there with a label you cannot read: it is not written over")
    posts_added = entries_added = 0
    for item in doc.posts:
        posts_added += await _import_post(conn, who, item, label)
    for item in doc.entries:
        entries_added += await store.put_entry(conn, who.access.id, item.number, _entry_values(item), label)
    return EditorialImported(
        posts_added=posts_added,
        posts_updated=len(doc.posts) - posts_added,
        entries_added=entries_added,
        entries_updated=len(doc.entries) - entries_added,
    )


def notebook_files(
    cfg: settings.Config, entries: list[store.Entry], notebook: str | None
) -> list[EditorialNotebookFile]:
    """Each notebook as its markdown file: those of the config in its order, then any an entry names that the config
    no longer lists."""
    names = list(cfg.notebook_names) + sorted({e.notebook for e in entries} - set(cfg.notebook_names))
    if notebook:
        names = [name for name in names if name == notebook]
    files = []
    for name in names:
        book = cfg.notebook(name)
        mine = [entry.as_ledger() for entry in entries if entry.notebook == name]
        markdown = ledger.notebook_markdown(book.title if book else name, book.intro if book else "", mine, cfg.person)
        files.append(EditorialNotebookFile(name=name, file=f"{name}.md", markdown=markdown))
    return files


async def _document(conn: AsyncConnection, who: Viewer, entries: list[store.Entry]) -> dict:
    posts = []
    for row in [row for row in await store.posts(conn, who.access.id) if who.sees(row.label)]:
        shown = await show_post(conn, who, row.slug)
        posts.append(
            {
                **shown.model_dump(
                    mode="json",
                    include={"slug", "title", "stage", "branch", "preview_url", "url", "published_at", "d7", "d28"},
                ),
                "history": [step.model_dump(mode="json") for step in shown.history],
                "gates": [gate.model_dump(mode="json", exclude={"answered_by", "ask"}) for gate in shown.gates],
                "rounds": [item.model_dump(mode="json", exclude={"judge"}) for item in shown.rounds],
            }
        )
    shown = [entry_model(entry).model_dump(mode="json", exclude={"probe_task"}) for entry in entries]
    return {"posts": posts, "entries": shown}


async def export(conn: AsyncConnection, who: Viewer, notebook: str | None, form: str) -> EditorialExport:
    """The notebook as its markdown files, or with ``json`` everything import takes."""
    entries = await _visible_entries(conn, who)
    if notebook and not any(entry.notebook == notebook for entry in entries):
        _known_notebook(who.cfg, notebook)
    if form == "json":
        chosen = [entry for entry in entries if not notebook or entry.notebook == notebook]
        data = await _document(conn, who, chosen)
        if notebook:
            data["posts"] = []
        return EditorialExport(format="json", notebooks=[], document=data)
    return EditorialExport(format="markdown", notebooks=notebook_files(who.cfg, entries, notebook), document=None)
