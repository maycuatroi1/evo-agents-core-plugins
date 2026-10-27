"""What the hub holds of the targets okr links to, read through the core plugin API alone: the tasks of the plugin tasks
(``read_tasks``, with their status groups and prefix from its config, ``read_task_blockers`` and the open decisions of
their runs), the use cases of the plugin srs (``read_srs_items``, ``read_srs_versions``, and ``read_task_srs_items``
for the tasks that link each), the plans (``read_plans``, ``read_plan_steps``) and the goals (``read_goals``) with the
latest value of their signal (``read_signals``). okr owns no table of these and imports neither plugin.

``catalog`` reads what a target is checked against when a link is made, and ``facts`` what the roll-up needs of the
targets the links name, keyed by the target as the link holds it. A task, a plan, a use case's document and a signal
carry a label, and the reader sees them through the sink X-Evo-Sink names, else the project's hub sink
(``hub.read_visibility``): what the reader may not see still counts in the figures, without its title.

A goal's state compares the latest value of its metric's key (of its tenant, when the metric names one) that the
reader may see with the metric's target: met, not_met, no_signal without a value, no_metric for a goal without a
metric. It does not sum values over a window as the Loop's measure does.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from sqlalchemy.ext.asyncio import AsyncConnection

from evo_agents.hub.server import core_plugin_api as hub
from evo_core_plugins.okr import rules, store
from evo_core_plugins.okr.rules import Facts, GoalFact, Link, PlanFact, TaskFact, UseCaseFact

TASKS, SRS = "tasks", "srs"
DEFAULT_PREFIX = "T"
DEFAULT_GROUPS = {  # the statuses of the plugin tasks when its config names none
    "backlog": "todo",
    "todo": "todo",
    "in_progress": "doing",
    "in_review": "review",
    "done": "done",
    "cancelled": "cancelled",
}
MAX_TASKS = 5000  # the most rows a read of the hub returns
USE_CASE = "use_case"


@dataclass(frozen=True)
class Catalog:
    """The targets of the project a link may name, as the hub holds them now."""

    project: str
    prefix: str
    groups: dict[str, str]
    tasks: dict[int, hub.TaskRef]  # by number
    use_cases: tuple[hub.SrsItemRef, ...]  # every item of the project's SRS documents
    plans: dict[str, hub.PlanRef]  # by slug
    goals: tuple[hub.GoalRef, ...]

    def task(self, target: str, *, strict: bool = True) -> hub.TaskRef | None:
        """The task ``<prefix>-<n>`` (or ``<n>``) names; not ``strict``, under any prefix, as a link holds it."""
        number = rules.task_number(target, self.prefix) if strict else rules.any_task_number(target)
        return None if number is None else self.tasks.get(number)

    def use_case(self, target: str) -> hub.SrsItemRef | None:
        """The SRS item a use case's target names, ``<document>:<code>`` or a code alone (unique in the project), of
        any kind; None when there is none."""
        slug, code = rules.use_case_parts(target)
        key = rules.code_key(code)
        found = [
            item
            for item in self.use_cases
            if item.code and rules.code_key(item.code) == key and (slug is None or item.document == slug)
        ]
        return found[0] if len(found) == 1 else None

    def goal(self, target: str) -> hub.GoalRef | None:
        text = target.strip()
        return next((g for g in self.goals if g.code == text.upper() or (g.alias and g.alias == text.lower())), None)

    def resolve(self, kind: str, target: str) -> str:
        """The target as a link holds it, once the hub holds it in the project: ``<prefix>-<n>`` for a task,
        ``<document>:<code>`` for a use case, the slug of a plan, ``G-<n>`` for a goal. Refused 404 otherwise, 422 for
        an SRS item that is no use case."""
        if kind == "task":
            found = self.task(target)
            if found is not None:
                return f"{self.prefix}-{found.number}"
            raise hub.Refused(404, f"project {self.project} has no task {target}")
        if kind == USE_CASE:
            item = self.use_case(target)
            if item is None:
                raise hub.Refused(404, f"project {self.project} has no use case {target} in its SRS documents")
            if item.kind != USE_CASE:
                raise hub.Refused(422, f"{target} is an SRS item of kind {item.kind}, not a use case")
            return rules.use_case_target(item.document, item.code or "")
        if kind == "plan":
            if target in self.plans:
                return target
            raise hub.Refused(404, f"project {self.project} has no plan {target}")
        if kind == "goal":
            goal = self.goal(target)
            if goal is not None:
                return goal.code
            raise hub.Refused(404, f"project {self.project} has no goal {target}")
        raise hub.Refused(422, f"a link's kind is one of task, use_case, plan, goal, not {kind!r}")


async def catalog(conn: AsyncConnection, project: str) -> Catalog:
    """The targets of ``project``: its tasks, SRS items, plans and goals."""
    plugin = store.handle()
    tasks_config = await hub.enabled_plugin_config(conn, plugin, project, TASKS)
    values = dict(tasks_config.values) if tasks_config is not None else {}
    statuses = values.get("statuses")
    groups = {s["key"]: s["group"] for s in statuses} if statuses else dict(DEFAULT_GROUPS)
    tasks = {task.number: task for task in await hub.read_tasks(conn, plugin, project, limit=MAX_TASKS)}
    plans = {plan.plan_id: plan for plan in await hub.read_plans(conn, plugin, project)}
    return Catalog(
        project,
        values.get("prefix") or DEFAULT_PREFIX,
        groups,
        tasks,
        await hub.read_srs_items(conn, plugin, project),
        plans,
        await hub.read_goals(conn, plugin, project),
    )


async def visibility(conn: AsyncConnection, access: hub.ProjectRef, sink: str | None) -> hub.Visibility:
    """How the caller sees the labelled data of the project, through ``sink``, else the project's hub sink."""
    return await hub.read_visibility(conn, store.handle(), access.name, max_level=access.max_level, sink=sink)


