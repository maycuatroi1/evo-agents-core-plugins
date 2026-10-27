"""The core plugin okr: a project's strategy as a tree, tied to what the hub delivers it with
(``docs/okr-plugin.md``).

The tree is business line -> objective -> key result -> deliverable, each item with a code of its kind (BL-1, O-1,
KR-1, D-1), a status (draft, active, done, dropped, archived), an owner, a period and a due date (``tables``). A
deliverable links to the hub's tasks, use cases of the plugin srs and plans; a key result links to the goal of the
project that measures it, a goal of the Loop with its metric and target. The plugin keeps the tree and the links in its
own tables, reads the hub's tasks, SRS items, plans, goals and signals through the core plugin API (``facts``) and
computes on read how far each deliverable, key result, objective and business line has come, and what the tree lacks
(``rules``): a roll-up that writes nothing.

A source outside the hub writes its items through ``import``, upserted by the ref it gave them; an item a source wrote
changes only through it, and its links stay editable on the hub. The routes under ``/v1/x/okr/<project>``
(``server``, ``service``, ``models``) serve the page ``tree`` (``ui/pages``), ``evo-agents hub okr`` (``cli.json``,
``cli_text``) and the tools ``okr__tree``, ``okr__item``, ``okr__link`` and ``okr__unlink`` (``tools``). The package
imports no other core plugin (import-linter contract ``plugins-own-package``).
"""

import json
from pathlib import Path

SERVER = "evo_core_plugins.okr.server"
TOOLS = "evo_core_plugins.okr.tools"

TABLES = (
    ("okr_items", "The items of a project's tree: kind, code, ref, title, status, owner, period, due, source"),
    ("okr_parents", "The edges of the tree: each item's parents"),
    ("okr_links", "What each item is delivered or measured by on the hub: tasks, use cases, plans, goals"),
)

PAGES = {
    "tree": {
        "title": "OKR",
        "icon": "workflow",
        "description": "The strategy as a tree, how far each part has come, its goals and its gaps",
        "entry": "pages/tree.html",
    },
}

# The commands of `evo-agents hub okr`, a file the CLI reads too without importing the plugin (cli_plugin_commands)
CLI = json.loads(Path(__file__).with_name("cli.json").read_text(encoding="utf-8"))


def _tools() -> list[dict]:
    from evo_core_plugins.okr import tools

    return [
        {
            "name": "tree",
            "title": "Read the OKR tree",
            "description": "The project's business lines, objectives, key results and deliverables, each with how far "
            "it has come (from the tasks, use cases and plans its deliverables link), its goal's state and its links, "
            "and the gaps: a deliverable with no link, a key result with no goal, an objective with no key result, "
            "what is late, links whose target is gone.",
            "python": f"{TOOLS}:tree",
            "input_schema": tools.TREE_SCHEMA,
        },
        {
            "name": "item",
            "title": "Read one item of the OKR tree",
            "description": "One item by its code (KR-3) or ref, with its parents, children, links, roll-up and gaps.",
            "python": f"{TOOLS}:item",
            "input_schema": tools.ITEM_SCHEMA,
        },
        {
            "name": "link",
            "title": "Link an item of the OKR tree",
            "description": "Link a deliverable to a task (T-12), a use case (<document>:<code>) or a plan (its slug), "
            "or a key result to its goal (G-3), once the project holds the target (writer).",
            "python": f"{TOOLS}:link",
            "input_schema": tools.LINK_SCHEMA,
        },
        {
            "name": "unlink",
            "title": "Take a link off an item of the OKR tree",
            "description": "Take a link off an item by the link's id, as okr__item lists it (writer).",
            "python": f"{TOOLS}:unlink",
            "input_schema": tools.UNLINK_SCHEMA,
        },
    ]


def _manifest() -> dict:
    return {
        "id": "okr",
        "version": "1.1.0",
        "publisher": "evo-agents",
        "tier": "core",
        "name": "OKR",
        "description": "A project's strategy as a tree of business lines, objectives, key results and deliverables, "
        "tied to the hub's tasks, use cases, plans and goals, with how far each part has come.",
        "engines": {"evo-agents": ">=0.21"},
        "plugin_api": 1,
        "permissions": [],
        "schema": {
            "metadata": "evo_core_plugins.okr.tables:metadata",
            "migrations": "evo_core_plugins.okr.migrations",
        },
        "ui": "evo_core_plugins.okr:ui",
        "contributes": {
            "routes": [{"name": "okr", "title": "The OKR tree of a project", "python": f"{SERVER}:router"}],
            "pages": [{"name": name, **page} for name, page in PAGES.items()],
            "mcp_tools": _tools(),
            "tables": [{"name": name, "title": title} for name, title in TABLES],
            "cli": CLI,
        },
    }


API = (1, 7)  # the version of the core plugin API the plugin is written for


def manifest() -> dict:
    """The manifest, once this hub serves the version of the API the plugin is written for. The API is imported here:
    every process that reads the entry points imports this module, the CLI included."""
    from evo_agents.hub.server import core_plugin_api as hub

    hub.require(*API)
    return _manifest()


__all__ = ["manifest"]
