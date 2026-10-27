"""Failure triage: when a run fails, ask Jev which cause the failure has (the event ``run.state``, with the grant
``runs:read``).

The plugin reads the run's detail through the API (``read_run_failure``: the sanitized error, the cause, whether the
hub guessed it, the last events), puts one choice question to Jev among the causes the hub knows, and:

- mode ``apply``, a cause the hub guessed, a confidence at the threshold and fewer acts today than the cap: the cause
  is changed through ``classify_run_failure``. It stays a guess, the triage rules and the reruns read it as before,
  and a writer restores the previous one (``evo-agents hub run-cause restore``);
- anything else (mode ``suggest``, a confidence under the threshold, a cause the worker reported, the cap): only a
  suggestion, an act of the plugin that is not applied.

A run is asked once for each model. The hub does not wait for Jev: a failed or late call skips the run.
"""

from __future__ import annotations

import logging

from evo_agents.hub.server import core_plugin_api as hub
from evo_core_plugins.jev import automatic, store

log = logging.getLogger(__name__)
FEATURE = "triage"

# the causes the hub knows (``runs.FAILURE_CAUSES``), each in one sentence
CAUSES = {
    "origin": "the project lists no origin for a repo the run needs",
    "credentials": "no credential reads a repo of the run, or git refused a fetch or a push",
    "missing_tool": "a program that a verify command or a check calls is not on the worker's PATH",
    "push_conflict": "the remote branch moved on and the run's own commits could not go on top of it",
    "verify_failed": "a verify command the worker ran again exited with a failure",
    "timeout": "the run ran past its timeout",
    "cost_cap": "the agent stopped at the run's cost cap",
    "turn_cap": "the agent stopped at the run's turns cap",
    "time_cap": "the agent stopped at the run's time cap",
    "checkout": "the checkout, the fetch or a worktree of the run went wrong",
    "runtime": "the worker has no adapter for the runtime, or cannot start the agent as the run asks",
    "worker_stopped": "the worker daemon was stopped or failed while it held the run",
    "branch_mismatch": "the worktree is on another branch than the run's",
    "rate_limit": "the agent's account hit its usage limit and the run could not move to another account",
    "account_auth": "the agent's account failed to authenticate and the run could not move to another one",
    "environment": "the worker cannot run the agent in the environment the run asks for",
    "push_declined": "the remote declined the push of the run's branch by a rule of its own",
    "no_worker": "no worker claimed the run in time",
    "no_answer": "the agent of a question run wrote no answer",
}
QUESTION = {
    "type": "choice",
    "instructions": "Why did this run fail? Choose the cause that best describes the failure.",
    "criteria": CAUSES,
}


def state_of(failure) -> str:
    """The text Jev reads: what the API gave of the failed run, nothing else."""
    lines = [
        f"A run of kind {failure.kind} ended failed.",
        f"The hub's present cause: {failure.failure_cause or 'none'}.",
        f"Error: {failure.error or 'none'}",
    ]
    lines += [f"event {e.seq} ({e.kind}): {e.text}" for e in failure.events]
    return "\n".join(lines)


async def on_run_state(params: dict, context: hub.Context) -> dict:
    """The event ``run.state``: a run that moved to failed gets its cause read by Jev."""
    payload = params.get("payload") or {}
    run_id = payload.get("run_id")
    if payload.get("to") != "failed" or not isinstance(run_id, int):
        return {}
    on = await automatic.setup(context, params.get("project"), FEATURE)
    if on is None:
        return {}
    async with hub.transaction(context) as conn:
        found = await hub.read_run_failure(conn, store.handle(), on.project, run_id)
    if not found.items:
        log.info("jev triage skipped", extra={"project": on.project, "run": run_id, "why": found.reason})
        return {"skipped": found.reason}
    failure = found.items[0]
    sent = await automatic.put(on, f"run:{run_id}", state_of(failure), {"cause": QUESTION}, run_id=run_id)
    if sent.asked is None:
        return {"skipped": sent.reason}
    answer = sent.asked.answers["cause"]
    cause, confidence = answer.choice or "", answer.confidence or 0.0
    target, previous = f"run:{run_id}", failure.failure_cause
    async with hub.transaction(context) as conn:
        if cause not in CAUSES or cause == previous:
            await automatic.act(conn, on, "cause", target, f"agrees: {cause}", confidence, False)
            return {"cause": cause, "applied": False}
        verdict = await _verdict(conn, on, failure, confidence)
        if verdict == "apply":
            try:
                done = await hub.classify_run_failure(
                    conn, store.handle(), on.project, run_id, cause, model=on.model, confidence=confidence
                )
            except (hub.Refused, ValueError) as exc:  # the run moved on, or a writer restored one: only a suggestion
                words = getattr(exc, "detail", None) or str(exc)
                await automatic.act(conn, on, "cause", target, f"suggest {cause}: {words}", confidence, False)
                return {"cause": cause, "applied": False}
            await automatic.act(conn, on, "cause", target, f"{done.previous} -> {done.cause}", confidence, True)
            return {"cause": cause, "applied": True}
        await automatic.act(
            conn, on, "cause", target, f"suggest {cause} ({previous or 'no cause'} now)", confidence, False
        )
    return {"cause": cause, "applied": False}


async def _verdict(conn, on: automatic.Setup, failure, confidence: float) -> str:
    """``apply`` only for a cause the hub guessed, in the mode apply, at the threshold and within the cap."""
    if on.found.modes[FEATURE] != "apply" or not failure.inferred or failure.failure_cause is None:
        return "suggest"
    if confidence < on.threshold() or not await automatic.room(conn, on):
        return "suggest"
    return "apply"


__all__ = ["CAUSES", "on_run_state"]
