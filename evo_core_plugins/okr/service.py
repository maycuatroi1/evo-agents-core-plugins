"""What the routes (``server``) and the MCP tools (``tools``) of okr do, for a caller whose access to the project is
known (``Viewer``): read the tree with its roll-up and gaps, show one item, add and change an item, link and unlink
it, and import a source's bundle.

A write takes the project's tree (``store.lock_tree``) for its transaction, so two writers never take the same code
or check a shape against a tree the other is changing. Every answer is read again after the write, with the roll-up
the hub's data gives now (``facts``, ``rules``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncConnection

from evo_agents.hub.server import core_plugin_api as hub
from evo_core_plugins.okr import facts as hub_facts
from evo_core_plugins.okr import rules, store
from evo_core_plugins.okr.models import (
    OkrGap,
    OkrGoal,
    OkrImported,
    OkrImportedItem,
    OkrImportedLink,
    OkrImportIn,
    OkrItem,
    OkrItemIn,
    OkrItemPatch,
    OkrItemRef,
    OkrLink,
    OkrLinkIn,
    OkrLinkMade,
    OkrNode,
    OkrRollup,
    OkrTree,
    OkrUnlinked,
)
from evo_core_plugins.okr.tables import BUSINESS_LINE, KINDS, STATUSES

IMPORT_ACTION = "okr.import"  # the audit's action of an import that wrote
MAX_PROBLEMS = 20  # the problems of a bundle a refusal names
IMPORT_FIELDS = (*store.FIELDS, *store.SOURCE_FIELDS)  # what an import writes of an item


@dataclass(frozen=True)
class Viewer:
    """A caller in a project: their session, their access and the sink they read through."""

    session: hub.Session
    access: hub.ProjectRef
    sink: str | None


async def viewer(conn: AsyncConnection, session: hub.Session, project: str, sink: str | None) -> Viewer:
    """The caller's access to ``project``, which enables the plugin; 403 without a grant on it."""
    access = await hub.project_access(conn, session, project)
    store.reader(access)
    return Viewer(session, access, sink)


def today() -> date:
    return datetime.now(UTC).date()


def said(exc: ValidationError) -> str:
    """The first problems pydantic found, one line."""
    return "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:5])


# Reading


@dataclass(frozen=True)
class State:
    tree: rules.Tree
    facts: rules.Facts


async def _tree(conn: AsyncConnection, who: Viewer) -> rules.Tree:
    project_id = who.access.id
    found = await store.items(conn, project_id)
    return rules.Tree(found, await store.edges(conn, project_id), await store.links(conn, project_id))


async def _state(conn: AsyncConnection, who: Viewer) -> State:
    tree = await _tree(conn, who)
    found = await hub_facts.catalog(conn, who.access.name)
    sees = await hub_facts.visibility(conn, who.access, who.sink)
    every = [link for links in tree.links.values() for link in links]
    return State(tree, await hub_facts.facts(conn, found, sees, every, today()))


def find(tree: rules.Tree, text: str) -> rules.Item | None:
    """The item a code names (in any case), else the item whose ref it is: a code wins over a ref that looks like
    one."""
    parsed = rules.parse_code(text)
    if parsed is not None:
        for item in tree.items.values():
            if (item.kind, item.number) == parsed:
                return item
    return next((item for item in tree.items.values() if item.ref == text.strip()), None)


def _missing(who: Viewer, text: str) -> hub.Refused:
    return hub.Refused(404, f"no item {text} in project {who.access.name}: see `evo-agents hub okr tree`")


def _item(who: Viewer, tree: rules.Tree, text: str) -> rules.Item:
    found = find(tree, text)
    if found is None:
        raise _missing(who, text)
    return found


def _goal(found: rules.GoalFact | None) -> OkrGoal | None:
    if found is None:
        return None
    return OkrGoal(
        code=found.ref,
        statement=found.statement,
        status=found.status,
        metric=found.metric_text,
        value=found.value,
        measured_at=found.measured_at,
        state=found.state,
    )


