# The core plugin jev: decisions put to Jev, with a budget and a ledger

The plugin **jev** lets a project put questions about a state to Jev, the System One model of TypeSafe, and keeps what
each call cost and what Jev decided. Its code is `evo_core_plugins/jev`; evo-agents-core-plugins ships it as a core
plugin. It asks for API 1.6 of `core_plugin_api`, imports nothing else of the hub, keeps its tables with SQLAlchemy Core
and its own migration chain (`jev_0001`, version table `alembic_version_jev`), and imports no other plugin.

It does nothing, and sends nothing, when any of these holds: the project has not enabled it, it has no `api_key`, the
project's policy declares no sink `jev@typesafe`, or every feature is off. In those cases the vendor receives no
request, no table gets a row and no act is applied.

## Enabling it

```sh
evo-agents hub plugin enable jev --project northwind
evo-agents hub plugin config jev --project northwind --set model=jev-1.2.0
evo-agents hub plugin config jev --project northwind --secret api_key < key-file
```

The project's policy must also declare the egress sink the plugin names in its manifest: id `jev@typesafe`, kind
`llm-backend`, host `api.typesafe.ai`. A hub admin sets its clearance; the plugin reads accepted rules through the
sink, so what a project's policy keeps from that sink never leaves the hub.

## Config

| Field | Meaning |
| --- | --- |
| `api_key` | the project's TypeSafe key (x-secret); it travels only in the `Authorization` header |
| `model` | the pinned version, `^jev-[0-9]+\.[0-9]+\.[0-9]+$`; an alias is refused, and so is an answer from another model |
| `base_url` | https only; every address it resolves to must be public; the call goes to the checked address, with no redirect followed |
| `daily_usd` | the most the project's calls may cost in a UTC day (default 1) |
| `triage_mode`, `kg_review_mode`, `corrections_mode` | `off` (default), `suggest` (record what Jev answered) or `apply` |
| `triage_threshold`, `corrections_threshold` | the confidence an answer needs to be applied (0.9) |
| `kg_review_noul_yes`, `kg_review_noul_no` | the noul value at or above which a review is applied as yes, at or below which as no (0.9, 0.1) |
| `*_cap` | the most acts a feature applies by itself in a day (50) |
| `rerank` | `off` (default) or `on` |

## The client

One request is `POST <base_url>/v1/systemone` with `{model, state, questions}`; the answer carries `{model, answers,
usage}`. The timeout is under 30 seconds, there is no retry, the reply is read to at most 1 MB, and a request is at
most 120000 bytes. An error says the status the vendor gave and never a body or a header of it.

A question has a `type`: `choice` (criteria: an object of 2 to 8 options with their words), `noul` (an optional object
with the keys `true` and `false`) or `score` (a list of 2 to 10 levels, lowest first).

Cost is input tokens times 0.042 USD per million. Before the call the plugin books an upper bound (the request bytes
at that price) against `daily_usd` and refuses the call when it would pass it; afterwards it books the real figure.
[Inference] Calls that run at the same moment can overshoot the budget by what each of them estimated.

## Tools

| Tool | What it does |
| --- | --- |
| `jev__decide` | puts `state` and `questions` to Jev as the member at the origin of the run (a writer) and returns the answers with their cost |
| `jev__usage` | returns the cost of the last 24 hours and 7 days against the budget |

A refusal comes back as `refused: <reason>` with the error flag set: not configured, no sink declared, over the daily
budget, a wrong model, or a request too large. State a tool passes has no label of the hub's, so the gates are the
project's sink declaration and the caller's writer role.

## Tables

| Table | What it holds |
| --- | --- |
| `jev_usage` | one row for each call: project, member, run, feature, model, input tokens, cost, status (`ok` or `error`), time |
| `jev_acts` | one row for each decision: kind, feature, target, outcome, model, confidence, whether it was applied, when it was undone, time |

A failed call is booked once, with its status and no vendor text. Acts are recorded as not applied; a feature that
applies acts checks `can_apply` first: its mode, the threshold and the cap of the day. The hub emits no event when an
applied act is undone, so `undone_at` is set only by the plugin's own `mark_undone`.

## Page, routes and CLI

The page **Jev** shows the status of each feature, the cost of 24 hours and 7 days against the budget, and the recent
acts, each with the hub's command that undoes it. It is laid out for 375 px and uses the hub kit's light and dark
tokens. Undo is the hub's own: for a triage act `evo-agents hub run-cause restore RUN --project P`
(`POST /v1/projects/{p}/runs/{id}/cause/restore`), for a knowledge-graph review
`evo-agents hub kg review undismiss FINGERPRINT --project P` (`DELETE /v1/kg/{project}/review/{fp}/dismiss`).

Routes, under `/v1/x/jev/<project>`: `GET status`, `GET usage`, `GET acts?limit=`, `POST ask`. Each of the first three
takes `render=text`.

```sh
evo-agents hub jev status --project northwind
evo-agents hub jev ask --project northwind --file ask.json
evo-agents hub jev usage --project northwind --json
evo-agents hub jev acts --project northwind --limit 20
```

`ask.json`:

```json
{
  "state": "The release note for lumen 2.1 is drafted.",
  "questions": {
    "ready": {"type": "noul", "instructions": "Is the note ready to send?"}
  }
}
```

## Testing

`plugin_tests/test_jev_plugin.py` runs the plugin against a fake Jev server (an `httpx.MockTransport`), with the
resolver and the transport of `evo_core_plugins.jev.client` replaced. Tests whose names hold `optional` show the plugin
does nothing when it is not enabled, has no key, has no sink or has every feature off.
