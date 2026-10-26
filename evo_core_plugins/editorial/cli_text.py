"""The words of ``evo-agents hub editorial`` without ``--json``: the routes answer them for the query ``render=text``
(``cli.json``, ``output.render``), and the CLI prints them as they are. Each function takes what the route answers as
JSON. Standard library only.
"""

from __future__ import annotations

import json


def table(header: tuple[str, ...], rows: list[tuple]) -> list[str]:
    """The lines of a table as the CLI prints one: each column as wide as its widest cell, two spaces between."""
    widths = [max(len(str(cell)) for cell in column) for column in zip(header, *rows, strict=False)]
    lines = (("  ".join(str(c).ljust(w) for c, w in zip(row, widths, strict=True))).rstrip() for row in (header, *rows))
    return list(lines)


def _day(value: str | None) -> str:
    return (value or "")[:10]


def posts(found: list) -> str:
    if not found:
        return "No posts yet: `evo-agents hub editorial set <slug> --stage <stage>` makes one"
    rows = [
        (p["slug"], p["stage"], p["waiting_gate"] or "-", p["rounds"], p["url"] or p["preview_url"] or "-")
        for p in found
    ]
    return "\n".join(table(("slug", "stage", "waiting gate", "rounds", "link"), rows))


def post(found: dict) -> str:
    lines = [f"{found['slug']}  {found['title']}".rstrip(), f"stage {found['stage']}"]
    for name, title in (("branch", "branch"), ("preview_url", "preview"), ("url", "url")):
        if found.get(name):
            lines.append(f"{title} {found[name]}")
    for name in ("d7", "d28"):
        if found.get(name):
            lines.append(f"{name}: " + ", ".join(f"{k} {v}" for k, v in found[name].items()))
    if found["gates"]:
        lines.append("Gates:")
        rows = [
            (g["stage"], g["kind"], g["state"], _day(g["answered_at"]), g["answered_via"] or "", g["answered_by"] or "")
            for g in found["gates"]
        ]
        lines += ["  " + line for line in table(("stage", "kind", "state", "answered", "via", "by"), rows)]
    for item in found["rounds"]:
        lines.append(f"Round {item['number']} at {item['stage']}, {_day(item['at'])}: {len(item['comments'])} comments")
        if item["note"]:
            lines.append(f"  {item['note']}")
        lines += [f"  {c['author'] or '?'}: {c['text']}" for c in item["comments"]]
    if found["feedback"]:
        lines.append("Feedback: " + ", ".join(found["feedback"]))
    return "\n".join(lines)


def entries(found: list) -> str:
    if not found:
        return "No entries"
    rows = [(e["id"], e["notebook"], e["seen"], e["post"] or "-", e["title"]) for e in found]
    lines = table(("id", "notebook", "seen", "post", "title"), rows)
    if len(found) == 1:
        lines += ["", f"Rule: {found[0]['rule']}"]
    return "\n".join(lines)


def imported(found: dict) -> str:
    return (
        f"Posts: {found['posts_added']} added, {found['posts_updated']} updated. "
        f"Entries: {found['entries_added']} added, {found['entries_updated']} updated."
    )


def exported(found: dict) -> str:
    """With markdown, each notebook's file as it is (one notebook prints exactly its file, as print ends it with its
    newline), a blank line between two; with json, the file import takes."""
    if found["format"] == "json":
        return json.dumps(found["document"], ensure_ascii=False, indent=2)
    return "\n\n".join(book["markdown"].removesuffix("\n") for book in found["notebooks"])


__all__ = ["entries", "exported", "imported", "post", "posts", "table"]