def _rollup(found: rules.Rollup) -> OkrRollup:
    return OkrRollup(
        progress=None if found.progress is None else round(found.progress, 4),
        deliverables=found.deliverables,
        tasks_done=found.tasks_done,
        tasks_total=found.tasks_total,
        tasks_late=found.tasks_late,
        tasks_blocked=found.tasks_blocked,
        krs_met=found.krs_met,
        krs_total=found.krs_total,
        goal=_goal(found.goal),
    )


def _link(link: rules.Link, facts: rules.Facts) -> OkrLink:
    """A link with what the hub holds of its target now."""
    base = {
        "id": link.id,
        "kind": link.kind,
        "target": link.target,
        "created_by": link.created_by,
        "created_at": link.created_at,
    }
    found = facts.of(link.kind, link.target)
    if found is None:
        return OkrLink(**base, gone=True, visible=True)
    share = rules.done_share(link, facts)
    if isinstance(found, rules.TaskFact):
        closed = found.group == rules.TASK_CANCELLED
        return OkrLink(
            **base,
            gone=False,
            visible=found.visible,
            title=found.title,
            status=found.status,
            done=int(found.group == rules.TASK_DONE),
            total=0 if closed else 1,
            share=share,
            late=rules.late_task(found, facts.today),
            blocked=found.blocked and found.group != rules.TASK_DONE,
        )
    if isinstance(found, rules.UseCaseFact):
        return OkrLink(
            **base,
            gone=False,
            visible=found.visible,
            title=found.title,
            status=found.status,
            done=found.tasks_done,
            total=found.tasks_total,
            share=share,
        )
    if isinstance(found, rules.PlanFact):
        return OkrLink(
            **base,
            gone=False,
            visible=found.visible,
            title=found.title,
            status=found.status,
            done=found.steps_done,
            total=found.steps_total,
            share=share,
            blocked=found.steps_blocked > 0,
        )
    return OkrLink(**base, gone=False, visible=True, title=found.statement, status=found.state)


def _gap(found: rules.Gap) -> OkrGap:
    return OkrGap(kind=found.kind, item=found.item, title=found.title, detail=found.detail)


def _ref(item: rules.Item) -> OkrItemRef:
    return OkrItemRef(code=item.code, kind=item.kind, title=item.title, status=item.status)


def _detail(state: State, item: rules.Item) -> OkrItem:
    tree, facts = state.tree, state.facts
    return OkrItem(
        code=item.code,
        ref=item.ref,
        kind=item.kind,
        title=item.title,
        body_md=item.body_md,
        status=item.status,
        owner=item.owner,
        period=item.period,
        due=item.due,
        baseline=item.baseline,
        target=item.target,
        source=item.source,
        source_url=item.source_url,
        source_rev=item.source_rev,
        parents=[_ref(parent) for parent in tree.ordered(tree.parents[item.id])],
        children=[_ref(child) for child in tree.ordered(tree.children[item.id])],
        links=[_link(link, facts) for link in tree.links[item.id]],
        rollup=_rollup(tree.rollup(item.id, facts)),
        gaps=[_gap(gap) for gap in tree.gaps(facts, [item.id])],
        created_by=item.created_by,
        created_at=item.created_at,
        updated_by=item.updated_by,
        updated_at=item.updated_at,
    )


