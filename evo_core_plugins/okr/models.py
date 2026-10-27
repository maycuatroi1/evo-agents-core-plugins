"""The API of the plugin okr as Pydantic models, each named ``Okr...`` in the hub's OpenAPI document: the tree with its
roll-up and gaps, one item, the bodies that write an item or a link, and the import bundle with its report.

An item is named by its code (``BL-1``, ``O-2``, ``KR-3``, ``D-4``) or by the ``ref`` a source gave it. A link's
target is a task's code (``T-12``), a use case as ``<document slug>:<code>`` (``northwind-srs:UC ORD-1``; a code
alone when it is unique in the project), a plan's slug, or a goal's code (``G-3``) or alias.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, Field

from evo_core_plugins.okr.tables import (
    KINDS,
    MAX_BODY_CHARS,
    MAX_FIELD_CHARS,
    MAX_PERIOD_CHARS,
    MAX_REV_CHARS,
    MAX_TARGET_CHARS,
    MAX_TITLE_CHARS,
    MAX_URL_CHARS,
    OWNER,
    REF,
    SOURCE,
    STATUSES,
    TARGET_KINDS,
)

Kind = Literal[*KINDS]
Status = Literal[*STATUSES]
TargetKind = Literal[*TARGET_KINDS]
MAX_IMPORT_ITEMS = 2000
MAX_IMPORT_LINKS = 10_000
MAX_PARENTS = 50
CLEARABLE = ("body_md", "owner", "period", "due", "baseline", "target", "ref")  # what an item may have none of


def _blank_is_none(value):
    """An empty string from the command line clears a field, as null does."""
    return None if isinstance(value, str) and not value.strip() else value


def _optional(inner, description: str | None = None):
    """A field that may be null, an empty string read as null, ``inner`` when given."""
    return Annotated[inner | None, BeforeValidator(_blank_is_none), Field(description=description)]


TitleText = Annotated[str, Field(min_length=1, max_length=MAX_TITLE_CHARS)]
Body = _optional(Annotated[str, Field(max_length=MAX_BODY_CHARS)], "the item's text, in Markdown")
Owner = _optional(Annotated[str, Field(pattern=OWNER)], "the login of who answers for it")
Period = _optional(Annotated[str, Field(max_length=MAX_PERIOD_CHARS)], "free text, such as 2026-Q4")
Due = _optional(date, "YYYY-MM-DD")
Text = _optional(Annotated[str, Field(max_length=MAX_FIELD_CHARS)])
Ref = _optional(Annotated[str, Field(pattern=REF)], "the id a source outside the hub gave it, unique in the project")


# Reading


class OkrGoal(BaseModel):
    code: str = Field(description="G-<n>")
    statement: str
    status: str = Field(description="the goal's own status: active, paused or closed")
    metric: str = Field(description="how its metric reads, such as `search.zero_rate p50 over 30 days <= 0.05`")
    value: float | None = Field(description="the latest value of its signal the caller may see")
    measured_at: datetime | None
    state: str = Field(description="met, not_met, no_signal or no_metric: the latest value against the target")


class OkrRollup(BaseModel):
    progress: float | None = Field(description="0 to 1, computed on read; null when nothing below counts")
    deliverables: int = Field(description="the distinct open deliverables it counts")
    tasks_done: int
    tasks_total: int = Field(description="the distinct tasks its deliverables link, cancelled ones left out")
    tasks_late: int = Field(description="due before today and not done")
    tasks_blocked: int = Field(description="not done, with an open blocker or an open decision of a run")
    krs_met: int
    krs_total: int = Field(description="the open key results at or below it")
    goal: OkrGoal | None = Field(default=None, description="a key result's goal")


class OkrLink(BaseModel):
    id: int
    kind: str = Field(description="task, use_case, plan or goal")
    target: str = Field(description="T-12, <document>:<code>, a plan's slug or G-3")
    gone: bool = Field(description="the hub no longer holds the target")
    visible: bool = Field(description="false: the caller may not read its title; it still counts")
    title: str | None = None
    status: str | None = Field(
        default=None,
        description="a task's status, a use case's state (draft, in_review, approved, retired), a plan's status, a "
        "goal's state (met, not_met, no_signal, no_metric)",
    )
    done: int | None = Field(default=None, description="a task 1 or 0, a use case's done tasks, a plan's done steps")
    total: int | None = Field(default=None, description="a task 1 (0 cancelled), a use case's tasks, a plan's steps")
    share: float | None = Field(default=None, description="what it counts for in the deliverable's progress")
    late: bool = False
    blocked: bool = False
    created_by: str | None = None
    created_at: datetime


class OkrGap(BaseModel):
    kind: str = Field(description="no_link, no_goal, no_kr, late or gone")
    item: str = Field(description="the item's code")
    title: str
    detail: str


class OkrItemRef(BaseModel):
    code: str
    kind: str
    title: str
    status: str


class OkrNode(BaseModel):
    code: str
    ref: str | None
    kind: str
    title: str
    status: str
    owner: str | None
    period: str | None
    due: date | None
    baseline: str | None
    target: str | None
    source: str | None
    rollup: OkrRollup
    links: list[OkrLink]
    children: list[OkrNode] = Field(description="a deliverable under two key results is under each")


class OkrTree(BaseModel):
    project: str
    today: date
    counts: dict[str, int] = Field(description="kind -> how many items the tree shows")
    roots: list[OkrNode] = Field(description="the business lines, then the objectives without one")
    gaps: list[OkrGap]


class OkrItem(BaseModel):
    code: str
    ref: str | None
    kind: str
    title: str
    body_md: str | None
    status: str
    owner: str | None
    period: str | None
    due: date | None
    baseline: str | None
    target: str | None
    source: str | None = Field(description="the import that writes it; its fields then change only there")
    source_url: str | None
    source_rev: str | None
    parents: list[OkrItemRef]
    children: list[OkrItemRef]
    links: list[OkrLink]
    rollup: OkrRollup
    gaps: list[OkrGap]
    created_by: str | None
    created_at: datetime
    updated_by: str | None
    updated_at: datetime


# Writing


class OkrItemIn(BaseModel):
    kind: Kind
    title: TitleText
    ref: Ref = None
    body_md: Body = None
    status: Status = "active"
    owner: Owner = None
    period: Period = None
    due: Due = None
    baseline: Text = None
    target: Text = Field(default=None, description="a key result's target, such as `30 % of searches answered`")
    parents: list[str] = Field(default=[], max_length=MAX_PARENTS, description="codes or refs of its parents")


class OkrItemPatch(BaseModel):
    """What to change of an item: a field left out stays, null (or an empty string) clears one of CLEARABLE, and
    ``parents`` replaces the parents. An item an import wrote refuses every field (409): its source owns them."""

    title: TitleText | None = None
    ref: Ref = None
    body_md: Body = None
    status: Status | None = None
    owner: Owner = None
    period: Period = None
    due: Due = None
    baseline: Text = None
    target: Text = None
    parents: list[str] | None = Field(default=None, max_length=MAX_PARENTS, description="codes or refs")


class OkrLinkIn(BaseModel):
    kind: TargetKind = Field(description="a deliverable's task, use_case or plan; a key result's goal")
    target: str = Field(min_length=1, max_length=MAX_TARGET_CHARS)


class OkrLinkMade(BaseModel):
    made: bool = Field(description="false: the item linked the target already")
    item: str = Field(description="the item's code")
    link: OkrLink


class OkrUnlinked(BaseModel):
    deleted: bool
    item: str
    link: OkrLink = Field(description="the link as it was")


# Import


class OkrImportItem(BaseModel):
    ref: str = Field(pattern=REF)
    kind: Kind
    title: TitleText
    body_md: Body = None
    status: Status = "active"
    owner: Owner = None
    period: Period = None
    due: Due = None
    baseline: Text = None
    target: Text = None
    parents: list[str] = Field(default=[], max_length=MAX_PARENTS, description="refs in the bundle or on the hub")
    source_url: str | None = Field(default=None, max_length=MAX_URL_CHARS)
    source_rev: str | None = Field(default=None, max_length=MAX_REV_CHARS)


class OkrImportLink(BaseModel):
    item: str = Field(min_length=1, max_length=200, description="the item's ref (or code)")
    kind: TargetKind
    target: str = Field(min_length=1, max_length=MAX_TARGET_CHARS)


class OkrImportIn(BaseModel):
    """A bundle of a source: its items, upserted by ref, and their links, added. ``file`` is the same bundle as the
    text of a JSON file (the command line sends it so); ``dry_run`` and ``prune`` given beside it win when true."""

    source: str | None = Field(default=None, pattern=SOURCE, description="the source's name; required")
    dry_run: bool = False
    prune: bool = Field(default=False, description="archive the items of the source the bundle no longer lists")
    items: list[OkrImportItem] = Field(default=[], max_length=MAX_IMPORT_ITEMS)
    links: list[OkrImportLink] = Field(default=[], max_length=MAX_IMPORT_LINKS)
    file: str | None = Field(default=None, description="the bundle as JSON text, in place of the fields above")


class OkrImportedItem(BaseModel):
    ref: str
    code: str = Field(description="the code it has, or takes once the import is written")
    kind: str
    fields: list[str] = Field(default=[], description="updated: what changed")
    archived: bool = Field(default=False, description="missing: archived by prune")


class OkrImportedLink(BaseModel):
    item: str
    kind: str
    target: str
    result: str = Field(description="added, exists, not_found or refused")
    detail: str | None = None
    id: int | None = Field(default=None, description="the link's id once written")


class OkrImported(BaseModel):
    source: str
    dry_run: bool = Field(description="true: nothing was written, and this is what the import would do")
    prune: bool
    created: list[OkrImportedItem]
    updated: list[OkrImportedItem]
    unchanged: list[OkrImportedItem]
    missing: list[OkrImportedItem] = Field(description="the source's items the bundle no longer lists")
    links: list[OkrImportedLink]
