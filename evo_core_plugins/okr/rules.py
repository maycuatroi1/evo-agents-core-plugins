"""The rules of okr as pure functions, standard library only: an item's code, the shapes of the tree, the encoding of
a link's target, the status of a use case and of a goal, and the roll-up of the tree with its gaps. Nothing here reads
or writes; ``store`` and ``facts`` give what these compute from.

The tree is business line -> objective -> key result -> deliverable: an objective under at most one business line, a
key result under exactly one objective, a deliverable under one key result or more, a business line under nothing.
Each kind sits under the kind above it only, so no edge closes a cycle; ``closes_cycle`` checks it anyway.

The roll-up (``rollup``) writes nothing and leaves dropped and archived items out:

- a deliverable's progress is the mean of what each of its links has done: a task 1 when its status is in the group
  done, else 0 (a cancelled one counts for nothing); a use case the share of done tasks among the tasks that link it,
  0 with none (a retired one counts for nothing); a plan its steps done over its steps that are not descoped. With
  nothing to count, a deliverable whose status is done is 1, any other has no progress;
- a key result's progress is the mean of its deliverables', and it is met when its goal is (``goal_state``);
- an objective's and a business line's progress is the mean over the distinct deliverables below them, with the key
  results met among those below.
"""

from __future__ import annotations

import operator
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, datetime

from evo_core_plugins.okr.tables import (
    BUSINESS_LINE,
    CLOSED,
    DELIVERABLE,
    KEY_RESULT,
    KINDS,
    OBJECTIVE,
    PREFIXES,
    TARGETS,
)

KIND_OF_PREFIX = {prefix: kind for kind, prefix in PREFIXES.items()}
CODE_FORM = re.compile(r"(BL|O|KR|D)-([1-9][0-9]{0,8})", re.IGNORECASE)
PARENT_KIND = {OBJECTIVE: BUSINESS_LINE, KEY_RESULT: OBJECTIVE, DELIVERABLE: KEY_RESULT}
PARENTS = {BUSINESS_LINE: (0, 0), OBJECTIVE: (0, 1), KEY_RESULT: (1, 1), DELIVERABLE: (1, None)}  # (least, most)
WORDS = {
    BUSINESS_LINE: "a business line",
    OBJECTIVE: "an objective",
    KEY_RESULT: "a key result",
    DELIVERABLE: "a deliverable",
}
TASK_DONE, TASK_CANCELLED = "done", "cancelled"  # the groups of the plugin tasks' statuses that close a task
STEP_DONE, STEP_DESCOPED, STEP_BLOCKED = "done", "descoped", "blocked"  # of a plan's step
APPROVED_VERSIONS = ("approved", "superseded")  # a version of an SRS document that was approved
COMPARE = {">=": operator.ge, ">": operator.gt, "<=": operator.le, "<": operator.lt}  # a goal's metric comparator
GOAL_STATES = ("met", "not_met", "no_signal", "no_metric")
USE_CASE_STATES = ("draft", "in_review", "approved", "retired")
GAP_KINDS = ("no_link", "no_goal", "no_kr", "late", "gone")


# Codes


def code(kind: str, number: int) -> str:
    """The code of item ``number`` of ``kind``: BL-1, O-2, KR-3, D-4."""
    return f"{PREFIXES[kind]}-{number}"


def parse_code(text: str) -> tuple[str, int] | None:
    """(kind, number) of a code in any case (``kr-3``), None for anything else."""
    found = CODE_FORM.fullmatch(text.strip())
    return (KIND_OF_PREFIX[found[1].upper()], int(found[2])) if found else None


# The items as the store gives them


@dataclass(frozen=True)
class Item:
    id: int
    kind: str
    number: int
    ref: str | None
    title: str
    body_md: str | None
    status: str
    owner: str | None
    period: str | None
    due: date | None
    baseline: str | None
    target: str | None
    source: str | None
    source_url: str | None
    source_rev: str | None
    created_by: str | None
    updated_by: str | None
    created_at: datetime
    updated_at: datetime

    @property
    def code(self) -> str:
        return code(self.kind, self.number)

    @property
    def open(self) -> bool:
        return self.status not in CLOSED


@dataclass(frozen=True)
class Link:
    id: int
    item_id: int
    kind: str
    target: str
    created_by: str | None
    created_at: datetime


# Shapes