async def tree_view(
    conn: AsyncConnection, who: Viewer, *, status: str | None = None, line: str | None = None
) -> OkrTree:
    """The tree from its roots, each item with its roll-up and links, and its gaps. ``status`` shows the items of
    that status and those above them; without it, every item but the archived ones. ``line`` shows one business
    line (its code or ref) alone. The roll-up counts the whole tree whatever the filters show."""
    if status is not None and status not in STATUSES:
        raise hub.Refused(422, f"a status is one of {', '.join(STATUSES)}")
    state = await _state(conn, who)
    tree, facts = state.tree, state.facts
    roots = tree.roots()
    if line:
        chosen = _item(who, tree, line)
        if chosen.kind != BUSINESS_LINE:
            raise hub.Refused(422, f"{line} is {rules.WORDS[chosen.kind]}, not a business line")
        roots = [chosen]

    def matches(item: rules.Item) -> bool:
        return item.status == status if status else item.status != "archived"

    kept: dict[int, bool] = {}

    def keeps(item_id: int) -> bool:
        if item_id not in kept:
            kept[item_id] = matches(tree.items[item_id]) or any(keeps(c) for c in tree.children[item_id])
        return kept[item_id]

    shown: set[int] = set()

    def node(item: rules.Item) -> OkrNode:
        shown.add(item.id)
        return OkrNode(
            code=item.code,
            ref=item.ref,
            kind=item.kind,
            title=item.title,
            status=item.status,
            owner=item.owner,
            period=item.period,
            due=item.due,
            baseline=item.baseline,
            target=item.target,
            source=item.source,
            rollup=_rollup(tree.rollup(item.id, facts)),
            links=[_link(link, facts) for link in tree.links[item.id]],
            children=[node(tree.items[child]) for child in tree.children[item.id] if keeps(child)],
        )

    nodes = [node(root) for root in roots if keeps(root.id)]
    counts = {kind: sum(tree.items[i].kind == kind for i in shown) for kind in KINDS}
    gaps = tree.gaps(facts, [i for i in shown if matches(tree.items[i])])
    return OkrTree(project=who.access.name, today=facts.today, counts=counts, roots=nodes, gaps=[_gap(g) for g in gaps])


async def show_item(conn: AsyncConnection, who: Viewer, text: str) -> OkrItem:
    """One item, by its code or ref, with its parents, children, links, roll-up and gaps."""
    state = await _state(conn, who)
    return _detail(state, _item(who, state.tree, text))


async def _shown(conn: AsyncConnection, who: Viewer, item_id: int) -> OkrItem:
    state = await _state(conn, who)
    return _detail(state, state.tree.items[item_id])


# Writing


def _parents(who: Viewer, tree: rules.Tree, given: list[str]) -> list[rules.Item]:
    found = []
    for text in dict.fromkeys(given):
        parent = find(tree, text)
        if parent is None:
            raise hub.Refused(422, f"no parent {text} in project {who.access.name}: name an item by its code or ref")
        found.append(parent)
    return found


def _shape(kind: str, parents: list[rules.Item], *, code: str | None = None) -> None:
    problem = rules.shape_problem(kind, [parent.kind for parent in parents])
    if problem is not None:
        raise hub.Refused(422, f"{code}: {problem}" if code else problem)


def _ref_taken(tree: rules.Tree, ref: str | None, item_id: int | None = None) -> None:
    holder = next((item for item in tree.items.values() if ref and item.ref == ref and item.id != item_id), None)
    if holder is not None:
        raise hub.Refused(409, f"ref {ref} is the ref of {holder.code} already")


async def add_item(conn: AsyncConnection, who: Viewer, body: OkrItemIn) -> OkrItem:
    """A new item under the parents ``body`` names, numbered after the last of its kind (writer)."""
    store.writer(who.access, "adding to the OKR tree")
    await store.lock_tree(conn, who.access.id)
    tree = await _tree(conn, who)
    _ref_taken(tree, body.ref)
    parents = _parents(who, tree, body.parents)
    _shape(body.kind, parents)
    number = (await store.next_numbers(conn, who.access.id))[body.kind]
    values = {name: getattr(body, name) for name in store.FIELDS}
    item_id = await store.add_item(conn, who.access.id, body.kind, number, values, who.session.user_id)
    await store.set_parents(conn, item_id, [parent.id for parent in parents])
    return await _shown(conn, who, item_id)


