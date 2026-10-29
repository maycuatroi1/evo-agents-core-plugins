"""What the routes of the plugin editorial take and answer (``server``); ``evo-agents hub editorial`` prints the
answers with ``--json`` (``cli.json``)."""

from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import BaseModel, Field

from evo_core_plugins.editorial.tables import GATE_STATES

MAX_TEXT = 20_000


class EditorialGateSummary(BaseModel):
    stage: str
    kind: str
    state: str = Field(description=" | ".join(GATE_STATES))
    answered_at: dt.datetime | None = None
    answered_via: str | None = Field(None, description="what it was answered through: hub, cli, telegram...")


class EditorialRun(BaseModel):
    """The post's latest task run of the agent type writer."""

    run_id: int | None = None
    state: str | None = Field(None, description="running | done | failed | refused")
    stage: str | None = Field(None, description="the stage the task was handed at")
    error: str | None = Field(None, description="why it failed or was refused")
    at: dt.datetime | None = None


class EditorialPostSummary(BaseModel):
    """One post as ``posts`` lists it."""

    slug: str
    title: str
    stage: str
    waiting_gate: str | None = Field(None, description="the stage of the gate that waits for a person, if any")
    gates: list[EditorialGateSummary]
    rounds: int = Field(description="how many review rounds the post had")
    preview_url: str | None = None
    url: str | None = Field(None, description="the published post")
    run: EditorialRun | None = Field(None, description="the writer's latest run, none before the first")


class EditorialGate(EditorialGateSummary):
    opened_at: dt.datetime
    answered_by: str | None = None
    answer: Any = None
    ask: Any = Field(None, description="what the agent put to the person: proposals, questions")


class EditorialComment(BaseModel):
    id: str = Field(description="the id the comment's source gave it")
    author: str | None = None
    quote: str | None = Field(None, description="the sentence the comment marks")
    text: str
    at: dt.datetime | None = None


class EditorialJudge(BaseModel):
    """The judge's question of a round and what came of it."""

    state: str | None = Field(None, description="pending | passed | below | failed | refused")
    note: str | None = None
    passed: bool = Field(description="the machine gate: every axis 4 or more")


class EditorialRound(BaseModel):
    stage: str
    number: int
    at: dt.datetime
    note: str | None = None
    feedback: list[str] = Field(description="the feedback entries the round wrote, PH-<n>")
    scores: dict | None = None
    judge: EditorialJudge | None = None
    comments: list[EditorialComment]


class EditorialStageEntered(BaseModel):
    stage: str
    at: dt.datetime
    evidence: str | None = None


class EditorialPost(BaseModel):
    """One post with its gates, review rounds and comments, the stages it entered and its feedback entries."""

    slug: str
    title: str
    stage: str
    branch: str | None = None
    preview_url: str | None = None
    url: str | None = None
    comment_id: str | None = Field(None, description="the comment service keys its draft comments draft:<comment_id>")
    published_at: dt.datetime | None = None
    run: EditorialRun | None = None
    d7: dict | None = Field(None, description="the figures a person wrote in 7 days after it went out")
    d28: dict | None = Field(None, description="the figures a person wrote in 28 days after it went out")
    waiting_gate: str | None = None
    gates: list[EditorialGate]
    rounds: list[EditorialRound]
    history: list[EditorialStageEntered]
    feedback: list[str] = Field(description="the notebook's entries about this post, PH-<n>")
    created_at: dt.datetime
    updated_at: dt.datetime


class EditorialChoice(BaseModel):
    name: str
    title: str


class EditorialWorkspace(BaseModel):
    """Display labels only, not the plugin's operational configuration."""

    stages: list[EditorialChoice]
    notebooks: list[EditorialChoice]


