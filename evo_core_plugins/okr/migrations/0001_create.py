"""Create the three tables of okr: the items of a project's tree, their parents, and their links to the hub's items.
Written out here rather than made from ``tables.metadata``, so a later migration that changes a table finds it as this
one left it.

Revision ID: okr_0001
Revises:
"""

import sqlalchemy as sa
from alembic import op

revision = "okr_0001"
down_revision = None
branch_labels = None
depends_on = None

TABLES = ("okr_items", "okr_parents", "okr_links")


def _stamp(name: str) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


def _key(table: str, column: str, target: str, ondelete: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint([column], [f"{target}.id"], ondelete=ondelete, name=f"{table}_{column}_fkey")


def upgrade() -> None:
    op.create_table(
        "okr_items",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), nullable=False),
        sa.Column("project_id", sa.BigInteger, nullable=False),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("number", sa.Integer, nullable=False),
        sa.Column("ref", sa.Text),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("body_md", sa.Text),
        sa.Column("status", sa.Text, nullable=False, server_default="active"),
        sa.Column("owner", sa.Text),
        sa.Column("period", sa.Text),
        sa.Column("due", sa.Date),
        sa.Column("baseline", sa.Text),
        sa.Column("target", sa.Text),
        sa.Column("source", sa.Text),
        sa.Column("source_url", sa.Text),
        sa.Column("source_rev", sa.Text),
        sa.Column("created_by", sa.BigInteger),
        sa.Column("updated_by", sa.BigInteger),
        _stamp("created_at"),
        _stamp("updated_at"),
        _key("okr_items", "project_id", "projects", ondelete="CASCADE"),
        _key("okr_items", "created_by", "users", ondelete="SET NULL"),
        _key("okr_items", "updated_by", "users", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="okr_items_pkey"),
        sa.UniqueConstraint("project_id", "kind", "number", name="okr_items_code_key"),
        sa.UniqueConstraint("project_id", "ref", name="okr_items_ref_key"),
    )
    op.create_index("okr_items_source_idx", "okr_items", ["project_id", "source"])
    op.create_index("okr_items_created_by_idx", "okr_items", ["created_by"])
    op.create_index("okr_items_updated_by_idx", "okr_items", ["updated_by"])
    op.create_table(
        "okr_parents",
        sa.Column("child_id", sa.BigInteger, nullable=False),
        sa.Column("parent_id", sa.BigInteger, nullable=False),
        _key("okr_parents", "child_id", "okr_items", ondelete="CASCADE"),
        _key("okr_parents", "parent_id", "okr_items", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("child_id", "parent_id", name="okr_parents_pkey"),
    )
    op.create_index("okr_parents_parent_idx", "okr_parents", ["parent_id"])
    op.create_table(
        "okr_links",
        sa.Column("id", sa.BigInteger, sa.Identity(always=True), nullable=False),
        sa.Column("item_id", sa.BigInteger, nullable=False),
        sa.Column("target_kind", sa.Text, nullable=False),
        sa.Column("target", sa.Text, nullable=False),
        sa.Column("created_by", sa.BigInteger),
        _stamp("created_at"),
        _key("okr_links", "item_id", "okr_items", ondelete="CASCADE"),
        _key("okr_links", "created_by", "users", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="okr_links_pkey"),
        sa.UniqueConstraint("item_id", "target_kind", "target", name="okr_links_once_key"),
    )
    op.create_index("okr_links_created_by_idx", "okr_links", ["created_by"])


def downgrade() -> None:
    for name in reversed(TABLES):
        op.drop_table(name)
