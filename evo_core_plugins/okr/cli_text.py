"""The words of ``evo-agents hub okr tree|show|add|set|link|unlink|import`` without ``--json``: the routes answer them
for the query ``render=text`` (``cli.json``, ``output.render``), and the CLI prints them as they are. Each function
takes what the route answers as JSON. Standard library only.
"""

from __future__ import annotations

INDENT = "  "


def table(header: tuple[str, ...], rows: list[tuple]) -> list[str]:
    """The lines of a table as the CLI prints one: each column as wide as its widest cell, two spaces between."""
    widths = [max(len(str(cell)) for cell in column) for column in zip(header, *rows, strict=False)]
    lines = (("  ".join(str(c).ljust(w) for c, w in zip(row, widths, strict=True))).rstrip() for row in (header, *rows))
    return list(lines)


def percent(progress) -> str:
    return "-" if progress is None else f"{round(progress * 100)}%"


def goal(found: dict | None) -> str:
    if not found:
        return ""
    value = "" if found.get("value") is None else f" {found['value']:g}"
    return f"goal {found['code']} {found['state']}{value}"


def figures(rollup: dict, kind: str) -> str:
    """What the roll-up of an item says on its line."""
    said = [percent(rollup["progress"])]
    if kind in ("business_line", "objective") and rollup["krs_total"]:
        said.append(f"KRs {rollup['krs_met']}/{rollup['krs_total']} met")
    if kind == "key_result":
        said.append(goal(rollup.get("goal")) or "no goal")
    if rollup["tasks_total"]:
        extra = [f"{rollup[k]} {k[6:]}" for k in ("tasks_late", "tasks_blocked") if rollup[k]]
        said.append(
            f"tasks {rollup['tasks_done']}/{rollup['tasks_total']}" + (f" ({', '.join(extra)})" if extra else "")
        )
    return ", ".join(said)


def _lines(node: dict, depth: int) -> list[str]:
    head = (
        f"{INDENT * depth}{node['code']}  {node['title']}  [{node['status']}]  {figures(node['rollup'], node['kind'])}"
    )
    return [head.rstrip()] + [line for child in node["children"] for line in _lines(child, depth + 1)]


def gaps(found: list[dict]) -> list[str]:
    if not found:
        return []
    return ["Gaps:"] + [f"{INDENT}{gap['kind']}  {gap['item']}  {gap['detail']}" for gap in found]


def tree(found: dict) -> str:
    if not found["roots"]:
        return f"No item in the OKR tree of {found['project']} yet: `evo-agents hub okr add` or `import`"
    lines = [line for root in found["roots"] for line in _lines(root, 0)]
    return "\n".join(lines + gaps(found["gaps"]))


def link_row(link: dict) -> tuple:
    if link["gone"]:
        state = "gone"
    else:
        state = link.get("status") or ""
        if link.get("total"):
            state += f" {link['done']}/{link['total']}"
        state += " late" if link.get("late") else ""
        state += " blocked" if link.get("blocked") else ""
    title = link.get("title") or ("" if link["visible"] else "(hidden)")
    return (link["id"], link["kind"], link["target"], state.strip(), title)


def item(found: dict) -> str:
    lines = [f"{found['code']}  {found['title']}  [{found['status']}]  {found['kind'].replace('_', ' ')}"]
    facts = [
        (name, found.get(name))
        for name in ("ref", "owner", "period", "due", "baseline", "target", "source", "source_url")
        if found.get(name)
    ]
    lines += [f"{name}: {value}" for name, value in facts]
    if found["parents"]:
        lines.append("Under: " + ", ".join(f"{p['code']} {p['title']}" for p in found["parents"]))
    if found["children"]:
        lines.append("Over: " + ", ".join(f"{c['code']} {c['title']}" for c in found["children"]))
    lines.append("Progress: " + figures(found["rollup"], found["kind"]))
    if found["links"]:
        lines += table(("link", "kind", "target", "state", "title"), [link_row(k) for k in found["links"]])
    lines += gaps(found["gaps"])
    if found.get("body_md"):
        lines += ["", found["body_md"]]
    return "\n".join(lines)


def linked(found: dict) -> str:
    link = found["link"]
    verb = "links" if found["made"] else "linked already"
    return f"{found['item']} {verb} {link['kind']} {link['target']} (link {link['id']})"


def unlinked(found: dict) -> str:
    link = found["link"]
    return f"Took link {link['id']} ({link['kind']} {link['target']}) off {found['item']}"


def imported(found: dict) -> str:
    words = ("created", "updated", "unchanged", "missing")
    head = f"Source {found['source']}" + (" (dry run, nothing written)" if found["dry_run"] else "")
    lines = [head + ": " + ", ".join(f"{len(found[word])} {word}" for word in words)]
    for word in ("created", "updated", "missing"):
        for entry in found[word]:
            extra = f" ({', '.join(entry['fields'])})" if entry.get("fields") else ""
            extra += " archived" if entry.get("archived") else ""
            lines.append(f"{INDENT}{word} {entry['code']} {entry['ref']}{extra}")
    results = [link["result"] for link in found["links"]]
    if results:
        counted = ", ".join(f"{results.count(r)} {r}" for r in ("added", "exists", "not_found", "refused"))
        lines.append(f"Links: {counted}")
    for link in found["links"]:
        if link["result"] in ("not_found", "refused"):
            lines.append(f"{INDENT}{link['result']} {link['item']} {link['kind']} {link['target']}: {link['detail']}")
    return "\n".join(lines)
