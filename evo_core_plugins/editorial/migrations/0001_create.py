"""Create the six tables of editorial: posts, their stage history, gates, review rounds and comments, and the feedback
notebook. Written out here rather than made from ``tables.metadata``, so a later migration that changes a table finds
it as this one left it.

Revision ID: editorial_0001
Revises:
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "editorial_0001"
down_revision = None
branch_labels = None
depends_on = None

TABLES = (
    "editorial_posts",
    "editorial_stage_history",
    "editorial_gates",
    "editorial_rounds",
    "editorial_comments",
    "editorial_feedback",
)


def _id() -> sa.Column:
    return sa.Column("id", sa.BigInteger, sa.Identity(always=True), nullable=False)


def _stamp(name: str) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


def _key(table: str, column: str, target: str, ondelete: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint([column], [f"{target}.id"], ondelete=ondelete, name=f"{table}_{column}_fkey")


def upgrade() -> None:
    op.create_table(
        "editorial_posts",
        _id(),
        sa.Column("project_id", sa.BigInteger, nullable=False),
        sa.Column("slug", sa.Text, nullable=False),
        sa.Column("title", sa.Text, nullable=False, server_default=""),
        sa.Column("stage", sa.Text, nullable=False),
        sa.Column("branch", sa.Text),
        sa.Column("preview_url", sa.Text),
        sa.Column("url", sa.Text),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("d7", JSONB),
        sa.Column("d28", JSONB),
        sa.Column("label", JSONB, nullable=False, server_default="{}"),
        _stamp("created_at"),
        _stamp("updated_at"),
        _key("editorial_posts", "project_id", "projects", "CASCADE"),
        sa.PrimaryKeyConstraint("id", name="editorial_posts_pkey"),
        sa.UniqueConstraint("project_id", "slug", name="editorial_posts_slug_key"),
    )
    op.create_index("editorial_posts_stage_idx", "editorial_posts", ["project_id", "stage"])
    op.create_table(
        "editorial_stage_history",
        _id(),
        sa.Column("post_id", sa.BigInteger, nullable=False),
        sa.Column("stage", sa.Text, nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence", sa.Text),
        _key("editorial_stage_history", "post_id", "editorial_posts", "CASCADE"),
        sa.PrimaryKeyConstraint("id", name="editorial_stage_history_pkey"),
        sa.UniqueConstraint("post_id", "stage", "at", name="editorial_stage_history_once_key"),
    )
    op.create_table(
        "editorial_gates",
        _id(),
        sa.Column("post_id", sa.BigInteger, nullable=False),
        sa.Column("stage", sa.Text, nullable=False),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("state", sa.Text, nullable=False, server_default="waiting"),
        _stamp("opened_at"),
        sa.Column("answered_at", sa.DateTime(timezone=True)),
        sa.Column("answered_via", sa.Text),
        sa.Column("answered_by", sa.BigInteger),
        sa.Column("answer", JSONB),
        _key("editorial_gates", "post_id", "editorial_posts", "CASCADE"),
        _key("editorial_gates", "answered_by", "users", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="editorial_gates_pkey"),
        sa.UniqueConstraint("post_id", "stage", name="editorial_gates_stage_key"),
    )
    op.create_index("editorial_gates_answered_by_idx", "editorial_gates", ["answered_by"])
    op.create_table(
        "editorial_rounds",
        _id(),
        sa.Column("post_id", sa.BigInteger, nullable=False),
        sa.Column("stage", sa.Text, nullable=False),
        sa.Column("number", sa.Integer, nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("note", sa.Text),
        sa.Column("feedback", JSONB, nullable=False, server_default="[]"),
        sa.Column("scores", JSONB),
        _key("editorial_rounds", "post_id", "editorial_posts", "CASCADE"),
        sa.PrimaryKeyConstraint("id", name="editorial_rounds_pkey"),
        sa.UniqueConstraint("post_id", "stage", "number", name="editorial_rounds_number_key"),
    )
    op.create_table(
        "editorial_comments",
        _id(),
        sa.Column("round_id", sa.BigInteger, nullable=False),
        sa.Column("external_id", sa.Text, nullable=False),
        sa.Column("author", sa.Text),
        sa.Column("quote", sa.Text),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("at", sa.DateTime(timezone=True)),
        _key("editorial_comments", "round_id", "editorial_rounds", "CASCADE"),
        sa.PrimaryKeyConstraint("id", name="editorial_comments_pkey"),
        sa.UniqueConstraint("round_id", "external_id", name="editorial_comments_once_key"),
    )
    op.create_table(
        "editorial_feedback",
        _id(),
        sa.Column("project_id", sa.BigInteger, nullable=False),
        sa.Column("number", sa.Integer, nullable=False),
        sa.Column("notebook", sa.Text, nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("post", sa.Text),
        sa.Column("said", JSONB, nullable=False, server_default="[]"),
        sa.Column("agent_wrote", sa.Text),
        sa.Column("agent_note", sa.Text),
        sa.Column("agent_after", sa.Integer),
        sa.Column("person_fixed", sa.Text),
        sa.Column("fixed_note", sa.Text),
        sa.Column("fixed_after", sa.Integer),
        sa.Column("rule", sa.Text, nullable=False),
        sa.Column("check_line", sa.Text),
        sa.Column("seen", sa.Integer, nullable=False, server_default="1"),
        sa.Column("probe_id", sa.BigInteger),
        sa.Column("label", JSONB, nullable=False, server_default="{}"),
        _stamp("created_at"),
        _stamp("updated_at"),
        _key("editorial_feedback", "project_id", "projects", "CASCADE"),
        sa.PrimaryKeyConstraint("id", name="editorial_feedback_pkey"),
        sa.UniqueConstraint("project_id", "number", name="editorial_feedback_number_key"),
    )
    op.create_index("editorial_feedback_notebook_idx", "editorial_feedback", ["project_id", "notebook"])


def downgrade() -> None:
    for name in reversed(TABLES):
        op.drop_table(name)
