"""The routes of the plugin okr, under /v1/x/okr/<project>/ for a member with a grant on a project that enabled it (the
hub checks both first; a project that did not enable it answers 404).

A reader reads the tree with its roll-up and gaps (``GET /{project}/tree?status=&line=``) and one item by its code or
ref (``GET /{project}/items/{item}``). A writer adds an item (``POST /{project}/items``), changes one
(``PATCH /{project}/items/{item}``), links it to a task, use case, plan or goal of the project
(``POST /{project}/items/{item}/links``), takes a link off (``DELETE /{project}/items/{item}/links/{link_id}``) and
imports a source's bundle (``POST /{project}/import``). Reads of the hub's labelled data go through the sink
X-Evo-Sink names, else the project's hub sink.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Header, Path, Query, Request, Response
from fastapi.responses import JSONResponse

from evo_agents.hub.server import core_plugin_api as hub
from evo_core_plugins.okr import cli_text, service, store
from evo_core_plugins.okr.models import (
    OkrImported,
    OkrImportIn,
    OkrItem,
    OkrItemIn,
    OkrItemPatch,
    OkrLinkIn,
    OkrLinkMade,
    OkrTree,
    OkrUnlinked,
)
from evo_core_plugins.okr.tables import REF, STATUSES

REFUSALS = {code: {"model": hub.ErrorBody} for code in (403, 404, 409, 422)}
ProjectName = Annotated[str, Path(pattern=hub.PROJECT_NAME)]
ItemName = Annotated[str, Path(pattern=REF, description="the item's code (KR-3) or its ref")]
Sink = Annotated[str | None, Header(alias=store.SINK_HEADER)]
StatusName = Literal[*STATUSES]
Render = Annotated[
    Literal["text"] | None,
    Query(description="text: the words `evo-agents hub okr` prints, as {text}, instead of the answer"),
]

router = APIRouter(tags=["plugins"], responses={401: {"model": hub.ErrorBody}, **REFUSALS})


def _words(found, render: str | None, word):
    """``found``, or with ``render`` text the words of it the CLI prints (``cli_text``)."""
    if render != "text":
        return found
    return JSONResponse({"text": word(found.model_dump(mode="json"))})


async def _answer(request: Request, work):
    """``work(conn)`` in one transaction; a refusal (``hub.Refused``) is the hub's error body, nothing written."""
    async with hub.begin(request) as conn:
        return await work(conn)


@router.get("/{project}/tree", response_model=OkrTree)
async def tree(
    request: Request,
    project: ProjectName,
    user: hub.Caller,
    status: Annotated[StatusName | None, Query(description="items of this status and those above")] = None,
    line: Annotated[str | None, Query(pattern=REF, description="one business line, by its code or ref")] = None,
    sink: Sink = None,
    render: Render = None,
):
    """The tree from its business lines down, each item with its roll-up and links, and the gaps."""

    async def work(conn):
        who = await service.viewer(conn, user, project, sink)
        return await service.tree_view(conn, who, status=status, line=line)

    return _words(await _answer(request, work), render, cli_text.tree)


@router.get("/{project}/items/{item}", response_model=OkrItem)
async def show_item(
    request: Request, project: ProjectName, item: ItemName, user: hub.Caller, sink: Sink = None, render: Render = None
):
    """One item with its parents, children, links, roll-up and gaps."""

    async def work(conn):
        return await service.show_item(conn, await service.viewer(conn, user, project, sink), item)

    return _words(await _answer(request, work), render, cli_text.item)


@router.post("/{project}/items", status_code=201, response_model=OkrItem)
async def add_item(
    request: Request, project: ProjectName, body: OkrItemIn, user: hub.Caller, sink: Sink = None, render: Render = None
):
    """A new item under its parents, with the next code of its kind (writer)."""

    async def work(conn):
        return await service.add_item(conn, await service.viewer(conn, user, project, sink), body)

    return _words(await _answer(request, work), render, cli_text.item)


@router.patch("/{project}/items/{item}", response_model=OkrItem)
async def set_item(
    request: Request,
    project: ProjectName,
    item: ItemName,
    body: OkrItemPatch,
    user: hub.Caller,
    sink: Sink = None,
    render: Render = None,
):
    """Change an item's fields or parents (writer); 409 for an item a source writes."""

    async def work(conn):
        return await service.set_item(conn, await service.viewer(conn, user, project, sink), item, body)

    return _words(await _answer(request, work), render, cli_text.item)


@router.post("/{project}/items/{item}/links", status_code=201, response_model=OkrLinkMade)
async def link(
    request: Request,
    response: Response,
    project: ProjectName,
    item: ItemName,
    body: OkrLinkIn,
    user: hub.Caller,
    sink: Sink = None,
    render: Render = None,
):
    """Link the item to a task, use case, plan or goal the project holds (writer); 200 when it was linked already."""

    async def work(conn):
        return await service.link(conn, await service.viewer(conn, user, project, sink), item, body)

    found = await _answer(request, work)
    if not found.made:
        response.status_code = 200
    return _words(found, render, cli_text.linked)


@router.delete("/{project}/items/{item}/links/{link_id}", response_model=OkrUnlinked)
async def unlink(
    request: Request,
    project: ProjectName,
    item: ItemName,
    link_id: Annotated[int, Path(ge=1, description="the link's id, as the item shows it")],
    user: hub.Caller,
    sink: Sink = None,
    render: Render = None,
):
    """Take a link off the item (writer); an item a source writes keeps its links editable."""

    async def work(conn):
        return await service.unlink(conn, await service.viewer(conn, user, project, sink), item, link_id)

    return _words(await _answer(request, work), render, cli_text.unlinked)


@router.post("/{project}/import", response_model=OkrImported)
async def import_bundle(
    request: Request,
    project: ProjectName,
    body: OkrImportIn,
    user: hub.Caller,
    sink: Sink = None,
    render: Render = None,
):
    """Upsert a source's items by ref and add their links (writer); dry_run writes nothing and answers the same."""

    async def work(conn):
        return await service.import_bundle(conn, await service.viewer(conn, user, project, sink), body)

    return _words(await _answer(request, work), render, cli_text.imported)


__all__ = ["router"]
