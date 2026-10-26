"""The MCP tools of the plugin editorial, for the agents that write a project's posts and the members on /mcp:
``editorial__state`` reads a post's state or sets it, ``editorial__recall`` gives what to read before a stage (by
stage, post and keyword), ``editorial__feedback`` adds an entry to the feedback notebook or records that one came back.

A call acts for the member ``hub.tool_caller`` names (the member at the origin of a chat run, the member's own session
on /mcp), else for the member who dispatched the run, with that member's role in the project: a reader reads, a writer
sets and adds. Reads go through the caller's sink. Each answer is JSON, as the route of the same thing answers it.
"""

from __future__ import annotations

import json

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncConnection

from evo_agents.hub.server import core_plugin_api as hub
from evo_core_plugins.editorial import service, settings
from evo_core_plugins.editorial.models import EditorialFeedbackIn, EditorialRepeatIn, EditorialSetIn

SET_FIELDS = tuple(EditorialSetIn.model_fields)

STATE_SCHEMA = {
    "type": "object",
    "properties": {
        "slug": {"type": "string", "description": "the post's slug; left out, the list of posts"},
        "set": {
            "type": "object",
            "description": "what to set: stage, title, branch, preview_url, url, published_at, d7, d28, evidence, "
            "and gate with gate_state (waiting, answered, skipped), via and answer; left out, the post is read",
            "properties": {name: {} for name in SET_FIELDS},
            "additionalProperties": False,
        },
    },
}

RECALL_SCHEMA = {
    "type": "object",
    "properties": {
        "stage": {"type": "string", "description": "the stage about to start: the notebooks it reads"},
        "post": {"type": "string", "description": "the post's slug: the entries about it too"},
        "keyword": {"type": "string", "description": "only entries with every word of it"},
    },
}

FEEDBACK_SCHEMA = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["add", "repeat"]},
        "entry": {"type": "string", "description": "repeat: the entry that came back, PH-<n>"},
        "notebook": {"type": "string", "description": "add: the notebook of the project's config"},
        "title": {"type": "string", "description": "add: a short title"},
        "said": {"type": "string", "description": "what the person said, in their words"},
        "date": {"type": "string", "description": "add: the day, YYYY-MM-DD; repeat: when it was said"},
        "note": {"type": "string", "description": "where it was said, such as the post"},
        "post": {"type": "string", "description": "add: the post's slug"},
        "agent_wrote": {"type": "string", "description": "add: what the agent wrote"},
        "person_fixed": {"type": "string", "description": "add: what the person changed it to"},
        "rule": {"type": "string", "description": "add: the rule it gives"},
        "check": {"type": "string", "description": "add: how the rule is checked"},
        "probe_id": {"type": "integer", "description": "add: the curator probe that checks the rule"},
    },
    "required": ["action"],
}


def _text(text: str, *, error: bool = False) -> dict:
    return {"content": [{"type": "text", "text": text}], "is_error": error}


def _json(found) -> dict:
    if isinstance(found, list):
        data = [item.model_dump(mode="json") for item in found]
    else:
        data = found.model_dump(mode="json")
    return _text(json.dumps(data, ensure_ascii=False))


async def _viewer(conn: AsyncConnection, context: hub.Context, params: dict) -> service.Viewer:
    if context.project is None:
        raise hub.Refused(404, "the tool is called in a project")
    caller = await hub.tool_caller(conn, settings.handle(), context, params)
    session = caller.session
    if session is None and caller.run_id is not None:
        session = await hub.run_member(conn, settings.handle(), context.project, caller.run_id)
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
        said = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:5])
        return _text(f"refused: {said}", error=True)


async def state(params: dict, context: hub.Context) -> dict:
    """``editorial__state``: the posts, one post, or one post after setting what ``set`` gives."""

    async def work(conn, who, arguments):
        slug = arguments.get("slug")
        if not slug:
            return _json(await service.list_posts(conn, who))
        if arguments.get("set"):
            body = EditorialSetIn.model_validate(arguments["set"])
            return _json(await service.set_post(conn, who, str(slug), body))
        return _json(await service.show_post(conn, who, str(slug)))

    return await _call(params, context, work)


async def recall(params: dict, context: hub.Context) -> dict:
    """``editorial__recall``: the entries to read before a stage, about a post, with a keyword; seen most first."""

    async def work(conn, who, arguments):
        found = await service.recall(
            conn,
            who,
            stage=arguments.get("stage") or None,
            post=arguments.get("post") or None,
            keyword=arguments.get("keyword") or None,
        )
        return _json([service.entry_model(entry) for entry in found])

    return await _call(params, context, work)


async def feedback(params: dict, context: hub.Context) -> dict:
    """``editorial__feedback``: add an entry, or record that one came back; the entry as it is now."""

    async def work(conn, who, arguments):
        action = arguments.get("action")
        given = {key: value for key, value in arguments.items() if key not in ("action", "entry")}
        if action == "add":
            entry = await service.add_feedback(conn, who, EditorialFeedbackIn.model_validate(given))
        elif action == "repeat":
            if not arguments.get("entry"):
                raise hub.Refused(422, "repeat takes the entry that came back, PH-<n>")
            body = EditorialRepeatIn.model_validate({k: given.get(k) for k in ("said", "date", "note")})
            entry = await service.repeat_feedback(conn, who, str(arguments["entry"]), body)
        else:
            raise hub.Refused(422, "action is add or repeat")
        return _json(service.entry_model(entry))

    return await _call(params, context, work)


__all__ = ["FEEDBACK_SCHEMA", "RECALL_SCHEMA", "STATE_SCHEMA", "feedback", "recall", "state"]
