"""What the plugin jev does, for the routes, the tools and the commands alike.

A call to Jev passes the gates in this order, and the first that fails refuses with a reason a person can read, before
anything is sent or written: the project enables the plugin (the hub answers 404 otherwise); the caller has the writer
role; the project's config holds an ``api_key`` the hub can open and a pinned ``model``; the project's policy declares
the sink ``jev@typesafe``; the feature that asks is not off; and the day's spend plus the cost of this request stays
within ``daily_usd``. The call itself holds no database connection. Its answer is refused unless the model that
answered is the pinned one (the tokens it cost are still booked), and a failure books the call with no tokens and
says only what the plugin knows (the status code), never what the vendor sent.

``can_apply`` is the one place the modes, thresholds and caps of a feature are read, for the features that act by
themselves.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from decimal import Decimal

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncConnection

from evo_agents.hub.server import core_plugin_api as hub
from evo_core_plugins.jev import client, settings, store
from evo_core_plugins.jev.models import (
    JevAct,
    JevActs,
    JevAnswer,
    JevAsked,
    JevAskIn,
    JevFeature,
    JevMatch,
    JevMatches,
    JevStatus,
    JevUndo,
    JevUsage,
    JevWindow,
)

TOOL = "tool"  # the feature of a call a member or an agent makes by hand, which no mode gates
MAX_ACTS = 200
Begin = Callable[[], AbstractAsyncContextManager[AsyncConnection]]


@dataclass(frozen=True)
class Gate:
    """What the gates found for one call."""

    access: hub.ProjectRef
    session: hub.Session
    settings: settings.Settings


def said(exc: ValidationError) -> str:
    """The first problems pydantic found, one line."""
    return "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:5])


async def sink_declared(conn: AsyncConnection, project: str) -> bool:
    """Whether the project's policy declares the plugin's sink. The API has no question for it; a read that returns
    nothing says why, and the reason of a missing sink is the one that names it."""
    found = await hub.read_accepted_rules(conn, store.handle(), project, sink=settings.SINK, limit=1)
    return "declares no sink" not in (found.reason or "")


async def _config(conn: AsyncConnection, config, project: str):
    return await hub.plugin_config(conn, store.handle(), config, project=project)


def problems(found: settings.Settings, missing: tuple[str, ...], declared: bool, project: str) -> list[str]:
    """What stops a call before it starts, in words, in the order the gates test it."""
    out = []
    if "api_key" in missing:
        out.append("the api_key is sealed with a key this hub cannot open: set it again")
    elif not found.api_key:
        out.append(f"jev has no api_key in project {project}")
    if not found.model:
        out.append(f"jev has no pinned model in project {project}: set model to a version such as jev-1.0.0")
    if not declared:
        out.append(f"project {project} declares no sink {settings.SINK} in its policy")
    return out


async def _gate(conn: AsyncConnection, config, session: hub.Session, project: str, *, write: bool) -> Gate:
    access = await hub.project_access(conn, session, project)
    if write:
        store.writer(access, "asking Jev")
    else:
        store.reader(access)
    values = await _config(conn, config, project)
    return Gate(access, session, settings.read(values.values))


async def status(conn: AsyncConnection, config, session: hub.Session, project: str) -> JevStatus:
    gate = await _gate(conn, config, session, project, write=False)
    values = await _config(conn, config, project)
    declared = await sink_declared(conn, project)
    found = gate.settings
    spent = await store.spent_since(conn, gate.access.id, store.midnight())
    features = []
    for name in settings.FEATURES:
        mode = found.modes[name]
        row = JevFeature(name=name, mode=mode)
        if name != "rerank":
            raw = values.values
            row.threshold = float(raw.get(f"{name}_threshold", settings.DEFAULT_THRESHOLD))
            row.cap = int(raw.get(f"{name}_cap", settings.DEFAULT_CAP))
            row.applied_today = await store.applied_today(conn, gate.access.id, name)
            if name == "kg_review":
                row.noul_yes = float(raw.get("kg_review_noul_yes", settings.DEFAULT_THRESHOLD))
                row.noul_no = float(raw.get("kg_review_noul_no", settings.DEFAULT_NOUL_NO))
        features.append(row)
    return JevStatus(
        project=project,
        enabled=True,
        configured=found.configured,
        key_set=bool(found.api_key),
        model=found.model,
        base_url=found.base_url,
        sink=settings.SINK,
        sink_declared=declared,
        price_usd_per_million_tokens=settings.PRICE_PER_MILLION_USD,
        daily_usd=found.daily_usd,
        spent_today_usd=float(spent),
        features=features,
        problems=problems(found, tuple(values.missing_secrets), declared, project),
    )


def _window(found: dict) -> JevWindow:
    return JevWindow(**found)


async def usage(conn: AsyncConnection, config, session: hub.Session, project: str) -> JevUsage:
    gate = await _gate(conn, config, session, project, write=False)
    spans = store.windows()
    pid = gate.access.id
    return JevUsage(
        project=project,
        model=gate.settings.model,
        price_usd_per_million_tokens=settings.PRICE_PER_MILLION_USD,
        daily_usd=gate.settings.daily_usd,
        spent_today_usd=float(await store.spent_since(conn, pid, spans["today"])),
        last_24h=_window(await store.usage_window(conn, pid, spans["last_24h"])),
        last_7d=_window(await store.usage_window(conn, pid, spans["last_7d"])),
    )


def undo_of(project: str, feature: str, target: str, applied: bool, undone: bool) -> JevUndo | None:
    """How a member takes back an act the plugin applied, with the hub's own undo (it has no button for these on the
    web): the command, and the route behind it."""
    if not applied or undone:
        return None
    kind, _, ref = target.partition(":")
    if feature == "triage" and kind == "run" and ref.isdigit():
        path = f"/v1/projects/{project}/runs/{ref}/cause/restore"
        return JevUndo(command=f"evo-agents hub run-cause restore {ref} --project {project}", method="POST", path=path)
    if feature == "kg_review" and kind == "review" and ref:
        return JevUndo(
            command=f"evo-agents hub kg review undismiss {ref} --project {project}",
            method="DELETE",
            path=f"/v1/kg/{project}/review/{ref}/dismiss",
        )
    if feature == "kg_review" and kind == "decision" and ref.isdigit():
        return JevUndo(
            command=f"evo-agents hub kg decisions undo {ref} --project {project} --reason <why>",
            method="POST",
            path=f"/v1/kg/{project}/decisions/{ref}/undo",
        )
    return None


async def acts(conn: AsyncConnection, config, session: hub.Session, project: str, limit: int = 50) -> JevActs:
    gate = await _gate(conn, config, session, project, write=False)
    rows = await store.recent_acts(conn, gate.access.id, max(1, min(limit, MAX_ACTS)))
    return JevActs(
        project=project,
        acts=[
            JevAct(
                id=row.id,
                kind=row.kind,
                feature=row.feature,
                target=row.target,
                outcome=row.outcome,
                model=row.model,
                confidence=row.confidence,
                applied=row.applied,
                undone=row.undone_at is not None,
                undone_at=row.undone_at,
                created_at=row.created_at,
                undo=undo_of(project, row.feature, row.target, row.applied, row.undone_at is not None),
            )
            for row in rows
        ],
    )


async def matches(conn: AsyncConnection, config, session: hub.Session, project: str, limit: int = 50) -> JevMatches:
    """The corrections that repeat an earlier one or an accepted rule, newest first."""
    gate = await _gate(conn, config, session, project, write=False)
    rows = await store.recent_matches(conn, gate.access.id, max(1, min(limit, MAX_ACTS)))
    return JevMatches(
        project=project,
        matches=[
            JevMatch(
                id=row.id,
                day=row.day,
                evidence=row.evidence,
                candidate=row.candidate,
                model=row.model,
                confidence=row.confidence,
                state=row.state,
                created_at=row.created_at,
            )
            for row in rows
        ],
    )


async def can_apply(
    conn: AsyncConnection, project_id: int, found: settings.Settings, values: dict, feature: str, confidence: float
) -> str:
    """What a feature does with an answer of ``confidence``: ``off``, ``suggest`` (record it for a person) or
    ``apply``, which needs the mode apply, a confidence at the threshold and fewer applied acts today than the cap."""
    mode = found.modes.get(feature, "off")
    if mode != "apply":
        return mode if mode in ("off", "suggest") else "off"
    if confidence < float(values.get(f"{feature}_threshold", settings.DEFAULT_THRESHOLD)):
        return "suggest"
    done = await store.applied_today(conn, project_id, feature)
    if done >= int(values.get(f"{feature}_cap", settings.DEFAULT_CAP)):
        return "suggest"
    return "apply"


def _body(found: settings.Settings, asked: JevAskIn) -> dict:
    questions = {name: q.model_dump(exclude_none=True) for name, q in asked.questions.items()}
    return {"model": found.model, "state": asked.state, "questions": questions}


def _answers(asked: JevAskIn, reply: client.Reply) -> dict[str, JevAnswer]:
    """The answers of Jev as the questions asked for them; client.JevError when one is missing or off its type."""
    found = {}
    for name, question in asked.questions.items():
        raw = reply.answers.get(name)
        if not isinstance(raw, dict) or raw.get("type") != question.type:
            raise client.JevError(f"Jev gave no {question.type} answer to question {name}", sent=True)
        confidence = raw.get("confidence")
        confidence = (
            float(confidence) if isinstance(confidence, int | float) and not isinstance(confidence, bool) else None
        )
        if question.type == "choice":
            choice = raw.get("choice")
            if not isinstance(choice, str) or choice not in (question.criteria or {}):
                raise client.JevError(f"Jev's answer to question {name} is not one of its options", sent=True)
            found[name] = JevAnswer(type="choice", choice=choice, confidence=confidence, probabilities=_shape(raw))
        elif question.type == "noul":
            value = raw.get("noul")
            if not isinstance(value, int | float) or isinstance(value, bool) or not 0 <= value <= 1:
                raise client.JevError(f"Jev's answer to question {name} is not a number from 0 to 1", sent=True)
            found[name] = JevAnswer(type="noul", noul=float(value))
        else:
            value = raw.get("score")
            if not isinstance(value, int | float) or isinstance(value, bool):
                raise client.JevError(f"Jev's answer to question {name} is not a score", sent=True)
            legend = raw.get("legend")
            found[name] = JevAnswer(
                type="score",
                score=float(value),
                confidence=confidence,
                legend=legend if isinstance(legend, str) else None,
                probabilities=_shape(raw),
            )
    return found


def _shape(raw: dict):
    probabilities = raw.get("probabilities")
    return probabilities if isinstance(probabilities, dict | list) else None


def _outcome(answer: JevAnswer) -> str:
    if answer.type == "choice":
        return answer.choice or ""
    return f"{answer.noul:.3f}" if answer.type == "noul" else f"{answer.score:g}"


@dataclass(frozen=True)
class Exchange:
    """What one request to Jev came to: ``asked`` when it answered, else ``failure`` in words, and whether the request
    ``sent`` anything out (a refusal before the call sends nothing and books nothing)."""

    asked: JevAsked | None
    failure: str | None = None
    sent: bool = False
    status: int = 502


async def exchange(
    begin: Begin,
    config,
    project: str,
    asked: JevAskIn,
    *,
    feature: str = TOOL,
    session: hub.Session | None = None,
    run_id: int | None = None,
    audit_as: str = "decide",
    record_acts: bool = True,
) -> Exchange:
    """Put ``asked`` to Jev in ``project``, for ``session`` (a member, a writer) or, with none, for a feature of the
    plugin itself (a job or an event: the plugin is enabled in the project, and the gates after that are the same).
    ``hub.Refused`` for a gate that stops the call before anything is sent (409 for the config, the policy, a feature
    that is off or the budget; 422 for a request too large); once the call is made, a failure comes back in the
    ``Exchange``, booked as the call's usage and with no act."""
    async with begin() as conn:
        if session is not None:
            gate = await _gate(conn, config, session, project, write=True)
            project_id, found = gate.access.id, gate.settings
        else:
            project_id = (await hub.read_project(conn, store.handle(), project)).id
            found = settings.read((await _config(conn, config, project)).values)
        values = await _config(conn, config, project)
        why = problems(found, tuple(values.missing_secrets), await sink_declared(conn, project), project)
        if why:
            raise hub.Refused(409, why[0])
        if feature != TOOL and found.modes.get(feature, "off") == "off":
            raise hub.Refused(409, f"feature {feature} is off in project {project}")
        body = _body(found, asked)
        size = len(json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode())
        if size > client.MAX_REQUEST_BYTES:
            raise hub.Refused(422, f"the request is {size} bytes; a call takes at most {client.MAX_REQUEST_BYTES}")
        spent = await store.spent_since(conn, project_id, store.midnight())
        estimate = store.cost_of(size)  # one token is at least one byte: an upper bound
        if spent + estimate > Decimal(str(found.daily_usd)):
            raise hub.Refused(
                409,
                f"project {project} spent {spent:.4f} of its {found.daily_usd:g} USD a day, and this request may "
                f"cost {estimate:.4f}",
            )
    failure: client.JevError | None = None
    reply = None
    try:
        reply = await client.ask(found.base_url, found.api_key, body)
    except client.JevError as exc:
        failure = exc
    tokens = reply.input_tokens if reply is not None else 0
    wrong_model = reply is not None and reply.model != found.model
    answers: dict[str, JevAnswer] = {}
    if reply is not None and not wrong_model:
        try:
            answers = _answers(asked, reply)
        except client.JevError as exc:
            failure = exc
    if failure is None and wrong_model:
        failure = client.JevError(
            f"Jev answered with {client.shown_model(reply.model)}, not the pinned {found.model}; nothing was kept",
            sent=True,
        )
    async with begin() as conn:
        if failure is None or failure.sent:
            await store.record_usage(
                conn,
                project_id,
                user_id=session.user_id if session is not None else None,
                run_id=run_id,
                feature=feature,
                model=found.model,
                tokens=tokens,
                status="ok" if failure is None else "error",
            )
        if failure is None and record_acts:
            for name, answer in answers.items():
                await store.record_act(
                    conn,
                    project_id,
                    kind=answer.type,
                    feature=feature,
                    target=name,
                    outcome=_outcome(answer),
                    model=found.model,
                    confidence=answer.confidence,
                    applied=False,
                )
        note = f"{project}: failed" if failure is not None else f"{project}: {len(answers)} questions, {tokens} tokens"
        if failure is None or failure.sent:
            if session is not None:
                await hub.audit(conn, store.handle(), session, f"jev.{audit_as}", note, project=gate.access)
            else:
                await hub.record_audit(conn, store.handle(), project, f"jev.{audit_as}", note)
    if failure is not None:  # after the transaction, so the booking of the call stays
        return Exchange(None, str(failure), failure.sent)
    return Exchange(
        JevAsked(
            project=project,
            model=found.model,
            input_tokens=tokens,
            cost_usd=float(store.cost_of(tokens)),
            answers=answers,
        ),
        sent=True,
    )


