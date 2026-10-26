"""The feedback notebook as markdown, in the format a project kept it in before the plugin held it, one file per
notebook: what ``evo-agents hub editorial export`` prints for a backup or a rollback, and what ``recall`` and
``feedback list`` print as text.

A notebook file is its title as ``# <title>``, a blank line, the notebook's intro and a blank line when it has one,
then its entries in the order of their ids, a blank line between two, and one newline at the end. An entry is::

    ## PH-0042 <title>

    - Ngày: 2026-10-02
    - Bài: <post slug, or ->
    - <person>: "<what the person said>"
    - <person>: "<what they said when it came back>" (2026-10-09, <note>)
    - Agent viết: "<the sentence the agent wrote>"
    - <person> sửa: "<the sentence the person fixed it to>"
    - Luật: <the rule>
    - Kiểm: <how it is checked: by a machine or by a reviewer>
    - Lần gặp: 2

``<person>`` is the name the project's config gives (``person``). The line of the agent's sentence and the line of the
fixed one stand after the said lines unless ``agent_after`` or ``fixed_after`` puts them after that many said lines;
the agent's comes first when both stand at the same place. The labels are the notebook's own words and stay as they
are, so an export reads as the files did. Standard library only.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

PREFIX = "PH-"


def entry_id(number: int) -> str:
    """The id of entry ``number``: PH- and at least four digits."""
    return f"{PREFIX}{number:04d}"


def entry_number(text: str) -> int | None:
    """The number of an entry id (PH-0042, PH-42 or 42), None when ``text`` is none."""
    raw = text.strip().upper()
    raw = raw[len(PREFIX) :] if raw.startswith(PREFIX) else raw
    return int(raw) if raw.isdigit() and int(raw) > 0 else None


def _quoted(text: str, *notes: str | None) -> str:
    said = [note for note in notes if note]
    return f'"{text}"' + (f" ({', '.join(said)})" if said else "")


def _middle(entry: Mapping, person: str) -> list[str]:
    """The said lines with the agent's line and the fixed line where they stand."""
    said = list(entry.get("said") or [])
    placed: dict[int, list[str]] = {}
    if entry.get("agent_wrote"):
        at = entry.get("agent_after")
        placed.setdefault(len(said) if at is None else min(at, len(said)), []).append(
            f"- Agent viết: {_quoted(entry['agent_wrote'], entry.get('agent_note'))}"
        )
    if entry.get("person_fixed"):
        at = entry.get("fixed_after")
        placed.setdefault(len(said) if at is None else min(at, len(said)), []).append(
            f"- {person} sửa: {_quoted(entry['person_fixed'], entry.get('fixed_note'))}"
        )
    lines: list[str] = []
    for index, item in enumerate(said):
        lines += placed.get(index, [])
        lines.append(f"- {person}: {_quoted(item['text'], item.get('date'), item.get('note'))}")
    return lines + placed.get(len(said), [])


def entry_markdown(entry: Mapping, person: str) -> str:
    """One entry, from its heading to its Lần gặp line, with no newline at the end."""
    lines = [
        f"## {entry_id(entry['number'])} {entry['title']}",
        "",
        f"- Ngày: {entry['date']}",
        f"- Bài: {entry.get('post') or '-'}",
        *_middle(entry, person),
        f"- Luật: {entry['rule']}",
    ]
    if entry.get("check"):
        lines.append(f"- Kiểm: {entry['check']}")
    lines.append(f"- Lần gặp: {entry['seen']}")
    return "\n".join(lines)


def entries_markdown(entries: Iterable[Mapping], person: str) -> str:
    """Entries one after another, a blank line between two, no newline at the end."""
    return "\n\n".join(entry_markdown(entry, person) for entry in entries)


def notebook_markdown(title: str, intro: str | None, entries: Iterable[Mapping], person: str) -> str:
    """The file of one notebook: title, intro, its entries by id, one newline at the end."""
    parts = [f"# {title}"]
    if intro and intro.strip():
        parts.append(intro.strip("\n"))
    body = entries_markdown(sorted(entries, key=lambda entry: entry["number"]), person)
    if body:
        parts.append(body)
    return "\n\n".join(parts) + "\n"


__all__ = ["entries_markdown", "entry_id", "entry_markdown", "entry_number", "notebook_markdown"]
