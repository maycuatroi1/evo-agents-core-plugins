"""Corrections that repeat, in the plugin jev: the daily job reads the corrections of the day before through the API,
keeps the candidates that share words (earlier corrections and accepted rules) without calling Jev, puts one choice
question with a none option, records the matches in the plugin's table and, in the mode apply, pushes the day's repeat
rate to Signal (``evo_core_plugins.jev.corrections``), against a fake Jev server. All names are fictional.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest

from tests.hub import pg

if not pg.DSN:
    pytest.skip(pg.SKIP_REASON, allow_module_level=True)

from sqlalchemy import insert, select

from evo_agents.hub import tables
from evo_agents.hub.plugin_calls import CoreContext
from evo_core_plugins.jev import corrections
from plugin_tests.test_jev_plugin import (  # noqa: F401 (fixtures)
    BASE,
    MODEL,
    PROJECT,
    client,
    configure,
    count,
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

LABEL = {"level": "internal", "projects": [PROJECT]}
FIRST = "never add new files to northwind billing, edit the existing module instead"
EARLIER = "stop adding new files to northwind billing: edit the existing module"
UNRELATED = "rename the lumen total to the order total please"
KEY = "delivery.repeat_correction_rate"


def facet(hub_db, session_id: str, at: datetime, turns: list[str], flagged: list[int]) -> None:
    sql(
        hub_db,
        insert(tables.session_facets).values(
            project_id=project_id(hub_db),
            kind="session",
            session_id=session_id,
            at=at,
            label=LABEL,
            body={"user_turns": turns, "corrections": flagged},
        ),
    )


@pytest.fixture
def day(hub_db, jev):  # noqa: F811
    """The corrections of the day before (two, one of which repeats an earlier correction) and the earlier one."""
    start, _ = corrections.day_bounds()
    facet(hub_db, "s-yesterday", start + timedelta(hours=10), [FIRST, "thanks", UNRELATED], [0, 2])
    facet(hub_db, "s-before", start - timedelta(days=5), [EARLIER], [0])
    return start


def says(fake, choice: str, confidence: float = 0.95) -> None:
    fake.answer = lambda question: {
        "type": "choice",
        "choice": choice,
        "confidence": confidence,
        "probabilities": {choice: confidence},
    }


def run(client, hub_db) -> dict:
    context = CoreContext("jev", client.app.state.engine, client.app.state.config, PROJECT, project_id(hub_db))
    return client.portal.call(lambda: corrections.on_job({"projects": [PROJECT]}, context))


def matches(hub_db) -> list:
    m = jev_tables.matches.c
    return sql(hub_db, select(m.evidence, m.candidate, m.model, m.confidence, m.state).order_by(m.id))


def rates(hub_db) -> list[float]:
    s, k = tables.signals, tables.signal_keys
    query = select(s.c.value).join_from(s, k, k.c.id == s.c.key_id).where(k.c.name == KEY).order_by(s.c.id)
    return [row[0] for row in sql(hub_db, query)]


def declare_rate(hub_db) -> None:
    owner = sql(hub_db, select(tables.users.c.id).where(tables.users.c.login == "owner"))[0][0]
    values = {"project_id": project_id(hub_db), "name": KEY, "kind": "number", "created_by": owner}
    sql(hub_db, insert(tables.signal_keys).values(**values))


def test_jev_correction_that_repeats_an_earlier_one_is_matched_and_the_day_rate_is_pushed(
    client, jev, hub_db, fake, day
):
    configure(client, jev["owner"], "jev", {"corrections_mode": "apply"})
    declare_rate(hub_db)
    says(fake, "c1")
    done = run(client, hub_db)
    assert done[PROJECT]["asked"] == 1 and done[PROJECT]["corrections"] == 2, "the unrelated one is not asked"
    assert matches(hub_db) == [
        ("session:s-yesterday:user_turns:0", "session:s-before:user_turns:0", MODEL, 0.95, "match")
    ]
    (body,) = fake.bodies()
    question = body["questions"]["match"]
    assert question["type"] == "choice" and set(question["criteria"]) == {"c1", "none"}
    assert EARLIER in question["criteria"]["c1"] and body["state"] == FIRST
    assert rates(hub_db) == [0.5], "one match over the two corrections of the day"
    again = run(client, hub_db)
    assert again[PROJECT]["asked"] == 0 and len(fake.requests) == 1 and rates(hub_db) == [0.5]


def test_jev_correction_under_the_threshold_is_only_a_suggestion_and_none_is_no_match(client, jev, hub_db, fake, day):
    configure(client, jev["owner"], "jev", {"corrections_mode": "apply"})
    declare_rate(hub_db)
    says(fake, "c1", 0.6)
    run(client, hub_db)
    assert [row[4] for row in matches(hub_db)] == ["suggestion"] and rates(hub_db) == [0.0]
    sql(hub_db, jev_tables.asked.delete())
    sql(hub_db, jev_tables.matches.delete())
    says(fake, "none")
    run(client, hub_db)
    assert matches(hub_db) == []


def test_jev_correction_matches_a_rule_the_project_accepted(client, jev, hub_db, fake, day):
    worker = chat_worker(client, jev["owner"], "lumen-mini", slots=4)
    run_id = failed_step(client, jev, worker, cause=None, error="verify command `pytest` exited 1")
    title = "Edit the existing module of northwind billing"
    p = tables.proposals
    sql(
        hub_db,
        insert(p).values(
            project_id=project_id(hub_db),
            run_id=run_id,
            lens="corrections",
            kind="docs",
            title=title,
            summary="Never add new files to the billing module",
            paths=[],
            tier_reasons=["a docs change"],
            evidence=[],
            evidence_count=1,
            draft={},
            fingerprint=hashlib.sha256(title.encode()).hexdigest(),
            tier=1,
            state="accepted",
            label=LABEL,
            answered_at=datetime.now(UTC),
            answered_by=sql(hub_db, select(tables.users.c.id).limit(1))[0][0],
        ),
    )
    sql(hub_db, tables.session_facets.delete().where(tables.session_facets.c.session_id == "s-before"))
    configure(client, jev["owner"], "jev", {"corrections_mode": "suggest"})
    says(fake, "c1")
    run(client, hub_db)
    ((evidence, candidate, _, _, state),) = matches(hub_db)
    assert evidence == "session:s-yesterday:user_turns:0" and candidate.startswith("proposal:") and state == "match"


def test_jev_correction_suggest_mode_records_the_match_and_pushes_no_signal(client, jev, hub_db, fake, day):
    configure(client, jev["owner"], "jev", {"corrections_mode": "suggest"})
    declare_rate(hub_db)
    says(fake, "c1")
    run(client, hub_db)
    assert [row[4] for row in matches(hub_db)] == ["match"] and rates(hub_db) == []


def test_jev_correction_a_day_with_none_asks_nothing_and_pushes_no_rate(client, jev, hub_db, fake):
    configure(client, jev["owner"], "jev", {"corrections_mode": "apply"})
    declare_rate(hub_db)
    done = run(client, hub_db)
    assert done[PROJECT]["corrections"] == 0 and rates(hub_db) == []
    untouched(fake, hub_db)


def test_jev_correction_a_failed_call_skips_it_and_is_not_repeated(client, jev, hub_db, fake, day):
    configure(client, jev["owner"], "jev", {"corrections_mode": "apply"})
    fake.status = 500
    run(client, hub_db)
    fake.status = 200
    run(client, hub_db)
    assert len(fake.requests) == 1 and matches(hub_db) == []
    a = jev_tables.acts.c
    assert sql(hub_db, select(a.kind, a.applied)) == [("skipped", False)]


def test_jev_correction_matches_are_listed_by_the_route_and_the_cli_words(client, jev, hub_db, fake, day):
    configure(client, jev["owner"], "jev", {"corrections_mode": "suggest"})
    says(fake, "c1")
    run(client, hub_db)
    listed = ok(client.get(f"{BASE}/matches", headers=jev["alice"]))["matches"]
    assert [(m["evidence"], m["candidate"], m["state"]) for m in listed] == [
        ("session:s-yesterday:user_turns:0", "session:s-before:user_turns:0", "match")
    ]
    words = ok(client.get(f"{BASE}/matches?render=text", headers=jev["alice"]))["text"]
    assert "session:s-yesterday:user_turns:0" in words and "match" in words
    assert count(hub_db, jev_tables.matches) == 1


def test_jev_correction_does_nothing_while_the_feature_is_off(client, jev, hub_db, fake, day):
    assert run(client, hub_db) == {}
    untouched(fake, hub_db)
