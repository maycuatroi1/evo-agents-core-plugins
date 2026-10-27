"""Failure triage of the plugin jev: a run that moved to failed gets its cause read by Jev (``evo_core_plugins.jev.triage``),
against a fake Jev server. The handler runs with the context the hub gives an event; the hub, the runs and the plugin's
tables are real. A cause the hub guessed is changed in the mode apply at the threshold and within the cap, and stays a
guess; every other answer is a suggestion; a run is asked once for each model. All names are fictional.
"""

from __future__ import annotations

import pytest

from tests.hub import pg

if not pg.DSN:
    pytest.skip(pg.SKIP_REASON, allow_module_level=True)

from sqlalchemy import select

from evo_agents.hub import tables
from evo_agents.hub.plugin_calls import CoreContext
from evo_core_plugins.jev import triage
from plugin_tests.test_jev_plugin import (  # noqa: F401 (fixtures)
    BASE,
    MODEL,
    PROJECT,
    client,
    configure,
    count,
    declare_sink,
    enable,
    enabled,
    fake,
    jev,
    jev_tables,
    members,
    ok,
    project_id,
    sql,
    tasks_core,
    untouched,
)
from tests.hub.test_chat_runs import chat_worker
from tests.hub.test_triage import failed_step

ERROR = "verify command `pytest` exited 1"


@pytest.fixture
def worker(client, jev):  # noqa: F811
    return chat_worker(client, jev["owner"], "lumen-mini", slots=4)


def says(fake, cause: str, confidence: float = 0.95) -> None:
    fake.answer = lambda question: {
        "type": "choice",
        "choice": cause,
        "confidence": confidence,
        "probabilities": {cause: confidence},
    }


def failed(client, jev, worker, cause=None, error=ERROR) -> int:  # noqa: F811
    return failed_step(client, jev, worker, cause=cause, error=error)


def cause_of(hub_db, run_id: int) -> str | None:
    return sql(hub_db, select(tables.runs.c.failure_cause).where(tables.runs.c.id == run_id))[0][0]


def ends(client, hub_db, run_id: int, to: str = "failed") -> dict:
    """The handler of ``run.state`` for a run that moved to ``to``, as the hub calls it."""
    context = CoreContext("jev", client.app.state.engine, client.app.state.config, PROJECT, project_id(hub_db))
    params = {
        "event": "triage",
        "project": PROJECT,
        "kind": "run.state",
        "payload": {"run_id": run_id, "from": "running", "to": to},
    }
    return client.portal.call(lambda: triage.on_run_state(params, context))


def acts(hub_db) -> list:
    a = jev_tables.acts.c
    return sql(hub_db, select(a.kind, a.feature, a.target, a.outcome, a.confidence, a.applied).order_by(a.id))


def other_than(cause: str | None) -> str:
    return "timeout" if cause != "timeout" else "cost_cap"


def test_jev_triage_applies_a_cause_the_hub_guessed_in_apply_mode_over_the_threshold(client, jev, worker, hub_db, fake):
    configure(client, jev["owner"], "jev", {"triage_mode": "apply"})
    run_id = failed(client, jev, worker)
    before = cause_of(hub_db, run_id)
    chosen = other_than(before)
    says(fake, chosen)
    assert ends(client, hub_db, run_id) == {"cause": chosen, "applied": True}
    assert cause_of(hub_db, run_id) == chosen
    (body,) = fake.bodies()
    options = body["questions"]["cause"]["criteria"]
    assert body["questions"]["cause"]["type"] == "choice" and set(options) >= {"verify_failed", "timeout", "origin"}
    assert len(options) == 19 and ERROR in body["state"]
    ((kind, feature, target, outcome, confidence, applied),) = acts(hub_db)
    assert (kind, feature, target, applied) == ("cause", "triage", f"run:{run_id}", True)
    assert outcome == f"{before} -> {chosen}" and confidence == 0.95
    assert sql(hub_db, select(jev_tables.usage.c.feature, jev_tables.usage.c.run_id)) == [("triage", run_id)]
    listed = ok(client.get(f"{BASE}/acts", headers=jev["alice"]))["acts"][0]
    assert listed["undo"]["path"] == f"/v1/projects/{PROJECT}/runs/{run_id}/cause/restore"
    restored = client.post(listed["undo"]["path"], headers=jev["owner"])
    assert restored.status_code == 200 and cause_of(hub_db, run_id) == before


