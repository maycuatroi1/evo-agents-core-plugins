"""The core plugin editorial: the posts of a project's blog on their way out, and the notebook of what the person who
reviews them said (``docs/editorial-plugin.md``).

A post (slug, title, stage, branch, preview link, url, the figures 7 and 28 days after it went out) moves through the
stages the project's config lists in order; a stage with a gate (choose, interview, comments or publish) waits there for
a person, and the gate keeps when it was answered and through what. A post keeps its review rounds and the comments of
each. The feedback notebook keeps one entry for each thing the person corrected: its id PH-<n>, the day, the post, the
notebook, the person's words with their dates, what the agent wrote and what the person changed it to, the rule, how it
is checked, how many times it was seen, and the curator probe of the rule. ``export`` prints a notebook as the markdown
file it was kept in, and ``import`` takes the JSON of posts and entries and keeps their ids.

Once the config names the repo of posts, the plugin runs the flow (``flow``): a gate that opens sends its notice to
the gatekeepers with the link of the post's page, where they answer; an answer hands the agent type ``writer`` a task
on the post's branch, to the next gate; a run that ends short of a gate is followed by the next, within the type's
daily cap; a review round asks the agent type ``editor-judge`` to score the draft blind (``judge``) and reads the
reviewers' draft comments from the blog's comment service (``marginalia``); an entry of the notebook can carry a
curator probe of its rule (``probes``). It acts on a person's answer, a button and the hub's events, never on a clock:
the plugin runs no job.

No stage is named in the code: the config lists them (``settings``). The routes under ``/v1/x/editorial/<project>``
(``server``) serve the pages Posts and Feedback (``ui/pages``), ``evo-agents hub editorial`` (``cli.json``) and the
tools ``editorial__state``, ``editorial__recall``, ``editorial__feedback`` and ``editorial__comments`` (``tools``); the
knowledge graph's source gives one item for each entry and each post (``kg``). The package imports no other core plugin
(import-linter contract ``plugins-own-package``).
"""

import json
from pathlib import Path

SERVER = "evo_core_plugins.editorial.server"
TOOLS = "evo_core_plugins.editorial.tools"
KG = "evo_core_plugins.editorial.kg"
EVENTS = "evo_core_plugins.editorial.events"

WRITER_INSTRUCTIONS = (
    "You write the posts of the project's blog, one task at a time. Each task names a post, its branch and the stage "
    "it is at. Follow the project's writing skill from that stage to the next gate, then stop: never answer a gate "
    "for the person. Before writing a stage, read editorial__recall for it and keep every rule it gives. Set the "
    "post's stage with editorial__state as you go; entering a stage with a gate hands the post to the person, with "
    "what you ask them in ask. Commit and push your work to the post's branch only."
)
JUDGE_INSTRUCTIONS = (
    "You score the draft of a blog post, in a fresh context, without knowing who wrote it. Read the draft where the "
    "question says, change nothing, and answer with one JSON object only: slop (no filler, no stock phrases, no "
    "padding), giong (the voice of the blog), nguon (every claim and figure has its source) and hinh (the images and "
    "their captions serve the text), each a whole number from 0 to 5, and why, one line. Score what is there, not "
    "what the draft promises."
)

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
        {
            "name": "comments",
            "title": "Read the reviewers' draft comments",
            "description": "Read the comments the configured reviewers left on a post's draft (the blog's comment "
            "service, by the post's comment_id) into its latest review round, each once, with the sentence each "
            "highlights. Call it when you start on the comments of a round (writer).",
            "python": f"{TOOLS}:comments",
            "input_schema": tools.COMMENTS_SCHEMA,
        },
    ]


def _manifest() -> dict:
    from evo_core_plugins.editorial.flow import NOTICE_KINDS, WRITER
    from evo_core_plugins.editorial.judge import AGENT_TYPE as JUDGE
    from evo_core_plugins.editorial.settings import CONFIG

    return {
        "id": "editorial",
        "version": "1.2.0",
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
            "notice_kinds": [{"name": name, "title": title} for name, title in NOTICE_KINDS],
            "events": [
                {
                    "name": "results",
                    "title": "A writer's run ended",
                    "description": "The post goes on to the next task, waits at its gate, or shows why it stopped.",
                    "python": f"{EVENTS}:on_task_result",
                    "on": ["task.result"],
                },
                {
                    "name": "answers",
                    "title": "The judge answered",
                    "description": "The judge's scores go into the review round it was asked about.",
                    "python": f"{EVENTS}:on_agent_answer",
                    "on": ["agent.answer"],
                },
            ],
            "agent_types": [
                {
                    "name": WRITER,
                    "title": "Writer",
                    "description": "Writes a post on its branch from the stage it is at to the next gate, then stops.",
                    "mentioned_by": "admin",
                    "events": ["results"],
                    "profile": {
                        "handle": WRITER,
                        "name": "Writer",
                        "description": "Follows the writing skill to the next gate of a post, then stops.",
                        "instructions": WRITER_INSTRUCTIONS,
                    },
                },
                {
                    "name": JUDGE,
                    "title": "Editor judge",
                    "description": "Scores a draft blind on slop, giong, nguon and hinh, from 0 to 5; changes nothing.",
                    "mentioned_by": "admin",
                    "events": ["answers"],
                    "profile": {
                        "handle": JUDGE,
                        "name": "Editor judge",
                        "description": "Scores one draft post from 0 to 5 on four axes, in a fresh context.",
                        "instructions": JUDGE_INSTRUCTIONS,
                    },
                },
            ],
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
