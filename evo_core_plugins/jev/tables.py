"""The tables of the core plugin jev, in its own metadata (``schema.metadata`` of its manifest), made by its own chain
of migrations (``migrations``). Their keys point at the hub's projects, users and runs alone (``HUB_KEYS``).

jev_usage holds one row for each call to Jev that left the hub: the project, who made it (a member, or a run), the
feature, the pinned model, the input tokens the vendor counted, the cost at ``PRICE_PER_MILLION_USD``, whether the
call answered (``ok``) or failed (``error``, with no body of the failure kept) and when. The daily budget sums it.

jev_asked holds one row for each subject (a run, a review item's fingerprint, a correction's evidence) a feature put
to a model: a feature asks a model about a subject once, and a failed turn is not asked again for that model.

jev_matches holds the corrections that repeat an earlier one or an accepted rule: the day, the evidence of the
correction, the candidate it matches, the model, the confidence and the state (``match``, over the threshold in the
mode apply, or ``suggestion``).

jev_acts holds one row for each thing Jev decided: its kind (``choice``, ``noul``, ``score``, or the act of a
feature), the target it was about, the outcome, the model, the confidence when the answer had one, whether the
plugin applied it or only suggested it, and when a member undid it (``undone_at``).
"""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    Table,
    Text,
    UniqueConstraint,
    func,
)

from evo_agents.hub.server import core_plugin_api as hub

STATUSES = ("ok", "error")
MAX_TARGET_CHARS = 300
MAX_OUTCOME_CHARS = 500
MATCH_STATES = ("match", "suggestion")

metadata = hub.plugin_metadata()


def _stamp(name: str) -> Column:
    return Column(name, DateTime(timezone=True), nullable=False, server_default=func.now())


def _key(table: str, column: str, target: str, ondelete: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint([column], [f"{target}.id"], ondelete=ondelete, name=f"{table}_{column}_fkey")


usage = Table(
    "jev_usage",
    metadata,
    Column("id", BigInteger, Identity(always=True), nullable=False),
    Column("project_id", BigInteger, nullable=False),
    Column("user_id", BigInteger),
    Column("run_id", BigInteger),
    Column("feature", Text, nullable=False),
    Column("model", Text, nullable=False),
    Column("input_tokens", Integer, nullable=False, server_default="0"),
    Column("cost_usd", Numeric(14, 8), nullable=False, server_default="0"),
    Column("status", Text, nullable=False, server_default="ok"),
    _stamp("created_at"),
    _key("jev_usage", "project_id", "projects", ondelete="CASCADE"),
    _key("jev_usage", "user_id", "users", ondelete="SET NULL"),
    _key("jev_usage", "run_id", "runs", ondelete="SET NULL"),
    PrimaryKeyConstraint("id", name="jev_usage_pkey"),
    Index("jev_usage_project_time_idx", "project_id", "created_at"),
)

acts = Table(
    "jev_acts",
    metadata,
    Column("id", BigInteger, Identity(always=True), nullable=False),
    Column("project_id", BigInteger, nullable=False),
    Column("kind", Text, nullable=False),
    Column("feature", Text, nullable=False),
    Column("target", Text, nullable=False),
    Column("outcome", Text, nullable=False),
    Column("model", Text, nullable=False),
    Column("confidence", Float),
    Column("applied", Boolean, nullable=False, server_default="false"),
    Column("undone_at", DateTime(timezone=True)),
    _stamp("created_at"),
    _key("jev_acts", "project_id", "projects", ondelete="CASCADE"),
    PrimaryKeyConstraint("id", name="jev_acts_pkey"),
    Index("jev_acts_project_time_idx", "project_id", "created_at"),
)

asked = Table(
    "jev_asked",
    metadata,
    Column("project_id", BigInteger, nullable=False),
    Column("feature", Text, nullable=False),
    Column("subject", Text, nullable=False),
    Column("model", Text, nullable=False),
    _stamp("created_at"),
    _key("jev_asked", "project_id", "projects", ondelete="CASCADE"),
    PrimaryKeyConstraint("project_id", "feature", "subject", "model", name="jev_asked_pkey"),
)

matches = Table(
    "jev_matches",
    metadata,
    Column("id", BigInteger, Identity(always=True), nullable=False),
    Column("project_id", BigInteger, nullable=False),
    Column("day", Date, nullable=False),
    Column("evidence", Text, nullable=False),
    Column("candidate", Text, nullable=False),
    Column("model", Text, nullable=False),
    Column("confidence", Float, nullable=False),
    Column("state", Text, nullable=False),
    _stamp("created_at"),
    _key("jev_matches", "project_id", "projects", ondelete="CASCADE"),
    PrimaryKeyConstraint("id", name="jev_matches_pkey"),
    UniqueConstraint("project_id", "evidence", "model", name="jev_matches_evidence_key"),
    Index("jev_matches_project_day_idx", "project_id", "day"),
)

NAMES = (usage.name, acts.name, asked.name, matches.name)