async def set_item(conn: AsyncConnection, who: Viewer, text: str, body: OkrItemPatch) -> OkrItem:
    """Change the fields ``body`` gives of an item and, with ``parents``, its parents (writer). 409 for an item a
    source wrote: those fields change through its import."""
    store.writer(who.access, "changing the OKR tree")
    await store.lock_tree(conn, who.access.id)
    tree = await _tree(conn, who)
    item = _item(who, tree, text)
    given = set(body.model_fields_set)
    if item.source and given:
        named = ", ".join(sorted(given))
        raise hub.Refused(
            409,
            f"{item.code} comes from source {item.source}: its {named} change there, through "
            "`evo-agents hub okr import`; its links stay editable here",
        )
    for name in ("title", "status"):
        if name in given and getattr(body, name) is None:
            raise hub.Refused(422, f"an item always has a {name}")
    values = {name: getattr(body, name) for name in store.FIELDS if name in given}
    if values.get("ref"):
        _ref_taken(tree, values["ref"], item.id)
    if "parents" in given:
        parents = _parents(who, tree, body.parents or [])
        _shape(item.kind, parents, code=item.code)
        ids = [parent.id for parent in parents]
        if rules.closes_cycle(item.id, ids, tree.parents):
            raise hub.Refused(422, f"{item.code} under {', '.join(p.code for p in parents)} closes a cycle")
        await store.set_parents(conn, item.id, ids)
    if given:
        await store.change_item(conn, item.id, values, who.session.user_id)
    return await _shown(conn, who, item.id)


async def link(conn: AsyncConnection, who: Viewer, text: str, body: OkrLinkIn) -> OkrLinkMade:
    """Link an item to the hub's target ``body`` names, once it is there (writer): 404 for a target the project lacks,
    422 for a kind the item does not link, 409 for a key result's second goal. ``made`` false when it was linked."""
    store.writer(who.access, "linking the OKR tree")
    await store.lock_tree(conn, who.access.id)
    tree = await _tree(conn, who)
    item = _item(who, tree, text)
    allowed = rules.target_kinds(item.kind)
    if body.kind not in allowed:
        links = ", ".join(allowed) or "nothing"
        raise hub.Refused(422, f"{item.code} is {rules.WORDS[item.kind]}, which links {links}, not a {body.kind}")
    target = (await hub_facts.catalog(conn, who.access.name)).resolve(body.kind, body.target)
    other = next((k for k in tree.links[item.id] if k.kind == "goal" and k.target != target), None)
    if body.kind == "goal" and other is not None:
        raise hub.Refused(409, f"{item.code} is measured by goal {other.target} already: unlink it first")
    link_id, made = await store.add_link(conn, item.id, body.kind, target, who.session.user_id)
    state = await _state(conn, who)
    written = next(k for k in state.tree.links[item.id] if k.id == link_id)
    return OkrLinkMade(made=made, item=item.code, link=_link(written, state.facts))


async def unlink(conn: AsyncConnection, who: Viewer, text: str, link_id: int) -> OkrUnlinked:
    """Take link ``link_id`` off an item (writer), an item a source wrote included; the link as it was."""
    store.writer(who.access, "unlinking the OKR tree")
    state = await _state(conn, who)
    item = _item(who, state.tree, text)
    found = next((k for k in state.tree.links[item.id] if k.id == link_id), None)
    if found is None:
        raise hub.Refused(404, f"{item.code} has no link {link_id}: see `evo-agents hub okr show {item.code}`")
    was = _link(found, state.facts)
    await store.delete_link(conn, item.id, link_id)
    return OkrUnlinked(deleted=True, item=item.code, link=was)


# Import


def bundle_of(body: OkrImportIn) -> OkrImportIn:
    """The bundle ``body`` carries, from its ``file`` when it has one; 422 when it does not read or names no source."""
    if body.file is not None:
        try:
            data = json.loads(body.file)
        except ValueError as exc:
            raise hub.Refused(422, f"the file is no JSON: {exc}") from None
        if not isinstance(data, dict):
            raise hub.Refused(422, "the file holds one JSON object: source, items, links")
        data.pop("file", None)
        try:
            found = OkrImportIn.model_validate(data)
        except ValidationError as exc:
            raise hub.Refused(422, f"the file does not import: {said(exc)}") from None
        body = found.model_copy(update={"dry_run": body.dry_run or found.dry_run, "prune": body.prune or found.prune})
    if not body.source:
        raise hub.Refused(422, "an import names its source")
    return body


@dataclass
class _Planned:
    """An item of the bundle as the import will leave it."""

    ref: str
    kind: str
    number: int
    values: dict
    parents: list[str]  # the keys of its parents: an item's id as text, or "ref:<ref>" for a new one
    old: rules.Item | None

    @property
    def code(self) -> str:
        return rules.code(self.kind, self.number)

    @property
    def key(self) -> str:
        return str(self.old.id) if self.old else f"ref:{self.ref}"


