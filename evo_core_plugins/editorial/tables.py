"""The tables of the core plugin editorial, in its own metadata (``schema.metadata`` of its manifest), made by its own
chain of migrations (``migrations``). Their keys point at the hub's projects and users alone (``HUB_KEYS``).

editorial_posts holds one row for each post of a project, by slug: its title, the stage it is at (one of the stages
the project's config lists), the git branch it is written on, the link of its draft preview and the link of the
published post, when it was published, the figures a person wrote in on day 7 and day 28 after it went out, and the
label of the row (the project's default label when it was made).

editorial_stage_history holds each stage a post entered, when, and what showed it (a commit, a link).

editorial_gates holds the gate of a post at each stage the config gives one: its kind (choose, interview, comments,
publish), its state (waiting, answered, skipped), when it opened, and when, through what (hub, cli, telegram...)
and by whom it was answered, with the answer.

editorial_rounds holds the review rounds of a post at a stage, numbered from 1: when, a note, the feedback entries the
round wrote (their PH ids) and the scores a judge gave; editorial_comments the comments of a round, each once by the
id its source gave it, with its author, the sentence it marks and its text.

editorial_feedback is the feedback notebook: one row for each entry PH-<number> of a project, in a notebook the config
lists: its date, title and post, what the person said with when (``said``, a list of {text, date, note}), the sentence
the agent wrote and the one the person fixed it to (each with a note and the place of its line among the said lines),
the rule, the Kiểm line (``check_line``, how it is checked), how many times it was seen (Lần gặp) and the probe that
watches it. ``ledger`` prints it as the notebook's markdown.
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Column,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    PrimaryKeyConstraint,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB

from evo_agents.hub.server import core_plugin_api as hub

GATE_KINDS = ("choose", "interview", "comments", "publish")
GATE_STATES = ("waiting", "answered", "skipped")
NAME = r"^[a-z0-9][a-z0-9_-]{0,39}$"  # a stage or a notebook in the config
SLUG = r"^[a-z0-9][a-z0-9-]{0,159}$"  # a post

metadata = hub.plugin_metadata()


def _stamp(name: str) -> Column:
    return Column(name, DateTime(timezone=True), nullable=False, server_default=func.now())


def _key(table: str, column: str, target: str, ondelete: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint([column], [f"{target}.id"], ondelete=ondelete, name=f"{table}_{column}_fkey")


posts = Table(
    "editorial_posts",
    metadata,
    Column("id", BigInteger, Identity(always=True), nullable=False),
    Column("project_id", BigInteger, nullable=False),
    Column("slug", Text, nullable=False),
    Column("title", Text, nullable=False, server_default=""),
    Column("stage", Text, nullable=False),
    Column("branch", Text),
    Column("preview_url", Text),
    Column("url", Text),
    Column("published_at", DateTime(timezone=True)),
    Column("d7", JSONB),
    Column("d28", JSONB),
    Column("label", JSONB, nullable=False, server_default="{}"),
    _stamp("created_at"),
    _stamp("updated_at"),
    _key("editorial_posts", "project_id", "projects", ondelete="CASCADE"),
    PrimaryKeyConstraint("id", name="editorial_posts_pkey"),
    UniqueConstraint("project_id", "slug", name="editorial_posts_slug_key"),
    Index("editorial_posts_stage_idx", "project_id", "stage"),
)

stage_history = Table(
    "editorial_stage_history",
    metadata,
    Column("id", BigInteger, Identity(always=True), nullable=False),
    Column("post_id", BigInteger, nullable=False),
    Column("stage", Text, nullable=False),
    Column("at", DateTime(timezone=True), nullable=False),
    Column("evidence", Text),
    _key("editorial_stage_history", "post_id", "editorial_posts", ondelete="CASCADE"),
    PrimaryKeyConstraint("id", name="editorial_stage_history_pkey"),
    UniqueConstraint("post_id", "stage", "at", name="editorial_stage_history_once_key"),
)

gates = Table(
    "editorial_gates",
    metadata,
    Column("id", BigInteger, Identity(always=True), nullable=False),
    Column("post_id", BigInteger, nullable=False),
    Column("stage", Text, nullable=False),
    Column("kind", Text, nullable=False),
    Column("state", Text, nullable=False, server_default="waiting"),
    _stamp("opened_at"),
    Column("answered_at", DateTime(timezone=True)),
    Column("answered_via", Text),
    Column("answered_by", BigInteger),
    Column("answer", JSONB),
    _key("editorial_gates", "post_id", "editorial_posts", ondelete="CASCADE"),
    _key("editorial_gates", "answered_by", "users", ondelete="SET NULL"),
    PrimaryKeyConstraint("id", name="editorial_gates_pkey"),
    UniqueConstraint("post_id", "stage", name="editorial_gates_stage_key"),
    Index("editorial_gates_answered_by_idx", "answered_by"),
)

rounds = Table(
    "editorial_rounds",
    metadata,
    Column("id", BigInteger, Identity(always=True), nullable=False),
    Column("post_id", BigInteger, nullable=False),
    Column("stage", Text, nullable=False),
    Column("number", Integer, nullable=False),
    Column("at", DateTime(timezone=True), nullable=False),
    Column("note", Text),
    Column("feedback", JSONB, nullable=False, server_default="[]"),
    Column("scores", JSONB),
    _key("editorial_rounds", "post_id", "editorial_posts", ondelete="CASCADE"),
    PrimaryKeyConstraint("id", name="editorial_rounds_pkey"),
    UniqueConstraint("post_id", "stage", "number", name="editorial_rounds_number_key"),
)

comments = Table(
    "editorial_comments",
    metadata,
    Column("id", BigInteger, Identity(always=True), nullable=False),
    Column("round_id", BigInteger, nullable=False),
    Column("external_id", Text, nullable=False),
    Column("author", Text),
    Column("quote", Text),
    Column("text", Text, nullable=False),
    Column("at", DateTime(timezone=True)),
    _key("editorial_comments", "round_id", "editorial_rounds", ondelete="CASCADE"),
    PrimaryKeyConstraint("id", name="editorial_comments_pkey"),
    UniqueConstraint("round_id", "external_id", name="editorial_comments_once_key"),
)

feedback = Table(
    "editorial_feedback",
    metadata,
    Column("id", BigInteger, Identity(always=True), nullable=False),
    Column("project_id", BigInteger, nullable=False),
    Column("number", Integer, nullable=False),
    Column("notebook", Text, nullable=False),
    Column("title", Text, nullable=False),
    Column("date", Date, nullable=False),
    Column("post", Text),
    Column("said", JSONB, nullable=False, server_default="[]"),
    Column("agent_wrote", Text),
    Column("agent_note", Text),
    Column("agent_after", Integer),
    Column("person_fixed", Text),
    Column("fixed_note", Text),
    Column("fixed_after", Integer),
    Column("rule", Text, nullable=False),
    Column("check_line", Text),
    Column("seen", Integer, nullable=False, server_default="1"),
    Column("probe_id", BigInteger),
    Column("label", JSONB, nullable=False, server_default="{}"),
    _stamp("created_at"),
    _stamp("updated_at"),
    _key("editorial_feedback", "project_id", "projects", ondelete="CASCADE"),
    PrimaryKeyConstraint("id", name="editorial_feedback_pkey"),
    UniqueConstraint("project_id", "number", name="editorial_feedback_number_key"),
    Index("editorial_feedback_notebook_idx", "project_id", "notebook"),
)

NAMES = tuple(table.name for table in (posts, stage_history, gates, rounds, comments, feedback))