async def _tasks(conn: AsyncConnection, found: Catalog, sees: hub.Visibility, targets: set[str]) -> dict[str, TaskFact]:
    plugin = store.handle()
    chosen = {target: task for target in targets if (task := found.task(target, strict=False)) is not None}
    ids = sorted({task.id for task in chosen.values()})
    blocked = {row.task_id for row in await hub.read_task_blockers(conn, plugin, found.project, ids)}
    blocked |= {
        row.task_id for row in await hub.read_task_decisions(conn, plugin, found.project, ids, states=("open",))
    }
    facts = {}
    for target, task in chosen.items():
        visible = sees.visible(task.label)
        facts[target] = TaskFact(
            ref=f"{found.prefix}-{task.number}",
            title=task.title if visible else None,
            status=task.status if visible else None,
            group=found.groups.get(task.status, "todo"),
            due_on=task.due_on,
            blocked=task.id in blocked,
            visible=visible,
        )
    return facts


async def _use_cases(
    conn: AsyncConnection, found: Catalog, sees: hub.Visibility, targets: set[str]
) -> dict[str, UseCaseFact]:
    plugin = store.handle()
    chosen = {
        target: item for target in targets if (item := found.use_case(target)) is not None and item.kind == USE_CASE
    }
    if not chosen:
        return {}
    versions = {}
    for document in sorted({item.document for item in chosen.values()}):
        versions[document] = {
            v.number: v.state for v in await hub.read_srs_versions(conn, plugin, found.project, document)
        }
    tasks = {task.id: task for task in found.tasks.values()}
    linking: dict[int, list[hub.TaskRef]] = {}
    titles: dict[int, tuple[str | None, bool]] = {}
    for row in await hub.read_task_srs_items(conn, plugin, found.project, sorted(tasks)):
        if row.task_id in tasks:
            linking.setdefault(row.item_id, []).append(tasks[row.task_id])
        titles[row.item_id] = (row.title, sees.visible(row.label))
    facts = {}
    for target, item in chosen.items():
        counted = [t for t in linking.get(item.id, []) if found.groups.get(t.status, "todo") != rules.TASK_CANCELLED]
        title, visible = titles.get(item.id, (None, True))
        facts[target] = UseCaseFact(
            ref=rules.use_case_target(item.document, item.code or ""),
            title=title if visible else None,
            status=rules.use_case_status(item.created_in, item.retired_in, versions[item.document]),
            tasks_done=sum(found.groups.get(t.status, "todo") == rules.TASK_DONE for t in counted),
            tasks_total=len(counted),
            visible=visible,
        )
    return facts


async def _plans(conn: AsyncConnection, found: Catalog, sees: hub.Visibility, targets: set[str]) -> dict[str, PlanFact]:
    facts = {}
    for target in sorted(targets):
        plan = found.plans.get(target)
        if plan is None:
            continue
        steps = await hub.read_plan_steps(conn, store.handle(), found.project, target)
        counted = [step for step in steps if step.status != rules.STEP_DESCOPED]
        visible = sees.visible(plan.label)
        facts[target] = PlanFact(
            ref=target,
            title=plan.title if visible else None,
            status=plan.status,
            steps_done=sum(step.status == rules.STEP_DONE for step in counted),
            steps_total=len(counted),
            steps_blocked=sum(step.status == rules.STEP_BLOCKED for step in counted),
            visible=visible,
        )
    return facts


async def _goals(conn: AsyncConnection, found: Catalog, sees: hub.Visibility, targets: set[str]) -> dict[str, GoalFact]:
    facts = {}
    for target in sorted(targets):
        goal = found.goal(target)
        if goal is None:
            continue
        metric = dict(goal.metric) if goal.metric else None
        latest = None
        if metric and metric.get("key"):
            values = await hub.read_signals(conn, store.handle(), found.project, str(metric["key"]))
            tenant = metric.get("tenant")
            latest = next(
                (
                    value
                    for value in values
                    if value.value is not None and (not tenant or value.tenant == tenant) and sees.visible(value.label)
                ),
                None,
            )
        facts[target] = GoalFact(
            ref=goal.code,
            statement=goal.statement,
            status=goal.status,
            metric_text=goal.metric_text,
            value=None if latest is None else latest.value,
            measured_at=None if latest is None else latest.measured_at,
            state=rules.goal_state(metric, None if latest is None else latest.value),
        )
    return facts


async def facts(
    conn: AsyncConnection, found: Catalog, sees: hub.Visibility, links: Iterable[Link], today: date
) -> Facts:
    """What the hub holds of each target ``links`` name, keyed by the target as the link holds it."""
    wanted: dict[str, set[str]] = {kind: set() for kind in ("task", USE_CASE, "plan", "goal")}
    for link in links:
        wanted.setdefault(link.kind, set()).add(link.target)
    return Facts(
        today=today,
        tasks=await _tasks(conn, found, sees, wanted["task"]) if wanted["task"] else {},
        use_cases=await _use_cases(conn, found, sees, wanted[USE_CASE]),
        plans=await _plans(conn, found, sees, wanted["plan"]),
        goals=await _goals(conn, found, sees, wanted["goal"]),
    )


__all__ = ["Catalog", "catalog", "facts", "visibility"]