def _plan(who: Viewer, tree: rules.Tree, bundle: OkrImportIn, numbers: dict[str, int]) -> list[_Planned]:
    """The items of the bundle as the import will leave them, numbered; 422 naming every problem of the bundle."""
    problems: list[str] = []
    refs = [entry.ref for entry in bundle.items]
    problems += [f"ref {ref} is in the bundle twice" for ref in sorted({r for r in refs if refs.count(r) > 1})]
    by_ref = {item.ref: item for item in tree.items.values() if item.ref}
    planned: dict[str, _Planned] = {}
    for entry in bundle.items:
        old = by_ref.get(entry.ref)
        if old is not None and old.kind != entry.kind:
            problems.append(f"{entry.ref} is {old.code}, {rules.WORDS[old.kind]}, not {rules.WORDS[entry.kind]}")
        if old is not None and old.source and old.source != bundle.source:
            problems.append(f"{entry.ref} is {old.code}, which source {old.source} writes")
        if old is None:
            number = numbers[entry.kind]
            numbers[entry.kind] += 1
        else:
            number = old.number
        values = {name: getattr(entry, name) for name in IMPORT_FIELDS if name != "source"}
        values["source"] = bundle.source
        planned.setdefault(entry.ref, _Planned(entry.ref, entry.kind, number, values, [], old))
    for entry in bundle.items:
        here = planned[entry.ref]
        kinds = []
        for text in dict.fromkeys(entry.parents):
            if text in planned:
                kinds.append(planned[text].kind)
                here.parents.append(planned[text].key)
                continue
            parent = by_ref.get(text) or find(tree, text)
            if parent is None:
                problems.append(f"{entry.ref}: no parent {text} in the bundle or the project")
                continue
            kinds.append(parent.kind)
            here.parents.append(str(parent.id))
        problem = rules.shape_problem(entry.kind, kinds)
        if problem is not None and len(kinds) == len(set(entry.parents)):
            problems.append(f"{entry.ref}: {problem}")
    edges = {str(i): [str(p) for p in ps] for i, ps in tree.parents.items()}
    edges.update({here.key: here.parents for here in planned.values()})
    for here in planned.values():
        if rules.closes_cycle(here.key, here.parents, {k: v for k, v in edges.items() if k != here.key}):
            problems.append(f"{here.ref}: its parents close a cycle")
    if problems:
        more = f"; and {len(problems) - MAX_PROBLEMS} more" if len(problems) > MAX_PROBLEMS else ""
        listed = "; ".join(problems[:MAX_PROBLEMS])
        raise hub.Refused(
            422, f"the bundle of source {bundle.source} does not import, nothing was written: {listed}{more}"
        )
    return list(planned.values())


def _changed(tree: rules.Tree, here: _Planned) -> list[str]:
    old = here.old
    if old is None:
        return []
    fields = [name for name in IMPORT_FIELDS if getattr(old, name) != here.values[name]]
    if sorted(str(p) for p in tree.parents[old.id]) != sorted(here.parents):
        fields.append("parents")
    return fields


