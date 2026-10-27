"""The ledger of the plugin jev: what each call cost and what Jev decided, in the plugin's own tables, and who may
read or write them. SQLAlchemy Core on ``tables`` alone."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from evo_agents.hub.server import core_plugin_api as hub
from evo_core_plugins.jev import tables as jev
from evo_core_plugins.jev.settings import PRICE_PER_MILLION_USD

SINK_HEADER = "X-Evo-Sink"  # accepted and ignored: the plugin has one sink, which the policy must declare
MILLION = Decimal(1_000_000)
PRICE = Decimal(str(PRICE_PER_MILLION_USD))


def handle() -> hub.Plugin:
    """The plugin's handle, which every call of the hub's API takes."""
    return hub.plugin(__name__)


def cost_of(tokens: int) -> Decimal:
    """What ``tokens`` input tokens cost at the vendor's price."""
    return Decimal(tokens) * PRICE / MILLION


def midnight(now: datetime | None = None) -> datetime:
    """The start of the UTC day of ``now``."""
    now = now or datetime.now(UTC)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


# Who may do what


def reader(access: hub.ProjectRef) -> None:
    """Reading needs a grant on the project: a hub admin without one gets this far only."""
    if access.role is None or access.max_level is None:
        raise hub.Refused(403, f"reading Jev in project {access.name} needs a grant on it")


def writer(access: hub.ProjectRef, what: str) -> None:
    reader(access)
    if not hub.has_role(access.role, "writer"):
        raise hub.Refused(403, f"{what} in project {access.name} needs the writer role; you are {access.role}")


# The usage ledger


async def spent_since(conn: AsyncConnection, project_id: int, since: datetime) -> Decimal:
    u = jev.usage.c
    query = select(func.coalesce(func.sum(u.cost_usd), 0)).where(u.project_id == project_id, u.created_at >= since)
    return Decimal((await conn.execute(query)).scalar_one())


async def record_usage(
    conn: AsyncConnection,
    project_id: int,
    *,
    user_id: int | None,
    run_id: int | None,
    feature: str,
    model: str,
    tokens: int,
    status: str,
) -> None:
    await conn.execute(
        insert(jev.usage).values(
            project_id=project_id,
            user_id=user_id,
            run_id=run_id,
            feature=feature,
            model=model,
            input_tokens=tokens,
            cost_usd=cost_of(tokens),
            status=status,
        )
    )


async def usage_window(conn: AsyncConnection, project_id: int, since: datetime) -> dict:
    """Calls, failed calls, tokens and cost since ``since``, and the same by feature."""
    u = jev.usage.c
    failed = func.count().filter(u.status != "ok")
    totals = (
        await conn.execute(
            select(
                func.count().label("calls"),
                failed.label("failed"),
                func.coalesce(func.sum(u.input_tokens), 0).label("tokens"),
                func.coalesce(func.sum(u.cost_usd), 0).label("cost"),
            ).where(u.project_id == project_id, u.created_at >= since)
        )
    ).one()
    rows = (
        await conn.execute(
            select(
                u.feature, func.count().label("calls"), func.sum(u.input_tokens).label("tokens"), func.sum(u.cost_usd)
            )
            .where(u.project_id == project_id, u.created_at >= since)
            .group_by(u.feature)
            .order_by(u.feature)
        )
    ).all()
    return {
        "calls": totals.calls,
        "failed": totals.failed,
        "input_tokens": int(totals.tokens),
        "cost_usd": float(totals.cost),
        "by_feature": [
            {"feature": row.feature, "calls": row.calls, "input_tokens": int(row.tokens), "cost_usd": float(row[3])}
            for row in rows
        ],
    }


def windows(now: datetime | None = None) -> dict[str, datetime]:
    now = now or datetime.now(UTC)
    return {"today": midnight(now), "last_24h": now - timedelta(hours=24), "last_7d": now - timedelta(days=7)}


# The acts


