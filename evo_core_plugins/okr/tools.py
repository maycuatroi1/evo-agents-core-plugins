"""The MCP tools of the plugin okr, for the agents and the members on /mcp: ``okr__tree`` reads the tree with its
roll-up and gaps, ``okr__item`` one item, ``okr__link`` links an item to a task, use case, plan or goal of the
project, ``okr__unlink`` takes a link off.

A call acts for the member ``hub.tool_caller`` names (the member at the origin of a chat run, the member's own session
on /mcp), else for the member who dispatched the run, with that member's role in the project: a reader reads, a writer
links. Reads go through the caller's sink. Each answer is JSON, as the route of the same thing answers it.
"""

from __future__ import annotations

import json

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncConnection

from evo_agents.hub.server import core_plugin_api as hub
from evo_core_plugins.okr import service, store
from evo_core_plugins.okr.models import OkrLinkIn
from evo_core_plugins.okr.tables import STATUSES, TARGET_KINDS

TREE_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": list(STATUSES), "description": "the items of this status and above"},
        "line": {"type": "string", "description": "one business line, by its code (BL-1) or ref"},
    },
}

ITEM_SCHEMA = {
    "type": "object",
    "properties": {"item": {"type": "string", "description": "the item's code (KR-3) or ref"}},
    "required": ["item"],
}

LINK_SCHEMA = {
    "type": "object",
    "properties": {
        "item": {"type": "string", "description": "the item's code (D-4) or ref"},
        "kind": {
            "type": "string",
            "enum": list(TARGET_KINDS),
            "description": "a deliverable's task, use_case or plan; a key result's goal",
        },
        "target": {"type": "string", "description": "T-12, <document>:<code> of a use case, a plan's slug, or G-3"},
    },
    "required": ["item", "kind", "target"],
}

UNLINK_SCHEMA = {
    "type": "object",
    "properties": {
        "item": {"type": "string", "description": "the item's code or ref"},
        "link": {"type": "integer", "description": "the link's id, as okr__item lists it"},
    },
    "required": ["item", "link"],
}


def _text(text: str, *, error: bool = False) -> dict:
    return {"content": [{"type": "text", "text": text}], "is_error": error}


def _json(found) -> dict:
    return _text(json.dumps(found.model_dump(mode="json"), ensure_ascii=False))


async def _viewer(conn: AsyncConnection, context: hub.Context, params: dict) -> service.Viewer:
    if context.project is None:
        raise hub.Refused(404, "the tool is called in a project")
    caller = await hub.tool_caller(conn, store.handle(), context, params)
    session = caller.session
    if session is None and caller.run_id is not None:
        session = await hub.run_member(conn, store.handle(), context.project, caller.run_id)
    if session is None:
        raise hub.Refused(403, f"nobody with a grant on project {context.project} makes this call")
    return await service.viewer(conn, session, context.project, context.sink)


async def _call(params: dict, context: hub.Context, work) -> dict:
    """``work(conn, viewer, arguments)`` in one transaction; a refusal is an error the agent reads."""
    arguments = params.get("arguments") or {}
    try:
        async with hub.transaction(context) as conn:
            return await work(conn, await _viewer(conn, context, params), arguments)
    except hub.Refused as exc:
        return _text(f"refused: {exc.detail}", error=True)
    except ValidationError as exc:
        return _text(f"refused: {service.said(exc)}", error=True)


def _named(arguments: dict, name: str) -> str:
    value = arguments.get(name)
    if not isinstance(value, str) or not value.strip():
        raise hub.Refused(422, f"{name} names the item by its code or ref")
    return value.strip()


async def tree(params: dict, context: hub.Context) -> dict:
    """``okr__tree``: the tree with its roll-up and gaps, of one status or one business line."""

    async def work(conn, who, arguments):
        status = arguments.get("status") or None
        if status is not None and status not in STATUSES:
            raise hub.Refused(422, f"a status is one of {', '.join(STATUSES)}")
        return _json(await service.tree_view(conn, who, status=status, line=arguments.get("line") or None))

    return await _call(params, context, work)


async def item(params: dict, context: hub.Context) -> dict:
    """``okr__item``: one item with its parents, children, links, roll-up and gaps."""

    async def work(conn, who, arguments):
        return _json(await service.show_item(conn, who, _named(arguments, "item")))

    return await _call(params, context, work)


async def link(params: dict, context: hub.Context) -> dict:
    """``okr__link``: link an item to a target the project holds (writer)."""

    async def work(conn, who, arguments):
        body = OkrLinkIn.model_validate({"kind": arguments.get("kind"), "target": arguments.get("target")})
        return _json(await service.link(conn, who, _named(arguments, "item"), body))

    return await _call(params, context, work)


async def unlink(params: dict, context: hub.Context) -> dict:
    """``okr__unlink``: take a link off an item (writer)."""

    async def work(conn, who, arguments):
        link_id = arguments.get("link")
        if not isinstance(link_id, int) or isinstance(link_id, bool) or link_id < 1:
            raise hub.Refused(422, "link is the link's id, a whole number, as okr__item lists it")
        return _json(await service.unlink(conn, who, _named(arguments, "item"), link_id))

    return await _call(params, context, work)


__all__ = ["ITEM_SCHEMA", "LINK_SCHEMA", "TREE_SCHEMA", "UNLINK_SCHEMA", "item", "link", "tree", "unlink"]
