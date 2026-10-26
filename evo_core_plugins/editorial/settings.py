"""The plugin's config in a project (``CONFIG``, a JSON Schema) and its effective value.

The plugin knows no stage by name: the project lists its stages in order, each with the kind of its gate when it has
one (choose, interview, comments, publish) and the notebooks to read before it (``recall``); it lists its notebooks,
each with the title and intro its markdown starts with and whether every stage reads it (``always``). ``person`` is
the name the notebook's lines give the person whose words they keep, ``reviewers`` the reviewers whose comments on a
draft count, and ``daily_usd`` the most the agents of a post spend in a day.

The flow of a post (``flow``) reads the rest: ``repo``, the repo of the project the agent type writer writes posts in
(each on its branch ``post/<slug>``; without it the plugin hands no task and only keeps the state); ``skill``, the
project's writing skill the writer follows; ``minutes``, the agent time of one task; ``gatekeepers``, the members a
gate's notice goes to (the project's admins when none is listed); ``comments``, the comment service the draft comments
are read from (a Firebase project and its web API key, both public: the comments are readable without a credential).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncConnection

from evo_agents.hub.server import core_plugin_api as hub
from evo_core_plugins.editorial.tables import GATE_KINDS, NAME

REPO = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$"  # a repo, a skill, a Firebase project or collection

DEFAULT_PERSON = "Owner"
DEFAULT_SKILL = "writing"
DEFAULT_MINUTES = 60

CONFIG = {
    "type": "object",
    "properties": {
        "stages": {
            "title": "Stages",
            "description": "The stages a post goes through, in order. A stage with a gate waits for a person there; "
            "recall names the notebooks an agent reads before it.",
            "type": "array",
            "default": [],
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "pattern": NAME},
                    "title": {"type": "string"},
                    "gate": {"type": "string", "enum": list(GATE_KINDS)},
                    "recall": {"type": "array", "items": {"type": "string", "pattern": NAME}, "default": []},
                },
                "required": ["name"],
                "additionalProperties": False,
            },
        },
        "notebooks": {
            "title": "Notebooks",
            "description": "The notebooks of feedback: the title and intro their markdown starts with, and whether "
            "an agent reads one before every stage.",
            "type": "array",
            "default": [],
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "pattern": NAME},
                    "title": {"type": "string"},
                    "intro": {"type": "string"},
                    "always": {"type": "boolean", "default": False},
                },
                "required": ["name", "title"],
                "additionalProperties": False,
            },
        },
        "person": {
            "title": "Person",
            "description": "The name the notebook's lines give the person whose words they keep.",
            "type": "string",
            "minLength": 1,
            "default": DEFAULT_PERSON,
        },
        "reviewers": {
            "title": "Reviewers",
            "description": "The reviewers whose comments on a draft count, as the comment service names them.",
            "type": "array",
            "items": {"type": "string"},
            "default": [],
        },
        "daily_usd": {
            "title": "Cost cap a day (USD)",
            "description": "The most the agents of a post spend in a day. Enable the agent type writer with this "
            "daily_usd: the hub stops its tasks at it, and the post shows why.",
            "type": "number",
            "minimum": 0,
        },
        "repo": {
            "title": "Repo of the posts",
            "description": "The project's repo the writer writes posts in, each on its branch post/<slug>. Left out, "
            "the plugin hands no task and only keeps the state of the posts.",
            "type": "string",
            "pattern": REPO,
        },
        "skill": {
            "title": "Writing skill",
            "description": "The project's skill the writer follows from a stage to the next gate.",
            "type": "string",
            "pattern": REPO,
            "default": DEFAULT_SKILL,
        },
        "minutes": {
            "title": "Agent time of a task (minutes)",
            "description": "How long one task of the writer may run.",
            "type": "integer",
            "minimum": 1,
            "maximum": hub.MAX_TASK_MINUTES,
            "default": DEFAULT_MINUTES,
        },
        "gatekeepers": {
            "title": "Gatekeepers",
            "description": "The members (logins) a gate's notice goes to; the project's admins when none is listed.",
            "type": "array",
            "items": {"type": "string"},
            "default": [],
        },
        "comments": {
            "title": "Comment service",
            "description": "The Firebase project the draft comments are kept in, and its web API key. Both are "
            "public: the comments are read without a credential, as the blog's pages read them.",
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "pattern": REPO},
                "api_key": {"type": "string", "maxLength": 200},
                "collection": {"type": "string", "pattern": REPO, "default": "marginalia_comments"},
            },
            "additionalProperties": False,
        },
    },
}


@dataclass(frozen=True)
class Stage:
    name: str
    title: str
    gate: str | None  # the kind of its gate, None for none
    recall: tuple[str, ...]  # the notebooks to read before it


@dataclass(frozen=True)
class Notebook:
    name: str
    title: str
    intro: str
    always: bool  # read before every stage


@dataclass(frozen=True)
class Comments:
    project_id: str
    api_key: str
    collection: str = "marginalia_comments"


@dataclass(frozen=True)
class Config:
    stages: tuple[Stage, ...] = ()
    notebooks: tuple[Notebook, ...] = ()
    person: str = DEFAULT_PERSON
    reviewers: tuple[str, ...] = ()
    daily_usd: float | None = None
    repo: str | None = None
    skill: str = DEFAULT_SKILL
    minutes: int = DEFAULT_MINUTES
    gatekeepers: tuple[str, ...] = ()
    comments: Comments | None = None

    @property
    def stage_names(self) -> tuple[str, ...]:
        return tuple(stage.name for stage in self.stages)

    @property
    def notebook_names(self) -> tuple[str, ...]:
        return tuple(book.name for book in self.notebooks)

    def stage(self, name: str) -> Stage | None:
        return next((stage for stage in self.stages if stage.name == name), None)

    def notebook(self, name: str) -> Notebook | None:
        return next((book for book in self.notebooks if book.name == name), None)

    def order(self, stage: str) -> int:
        """Where ``stage`` stands among the stages; one the config no longer lists comes last."""
        names = self.stage_names
        return names.index(stage) if stage in names else len(names)

    def recall(self, stage: str) -> tuple[str, ...]:
        """The notebooks to read before ``stage``: those it names, then those read before every stage."""
        found = self.stage(stage)
        named = list(found.recall) if found else []
        return tuple(dict.fromkeys(named + [book.name for book in self.notebooks if book.always]))


def _names(value) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str) and re.fullmatch(NAME, item))


def _stages(value) -> tuple[Stage, ...]:
    found: dict[str, Stage] = {}
    for item in value if isinstance(value, list) else ():
        name = item.get("name") if isinstance(item, dict) else None
        if not isinstance(name, str) or not re.fullmatch(NAME, name) or name in found:
            continue
        gate = item.get("gate")
        title = item.get("title")
        found[name] = Stage(
            name,
            title if isinstance(title, str) else name,
            gate if gate in GATE_KINDS else None,
            _names(item.get("recall")),
        )
    return tuple(found.values())


def _notebooks(value) -> tuple[Notebook, ...]:
    found: dict[str, Notebook] = {}
    for item in value if isinstance(value, list) else ():
        name = item.get("name") if isinstance(item, dict) else None
        if not isinstance(name, str) or not re.fullmatch(NAME, name) or name in found:
            continue
        title, intro = item.get("title"), item.get("intro")
        found[name] = Notebook(
            name,
            title if isinstance(title, str) and title else name,
            intro if isinstance(intro, str) else "",
            item.get("always") is True,
        )
    return tuple(found.values())


def _word(value, default: str | None) -> str | None:
    return value if isinstance(value, str) and re.fullmatch(REPO, value) else default


def _texts(value) -> tuple[str, ...]:
    return tuple(item for item in value if isinstance(item, str) and item) if isinstance(value, list) else ()


def _comments(value) -> Comments | None:
    if not isinstance(value, dict):
        return None
    project_id, key = _word(value.get("project_id"), None), value.get("api_key")
    if project_id is None or not isinstance(key, str) or not key:
        return None
    return Comments(project_id, key, _word(value.get("collection"), None) or Comments.collection)


def parse(values) -> Config:
    """The config of ``values`` (the effective values the hub gives), what does not read left out."""
    person = values.get("person")
    cap = values.get("daily_usd")
    minutes = values.get("minutes")
    return Config(
        _stages(values.get("stages")),
        _notebooks(values.get("notebooks")),
        person.strip() if isinstance(person, str) and person.strip() else DEFAULT_PERSON,
        _texts(values.get("reviewers")),
        float(cap) if isinstance(cap, int | float) and not isinstance(cap, bool) and cap >= 0 else None,
        _word(values.get("repo"), None),
        _word(values.get("skill"), None) or DEFAULT_SKILL,
        minutes
        if isinstance(minutes, int) and not isinstance(minutes, bool) and 1 <= minutes <= hub.MAX_TASK_MINUTES
        else DEFAULT_MINUTES,
        _texts(values.get("gatekeepers")),
        _comments(values.get("comments")),
    )


def handle() -> hub.Plugin:
    """The plugin's handle, which every call of the hub's API takes."""
    return hub.plugin(__name__)


async def config(conn: AsyncConnection, project: str) -> Config:
    """The config of the plugin in ``project``, which enables it (404 otherwise). No secret field."""
    found = await hub.plugin_config(conn, handle(), None, project=project)
    return parse(found.values)


__all__ = ["CONFIG", "Comments", "Config", "Notebook", "Stage", "config", "handle", "parse"]
