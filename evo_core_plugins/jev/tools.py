"""The MCP tools of the plugin jev, for the agents and the members on /mcp: ``jev__decide`` puts questions about a
state to Jev in one request, ``jev__usage`` reads what Jev cost.

A call acts for the member ``hub.tool_caller`` names (the member at the origin of a chat run, the member's own session
on /mcp), else for the member who dispatched the run, with that member's role in the project: a reader reads the
usage, a writer asks. The state an agent hands the tool carries no label of the hub's, so the gates are the ones that
stand: the project declares the sink ``jev@typesafe``, the caller is a writer, and the project holds the key and the
pinned model. A refusal is an error the agent reads. Each answer is JSON, as the route of the same thing answers it.
"""

from __future__ import annotations

import json

from sqlalchemy.ext.asyncio import AsyncConnection

from evo_agents.hub.server import core_plugin_api as hub
from evo_core_plugins.jev import service, store

DECIDE_SCHEMA = {
    "type": "object",
    "properties": {
        "state": {
            "description": "what the questions are about: text, or a JSON object or list",
            "type": ["string", "object", "array"],
        },
        "questions": {
            "type": "object",
            "description": "name -> {type, instructions, criteria}. type is choice (criteria: option -> what it means), "
            "noul (a number 0 to 1, how much it is a yes; criteria optional: {true, false}) or score (criteria: the "
            "levels, lowest first, 2 to 10)",
            "additionalProperties": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["choice", "noul", "score"]},
                    "instructions": {"type": "string"},
                    "criteria": {"type": ["object", "array"]},
                },
                "required": ["type"],
            },
        },
    },
    "required": ["state", "questions"],
}
USAGE_SCHEMA = {"type": "object", "properties": {}}


def _text(text: str, *, error: bool = False) -> dict:
    return {"content": [{"type": "text", "text": text}], "is_error": error}


def _json(found) -> dict:
    return _text(json.dumps(found.model_dump(mode="json"), ensure_ascii=False))


async def _session(conn: AsyncConnection, context: hub.Context, params: dict):
    if context.project is None:
        raise hub.Refused(404, "the tool is called in a project")
    caller = await hub.tool_caller(conn, store.handle(), context, params)
    session = caller.session
    if session is None and caller.run_id is not None:
        session = await hub.run_member(conn, store.handle(), context.project, caller.run_id)
    if session is None:
        raise hub.Refused(403, f"nobody with a grant on project {context.project} makes this call")
    return session, caller.run_id


async def decide(params: dict, context: hub.Context) -> dict:
    """``jev__decide``: the questions about the state, in one request to Jev (writer)."""
    arguments = params.get("arguments") or {}
    try:
        async with hub.transaction(context) as conn:
            session, run_id = await _session(conn, context, params)
        asked = service.parse(arguments.get("state"), arguments.get("questions"))
        found = await service.ask(
            lambda: hub.transaction(context), context.config, session, context.project, asked, run_id=run_id
        )
    except hub.Refused as exc:
        return _text(f"refused: {exc.detail}", error=True)
    return _json(found)


async def usage(params: dict, context: hub.Context) -> dict:
    """``jev__usage``: what Jev cost the project, against its daily budget."""
    try:
        async with hub.transaction(context) as conn:
            session, _ = await _session(conn, context, params)
            found = await service.usage(conn, context.config, session, context.project)
    except hub.Refused as exc:
        return _text(f"refused: {exc.detail}", error=True)
    return _json(found)


__all__ = ["DECIDE_SCHEMA", "USAGE_SCHEMA", "decide", "usage"]