def shape_problem(kind: str, parent_kinds: list[str]) -> str | None:
    """What is wrong with an item of ``kind`` under parents of ``parent_kinds``; None when the shape holds."""
    least, most = PARENTS[kind]
    wanted = PARENT_KIND.get(kind)
    if wanted is None:
        return None if not parent_kinds else f"{WORDS[kind]} is under nothing"
    wrong = sorted({found for found in parent_kinds if found != wanted})
    if wrong:
        named = ", ".join(WORDS[found] for found in wrong)
        return f"{WORDS[kind]} is under {WORDS[wanted]}, not {named}"
    count = len(parent_kinds)
    if count < least or (most is not None and count > most):
        if (least, most) == (1, 1):
            need = f"exactly one {wanted.replace('_', ' ')}"
        elif most is None:
            need = f"at least one {wanted.replace('_', ' ')}"
        else:
            need = f"at most one {wanted.replace('_', ' ')}"
        return f"{WORDS[kind]} is under {need}; {count} given"
    return None


def closes_cycle(child: int, parents: Iterable[int], edges: Mapping[int, Iterable[int]]) -> bool:
    """Whether putting ``child`` under ``parents`` closes a cycle, ``edges`` mapping each item to its parents now:
    whether ``child`` is one of the parents or above one of them."""
    seen: set[int] = set()
    stack = list(parents)
    while stack:
        at = stack.pop()
        if at == child:
            return True
        if at in seen:
            continue
        seen.add(at)
        stack.extend(edges.get(at, ()))
    return False


def target_kinds(kind: str) -> tuple[str, ...]:
    """The kinds of target an item of ``kind`` links to: none for a business line or an objective."""
    return TARGETS.get(kind, ())


# Targets


def task_number(text: str, prefix: str) -> int | None:
    """The number a task's code names, ``<prefix>-<n>`` in any case or ``<n>`` alone; None for anything else."""
    found = re.fullmatch(rf"(?:{re.escape(prefix)}-)?([1-9][0-9]{{0,8}})", text.strip(), re.IGNORECASE)
    return int(found[1]) if found else None


def any_task_number(text: str) -> int | None:
    """The number of a task's code under any prefix, ``<prefix>-<n>``: a link made before the plugin tasks took
    another prefix still finds its task."""
    found = re.fullmatch(r"(?:[A-Za-z][A-Za-z0-9]*-)?([1-9][0-9]{0,8})", text.strip())
    return int(found[1]) if found else None


def tidy(text: str) -> str:
    """Whitespace runs as one space, as the plugin srs shows a code."""
    return " ".join(text.split())


def code_key(text: str) -> str:
    """The form two codes of the plugin srs compare in: whitespace runs as one space, case folded."""
    return tidy(text).casefold()


def use_case_parts(text: str) -> tuple[str | None, str]:
    """(the document's slug or None, the code) of a use case's target, ``<document>:<code>`` or a code alone."""
    slug, colon, rest = text.strip().partition(":")
    return (slug.strip(), tidy(rest)) if colon else (None, tidy(slug))


def use_case_target(document: str, item_code: str) -> str:
    """How a link names a use case: ``<document slug>:<code>``, the code as the document shows it."""
    return f"{document}:{tidy(item_code)}"


def use_case_status(created_in: int | None, retired_in: int | None, versions: Mapping[int, str]) -> str:
    """retired once a version that drops it was approved; approved when a version that holds it was; in_review while
    one is in review; draft otherwise. ``versions`` maps the document's version numbers to their states."""
    if retired_in is not None and versions.get(retired_in) in APPROVED_VERSIONS:
        return "retired"
    holding = [
        state
        for number, state in versions.items()
        if (created_in is None or number >= created_in) and (retired_in is None or number < retired_in)
    ]
    if any(state in APPROVED_VERSIONS for state in holding):
        return "approved"
    return "in_review" if "in_review" in holding else "draft"


def goal_state(metric: Mapping | None, value: float | None) -> str:
    """met or not_met when the goal's metric compares the value with its target; no_signal without a value;
    no_metric for a goal without a metric, or one whose comparator or target cannot compare."""
    if not metric or metric.get("comparator") not in COMPARE or not isinstance(metric.get("target"), int | float):
        return "no_metric"
    if value is None:
        return "no_signal"
    return "met" if COMPARE[metric["comparator"]](value, metric["target"]) else "not_met"