async def ask(
    begin: Begin,
    config,
    session: hub.Session,
    project: str,
    asked: JevAskIn,
    *,
    feature: str = TOOL,
    run_id: int | None = None,
    audit_as: str = "decide",
) -> JevAsked:
    """Put ``asked`` to Jev for ``session`` in ``project``: refuses with ``hub.Refused`` (409 for a gate, 502 for a
    failed call, 422 for a request too large) and books the call and what Jev decided."""
    done = await exchange(
        begin, config, project, asked, feature=feature, session=session, run_id=run_id, audit_as=audit_as
    )
    if done.asked is None:
        raise hub.Refused(done.status, done.failure or "Jev did not answer")
    return done.asked


async def automatic(
    begin: Begin, config, project: str, asked: JevAskIn, *, feature: str, run_id: int | None = None
) -> Exchange:
    """The call a feature of the plugin makes by itself: as ``exchange`` with no member, no act booked (the feature
    books its own) and a refusal before the call returned as an ``Exchange`` that sent nothing."""
    try:
        return await exchange(
            begin, config, project, asked, feature=feature, run_id=run_id, audit_as=feature, record_acts=False
        )
    except hub.Refused as exc:
        return Exchange(None, str(exc.detail), False, exc.status_code)


def parse(state, questions) -> JevAskIn:
    """The request a tool or a command gives, as a model; ``hub.Refused`` 422 with what is wrong."""
    try:
        return JevAskIn.model_validate({"state": state, "questions": questions})
    except ValidationError as exc:
        raise hub.Refused(422, said(exc)) from None


__all__ = ["TOOL", "Exchange", "ask", "automatic", "acts", "can_apply", "exchange", "parse", "status", "usage"]