async def record_act(
    conn: AsyncConnection,
    project_id: int,
    *,
    kind: str,
    feature: str,
    target: str,
    outcome: str,
    model: str,
    confidence: float | None,
    applied: bool,
) -> int:
    return (
        await conn.execute(
            insert(jev.acts)
            .values(
                project_id=project_id,
                kind=kind,
                feature=feature,
                target=target[: jev.MAX_TARGET_CHARS],
                outcome=outcome[: jev.MAX_OUTCOME_CHARS],
                model=model,
                confidence=confidence,
                applied=applied,
            )
            .returning(jev.acts.c.id)
        )
    ).scalar_one()


async def recent_acts(conn: AsyncConnection, project_id: int, limit: int) -> list:
    a = jev.acts.c
    query = select(jev.acts).where(a.project_id == project_id).order_by(a.created_at.desc(), a.id.desc()).limit(limit)
    return list((await conn.execute(query)).all())


async def applied_today(conn: AsyncConnection, project_id: int, feature: str, now: datetime | None = None) -> int:
    """How many acts of ``feature`` the plugin applied by itself since UTC midnight, undone ones included: the cap
    counts what was done, not what stayed."""
    a = jev.acts.c
    query = select(func.count()).where(
        a.project_id == project_id, a.feature == feature, a.applied.is_(True), a.created_at >= midnight(now)
    )
    return int((await conn.execute(query)).scalar_one())


async def mark_undone(conn: AsyncConnection, project_id: int, act_id: int) -> bool:
    """Note that a member undid act ``act_id`` (through the hub's own undo): False when it is not this project's or was
    noted already."""
    a = jev.acts.c
    done = await conn.execute(
        update(jev.acts)
        .where(a.id == act_id, a.project_id == project_id, a.undone_at.is_(None))
        .values(undone_at=func.now())
    )
    return done.rowcount == 1


# What a feature asked a model once


async def claim(conn: AsyncConnection, project_id: int, feature: str, subject: str, model: str) -> bool:
    """Take the right to ask ``model`` about ``subject`` for ``feature``: True the first time, False once it was asked
    (a failed turn counts: the call may have cost money, and the next pass does not repeat it)."""
    taken = await conn.execute(
        pg_insert(jev.asked)
        .values(project_id=project_id, feature=feature, subject=subject[: jev.MAX_TARGET_CHARS], model=model)
        .on_conflict_do_nothing()
        .returning(jev.asked.c.subject)
    )
    return taken.first() is not None


async def release(conn: AsyncConnection, project_id: int, feature: str, subject: str, model: str) -> None:
    """Give the claim back, for a turn that stopped before anything was sent."""
    t = jev.asked.c
    await conn.execute(
        delete(jev.asked).where(
            t.project_id == project_id,
            t.feature == feature,
            t.subject == subject[: jev.MAX_TARGET_CHARS],
            t.model == model,
        )
    )


# The corrections that repeat


async def record_match(
    conn: AsyncConnection,
    project_id: int,
    *,
    day: date,
    evidence: str,
    candidate: str,
    model: str,
    confidence: float,
    state: str,
) -> None:
    """One correction's match (``jev.MATCH_STATES``); a correction matched already by this model keeps its row."""
    await conn.execute(
        pg_insert(jev.matches)
        .values(
            project_id=project_id,
            day=day,
            evidence=evidence[: jev.MAX_TARGET_CHARS],
            candidate=candidate[: jev.MAX_TARGET_CHARS],
            model=model,
            confidence=confidence,
            state=state,
        )
        .on_conflict_do_nothing()
    )


async def recent_matches(conn: AsyncConnection, project_id: int, limit: int) -> list:
    m = jev.matches.c
    query = (
        select(jev.matches).where(m.project_id == project_id).order_by(m.created_at.desc(), m.id.desc()).limit(limit)
    )
    return list((await conn.execute(query)).all())


async def matched_on(conn: AsyncConnection, project_id: int, day: date) -> int:
    """How many corrections of ``day`` a model matched over the threshold (state ``match``)."""
    m = jev.matches.c
    query = select(func.count()).where(m.project_id == project_id, m.day == day, m.state == "match")
    return int((await conn.execute(query)).scalar_one())