# What the hub holds of the targets


@dataclass(frozen=True)
class TaskFact:
    ref: str
    title: str | None  # None when the reader may not see the task
    status: str | None
    group: str
    due_on: date | None
    blocked: bool
    visible: bool


@dataclass(frozen=True)
class UseCaseFact:
    ref: str  # <document>:<code>
    title: str | None
    status: str  # USE_CASE_STATES
    tasks_done: int
    tasks_total: int  # the tasks that link it, cancelled ones left out
    visible: bool


@dataclass(frozen=True)
class PlanFact:
    ref: str  # the slug
    title: str | None
    status: str | None
    steps_done: int
    steps_total: int  # descoped steps left out
    steps_blocked: int
    visible: bool


@dataclass(frozen=True)
class GoalFact:
    ref: str  # G-<n>
    statement: str
    status: str  # active, paused or closed
    metric_text: str
    value: float | None
    measured_at: datetime | None
    state: str  # GOAL_STATES


@dataclass(frozen=True)
class Facts:
    """What the hub holds of the targets the links name, read once for the roll-up."""

    today: date
    tasks: Mapping[str, TaskFact] = field(default_factory=dict)
    use_cases: Mapping[str, UseCaseFact] = field(default_factory=dict)
    plans: Mapping[str, PlanFact] = field(default_factory=dict)
    goals: Mapping[str, GoalFact] = field(default_factory=dict)

    def of(self, kind: str, target: str):
        """The fact of the target a link names; None when the hub no longer holds it."""
        found = {"task": self.tasks, "use_case": self.use_cases, "plan": self.plans, "goal": self.goals}.get(kind, {})
        return found.get(target)


def late_task(task: TaskFact, today: date) -> bool:
    return task.due_on is not None and task.due_on < today and task.group not in (TASK_DONE, TASK_CANCELLED)


def done_share(link: Link, facts: Facts) -> float | None:
    """What a deliverable's link has done, 0 to 1; None when it counts for nothing (see the module)."""
    found = facts.of(link.kind, link.target)
    if found is None:
        return None
    if isinstance(found, TaskFact):
        return None if found.group == TASK_CANCELLED else float(found.group == TASK_DONE)
    if isinstance(found, UseCaseFact):
        if found.status == "retired":
            return None
        return found.tasks_done / found.tasks_total if found.tasks_total else 0.0
    if isinstance(found, PlanFact):
        return found.steps_done / found.steps_total if found.steps_total else None
    return None


# The roll-up


@dataclass(frozen=True)
class Rollup:
    progress: float | None  # 0 to 1
    deliverables: int  # the distinct deliverables it counts, itself for a deliverable
    tasks_done: int
    tasks_total: int  # cancelled tasks left out
    tasks_late: int
    tasks_blocked: int
    krs_met: int
    krs_total: int
    goal: GoalFact | None = None  # a key result's


@dataclass(frozen=True)
class Gap:
    kind: str  # GAP_KINDS
    item: str  # the item's code
    title: str
    detail: str


