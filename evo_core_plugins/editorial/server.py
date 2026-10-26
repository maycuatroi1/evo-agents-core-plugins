"""The routes of the plugin editorial, under /v1/x/editorial/<project>/ for a member with a grant on a project that
enabled it (the hub checks both first; a project that did not enable it answers 404).

A reader reads the posts (``GET /{project}/posts?stage=``), one post with its gates, review rounds and comments
(``GET /{project}/posts/{slug}``), the feedback notebook (``GET /{project}/feedback?notebook=&stage=&post=&seen=&q=``),
what to read before a stage (``GET /{project}/recall?stage=&post=&q=``) and the export (``GET /{project}/export``). A
writer sets a post's state (``POST /{project}/posts/{slug}``), adds an entry (``POST /{project}/feedback``) and
records a repeat (``POST /{project}/feedback/{entry}/repeat``). An admin imports (``POST /{project}/import``). Reads go
through the sink X-Evo-Sink names, else the project's hub sink: what the caller may not read is not there for them.

``evo-agents hub editorial feedback list|add|repeat`` is one command whose first word reaches the route as the query
``action``: the route refuses a word that does not fit it, so ``feedback add`` without what was said is no listing.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Header, Path, Query, Request
from fastapi.responses import JSONResponse

from evo_agents.hub.server import core_plugin_api as hub
from evo_core_plugins.editorial import cli_text, service, store
from evo_core_plugins.editorial.models import (
    EditorialEntry,
    EditorialExport,
    EditorialFeedbackIn,
    EditorialImported,
    EditorialImportIn,
    EditorialPost,
    EditorialPostSummary,
    EditorialRepeatIn,
    EditorialSetIn,
)
from evo_core_plugins.editorial.tables import NAME, SLUG

REFUSALS = {code: {"model": hub.ErrorBody} for code in (403, 404, 409, 422)}
ProjectName = Annotated[str, Path(pattern=hub.PROJECT_NAME)]
Slug = Annotated[str, Path(pattern=SLUG, description="the post's slug")]
Sink = Annotated[str | None, Header(alias=store.SINK_HEADER)]
Render = Annotated[
    Literal["text"] | None,
    Query(description="text: the words `evo-agents hub editorial` prints, as {text}, instead of the answer"),
]
StageQuery = Annotated[str | None, Query(pattern=NAME, description="a stage of the project's config")]
NotebookQuery = Annotated[str | None, Query(pattern=NAME, description="a notebook of the project's config")]
PostQuery = Annotated[str | None, Query(pattern=SLUG, description="a post's slug")]
Keyword = Annotated[str | None, Query(max_length=200, description="every word of it, in any case")]
Action = Annotated[Literal["list", "add", "repeat"] | None, Query(description="what the CLI was asked to do")]

router = APIRouter(tags=["plugins"], responses={401: {"model": hub.ErrorBody}, **REFUSALS})


def _words(found, render: str | None, word):
    """``found``, or with ``render`` text the words of it the CLI prints (``cli_text``)."""
    if render != "text":
        return found
    if isinstance(found, list):
        data = [item.model_dump(mode="json") for item in found]
    else:
        data = found.model_dump(mode="json")
    return JSONResponse({"text": word(data)})


async def _answer(request: Request, work):
    """``work(conn)`` in one transaction; a refusal (``hub.Refused``) is the hub's error body, nothing written."""
    async with hub.begin(request) as conn:
        return await work(conn)


def _action(action: str | None, wanted: str, hint: str) -> None:
    if action is not None and action != wanted:
        raise hub.Refused(422, hint)


@router.get("/{project}/posts", response_model=list[EditorialPostSummary])
async def list_posts(
    request: Request,
    project: ProjectName,
    user: hub.Caller,
    stage: StageQuery = None,
    sink: Sink = None,
    render: Render = None,
):
    """The posts by the order of their stages: the gate that waits, the preview and the url, how many rounds."""

    async def work(conn):
        return await service.list_posts(conn, await service.viewer(conn, user, project, sink), stage)

    return _words(await _answer(request, work), render, cli_text.posts)


@router.get("/{project}/posts/{slug}", response_model=EditorialPost)
async def show_post(
    request: Request, project: ProjectName, slug: Slug, user: hub.Caller, sink: Sink = None, render: Render = None
):
    """One post with its gates, review rounds and comments, the stages it entered and its feedback entries."""

    async def work(conn):
        return await service.show_post(conn, await service.viewer(conn, user, project, sink), slug)

    return _words(await _answer(request, work), render, cli_text.post)


