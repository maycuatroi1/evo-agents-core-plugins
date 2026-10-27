"""The plugin okr's reads and writes of its own tables (SQLAlchemy Core), and who may read and write them.

An item's number is the next of its kind in the project, taken under a lock of the project's tree for the rest of the
transaction, so two writers never take the same code. Parents are written whole for a child; a link is written once
for each item, kind and target.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from evo_agents.hub.server import core_plugin_api as hub
from evo_core_plugins.okr import tables as okr
from evo_core_plugins.okr.rules import Item, Link

SINK_HEADER = "X-Evo-Sink"  # evo_agents.hub.server.plans.SINK_HEADER
TREE_LOCK = 0x6F6B72  # the first key of the advisory lock of a project's tree ("okr"); the second is the project's id
FIELDS = ("title", "body_md", "status", "owner", "period", "due", "baseline", "target", "ref")  # an item's own
SOURCE_FIELDS = ("source", "source_url", "source_rev")


def handle() -> hub.Plugin:
    """The plugin's handle, which every call of the hub's API takes."""
    return hub.plugin(__name__)


# Who may do what


def reader(access: hub.ProjectRef) -> None:
    """Reading needs a grant on the project: a hub admin without one gets this far only."""
    if access.role is None or access.max_level is None:
        raise hub.Refused(403, f"reading the OKR tree of project {access.name} needs a grant on it")


def writer(access: hub.ProjectRef, what: str) -> None:
    reader(access)
    if not hub.has_role(access.role, "writer"):
        raise hub.Refused(403, f"{what} in project {access.name} needs the writer role; you are {access.role}")


# Reads


def _columns():
    c = okr.items.c
    return (
        c.id,
        c.kind,
        c.number,
        c.ref,
        c.title,
        c.body_md,
        c.status,
        c.owner,
        c.period,
        c.due,
        c.baseline,
        c.target,
        c.source,
        c.source_url,
        c.source_rev,
        c.created_by,
        c.updated_by,
        c.created_at,
        c.updated_at,
    )


async def _logins(conn: AsyncConnection, ids: Iterable[int | None]) -> dict[int, str]:
    wanted = {user_id for user_id in ids if user_id is not None}
    if not wanted:
        return {}
    return {user.id: user.login for user in await hub.read_users(conn, handle(), ids=wanted)}


async def items(conn: AsyncConnection, project_id: int) -> list[Item]:
    """Every item of a project, by kind and number, with the logins of who made and last changed it."""
    c = okr.items.c
    rows = list(await conn.execute(select(*_columns()).where(c.project_id == project_id).order_by(c.kind, c.number)))
    logins = await _logins(conn, [row.created_by for row in rows] + [row.updated_by for row in rows])
    return [
        Item(
            row.id,
            row.kind,
            row.number,
            row.ref,
            row.title,
            row.body_md,
            row.status,
            row.owner,
            row.period,
            row.due,
            row.baseline,
            row.target,
            row.source,
            row.source_url,
            row.source_rev,
            logins.get(row.created_by),
            logins.get(row.updated_by),
            row.created_at,
            row.updated_at,
        )
        for row in rows
    ]


async def edges(conn: AsyncConnection, project_id: int) -> list[tuple[int, int]]:
    """(child, parent) of every edge of a project's tree."""
    p, i = okr.parents.c, okr.items.c
    query = (
        select(p.child_id, p.parent_id)
        .join_from(okr.parents, okr.items, i.id == p.child_id)
        .where(i.project_id == project_id)
        .order_by(p.child_id, p.parent_id)
    )
    return [(row.child_id, row.parent_id) for row in await conn.execute(query)]


async def links(conn: AsyncConnection, project_id: int) -> list[Link]:
    """Every link of a project's items, oldest first, with the login of who made it."""
    k, i = okr.links.c, okr.items.c
    query = (
        select(k.id, k.item_id, k.target_kind, k.target, k.created_by, k.created_at)
        .join_from(okr.links, okr.items, i.id == k.item_id)
        .where(i.project_id == project_id)
        .order_by(k.id)
    )
    rows = list(await conn.execute(query))
    logins = await _logins(conn, [row.created_by for row in rows])
    return [
        Link(row.id, row.item_id, row.target_kind, row.target, logins.get(row.created_by), row.created_at)
        for row in rows
    ]


# Writes


async def lock_tree(conn: AsyncConnection, project_id: int) -> None:
    """Hold the project's tree for the rest of the transaction: the next writer of it waits until this one ends."""
    await conn.execute(select(func.pg_advisory_xact_lock(TREE_LOCK, project_id)))


async def next_numbers(conn: AsyncConnection, project_id: int) -> dict[str, int]:
    """kind -> the number its next item takes in the project (1 for a kind without any yet); under ``lock_tree``."""
    c = okr.items.c
    found = await conn.execute(select(c.kind, func.max(c.number)).where(c.project_id == project_id).group_by(c.kind))
    held = {kind: number for kind, number in found}
    return {kind: (held.get(kind) or 0) + 1 for kind in okr.KINDS}


async def add_item(
    conn: AsyncConnection, project_id: int, kind: str, number: int, values: Mapping[str, Any], by: int | None
) -> int:
    """Write a new item with ``values`` (of FIELDS and SOURCE_FIELDS); its id."""
    statement = insert(okr.items).values(
        project_id=project_id, kind=kind, number=number, created_by=by, updated_by=by, **values
    )
    return (await conn.execute(statement.returning(okr.items.c.id))).scalar_one()


async def change_item(conn: AsyncConnection, item_id: int, values: Mapping[str, Any], by: int | None) -> None:
    """Write ``values`` (of FIELDS and SOURCE_FIELDS) over an item, as changed now by ``by``."""
    c = okr.items.c
    await conn.execute(update(okr.items).where(c.id == item_id).values(updated_by=by, updated_at=func.now(), **values))


async def set_parents(conn: AsyncConnection, child_id: int, parent_ids: Iterable[int]) -> None:
    """The parents of an item, in place of those it had."""
    p = okr.parents
    await conn.execute(delete(p).where(p.c.child_id == child_id))
    rows = [{"child_id": child_id, "parent_id": parent_id} for parent_id in dict.fromkeys(parent_ids)]
    if rows:
        await conn.execute(insert(p), rows)


async def add_link(conn: AsyncConnection, item_id: int, kind: str, target: str, by: int | None) -> tuple[int, bool]:
    """(the id of the link of ``item_id`` to ``target`` of ``kind``, whether this call made it); once each."""
    k = okr.links
    statement = (
        pg_insert(k)
        .values(item_id=item_id, target_kind=kind, target=target, created_by=by)
        .on_conflict_do_nothing(constraint="okr_links_once_key")
        .returning(k.c.id)
    )
    made = (await conn.execute(statement)).scalar()
    if made is not None:
        return made, True
    found = await conn.scalar(
        select(k.c.id).where(k.c.item_id == item_id, k.c.target_kind == kind, k.c.target == target)
    )
    return found, False


async def delete_link(conn: AsyncConnection, item_id: int, link_id: int) -> bool:
    """Whether the link ``link_id`` of ``item_id`` was there and is gone."""
    k = okr.links.c
    gone = await conn.execute(delete(okr.links).where(k.id == link_id, k.item_id == item_id).returning(k.id))
    return gone.scalar() is not None


__all__ = [
    "FIELDS",
    "SINK_HEADER",
    "SOURCE_FIELDS",
    "add_item",
    "add_link",
    "change_item",
    "delete_link",
    "edges",
    "handle",
    "items",
    "links",
    "lock_tree",
    "next_numbers",
    "reader",
    "set_parents",
    "writer",
]
