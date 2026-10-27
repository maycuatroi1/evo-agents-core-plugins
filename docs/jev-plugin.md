# The core plugin jev: decisions put to Jev, with a budget and a ledger

The plugin **jev** lets a project put questions about a state to Jev, the System One model of TypeSafe, and keeps what
each call cost and what Jev decided. Its code is `evo_core_plugins/jev`; evo-agents-core-plugins ships it as a core
plugin. It asks for API 1.7 of `core_plugin_api`, imports nothing else of the hub, keeps its tables with SQLAlchemy Core
and its own migration chain (`jev_0001`, `jev_0002`, version table `alembic_version_jev`), and imports no other plugin.

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
| `rerank` | `off` (default) or `on`: the ranker below is called for the project's searches |

## What the plugin does by itself

Three features act without a member asking, and a fourth, rerank, answers when the hub's search asks. Each is off until its mode is set, and each passes the same gates as a
call of a member: the plugin enabled in the project, an `api_key` and a pinned `model`, the sink declared, the mode not
`off`, and the daily budget. A call has no member behind it, so its audit row has no actor. A feature asks a model
about a subject once (table `jev_asked`): a call Jev failed or answered late is booked as an act of kind `skipped`,
the hub's job or event is not held up, and the subject is not asked again for that model. Text leaves the hub only as
the core plugin API returns it, which is through the sink and its label gate. The permission `runs:read` is asked
for the event of the triage.

| Feature | When | What it asks | What it does |
| --- | --- | --- | --- |
| triage | the event `run.state` to `failed` | a `choice` among the 19 failure causes of the hub, each with a sentence | mode `apply`, a cause the hub guessed, a confidence at `triage_threshold` and fewer acts today than `triage_cap`: the cause is changed through the API and stays a guess, so the triage rules and the reruns read it as before. Otherwise an act that is not applied. A cause the worker reported only gets a suggestion |
| kg_review | the job `kg_review`, at minute 0 of each hour | `possible_duplicate`: a `noul`, are the two nodes one; `ambiguous_match` (an edge): a `choice` among the files it may point to, and `unsure` | duplicate, noul at or above `kg_review_noul_yes` in mode `apply` and within the cap: a merge decision, active; at or below `kg_review_noul_no`: the item is dismissed, with the reason; in between, or in mode `suggest`: the merge is proposed. A match where Jev confirms the target the edge has is dismissed. Another target is only an act that is not applied |
| corrections | the job `corrections`, daily at 01:30 UTC | the corrections of the day before: a `choice` among the candidates and `none` | a candidate is an earlier correction (90 days) or an accepted rule that shares at least 3 words and a quarter of the shorter text's words, found without a call to Jev; a match at `corrections_threshold` is a row of `jev_matches` in state `match`, below it `suggestion`; in mode `apply` the signal `delivery.repeat_correction_rate` of the day is pushed: matches over the day's corrections, left out for a day with none |

[Inference] The API's text of a review item has no relation name and no text per node, so an `ambiguous_match` cannot
become a link decision, and an item of one node (a mention) is not asked. The signal key must be declared by an admin
of the project, or the push is refused and the matches stay in the table.

Everything applied can be undone with the hub's own command (the page and `evo-agents hub jev acts` list it):
`evo-agents hub run-cause restore RUN`, `evo-agents hub kg decisions undo N --project P --reason WHY` and
`evo-agents hub kg review undismiss FINGERPRINT`. The cap counts acts applied, undone ones included. The signal is a
value of the day that the hub's Signal keeps.

## The client

One request is `POST <base_url>/v1/systemone` with `{model, state, questions}`; the answer carries `{model, answers,
usage}`. The timeout is under 30 seconds, there is no retry, the reply is read to at most 1 MB, and a request is at
most 120000 bytes. An error says the status the vendor gave and never a body or a header of it.

A question has a `type`: `choice` (criteria: an object of 2 to 8 options with their words), `noul` (an optional object
with the keys `true` and `false`) or `score` (a list of 2 to 10 levels, lowest first).

Cost is input tokens times 0.042 USD per million. Before the call the plugin books an upper bound (the request bytes
at that price) against `daily_usd` and refuses the call when it would pass it; afterwards it books the real figure.
[Inference] Calls that run at the same moment can overshoot the budget by what each of them estimated.

## Rerank

The plugin contributes the ranker `rerank` (extension point `rankers`, sink `jev@typesafe`). When a project has
`rerank` on, `history_search` and the hub's `kg_search` hand it the query and the first hits whose label the sink may
read, at most 20. The plugin puts them to Jev in one request: the query and the hits are the state, and each hit is a
`score` question on four ordered levels (unrelated, mentions the topic, partly answers, answers the query). The hits
come back by score, highest first; equal scores keep the hub's order. The call is booked as feature `rerank` in
`jev_usage` and is bound by the daily budget. The hub gives the whole search 2 seconds and the plugin waits 1.7: when
Jev fails, is late, the budget is spent or the model that answered is not the pinned one, the ranker answers no
order and the hub keeps the old one (`reranked` false). A late call still finishes and its cost is booked. It is not
an act: nothing is changed, so there is nothing to undo, and the call is not recorded once per subject.

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
| `jev_asked` | one row for each subject (a run, a review fingerprint, a correction's evidence) a feature put to a model |
| `jev_matches` | one row for each correction that repeats an earlier one or an accepted rule: day, evidence, candidate, model, confidence, state (`match` or `suggestion`) |
| `jev_acts` | one row for each decision: kind, feature, target, outcome, model, confidence, whether it was applied, when it was undone, time |

A failed call is booked once, with its status and no vendor text. Acts are recorded as not applied; a feature that
applies acts checks `can_apply` first: its mode, the threshold and the cap of the day. The hub emits no event when an
applied act is undone, so `undone_at` is set only by the plugin's own `mark_undone`.

## Page, routes and CLI

The page **Jev** shows the status of each feature, the cost of 24 hours and 7 days against the budget, and the recent
acts, each with the hub's command that undoes it. It is laid out for 375 px and uses the hub kit's light and dark
tokens. Undo is the hub's own: for a triage act `evo-agents hub run-cause restore RUN --project P`
(`POST /v1/projects/{p}/runs/{id}/cause/restore`), for a knowledge-graph review
`evo-agents hub kg review undismiss FINGERPRINT --project P` (`DELETE /v1/kg/{project}/review/{fp}/dismiss`), for a
decision `evo-agents hub kg decisions undo N --project P --reason WHY` (`POST /v1/kg/{project}/decisions/{n}/undo`). The
page also lists the corrections that repeat.

Routes, under `/v1/x/jev/<project>`: `GET status`, `GET usage`, `GET acts?limit=`, `GET matches?limit=`, `POST ask`. Each of
the four reads takes `render=text`.

```sh
evo-agents hub jev status --project northwind
evo-agents hub jev ask --project northwind --file ask.json
evo-agents hub jev usage --project northwind --json
evo-agents hub jev acts --project northwind --limit 20
evo-agents hub jev matches --project northwind
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
does nothing when it is not enabled, has no key, has no sink or has every feature off. `test_jev_triage.py`,
`test_jev_review.py`, `test_jev_corrections.py` and `test_jev_rank.py` run each feature against the same fake, with real runs,
decisions, dismissals, sessions and signals on the hub.
