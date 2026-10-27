"""What the features that act by themselves (``triage``, ``review``, ``corrections``) share: the gates they pass
before they ask Jev anything, and the one question they put for a subject.

A feature does nothing, sends nothing and writes nothing unless ``setup`` finds the plugin enabled in the project, the
feature's mode not off, an ``api_key`` and a pinned ``model``, and the sink declared in the project's policy
(``docs/jev-plugin.md``). It asks a model about a subject once (``store.claim``): a turn Jev failed or answered late
is skipped, with the reason in the plugin's acts, and never blocks the hub, whose job or event it runs in. The daily
budget holds for these calls as for a member's (``service.exchange``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from evo_agents.hub.server import core_plugin_api as hub
from evo_core_plugins.jev import service, settings, store
from evo_core_plugins.jev.models import JevAsked

log = logging.getLogger(__name__)
MAX_REASON = 900  # the words of a decision's reason, under the hub's 1000


@dataclass(frozen=True)
class Setup:
    """What a feature reads once, when it starts a pass."""

    feature: str
    project: str
    project_id: int
    found: settings.Settings
    values: dict
    context: hub.Context

    @property
    def model(self) -> str:
        return self.found.model or ""

    def threshold(self, name: str = "threshold") -> float:
        return float(self.values.get(f"{self.feature}_{name}", settings.DEFAULT_THRESHOLD))


@dataclass(frozen=True)
class Put:
    """The result of putting a question: the answers, or why there are none; ``stop`` when no later question of this
    pass can go out either (the budget, the config)."""

    asked: JevAsked | None = None
    reason: str | None = None
    stop: bool = False


async def setup(context: hub.Context, project: str | None, feature: str) -> Setup | None:
    """The ``Setup`` of ``feature`` in ``project``, or None when it must do nothing (and has asked and written
    nothing): the project did not enable the plugin, the mode is off, the key or the model is missing, or the sink
    is not declared."""
    if not project:
        return None
    try:
        async with hub.transaction(context) as conn:
            enabled = await hub.read_project(conn, store.handle(), project)
            config = await hub.plugin_config(conn, store.handle(), context.config, project=project)
            found = settings.read(config.values)
            if found.modes.get(feature, "off") == "off":
                return None
            declared = await service.sink_declared(conn, project)
    except hub.Refused:
        return None
    why = service.problems(found, tuple(config.missing_secrets), declared, project)
    if why:
        log.info("jev %s skipped", feature, extra={"project": project, "why": why[0]})
        return None
    return Setup(feature, project, enabled.id, found, dict(config.values), context)


async def put(on: Setup, subject: str, state: str | dict, questions: dict, *, run_id: int | None = None) -> Put:
    """Put ``questions`` about ``state`` to Jev for ``subject``, once for the pinned model. A failure is booked and
    noted as an act of kind ``skipped``; a refusal before the call gives the claim back."""
    try:
        asked = service.parse(state, questions)
    except hub.Refused as exc:
        return Put(reason=str(exc.detail))
    async with hub.transaction(on.context) as conn:
        if not await store.claim(conn, on.project_id, on.feature, subject, on.model):
            return Put(reason="asked already")
    done = await service.automatic(
        lambda: hub.transaction(on.context), on.context.config, on.project, asked, feature=on.feature, run_id=run_id
    )
    if done.asked is not None:
        return Put(done.asked)
    async with hub.transaction(on.context) as conn:
        if not done.sent:
            await store.release(conn, on.project_id, on.feature, subject, on.model)
        else:
            await act(conn, on, "skipped", subject, (done.failure or "Jev did not answer"), None, False)
    log.info("jev %s skipped", on.feature, extra={"project": on.project, "subject": subject, "why": done.failure})
    return Put(reason=done.failure, stop=not done.sent)


async def act(conn, on: Setup, kind: str, target: str, outcome: str, confidence: float | None, applied: bool) -> int:
    """Book what the feature did or only suggested."""
    return await store.record_act(
        conn,
        on.project_id,
        kind=kind,
        feature=on.feature,
        target=target,
        outcome=outcome,
        model=on.model,
        confidence=confidence,
        applied=applied,
    )


async def room(conn, on: Setup) -> bool:
    """Whether the feature may still apply an act today: fewer applied than its cap."""
    done = await store.applied_today(conn, on.project_id, on.feature)
    return done < int(on.values.get(f"{on.feature}_cap", settings.DEFAULT_CAP))


def reason(on: Setup, words: str, confidence: float | None) -> str:
    """The reason a decision of the feature carries: the model, the confidence and what it saw."""
    shown = "n/a" if confidence is None else f"{confidence:.2f}"
    return f"jev {on.model}, confidence {shown}: {words}"[:MAX_REASON]
