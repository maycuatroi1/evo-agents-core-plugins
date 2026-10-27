"""The routes of the plugin jev, under /v1/x/jev/<project>/ for a member with a grant on a project that enabled it (the
hub checks both first; a project that did not enable it answers 404).

A reader reads the status (``GET /{project}/status``), the cost of the last 24 hours and 7 days
(``GET /{project}/usage``) and the recent acts with how to undo each (``GET /{project}/acts``) and the corrections that repeat
(``GET /{project}/matches``). A writer puts
questions to Jev (``POST /{project}/ask``). Nothing is sent to Jev unless the project set an api_key and a pinned
model, declared the sink ``jev@typesafe`` in its policy and stays within its daily budget.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Path, Query, Request
from fastapi.responses import JSONResponse

from evo_agents.hub.server import core_plugin_api as hub
from evo_core_plugins.jev import cli_text, service
from evo_core_plugins.jev.models import JevActs, JevAsked, JevAskIn, JevMatches, JevStatus, JevUsage

REFUSALS = {code: {"model": hub.ErrorBody} for code in (403, 404, 409, 422, 502)}
ProjectName = Annotated[str, Path(pattern=hub.PROJECT_NAME)]
Render = Annotated[
    Literal["text"] | None,
    Query(description="text: the words `evo-agents hub jev` prints, as {text}, instead of the answer"),
]

router = APIRouter(tags=["plugins"], responses={401: {"model": hub.ErrorBody}, **REFUSALS})


def _words(found, render: str | None, word):
    """``found``, or with ``render`` text the words of it the CLI prints (``cli_text``)."""
    if render != "text":
        return found
    return JSONResponse({"text": word(found.model_dump(mode="json"))})


@router.get("/{project}/status", response_model=JevStatus)
async def status(request: Request, project: ProjectName, user: hub.Caller, render: Render = None):
    """Whether Jev is set up in the project, what its features do and what it spent today."""
    async with hub.begin(request) as conn:
        found = await service.status(conn, hub.hub_config(request), user, project)
    return _words(found, render, cli_text.status)


@router.get("/{project}/usage", response_model=JevUsage)
async def usage(request: Request, project: ProjectName, user: hub.Caller, render: Render = None):
    """The cost of the last 24 hours and 7 days, by feature, against the daily budget."""
    async with hub.begin(request) as conn:
        found = await service.usage(conn, hub.hub_config(request), user, project)
    return _words(found, render, cli_text.usage)


@router.get("/{project}/acts", response_model=JevActs)
async def acts(
    request: Request,
    project: ProjectName,
    user: hub.Caller,
    limit: Annotated[int, Query(ge=1, le=service.MAX_ACTS, description="how many, newest first")] = 50,
    render: Render = None,
):
    """What Jev decided, newest first, each with the hub's command that undoes it when the plugin applied it."""
    async with hub.begin(request) as conn:
        found = await service.acts(conn, hub.hub_config(request), user, project, limit)
    return _words(found, render, cli_text.acts)


@router.get("/{project}/matches", response_model=JevMatches)
async def matches(
    request: Request,
    project: ProjectName,
    user: hub.Caller,
    limit: Annotated[int, Query(ge=1, le=service.MAX_ACTS, description="how many, newest first")] = 50,
    render: Render = None,
):
    """The corrections that repeat an earlier one or a rule the project accepted, newest first."""
    async with hub.begin(request) as conn:
        found = await service.matches(conn, hub.hub_config(request), user, project, limit)
    return _words(found, render, cli_text.matches)


@router.post("/{project}/ask", response_model=JevAsked)
async def ask(request: Request, project: ProjectName, body: JevAskIn, user: hub.Caller, render: Render = None):
    """Put the questions about the state to Jev, in one request (writer); the answers, the tokens and the cost."""
    found = await service.ask(
        lambda: hub.begin(request), hub.hub_config(request), user, project, body, feature=service.TOOL
    )
    return _words(found, render, cli_text.asked)


__all__ = ["router"]