async def import_bundle(conn: AsyncConnection, who: Viewer, body: OkrImportIn) -> OkrImported:
    """Upsert a source's items by ref and add their links (writer); with ``dry_run`` nothing is written and the
    answer is the same report. A bundle with a problem of shape, kind or parent writes nothing (422); a link whose
    target the project lacks, or that the item does not take, is reported and the rest goes on."""
    store.writer(who.access, "importing into the OKR tree")
    bundle = bundle_of(body)
    project_id, by = who.access.id, who.session.user_id
    await store.lock_tree(conn, project_id)
    tree = await _tree(conn, who)
    planned = _plan(who, tree, bundle, await store.next_numbers(conn, project_id))
    listed = {here.ref for here in planned}
    report = {"created": [], "updated": [], "unchanged": [], "missing": []}
    changes = {}
    for here in planned:
        fields = _changed(tree, here)
        changes[here.ref] = fields
        word = "created" if here.old is None else ("updated" if fields else "unchanged")
        report[word].append(OkrImportedItem(ref=here.ref, code=here.code, kind=here.kind, fields=fields))
    missing = [
        item
        for item in tree.ordered()
        if item.source == bundle.source and item.ref not in listed and item.status != "archived"
    ]
    report["missing"] = [
        OkrImportedItem(ref=item.ref or "", code=item.code, kind=item.kind, archived=bundle.prune) for item in missing
    ]
    found = await hub_facts.catalog(conn, who.access.name)
    results = _links(tree, planned, bundle, found)

    if not bundle.dry_run:
        made: dict[str, int] = {}  # the id of each new item, by its key

        def item_id(key: str) -> int:
            return made[key] if key in made else int(key)

        for here in planned:
            if here.old is None:
                made[here.key] = await store.add_item(conn, project_id, here.kind, here.number, here.values, by)
            elif changes[here.ref]:
                await store.change_item(conn, here.old.id, here.values, by)
        for here in planned:
            if here.old is None or "parents" in changes[here.ref]:
                await store.set_parents(conn, item_id(here.key), [item_id(key) for key in here.parents])
        if bundle.prune:
            for item in missing:
                await store.change_item(conn, item.id, {"status": "archived"}, by)
        for result, key in results:
            if key is not None:
                result.id, _ = await store.add_link(conn, item_id(key), result.kind, result.target, by)
        counts = ", ".join(f"{len(report[word])} {word}" for word in ("created", "updated", "unchanged", "missing"))
        target = f"source {bundle.source}: {counts}"
        await hub.audit(conn, store.handle(), who.session, IMPORT_ACTION, target, project=who.access)
    return OkrImported(
        source=bundle.source,
        dry_run=bundle.dry_run,
        prune=bundle.prune,
        links=[result for result, _ in results],
        **report,
    )


def _links(
    tree: rules.Tree, planned: list[_Planned], bundle: OkrImportIn, found: hub_facts.Catalog
) -> list[tuple[OkrImportedLink, str | None]]:
    """Each link of the bundle with what the import does of it, and the key of its item: added, exists (the item has
    it already), not_found (the project lacks the target) or refused (no such item, a kind the item does not take,
    a key result's second goal)."""
    by_ref = {here.ref: here for here in planned}
    held = {(k.item_id, k.kind, k.target): k.id for links in tree.links.values() for k in links}
    goals = {str(k.item_id): k.target for links in tree.links.values() for k in links if k.kind == "goal"}
    added: set[tuple[str, str, str]] = set()
    results = []
    for entry in bundle.links:
        result = OkrImportedLink(item=entry.item, kind=entry.kind, target=entry.target, result="refused")
        here = by_ref.get(entry.item)
        item = here.old if here is not None else find(tree, entry.item)
        kind = here.kind if here is not None else (item.kind if item else None)
        key = here.key if here is not None else (str(item.id) if item else None)
        if kind is None:
            result.detail = f"no item {entry.item} in the bundle or the project"
        elif entry.kind not in rules.target_kinds(kind):
            allowed = ", ".join(rules.target_kinds(kind)) or "nothing"
            result.detail = f"{rules.WORDS[kind]} links {allowed}, not a {entry.kind}"
        else:
            try:
                target = found.resolve(entry.kind, entry.target)
            except hub.Refused as exc:
                target = None
                result.result = "not_found" if exc.status_code == 404 else "refused"
                result.detail = str(exc.detail)
            if target is not None:
                result.target = target
                existing = held.get((item.id, entry.kind, target)) if item is not None else None
                if existing is not None or (key, entry.kind, target) in added:
                    result.result, result.id = "exists", existing
                elif entry.kind == "goal" and goals.get(key, target) != target:
                    result.detail = f"{entry.item} is measured by goal {goals[key]} already"
                else:
                    result.result = "added"
                    added.add((key, entry.kind, target))
                    if entry.kind == "goal":
                        goals[key] = target
        results.append((result, key if result.result == "added" else None))
    return results


__all__ = [
    "Viewer",
    "add_item",
    "bundle_of",
    "find",
    "import_bundle",
    "link",
    "set_item",
    "show_item",
    "tree_view",
    "unlink",
    "viewer",
]
