"""The words of ``evo-agents hub jev status|ask|usage|acts|matches`` without ``--json``: the routes answer them for the query
``render=text`` (``cli.json``, ``output.render``), and the CLI prints them as they are. Each function takes what the
route answers as JSON. Standard library only.
"""

from __future__ import annotations

INDENT = "  "


def table(header: tuple[str, ...], rows: list[tuple]) -> list[str]:
    """The lines of a table as the CLI prints one: each column as wide as its widest cell, two spaces between."""
    widths = [max(len(str(cell)) for cell in column) for column in zip(header, *rows, strict=False)]
    lines = (("  ".join(str(c).ljust(w) for c, w in zip(row, widths, strict=True))).rstrip() for row in (header, *rows))
    return list(lines)


def usd(value: float) -> str:
    return f"{value:.4f} USD"


def status(found: dict) -> str:
    lines = [
        f"Jev in {found['project']}: {'ready' if not found['problems'] else 'not ready'}",
        f"{INDENT}model {found['model'] or '-'}, key {'set' if found['key_set'] else 'not set'}, "
        f"sink {found['sink']} {'declared' if found['sink_declared'] else 'not declared'}",
        f"{INDENT}spent today {usd(found['spent_today_usd'])} of {found['daily_usd']:g} USD "
        f"({found['price_usd_per_million_tokens']:g} USD per million input tokens)",
    ]
    lines += [f"{INDENT}{problem}" for problem in found["problems"]]
    rows = []
    for feature in found["features"]:
        cap = "" if feature["cap"] is None else f"{feature['applied_today']}/{feature['cap']} today"
        threshold = "" if feature["threshold"] is None else f"{feature['threshold']:g}"
        rows.append((feature["name"], feature["mode"], threshold, cap))
    return "\n".join(lines + [""] + table(("feature", "mode", "threshold", "applied"), rows))


def asked(found: dict) -> str:
    lines = [f"{found['model']}: {found['input_tokens']} input tokens, {usd(found['cost_usd'])}"]
    for name, answer in found["answers"].items():
        value = (
            answer["choice"]
            if answer["type"] == "choice"
            else answer["noul"]
            if answer["type"] == "noul"
            else answer["score"]
        )
        confidence = "" if answer.get("confidence") is None else f" (confidence {answer['confidence']:.2f})"
        lines.append(f"{INDENT}{name} [{answer['type']}]: {value}{confidence}")
    return "\n".join(lines)


def usage(found: dict) -> str:
    lines = [f"Jev in {found['project']}: today {usd(found['spent_today_usd'])} of {found['daily_usd']:g} USD"]
    for key, title in (("last_24h", "24 hours"), ("last_7d", "7 days")):
        window = found[key]
        lines.append(
            f"{title}: {window['calls']} calls ({window['failed']} failed), {window['input_tokens']} input tokens, "
            f"{usd(window['cost_usd'])}"
        )
        lines += [
            f"{INDENT}{row['feature']}: {row['calls']} calls, {usd(row['cost_usd'])}" for row in window["by_feature"]
        ]
    return "\n".join(lines)


def acts(found: dict) -> str:
    if not found["acts"]:
        return f"No act of Jev in {found['project']} yet"
    rows = [
        (
            act["id"],
            act["created_at"][:19].replace("T", " "),
            act["feature"],
            act["kind"],
            act["target"],
            act["outcome"],
            "-" if act["confidence"] is None else f"{act['confidence']:.2f}",
            "undone" if act["undone"] else "applied" if act["applied"] else "suggested",
        )
        for act in found["acts"]
    ]
    lines = table(("id", "when", "feature", "kind", "target", "outcome", "conf", "state"), rows)
    undo = [f"{INDENT}{act['id']}: {act['undo']['command']}" for act in found["acts"] if act["undo"]]
    return "\n".join(lines + (["", "Undo:"] + undo if undo else []))


def matches(found: dict) -> str:
    if not found["matches"]:
        return f"No correction of {found['project']} matched an earlier one or an accepted rule yet"
    rows = [
        (m["id"], m["day"], m["evidence"], m["candidate"], f"{m['confidence']:.2f}", m["state"])
        for m in found["matches"]
    ]
    return "\n".join(table(("id", "day", "evidence", "candidate", "conf", "state"), rows))
