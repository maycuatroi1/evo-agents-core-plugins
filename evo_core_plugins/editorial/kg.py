"""The source ``plugin.editorial`` of a project's knowledge graph: one item for each entry of the feedback notebook
(``plugin.editorial:feedback:PH-0042``, its markdown as the notebook prints it) and one for each post
(``plugin.editorial:post:<slug>``, its stage, links and gates), each with its own label.
"""

from __future__ import annotations

from datetime import UTC, datetime

from evo_agents.hub.server import core_plugin_api as hub
from evo_core_plugins.editorial import ledger, settings, store


def utc_text(value: datetime) -> str:
    """A time as the graph keeps it (as ``evo_agents.kg.ids.utc_text`` writes it), which sorts as text in time
    order."""
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def entry_item(source: str, entry: store.Entry, person: str) -> dict:
    """The kg/1 item of a notebook entry: its block of markdown, its notebook, post, rule and times seen."""
    return {
        "id": f"{source}:feedback:{entry.id}",
        "kind": "doc",
        "title": f"{entry.id} {entry.title}",
        "rev_time": utc_text(entry.updated_at),
        "fragments": [{"anchor": "_preamble", "level": 0, "text": ledger.entry_markdown(entry.as_ledger(), person)}],
        "props": {
            "entry": entry.id,
            "notebook": entry.notebook,
            "post": entry.post,
            "rule": entry.rule,
            "seen": entry.seen,
        },
        "label": entry.label,
    }


def post_item(source: str, post: store.Post, gates: list[store.Gate]) -> dict:
    """The kg/1 item of a post: its title, stage, links and the state of each gate."""
    lines = [f"{post.title or post.slug}: stage {post.stage}"]
    lines += [f"{name} {value}" for name, value in (("preview", post.preview_url), ("url", post.url)) if value]
    lines += [f"gate {gate.stage} ({gate.kind}): {gate.state}" for gate in gates]
    return {
        "id": f"{source}:post:{post.slug}",
        "kind": "doc",
        "title": post.title or post.slug,
        "rev_time": utc_text(post.updated_at),
        "fragments": [{"anchor": "_preamble", "level": 0, "text": "\n".join(lines)}],
        "props": {"slug": post.slug, "stage": post.stage, "url": post.url, "preview_url": post.preview_url},
        "label": post.label,
    }


async def kg_source(params: dict, context: hub.Context) -> dict:
    """The contribution ``notebook``: ``params`` names the source and the project."""
    if context.engine is None or context.project_id is None or context.project is None:
        return {"items": [], "identifiers": []}
    async with hub.transaction(context) as conn:
        cfg = await settings.config(conn, context.project)
        entries = await store.entries(conn, context.project_id)
        posts = await store.posts(conn, context.project_id)
        gates = await store.gates(conn, [post.id for post in posts])
    source = params["source"]
    items = [entry_item(source, entry, cfg.person) for entry in entries]
    items += [post_item(source, post, gates.get(post.id, [])) for post in posts]
    return {"items": items, "identifiers": []}


__all__ = ["entry_item", "kg_source", "post_item"]
