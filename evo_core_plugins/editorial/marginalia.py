"""The draft comments of a post, read from the comment service the blog's pages use (Marginalia, kept in Firestore).

A reviewer highlights a sentence of the draft preview and comments on it; the page keeps the comment in the
collection the config names (``marginalia_comments``) under the post's key ``draft:<comment_id>``, with the sentence
(``anchor.exact``), the text (``body``), the author (``author.name``), when (``createdAt``) and its state (``status``
visible or hidden). Those documents are readable by anyone: the plugin reads them with Firestore's REST API and the
project's web API key, which is public, and no credential (``settings.Comments``). It never writes there.

``pull`` keeps the comments of the reviewers the config lists (by their name in the service) in the post's latest round
at its stage with a comments gate, each once by the document's id. It runs when the post enters that stage and when a
person asks for it (the page's button, ``editorial__comments``), never on a schedule. ``FETCH`` is what reads the
service; a test puts a fake there.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime

from evo_core_plugins.editorial.settings import Comments

BASE = "https://firestore.googleapis.com/v1"
TIMEOUT = 15.0
MAX_COMMENTS = 500
KEY = "draft:"


@dataclass(frozen=True)
class Found:
    id: str
    author: str | None
    quote: str | None
    text: str
    at: datetime | None
    parent: str | None


def key(comment_id: str) -> str:
    """The post's key in the service."""
    return f"{KEY}{comment_id}"


def query(service: Comments, post_key: str) -> dict:
    """The body of ``runQuery``: the visible comments of the post."""

    def equal(field: str, value: str) -> dict:
        return {"fieldFilter": {"field": {"fieldPath": field}, "op": "EQUAL", "value": {"stringValue": value}}}

    return {
        "structuredQuery": {
            "from": [{"collectionId": service.collection}],
            "where": {
                "compositeFilter": {"op": "AND", "filters": [equal("postId", post_key), equal("status", "visible")]}
            },
            "limit": MAX_COMMENTS,
        }
    }


async def fetch(service: Comments, post_key: str) -> list[dict]:
    """The documents ``runQuery`` answers for the post, as Firestore's REST API gives them."""
    import httpx

    url = f"{BASE}/projects/{service.project_id}/databases/(default)/documents:runQuery"
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        answer = await client.post(url, params={"key": service.api_key}, json=query(service, post_key))
    answer.raise_for_status()
    return [item["document"] for item in answer.json() if isinstance(item, dict) and "document" in item]


FETCH: Callable[[Comments, str], Awaitable[list[dict]]] = fetch


def _value(field: dict | None):
    """The Python value of one Firestore field."""
    if not isinstance(field, dict):
        return None
    for kind in ("stringValue", "timestampValue", "booleanValue", "integerValue", "doubleValue"):
        if kind in field:
            return field[kind]
    if "mapValue" in field:
        return {name: _value(value) for name, value in (field["mapValue"].get("fields") or {}).items()}
    return None


def _when(text) -> datetime | None:
    if not isinstance(text, str):
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def read(document: dict) -> Found | None:
    """One comment of a document, None for one that is deleted, hidden or holds no text."""
    fields = {name: _value(value) for name, value in (document.get("fields") or {}).items()}
    body = fields.get("body")
    if fields.get("deleted") is True or fields.get("status") not in (None, "visible") or not isinstance(body, str):
        return None
    anchor = fields.get("anchor") if isinstance(fields.get("anchor"), dict) else {}
    author = fields.get("author") if isinstance(fields.get("author"), dict) else {}
    name = str(document.get("name") or "").rsplit("/", 1)[-1]
    if not name or not body.strip():
        return None
    parent = fields.get("parentId")
    return Found(
        name,
        author.get("name") if isinstance(author.get("name"), str) else None,
        anchor.get("exact") if isinstance(anchor.get("exact"), str) else None,
        body,
        _when(fields.get("createdAt")),
        parent if isinstance(parent, str) and parent else None,
    )


def of_reviewers(documents: list[dict], reviewers: tuple[str, ...]) -> list[Found]:
    """The comments of the reviewers the config lists, by their name in the service, in time order."""
    wanted = {name.casefold() for name in reviewers}
    found = [item for item in (read(document) for document in documents) if item is not None]
    mine = [item for item in found if item.author and item.author.casefold() in wanted]
    return sorted(mine, key=lambda item: (item.at is None, item.at or datetime.min, item.id))


__all__ = ["FETCH", "Found", "fetch", "key", "of_reviewers", "query", "read"]
