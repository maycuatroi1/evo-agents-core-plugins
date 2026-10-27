"""The tables of the core plugin okr, in its own metadata (``schema.metadata`` of its manifest), made by its own chain
of migrations (``migrations``): a project's strategy as a tree and the hub's items each part of it is delivered by
(``docs/okr-plugin.md``). Their keys point at the hub's projects and users alone (``HUB_KEYS``).

okr_items holds one row for each part of the tree: its kind (business_line, objective, key_result, deliverable), its
number within the project and the kind, which makes its code (BL-1, O-1, KR-1, D-1), the id a source outside the hub
gave it (``ref``, unique in the project when set), its title and text, status, owner (a login), period, due date, the
baseline and target of a key result, the source an import wrote it from with that source's link and revision, and who
made and last changed it. An item is never deleted: an import that no longer lists it archives it.

okr_parents holds the edges of the tree, one row for each child and parent: an objective under at most one business
line, a key result under exactly one objective, a deliverable under one key result or more. A business line has none.

okr_links holds what an item is delivered or measured by on the hub, one row for each item, kind and target: a
deliverable's task (``T-12``), use case (``<document>:<code>``) and plan (its slug), a key result's goal (``G-3``).
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

from evo_agents.hub.server import core_plugin_api as hub

KINDS = ("business_line", "objective", "key_result", "deliverable")  # from the top of the tree down
BUSINESS_LINE, OBJECTIVE, KEY_RESULT, DELIVERABLE = KINDS
PREFIXES = {BUSINESS_LINE: "BL", OBJECTIVE: "O", KEY_RESULT: "KR", DELIVERABLE: "D"}  # of an item's code
STATUSES = ("draft", "active", "done", "dropped", "archived")
CLOSED = ("dropped", "archived")  # out of every roll-up and gap
TARGET_KINDS = ("task", "use_case", "plan", "goal")
TARGETS = {DELIVERABLE: ("task", "use_case", "plan"), KEY_RESULT: ("goal",)}  # what each kind of item links to

CODE = r"^(?:BL|O|KR|D)-[1-9][0-9]{0,8}$"  # an item's code, as shown
REF = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$"  # the id a source gives an item: no slash, no space
SOURCE = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$"
OWNER = r"^[A-Za-z0-9][A-Za-z0-9_-]{0,99}$"  # a login, as the hub's Login has it
MAX_TITLE_CHARS = 300
MAX_BODY_CHARS = 20_000
MAX_FIELD_CHARS = 500  # baseline, target
MAX_PERIOD_CHARS = 40
MAX_URL_CHARS = 2000
MAX_REV_CHARS = 200
MAX_TARGET_CHARS = 300

metadata = hub.plugin_metadata()


def _stamp(name: str) -> Column:
    return Column(name, DateTime(timezone=True), nullable=False, server_default=func.now())


def _key(table: str, column: str, target: str, ondelete: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint([column], [f"{target}.id"], ondelete=ondelete, name=f"{table}_{column}_fkey")


def _items_table() -> Table:
    return Table(
        "okr_items",
        metadata,
        Column("id", BigInteger, Identity(always=True), nullable=False),
        Column("project_id", BigInteger, nullable=False),
        Column("kind", Text, nullable=False),
        Column("number", Integer, nullable=False),
        Column("ref", Text),
        Column("title", Text, nullable=False),
        Column("body_md", Text),
        Column("status", Text, nullable=False, server_default="active"),
        Column("owner", Text),
        Column("period", Text),
        Column("due", Date),
        Column("baseline", Text),
        Column("target", Text),
        Column("source", Text),
        Column("source_url", Text),
        Column("source_rev", Text),
        Column("created_by", BigInteger),
        Column("updated_by", BigInteger),
        _stamp("created_at"),
        _stamp("updated_at"),
        _key("okr_items", "project_id", "projects", ondelete="CASCADE"),
        _key("okr_items", "created_by", "users", ondelete="SET NULL"),
        _key("okr_items", "updated_by", "users", ondelete="SET NULL"),
        PrimaryKeyConstraint("id", name="okr_items_pkey"),
        UniqueConstraint("project_id", "kind", "number", name="okr_items_code_key"),
        UniqueConstraint("project_id", "ref", name="okr_items_ref_key"),
        Index("okr_items_source_idx", "project_id", "source"),
        Index("okr_items_created_by_idx", "created_by"),
        Index("okr_items_updated_by_idx", "updated_by"),
    )


def _parents_table() -> Table:
    return Table(
        "okr_parents",
        metadata,
        Column("child_id", BigInteger, nullable=False),
        Column("parent_id", BigInteger, nullable=False),
        _key("okr_parents", "child_id", "okr_items", ondelete="CASCADE"),
        _key("okr_parents", "parent_id", "okr_items", ondelete="CASCADE"),
        PrimaryKeyConstraint("child_id", "parent_id", name="okr_parents_pkey"),
        Index("okr_parents_parent_idx", "parent_id"),
    )


def _links_table() -> Table:
    return Table(
        "okr_links",
        metadata,
        Column("id", BigInteger, Identity(always=True), nullable=False),
        Column("item_id", BigInteger, nullable=False),
        Column("target_kind", Text, nullable=False),
        Column("target", Text, nullable=False),
        Column("created_by", BigInteger),
        _stamp("created_at"),
        _key("okr_links", "item_id", "okr_items", ondelete="CASCADE"),
        _key("okr_links", "created_by", "users", ondelete="SET NULL"),
        PrimaryKeyConstraint("id", name="okr_links_pkey"),
        UniqueConstraint("item_id", "target_kind", "target", name="okr_links_once_key"),
        Index("okr_links_created_by_idx", "created_by"),
    )


items = _items_table()
parents = _parents_table()
links = _links_table()

NAMES = tuple(table.name for table in (items, parents, links))