def test_jev_triage_asks_a_run_once_for_each_model(client, jev, worker, hub_db, fake):
    configure(client, jev["owner"], "jev", {"triage_mode": "apply"})
    run_id = failed(client, jev, worker)
    says(fake, other_than(cause_of(hub_db, run_id)))
    assert ends(client, hub_db, run_id)["applied"] is True
    assert ends(client, hub_db, run_id) == {"skipped": "asked already"}
    assert len(fake.requests) == 1 and count(hub_db, jev_tables.asked) == 1
    sql(hub_db, jev_tables.asked.update().values(model="jev-0.9.0"))  # another pinned model asks again
    ends(client, hub_db, run_id)
    assert len(fake.requests) == 2


def test_jev_triage_suggest_mode_and_a_low_confidence_only_suggest(client, jev, worker, hub_db, fake):
    first, second = failed(client, jev, worker), failed(client, jev, worker)
    before = cause_of(hub_db, first)
    says(fake, other_than(before))
    configure(client, jev["owner"], "jev", {"triage_mode": "suggest"})
    assert ends(client, hub_db, first)["applied"] is False
    configure(client, jev["owner"], "jev", {"triage_mode": "apply"})
    says(fake, other_than(before), 0.6)
    assert ends(client, hub_db, second)["applied"] is False
    assert cause_of(hub_db, first) == before and cause_of(hub_db, second) == before
    assert [(row[3].split(" ")[0], row[5]) for row in acts(hub_db)] == [("suggest", False), ("suggest", False)]


def test_jev_triage_a_cause_the_worker_reported_only_gets_a_suggestion(client, jev, worker, hub_db, fake):
    configure(client, jev["owner"], "jev", {"triage_mode": "apply"})
    run_id = failed(client, jev, worker, cause="credentials", error="no credential reads northwind-api")
    says(fake, "timeout")
    assert ends(client, hub_db, run_id) == {"cause": "timeout", "applied": False}
    assert cause_of(hub_db, run_id) == "credentials"
    assert [row[5] for row in acts(hub_db)] == [False]


def test_jev_triage_stops_at_the_daily_cap(client, jev, worker, hub_db, fake):
    configure(client, jev["owner"], "jev", {"triage_mode": "apply", "triage_cap": 1})
    first, second = failed(client, jev, worker), failed(client, jev, worker)
    says(fake, other_than(cause_of(hub_db, first)))
    assert ends(client, hub_db, first)["applied"] is True
    assert ends(client, hub_db, second)["applied"] is False
    assert [row[5] for row in acts(hub_db)] == [True, False]


def test_jev_triage_a_failed_call_skips_the_run_and_is_not_repeated(client, jev, worker, hub_db, fake):
    configure(client, jev["owner"], "jev", {"triage_mode": "apply"})
    run_id = failed(client, jev, worker)
    before = cause_of(hub_db, run_id)
    fake.status = 500
    assert "skipped" in ends(client, hub_db, run_id)
    assert cause_of(hub_db, run_id) == before and len(fake.requests) == 1
    fake.status = 200
    assert ends(client, hub_db, run_id) == {"skipped": "asked already"} and len(fake.requests) == 1
    ((kind, feature, _, _, _, applied),) = acts(hub_db)
    assert (kind, feature, applied) == ("skipped", "triage", False)


def test_jev_triage_a_move_to_another_state_and_a_project_that_is_off_do_nothing(client, jev, worker, hub_db, fake):
    run_id = failed(client, jev, worker)
    assert ends(client, hub_db, run_id, to="succeeded") == {}
    assert ends(client, hub_db, run_id) == {}  # the feature is off: the default
    untouched(fake, hub_db)
