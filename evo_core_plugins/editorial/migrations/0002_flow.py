"""The flow of a post (API 1.4): the post's comment key and its task run of the agent type writer, what a gate puts to
the person, the judge's question of a review round, and the task and verify of a feedback entry's probe.

Revision ID: editorial_0002
Revises: editorial_0001
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "editorial_0002"
down_revision = "editorial_0001"
branch_labels = None
depends_on = None

COLUMNS = {
    "editorial_posts": (
        ("comment_id", sa.Text),
        ("run_id", sa.BigInteger),
        ("run_state", sa.Text),
        ("run_stage", sa.Text),
        ("run_error", sa.Text),
        ("run_at", sa.DateTime(timezone=True)),
    ),
    "editorial_gates": (("ask", JSONB),),
    "editorial_rounds": (("question_id", sa.BigInteger), ("judge_state", sa.Text), ("judge_note", sa.Text)),
    "editorial_feedback": (("probe_task", sa.Text), ("probe_verify", sa.Text)),
}


def upgrade() -> None:
    for table, columns in COLUMNS.items():
        for name, kind in columns:
            op.add_column(table, sa.Column(name, kind))
    op.add_column("editorial_posts", sa.Column("run_count", sa.Integer, nullable=False, server_default="0"))
    op.create_index("editorial_posts_run_idx", "editorial_posts", ["project_id", "run_id"])


def downgrade() -> None:
    op.drop_index("editorial_posts_run_idx", table_name="editorial_posts")
    op.drop_column("editorial_posts", "run_count")
    for table, columns in COLUMNS.items():
        for name, _ in reversed(columns):
            op.drop_column(table, name)
