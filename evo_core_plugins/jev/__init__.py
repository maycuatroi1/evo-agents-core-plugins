"""The core plugin jev: Jev, the System One model of TypeSafe, as a tool, a page and commands, with a ledger of what it
cost and what it decided (``docs/jev-plugin.md``).

Jev answers questions about a state, in one request: a choice among options, a noul (how much a yes, from 0 to 1) or a
score on ordered levels. The plugin sends project text out, so it declares the egress sink ``jev@typesafe`` (kind
``llm-backend``, host ``api.typesafe.ai``) in its manifest and does nothing in a project that did not enable it, set an
``api_key`` and a pinned ``model``, and declare the sink in its policy (``settings``). Every feature (triage, graph
review, corrections, rerank) is off until the project turns it on. The client (``client``) pins each call to the
public address it checked and keeps the key in one header. The routes under ``/v1/x/jev/<project>`` (``server``,
``service``, ``models``) serve the page ``jev`` (``ui/pages``), ``evo-agents hub jev`` (``cli.json``, ``cli_text``)
and the tools ``jev__decide`` and ``jev__usage`` (``tools``). The ledger is two tables of its own (``tables``,
``store``). The package imports no other core plugin (import-linter contract ``plugins-own-package``).
"""

import json
from pathlib import Path

from evo_core_plugins.jev.settings import CONFIG, HOST, SINK, SINK_KIND

SERVER = "evo_core_plugins.jev.server"
TOOLS = "evo_core_plugins.jev.tools"
TRIAGE = "evo_core_plugins.jev.triage"
REVIEW = "evo_core_plugins.jev.review"
CORRECTIONS = "evo_core_plugins.jev.corrections"
RANK = "evo_core_plugins.jev.rank"
REVIEW_CRON = "0 * * * *"  # every hour, after the builds that queue the review
CORRECTIONS_CRON = "30 1 * * *"  # once a day, after the UTC day it reads has ended

TABLES = (
    ("jev_usage", "Each call to Jev: the project, who made it, the feature, the model, the input tokens and the cost"),
    (
        "jev_acts",
        "What Jev decided: the kind, the target, the outcome, the model, the confidence, applied or not, undone",
    ),
    ("jev_asked", "What a feature put to a model once: the subject and the model, so it is not asked again"),
    (
        "jev_matches",
        "The corrections that repeat an earlier one or an accepted rule: the evidence, the match, the model",
    ),
)

PAGES = {
    "jev": {
        "title": "Jev",
        "icon": "boxes",
        "description": "Whether Jev is set up, what it cost in the last day and week, and what it decided",
        "entry": "pages/jev.html",
    },
}

# The commands of `evo-agents hub jev`, a file the CLI reads too without importing the plugin (cli_plugin_commands)
CLI = json.loads(Path(__file__).with_name("cli.json").read_text(encoding="utf-8"))


def _tools() -> list[dict]:
    from evo_core_plugins.jev import tools

    return [
        {
            "name": "decide",
            "title": "Put questions about a state to Jev",
            "description": "Ask Jev, in one request, questions about a state (text or JSON): each a choice among "
            "options, a noul (0 to 1, how much a yes) or a score on ordered levels. Answers carry a confidence. "
            "Refused with a reason when Jev is not set up in the project, the project's policy declares no sink "
            "jev@typesafe, the daily budget is spent or the model that answered is not the pinned one (writer).",
            "python": f"{TOOLS}:decide",
            "input_schema": tools.DECIDE_SCHEMA,
        },
        {
            "name": "usage",
            "title": "Read what Jev cost",
            "description": "The calls, input tokens and cost of the last 24 hours and 7 days, by feature, against the "
            "project's daily budget.",
            "python": f"{TOOLS}:usage",
            "input_schema": tools.USAGE_SCHEMA,
        },
    ]


def _manifest() -> dict:
    return {
        "id": "jev",
        "version": "1.4.0",
        "publisher": "evo-agents",
        "tier": "core",
        "name": "Jev",
        "description": "Jev, TypeSafe's System One model, as a tool, a page and commands, with a ledger of its cost "
        "and of what it decided. Off until a project sets a key, pins a model and declares the sink.",
        "engines": {"evo-agents": ">=0.21"},
        "plugin_api": 1,
        "permissions": ["runs:read"],
        "config": CONFIG,
        "egress": [{"id": SINK, "kind": SINK_KIND, "host": HOST}],
        "schema": {
            "metadata": "evo_core_plugins.jev.tables:metadata",
            "migrations": "evo_core_plugins.jev.migrations",
        },
        "ui": "evo_core_plugins.jev:ui",
        "contributes": {
            "routes": [{"name": "jev", "title": "Jev in a project", "python": f"{SERVER}:router"}],
            "pages": [{"name": name, **page} for name, page in PAGES.items()],
            "mcp_tools": _tools(),
            "events": [
                {
                    "name": "triage",
                    "title": "Read why a failed run failed",
                    "description": "When a run moves to failed and the project turned triage on, asks Jev which cause "
                    "the failure has and applies it, or only suggests it.",
                    "on": ["run.state"],
                    "python": f"{TRIAGE}:on_run_state",
                }
            ],
            "jobs": [
                {
                    "name": "kg_review",
                    "title": "Decide the open items of the graph's review queue",
                    "description": "Asks Jev about the possible duplicates and ambiguous matches of the review "
                    "queue, and merges, dismisses, proposes or suggests, within the daily cap.",
                    "python": f"{REVIEW}:on_job",
                    "cron": REVIEW_CRON,
                },
                {
                    "name": "corrections",
                    "title": "Find the corrections that repeat",
                    "description": "Reads the corrections of the day before, asks Jev whether each repeats an "
                    "earlier one or an accepted rule, records the matches and pushes the day's repeat rate.",
                    "python": f"{CORRECTIONS}:on_job",
                    "cron": CORRECTIONS_CRON,
                },
            ],
            "rankers": [
                {
                    "name": "rerank",
                    "title": "Rank search hits with Jev",
                    "description": "Puts the first 20 hits of history_search and kg_search in the order Jev scores "
                    "them, in one request; leaves the order alone when Jev fails, is late or the budget is spent.",
                    "python": f"{RANK}:rank",
                    "sink": SINK,
                }
            ],
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