class Tree:
    """The items of a project with their edges and links, and what is computed from them."""

    def __init__(self, items: Iterable[Item], edges: Iterable[tuple[int, int]], links: Iterable[Link]):
        self.items = {item.id: item for item in items}
        self.parents: dict[int, list[int]] = {item_id: [] for item_id in self.items}
        self.children: dict[int, list[int]] = {item_id: [] for item_id in self.items}
        for child, parent in edges:
            if child in self.items and parent in self.items:
                self.parents[child].append(parent)
                self.children[parent].append(child)
        order = {item_id: (KINDS.index(item.kind), item.number) for item_id, item in self.items.items()}
        for ids in (*self.parents.values(), *self.children.values()):
            ids.sort(key=order.__getitem__)
        self.links: dict[int, list[Link]] = {item_id: [] for item_id in self.items}
        for link in links:
            if link.item_id in self.links:
                self.links[link.item_id].append(link)

    def ordered(self, ids: Iterable[int] | None = None) -> list[Item]:
        chosen = self.items.values() if ids is None else (self.items[i] for i in ids)
        return sorted(chosen, key=lambda item: (KINDS.index(item.kind), item.number))

    def roots(self) -> list[Item]:
        """The items under nothing: the business lines, and the objectives without one (and any item a change left
        without its parent)."""
        return [item for item in self.ordered() if not self.parents[item.id]]

    def open_children(self, item_id: int) -> list[Item]:
        return [self.items[child] for child in self.children[item_id] if self.items[child].open]

    def deliverables_below(self, item_id: int) -> list[Item]:
        """The open deliverables at or below an open item, each once, through open items only."""
        found: dict[int, Item] = {}
        stack = [item_id] if self.items[item_id].open else []
        while stack:
            item = self.items[stack.pop()]
            if item.kind == DELIVERABLE:
                found[item.id] = item
                continue
            stack.extend(child.id for child in self.open_children(item.id))
        return self.ordered(found)

    def key_results_below(self, item_id: int) -> list[Item]:
        item = self.items[item_id]
        if not item.open:
            return []
        if item.kind == KEY_RESULT:
            return [item]
        return [kr for child in self.open_children(item_id) for kr in self.key_results_below(child.id)]

    def goal_of(self, item_id: int, facts: Facts) -> GoalFact | None:
        for link in self.links[item_id]:
            if link.kind == "goal":
                return facts.goals.get(link.target)
        return None

    def progress_of(self, item_id: int, facts: Facts) -> float | None:
        """A deliverable's progress (see the module)."""
        shares = [share for link in self.links[item_id] if (share := done_share(link, facts)) is not None]
        if shares:
            return sum(shares) / len(shares)
        return 1.0 if self.items[item_id].status == "done" else None

    def rollup(self, item_id: int, facts: Facts) -> Rollup:
        """The roll-up of an item, computed on read."""
        item = self.items[item_id]
        below = self.deliverables_below(item_id)
        shown = [p for d in below if (p := self.progress_of(d.id, facts)) is not None]
        tasks: dict[str, TaskFact] = {}
        for deliverable in below:
            for link in self.links[deliverable.id]:
                found = facts.tasks.get(link.target) if link.kind == "task" else None
                if found is not None and found.group != TASK_CANCELLED:
                    tasks[found.ref] = found
        krs = self.key_results_below(item_id)
        met = [kr for kr in krs if (goal := self.goal_of(kr.id, facts)) is not None and goal.state == "met"]
        return Rollup(
            progress=sum(shown) / len(shown) if shown else None,
            deliverables=len(below),
            tasks_done=sum(task.group == TASK_DONE for task in tasks.values()),
            tasks_total=len(tasks),
            tasks_late=sum(late_task(task, facts.today) for task in tasks.values()),
            tasks_blocked=sum(task.blocked and task.group != TASK_DONE for task in tasks.values()),
            krs_met=len(met),
            krs_total=len(krs),
            goal=self.goal_of(item_id, facts) if item.kind == KEY_RESULT else None,
        )

    def gaps(self, facts: Facts, ids: Iterable[int] | None = None) -> list[Gap]:
        """What the tree lacks, of the items ``ids`` (all when None): an active deliverable with no link, an active
        key result with no goal, an objective in draft or active with no key result, an open item past its due
        date and not done, and a link of an open item whose target the hub no longer holds."""
        found = []
        for item in self.ordered(ids):
            links = self.links[item.id]
            if item.kind == DELIVERABLE and item.status == "active" and not links:
                found.append(Gap("no_link", item.code, item.title, "links no task, use case or plan"))
            if item.kind == KEY_RESULT and item.status == "active" and not any(link.kind == "goal" for link in links):
                found.append(Gap("no_goal", item.code, item.title, "links no goal"))
            if item.kind == OBJECTIVE and item.status in ("draft", "active"):
                if not any(child.kind == KEY_RESULT for child in self.open_children(item.id)):
                    found.append(Gap("no_kr", item.code, item.title, "has no key result"))
            if item.open and item.status != "done" and item.due is not None and item.due < facts.today:
                found.append(Gap("late", item.code, item.title, f"due {item.due.isoformat()}, not done"))
            if item.open:
                for link in links:
                    if facts.of(link.kind, link.target) is None:
                        found.append(Gap("gone", item.code, item.title, f"links {link.kind} {link.target}, gone"))
        return found


__all__ = [
    "Facts",
    "Gap",
    "GoalFact",
    "Item",
    "Link",
    "PlanFact",
    "Rollup",
    "TaskFact",
    "Tree",
    "UseCaseFact",
    "closes_cycle",
    "code",
    "goal_state",
    "parse_code",
    "shape_problem",
    "use_case_status",
]