class EditorialSetIn(BaseModel):
    """What to change of a post; a post that is not there is made, which needs a stage."""

    title: str | None = Field(None, max_length=500)
    stage: str | None = None
    branch: str | None = Field(None, max_length=300)
    preview_url: str | None = Field(None, max_length=2000)
    url: str | None = Field(None, max_length=2000)
    comment_id: str | None = Field(None, max_length=200, pattern=r"^[A-Za-z0-9_-]+$")
    published_at: dt.datetime | None = None
    d7: dict | str | None = Field(None, description="an object of figures, or its JSON text")
    d28: dict | str | None = Field(None, description="an object of figures, or its JSON text")
    evidence: str | None = Field(None, max_length=2000, description="what shows the post entered the stage")
    gate: str | None = Field(None, description="the stage of the gate to set")
    gate_state: str | None = Field(None, description=" | ".join(GATE_STATES))
    via: str | None = Field(None, max_length=100, description="what the gate was answered through; hub when unsaid")
    answer: Any = None
    ask: Any = Field(
        None, description="what to put to the person at the gate of the stage entered, or of gate: proposals, questions"
    )


class EditorialSaid(BaseModel):
    text: str
    date: str | None = Field(None, description="when it was said, as the notebook writes it")
    note: str | None = None


class EditorialEntry(BaseModel):
    """An entry of the feedback notebook."""

    id: str = Field(description="PH-<n>")
    notebook: str
    title: str
    date: dt.date
    post: str | None = None
    said: list[EditorialSaid]
    agent_wrote: str | None = None
    agent_note: str | None = None
    agent_after: int | None = Field(None, description="how many said lines its line follows; null after all")
    person_fixed: str | None = None
    fixed_note: str | None = None
    fixed_after: int | None = Field(None, description="how many said lines its line follows; null after all")
    rule: str
    check: str | None = Field(None, description="the Kiểm line: how the rule is checked")
    seen: int = Field(description="Lần gặp: how many times it was seen")
    probe_id: int | None = None
    probe_task: str | None = Field(None, description="the task of the probe; its verify only the admins read")


class EditorialFeedbackIn(BaseModel):
    """A new entry; the notebook and the post may come in the query instead."""

    notebook: str | None = None
    title: str | None = Field(None, max_length=500)
    said: str | None = Field(None, max_length=MAX_TEXT, description="what the person said")
    date: dt.date | None = Field(None, description="the day of the entry; today when unsaid")
    note: str | None = Field(None, max_length=500)
    post: str | None = None
    agent_wrote: str | None = Field(None, max_length=MAX_TEXT)
    person_fixed: str | None = Field(None, max_length=MAX_TEXT)
    rule: str | None = Field(None, max_length=MAX_TEXT)
    check: str | None = Field(None, max_length=MAX_TEXT)
    probe_id: int | None = None
    probe_task: str | None = Field(None, max_length=4000, description="the probe's task, with probe_verify (admin)")
    probe_verify: str | None = Field(None, max_length=2000, description="one shell line, exit 0 when the rule was kept")


class EditorialProbeIn(BaseModel):
    """The probe of an entry: its task and verify, or remove to retire it (admin)."""

    task: str | None = Field(None, max_length=4000)
    verify: str | None = Field(None, max_length=2000)
    remove: bool = False


class EditorialRepeatIn(BaseModel):
    """The entry was seen again, with what the person said this time."""

    said: str | None = Field(None, max_length=MAX_TEXT)
    date: str | None = Field(None, max_length=50, description="when it was said; today when unsaid")
    note: str | None = Field(None, max_length=500)


class EditorialImportIn(BaseModel):
    """The JSON of posts and notebook entries, as a file's text (``file``) or as an object (``document``)."""

    file: str | None = None
    document: dict | None = None


class EditorialImported(BaseModel):
    posts_added: int
    posts_updated: int
    entries_added: int
    entries_updated: int


class EditorialNotebookFile(BaseModel):
    name: str
    file: str = Field(description="the file name the notebook was kept in, <name>.md")
    markdown: str


class EditorialExport(BaseModel):
    format: str = Field(description="markdown | json")
    notebooks: list[EditorialNotebookFile]
    document: dict | None = Field(None, description="with json: what import takes, every post and entry")
