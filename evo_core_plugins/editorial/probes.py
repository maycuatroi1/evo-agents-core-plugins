"""The probe of a feedback entry: whether an agent keeps the entry's rule, measured by the hub's curator (API 1.4,
``hub.add_probe``).

A person gives an entry a probe when adding it or later: a ``task`` an agent does in the project's repo of posts and a
``verify``, one shell line that exits 0 when the agent kept the rule. The plugin renders the rule file of the entry's
notebook twice: arm on holds every rule of the notebook, arm off the same file without this entry's rule, so the probe
measures this rule alone. The file is a skill of the repo's harness (``.claude/skills/editorial-<notebook>/SKILL.md``),
a path the hub places as a change's harness file. The probe's ref is the entry's id (``editorial:PH-<n>``); adding it
again replaces the active one, and removing it retires it, keeping its weeks in the report.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncConnection

from evo_agents.hub.server import core_plugin_api as hub
from evo_core_plugins.editorial import ledger, store
from evo_core_plugins.editorial.settings import Config, handle

MAX_TASK = 4000
MAX_VERIFY = 2000


def ref(number: int) -> str:
    return f"editorial:{ledger.entry_id(number)}"


def path(notebook: str) -> str:
    return f".claude/skills/editorial-{notebook}/SKILL.md"


def render(cfg: Config, notebook: str, entries: list[store.Entry]) -> str:
    """The rule file of ``notebook`` with the rules of ``entries``, in their order."""
    book = cfg.notebook(notebook)
    title = book.title if book else notebook
    lines = [
        "---",
        f"name: editorial-{notebook}",
        f"description: The rules of the {title}. Read them before writing or changing a post.",
        "---",
        "",
        f"# {title}",
        "",
    ]
    if book and book.intro:
        lines += [book.intro.strip(), ""]
    lines += [f"- {entry.title}: {entry.rule}" for entry in entries]
    return "\n".join(lines).rstrip() + "\n"


def arms(cfg: Config, entry: store.Entry, entries: list[store.Entry]) -> tuple[dict, dict]:
    """The files of arm on (the notebook's rules) and arm off (the same without ``entry``'s)."""
    mine = [item for item in entries if item.notebook == entry.notebook]
    if all(item.number != entry.number for item in mine):
        mine.append(entry)
    mine.sort(key=lambda item: item.number)
    on = {path(entry.notebook): render(cfg, entry.notebook, mine)}
    off = {path(entry.notebook): render(cfg, entry.notebook, [item for item in mine if item.number != entry.number])}
    return on, off


async def put(
    conn: AsyncConnection, project: str, project_id: int, cfg: Config, entry: store.Entry, task: str, verify: str
) -> int:
    """Add (or replace) the probe of ``entry``; its id, kept on the entry with the task and the verify."""
    if cfg.repo is None:
        raise hub.Refused(422, "a probe runs in the repo of the posts: set repo in the config of plugin editorial")
    task, verify = (task or "").strip(), (verify or "").strip()
    if not task or not verify:
        raise hub.Refused(422, "a probe needs its task and its verify, one shell line that exits 0 when kept")
    if len(task) > MAX_TASK or len(verify) > MAX_VERIFY:
        raise hub.Refused(422, f"a probe's task is at most {MAX_TASK} characters and its verify {MAX_VERIFY}")
    on, off = arms(cfg, entry, await store.entries(conn, project_id))
    try:
        probe_id = await hub.add_probe(
            conn, handle(), project, ref(entry.number), repo=cfg.repo, task=task, verify=verify, on=on, off=off
        )
    except ValueError as exc:
        raise hub.Refused(422, str(exc)) from None
    await store.set_entry(
        conn, project_id, entry.number, {"probe_id": probe_id, "probe_task": task, "probe_verify": verify}
    )
    return probe_id


async def remove(conn: AsyncConnection, project: str, project_id: int, entry: store.Entry) -> bool:
    """Retire the probe of ``entry``; whether it had one."""
    removed = await hub.remove_probe(conn, handle(), project, ref(entry.number), note="removed on the editorial page")
    await store.set_entry(conn, project_id, entry.number, {"probe_id": None, "probe_task": None, "probe_verify": None})
    return removed


__all__ = ["arms", "path", "put", "ref", "remove", "render"]
