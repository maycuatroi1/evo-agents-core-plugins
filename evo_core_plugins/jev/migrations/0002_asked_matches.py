"""Add the two tables the automatic features keep: what was asked of a model once (``jev_asked``) and the corrections
that repeat an earlier one (``jev_matches``). Written out here, not made from ``tables.metadata``.

Revision ID: jev_0002
Revises: jev_0001
"""

import sqlalchemy as sa
from alembic import op

revision = "jev_0002"
down_revision = "jev_0001"
branch_labels = None
depends_on = None

TABLES = ("jev_asked", "jev_matches")


def _stamp(name: str) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


def _key(table: str, column: str, target: str, ondelete: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint([column], [f"{target}.id"], ondelete=ondelete, name=f"{table}_{column}_fkey")


def upgrade() -> None:
    op.create_table(
        "jev_asked",
        sa.Column("project_id", sa.BigInteger, nullable=False),
        sa.Column("feature", sa.Text, nullable=False),
        sa.Column("subject", sa.Text, nullable=False),
        sa.Column("model", sa.Text, nullable=False),
        _stamp("created_at"),
        _key("jev_asked", "project_id", "projects", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("project_id", "feature", "subject", "model", name="jev_asked_pkey"),
    )
    op.create_table(
        "jev_matches",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), nullable=False),
        sa.Column("project_id", sa.BigInteger, nullable=False),
        sa.Column("day", sa.Date, nullable=False),
        sa.Column("evidence", sa.Text, nullable=False),
        sa.Column("candidate", sa.Text, nullable=False),
        sa.Column("model", sa.Text, nullable=False),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("state", sa.Text, nullable=False),
        _stamp("created_at"),
        _key("jev_matches", "project_id", "projects", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="jev_matches_pkey"),
        sa.UniqueConstraint("project_id", "evidence", "model", name="jev_matches_evidence_key"),
    )
    op.create_index("jev_matches_project_day_idx", "jev_matches", ["project_id", "day"])


def downgrade() -> None:
    for name in reversed(TABLES):
        op.drop_table(name)
