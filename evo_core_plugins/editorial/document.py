"""The JSON file ``evo-agents hub editorial import`` takes and ``export --format json`` prints: every post with its
stage history, gates, review rounds and their comments, and every entry of the feedback notebook with its id::

    {
      "posts": [
        {"slug": "...", "title": "...", "stage": "...", "branch": "...", "preview_url": "...", "url": "...",
         "published_at": "...", "d7": {...}, "d28": {...},
         "history": [{"stage": "...", "at": "...", "evidence": "..."}],
         "gates": [{"stage": "...", "kind": "...", "state": "answered", "opened_at": "...", "answered_at": "...",
                    "answered_via": "...", "answer": ...}],
         "rounds": [{"stage": "...", "number": 1, "at": "...", "note": "...", "feedback": ["PH-0042"],
                     "scores": {...}, "comments": [{"id": "...", "author": "...", "quote": "...", "text": "...",
                                                     "at": "..."}]}]}
      ],
      "entries": [
        {"id": "PH-0042", "notebook": "...", "title": "...", "date": "2026-10-02", "post": "...",
         "said": [{"text": "...", "date": null, "note": null}], "agent_wrote": "...", "agent_note": null,
         "agent_after": null, "person_fixed": "...", "fixed_note": null, "fixed_after": null, "rule": "...",
         "check": "...", "seen": 2, "probe_id": null}
      ]
    }

A stage and a notebook are ones the project's config lists; a gate's kind, when the file leaves it out, is the one the
config gives its stage. Import keeps the ids: an entry keeps its number, a post its slug, a gate its stage, a round its
stage and number, a comment the id its source gave it.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from evo_core_plugins.editorial import ledger
from evo_core_plugins.editorial.settings import Config
from evo_core_plugins.editorial.tables import GATE_KINDS, GATE_STATES, SLUG

MAX_PROBLEMS = 20


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DocSaid(_Strict):
    text: str
    date: str | None = None
    note: str | None = None


class DocEntry(_Strict):
    id: str
    notebook: str
    title: str
    date: dt.date
    post: str | None = None
    said: list[DocSaid] = Field(default_factory=list)
    agent_wrote: str | None = None
    agent_note: str | None = None
    agent_after: int | None = Field(None, ge=0)
    person_fixed: str | None = None
    fixed_note: str | None = None
    fixed_after: int | None = Field(None, ge=0)
    rule: str
    check: str | None = None
    seen: int = Field(1, ge=0)
    probe_id: int | None = None

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        if ledger.entry_number(value) is None:
            raise ValueError("an entry id is PH-<number>")
        return value

    @property
    def number(self) -> int:
        number = ledger.entry_number(self.id)
        assert number is not None
        return number


class DocEntered(_Strict):
    stage: str
    at: dt.datetime
    evidence: str | None = None


class DocGate(_Strict):
    stage: str
    kind: str | None = None
    state: str = "waiting"
    opened_at: dt.datetime | None = None
    answered_at: dt.datetime | None = None
    answered_via: str | None = None
    answer: Any = None


class DocComment(_Strict):
    id: str
    author: str | None = None
    quote: str | None = None
    text: str
    at: dt.datetime | None = None


class DocRound(_Strict):
    stage: str
    number: int = Field(ge=1)
    at: dt.datetime
    note: str | None = None
    feedback: list[str] = Field(default_factory=list)
    scores: dict | None = None
    comments: list[DocComment] = Field(default_factory=list)


class DocPost(_Strict):
    slug: str
    title: str = ""
    stage: str
    branch: str | None = None
    preview_url: str | None = None
    url: str | None = None
    published_at: dt.datetime | None = None
    d7: dict | None = None
    d28: dict | None = None
    history: list[DocEntered] = Field(default_factory=list)
    gates: list[DocGate] = Field(default_factory=list)
    rounds: list[DocRound] = Field(default_factory=list)


class Document(_Strict):
    posts: list[DocPost] = Field(default_factory=list)
    entries: list[DocEntry] = Field(default_factory=list)


def _stage(cfg: Config, stage: str, where: str) -> list[str]:
    if stage in cfg.stage_names:
        return []
    return [f"{where}: stage {stage!r} is not one of the project's stages ({', '.join(cfg.stage_names) or 'none'})"]


def _post_problems(cfg: Config, index: int, post: DocPost) -> list[str]:
    where = f"posts[{index}] {post.slug}"
    found = [] if re.fullmatch(SLUG, post.slug) else [f"posts[{index}]: slug {post.slug!r} is not a slug"]
    found += _stage(cfg, post.stage, where)
    for at, item in enumerate(post.history):
        found += _stage(cfg, item.stage, f"{where} history[{at}]")
    stages = [gate.stage for gate in post.gates]
    for at, gate in enumerate(post.gates):
        place = f"{where} gates[{at}]"
        found += _stage(cfg, gate.stage, place)
        kind = gate.kind or (cfg.stage(gate.stage).gate if cfg.stage(gate.stage) else None)
        if kind not in GATE_KINDS:
            found.append(f"{place}: kind {kind!r} is none of {', '.join(GATE_KINDS)}")
        if gate.state not in GATE_STATES:
            found.append(f"{place}: state {gate.state!r} is none of {', '.join(GATE_STATES)}")
        if stages.count(gate.stage) > 1:
            found.append(f"{place}: the post has two gates at stage {gate.stage}")
    keys = [(item.stage, item.number) for item in post.rounds]
    for at, item in enumerate(post.rounds):
        place = f"{where} rounds[{at}]"
        found += _stage(cfg, item.stage, place)
        if keys.count((item.stage, item.number)) > 1:
            found.append(f"{place}: two rounds {item.number} at stage {item.stage}")
        found += [f"{place}: feedback {ph!r} is no PH-<n>" for ph in item.feedback if ledger.entry_number(ph) is None]
        ids = [comment.id for comment in item.comments]
        found += [f"{place}: comment {cid!r} is there twice" for cid in sorted(set(ids)) if ids.count(cid) > 1]
    return found


def problems(cfg: Config, doc: Document) -> list[str]:
    """What in ``doc`` does not fit the project's config, or is there twice."""
    found: list[str] = []
    slugs = [post.slug for post in doc.posts]
    found += [f"post {slug} is there twice" for slug in sorted(set(slugs)) if slugs.count(slug) > 1]
    for index, post in enumerate(doc.posts):
        found += _post_problems(cfg, index, post)
    numbers = [entry.number for entry in doc.entries]
    found += [f"{ledger.entry_id(n)} is there twice" for n in sorted(set(numbers)) if numbers.count(n) > 1]
    for entry in doc.entries:
        if entry.notebook not in cfg.notebook_names:
            known = ", ".join(cfg.notebook_names) or "none"
            found.append(f"{entry.id}: notebook {entry.notebook!r} is not one of the project's notebooks ({known})")
    return found


def parse(text: str | None, document: dict | None) -> Document:
    """The document of a file's ``text`` or of ``document``; ValueError with what is wrong."""
    if document is None:
        if not text or not text.strip():
            raise ValueError("give the JSON file of posts and entries")
        try:
            document = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"the file is no JSON: {exc}") from None
    if not isinstance(document, dict):
        raise ValueError("the file is one JSON object with posts and entries")
    try:
        return Document.model_validate(document)
    except ValidationError as exc:
        said = [
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}" for error in exc.errors()[:MAX_PROBLEMS]
        ]
        raise ValueError("; ".join(said)) from None


__all__ = ["DocEntry", "DocPost", "Document", "parse", "problems"]
