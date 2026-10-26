"""The core plugin editorial: the posts of a project's blog on their way out, and the notebook of what the person who
reviews them said (``docs/editorial-plugin.md``).

A post (slug, title, stage, branch, preview link, url, the figures 7 and 28 days after it went out) moves through the
stages the project's config lists in order; a stage with a gate (choose, interview, comments or publish) waits there for
a person, and the gate keeps when it was answered and through what. A post keeps its review rounds and the comments of
each. The feedback notebook keeps one entry for each thing the person corrected: its id PH-<n>, the day, the post, the
notebook, the person's words with their dates, what the agent wrote and what the person changed it to, the rule, how it
is checked, how many times it was seen, and the curator probe of the rule. ``export`` prints a notebook as the markdown
file it was kept in, and ``import`` takes the JSON of posts and entries and keeps their ids.

No stage is named in the code: the config lists them (``settings``). The routes under ``/v1/x/editorial/<project>``
(``server``) serve the pages Posts and Feedback (``ui/pages``), ``evo-agents hub editorial`` (``cli.json``) and the
tools ``editorial__state``, ``editorial__recall`` and ``editorial__feedback`` (``tools``); the knowledge graph's
source gives one item for each entry and each post (``kg``). The plugin runs no job and calls no other service. The
package imports no other core plugin (import-linter contract ``plugins-own-package``).
"""

import json
from pathlib import Path

SERVER = "evo_core_plugins.editorial.server"
TOOLS = "evo_core_plugins.editorial.tools"
KG = "evo_core_plugins.editorial.kg"

TABLES = (
    ("editorial_posts", "The posts of a project: slug, title, stage, branch, preview link, url and figures"),
    ("editorial_stage_history", "Each stage a post entered, when, and what showed it"),
    ("editorial_gates", "The gate of a post at a stage: its kind, state, and when and through what it was answered"),
    ("editorial_rounds", "The review rounds of a post at each stage"),
    ("editorial_comments", "The comments of a review round, by the id their source gave them"),
    ("editorial_feedback", "The feedback notebook: one entry PH-<n> for each thing the person corrected"),
)

PAGES = {
    "posts": {
        "title": "Posts",
        "icon": "kanban",
        "description": "The posts by stage, the gate that waits, previews and review rounds",
        "entry": "pages/posts.html",
    },
    "feedback": {
        "title": "Feedback notebook",
        "icon": "notebook-pen",
        "description": "What the reviewer corrected, by notebook, stage, post and times seen",
        "entry": "pages/feedback.html",
    },
}

# The commands of `evo-agents hub editorial`, a file the CLI reads too without importing the plugin (cli_plugin_commands)
CLI = json.loads(Path(__file__).with_name("cli.json").read_text(encoding="utf-8"))


def _tools() -> list[dict]:
    from evo_core_plugins.editorial import tools

    return [
        {
            "name": "state",
            "title": "Read or set the state of a post",
            "description": "With no slug, the posts by stage with the gate that waits; with a slug, one post with its "
            "gates, review rounds and comments; with set, change its stage, links, figures or a gate's state (writer).",
            "python": f"{TOOLS}:state",
            "input_schema": tools.STATE_SCHEMA,
        },
        {
            "name": "recall",
            "title": "What to read before a stage",
            "description": "The feedback entries of the notebooks a stage reads and those about a post, narrowed by a "
            "keyword, seen most first. Read them before writing.",
            "python": f"{TOOLS}:recall",
            "input_schema": tools.RECALL_SCHEMA,
        },
        {
            "name": "feedback",
            "title": "Add to the feedback notebook",
            "description": "add: a new entry with what the person said, the rule and how it is checked. repeat: an "
            "entry came back, seen once more, with what the person said this time (writer).",
            "python": f"{TOOLS}:feedback",
            "input_schema": tools.FEEDBACK_SCHEMA,
        },
    ]


def _manifest() -> dict:
    from evo_core_plugins.editorial.settings import CONFIG

    return {
        "id": "editorial",
        "version": "1.1.0",
        "publisher": "evo-agents",
        "tier": "core",
        "name": "Editorial",
        "description": "The posts of a blog through their stages and gates, and the notebook of the reviewer's feedback.",
        "engines": {"evo-agents": ">=0.21"},
        "plugin_api": 1,
        "permissions": [],
        "config": CONFIG,
        "schema": {
            "metadata": "evo_core_plugins.editorial.tables:metadata",
            "migrations": "evo_core_plugins.editorial.migrations",
        },
        "ui": "evo_core_plugins.editorial:ui",
        "contributes": {
            "routes": [
                {"name": "editorial", "title": "The posts and the feedback notebook", "python": f"{SERVER}:router"}
            ],
            "pages": [{"name": name, **page} for name, page in PAGES.items()],
            "mcp_tools": _tools(),
            "kg_sources": [
                {
                    "name": "notebook",
                    "title": "The feedback notebook's entries and the posts of a project",
                    "python": f"{KG}:kg_source",
                }
            ],
            "tables": [{"name": name, "title": title} for name, title in TABLES],
            "cli": CLI,
        },
    }


API = (1, 4)  # the version of the core plugin API the plugin is written for


def manifest() -> dict:
    """The manifest, once this hub serves the version of the API the plugin is written for. The API is imported here:
    every process that reads the entry points imports this module, the CLI included."""
    from evo_agents.hub.server import core_plugin_api as hub

    hub.require(*API)
    return _manifest()


__all__ = ["manifest"]
