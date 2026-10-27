"""Create the two tables of jev: the usage ledger and the acts. Written out here rather than made from
``tables.metadata``, so a later migration that changes a table finds it as this one left it.

Revision ID: jev_0001
Revises:
"""

import sqlalchemy as sa
from alembic import op

revision = "jev_0001"
down_revision = None
branch_labels = None
depends_on = None

TABLES = ("jev_usage", "jev_acts")


def _stamp(name: str) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


def _key(table: str, column: str, target: str, ondelete: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint([column], [f"{target}.id"], ondelete=ondelete, name=f"{table}_{column}_fkey")


def upgrade() -> None:
    op.create_table(
        "jev_usage",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), nullable=False),
        sa.Column("project_id", sa.BigInteger, nullable=False),
        sa.Column("user_id", sa.BigInteger),
        sa.Column("run_id", sa.BigInteger),
        sa.Column("feature", sa.Text, nullable=False),
        sa.Column("model", sa.Text, nullable=False),
        sa.Column("input_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Numeric(14, 8), nullable=False, server_default="0"),
        sa.Column("status", sa.Text, nullable=False, server_default="ok"),
        _stamp("created_at"),
        _key("jev_usage", "project_id", "projects", ondelete="CASCADE"),
        _key("jev_usage", "user_id", "users", ondelete="SET NULL"),
        _key("jev_usage", "run_id", "runs", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="jev_usage_pkey"),
    )
    op.create_index("jev_usage_project_time_idx", "jev_usage", ["project_id", "created_at"])
    op.create_table(
        "jev_acts",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), nullable=False),
        sa.Column("project_id", sa.BigInteger, nullable=False),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("feature", sa.Text, nullable=False),
        sa.Column("target", sa.Text, nullable=False),
        sa.Column("outcome", sa.Text, nullable=False),
        sa.Column("model", sa.Text, nullable=False),
        sa.Column("confidence", sa.Float),
        sa.Column("applied", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("undone_at", sa.DateTime(timezone=True)),
        _stamp("created_at"),
        _key("jev_acts", "project_id", "projects", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="jev_acts_pkey"),
    )
    op.create_index("jev_acts_project_time_idx", "jev_acts", ["project_id", "created_at"])


def downgrade() -> None:
    for name in reversed(TABLES):
        op.drop_table(name)