@router.post("/{project}/posts/{slug}", response_model=EditorialPost)
async def set_post(
    request: Request,
    project: ProjectName,
    slug: Slug,
    body: EditorialSetIn,
    user: hub.Caller,
    sink: Sink = None,
    render: Render = None,
):
    """Set a post's stage, title, links, figures or the state of one of its gates; a new slug makes the post."""

    async def work(conn):
        return await service.set_post(conn, await service.viewer(conn, user, project, sink), slug, body)

    return _words(await _answer(request, work), render, cli_text.post)


@router.get("/{project}/recall", response_model=list[EditorialEntry])
async def recall(
    request: Request,
    project: ProjectName,
    user: hub.Caller,
    stage: StageQuery = None,
    post: PostQuery = None,
    q: Keyword = None,
    sink: Sink = None,
    render: Render = None,
):
    """What to read before a stage: the entries of its notebooks and those about the post, seen most first."""

    async def work(conn):
        who = await service.viewer(conn, user, project, sink)
        found = await service.recall(conn, who, stage=stage, post=post, keyword=q)
        return [service.entry_model(entry) for entry in found]

    return _words(await _answer(request, work), render, cli_text.entries)


@router.get("/{project}/feedback", response_model=list[EditorialEntry])
async def list_feedback(
    request: Request,
    project: ProjectName,
    user: hub.Caller,
    notebook: NotebookQuery = None,
    stage: StageQuery = None,
    post: PostQuery = None,
    seen: Annotated[int | None, Query(ge=1, description="seen at least this many times")] = None,
    q: Keyword = None,
    action: Action = None,
    sink: Sink = None,
    render: Render = None,
):
    """The entries of the feedback notebook by number, of a notebook, a stage, a post, seen at least so often."""
    _action(action, "list", "feedback add needs --said, --title and --rule; feedback repeat needs the entry, PH-<n>")

    async def work(conn):
        who = await service.viewer(conn, user, project, sink)
        found = await service.list_feedback(conn, who, notebook=notebook, stage=stage, post=post, seen=seen, keyword=q)
        return [service.entry_model(entry) for entry in found]

    return _words(await _answer(request, work), render, cli_text.entries)


@router.post("/{project}/feedback", status_code=201, response_model=list[EditorialEntry])
async def add_feedback(
    request: Request,
    project: ProjectName,
    body: EditorialFeedbackIn,
    user: hub.Caller,
    notebook: NotebookQuery = None,
    post: PostQuery = None,
    action: Action = None,
    sink: Sink = None,
    render: Render = None,
):
    """A new entry of the notebook, numbered after the last; the answer is a list of that one entry."""
    _action(action, "add", "feedback repeat takes the entry, PH-<n>, and no --said of a new entry without it")

    async def work(conn):
        who = await service.viewer(conn, user, project, sink)
        given = body.model_copy(update={"notebook": body.notebook or notebook, "post": body.post or post})
        return [service.entry_model(await service.add_feedback(conn, who, given))]

    return _words(await _answer(request, work), render, cli_text.entries)


@router.post("/{project}/feedback/{entry}/repeat", response_model=list[EditorialEntry])
async def repeat_feedback(
    request: Request,
    project: ProjectName,
    entry: Annotated[str, Path(max_length=20, description="the entry, PH-<n>")],
    body: EditorialRepeatIn,
    user: hub.Caller,
    action: Action = None,
    sink: Sink = None,
    render: Render = None,
):
    """The entry came back: seen once more, with what the person said this time; a list of that one entry."""
    _action(action, "repeat", "an entry, PH-<n>, goes with feedback repeat")

    async def work(conn):
        who = await service.viewer(conn, user, project, sink)
        return [service.entry_model(await service.repeat_feedback(conn, who, entry, body))]

    return _words(await _answer(request, work), render, cli_text.entries)


@router.post("/{project}/import", response_model=EditorialImported)
async def import_document(
    request: Request,
    project: ProjectName,
    body: EditorialImportIn,
    user: hub.Caller,
    sink: Sink = None,
    render: Render = None,
):
    """Write the posts and entries of a JSON file, keeping their ids; the same file twice adds nothing (admin)."""

    async def work(conn):
        who = await service.viewer(conn, user, project, sink)
        return await service.import_document(conn, who, body.file, body.document)

    return _words(await _answer(request, work), render, cli_text.imported)


@router.get("/{project}/export", response_model=EditorialExport)
async def export(
    request: Request,
    project: ProjectName,
    user: hub.Caller,
    notebook: NotebookQuery = None,
    form: Annotated[Literal["markdown", "json"], Query(alias="format")] = "markdown",
    sink: Sink = None,
    render: Render = None,
):
    """The notebook as its markdown files, or with format json everything import takes."""

    async def work(conn):
        return await service.export(conn, await service.viewer(conn, user, project, sink), notebook, form)

    return _words(await _answer(request, work), render, cli_text.exported)


__all__ = ["router"]
