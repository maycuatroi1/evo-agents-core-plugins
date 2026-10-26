"""The events of the plugin editorial (``contributes.events``): the hub delivers each at least once, with retries, from
its own delivery of plugin events; the plugin runs no job.

``task.result``: a task run of the agent type writer ended (done, failed or cancelled), and the post it worked on
goes on (``flow.run_ended``). ``agent.answer``: the question of a review round to the agent type editor-judge was
answered, and its scores go into the round (``flow.answer_ended``). Each acts once: a second delivery of the same end
finds the post no longer running, or the round already scored the same way.
"""

from __future__ import annotations

from evo_agents.hub.server import core_plugin_api as hub
from evo_core_plugins.editorial import flow, judge, settings

RESULT_EVENT = "task.result"


async def _project_id(conn, project: str, context: hub.Context) -> int:
    if context.project_id is not None and context.project == project:
        return context.project_id
    return (await hub.read_project(conn, settings.handle(), project)).id


async def on_task_result(params: dict, context: hub.Context) -> dict:
    """A task run of the writer ended: the post goes on, or shows why it stopped."""
    payload = params.get("payload") or {}
    if params.get("kind") not in (None, RESULT_EVENT) or payload.get("agent_type") != flow.WRITER:
        return {}
    project = payload.get("project") or context.project
    if not isinstance(project, str):
        return {}
    async with hub.transaction(context) as conn:
        cfg = await settings.config(conn, project)
        done = await flow.run_ended(conn, project, await _project_id(conn, project, context), cfg, payload)
    return {"post": done}


async def on_agent_answer(params: dict, context: hub.Context) -> dict:
    """The judge answered a round's question: its scores kept in the round."""
    payload = params.get("payload") or {}
    if params.get("kind") not in (None, hub.ANSWER_EVENT) or payload.get("agent_type") != judge.AGENT_TYPE:
        return {}
    async with hub.transaction(context) as conn:
        done = await flow.answer_ended(conn, payload)
    return {"round": done}


__all__ = ["on_agent_answer", "on_task_result"]
