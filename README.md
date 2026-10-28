# evo-agents-core-plugins

The first-party core plugins of the [evo-agents](https://github.com/maycuatroi1/evo-agents) hub, out of evo-agents
and built on its API of core plugins alone (`evo_agents.hub.server.core_plugin_api`):

| Plugin | Package | What it does |
|---|---|---|
| `telegram` | `evo_core_plugins.telegram` | The hub's Telegram channel: a member links a private chat from the web, gets decisions, proposals and notices there, with the files of a run and of a question as photos or documents, and answers them with buttons or replies; and, in a project that enables it, the bridge of a Telegram group to a group chat of the hub, both ways ([docs/telegram-plugin.md](docs/telegram-plugin.md)) |
| `chats` | `evo_core_plugins.chats` | The messages of the hub's group chats in each project's knowledge graph, for who is in each chat |
| `pm` | `evo_core_plugins.pm` | The daily report of a project's delivery, read from the hub's tasks, srs, plans, runs and decisions, sent as a digest with escalations of old blockers ([docs/pm-plugin.md](docs/pm-plugin.md)) |
| `crm` | `evo_core_plugins.crm` | The people who found a project themselves, as contacts with a stage (lead, invited, activated, retained) pushed to Signal ([docs/crm-plugin.md](docs/crm-plugin.md)) |
| `marketing` | `evo_core_plugins.marketing` | The project's channels and the posts proposed on them, through a posting gate, a breaker, a budget and the weekly bulletin ([docs/marketing-plugin.md](docs/marketing-plugin.md)) |
| `editorial` | `evo_core_plugins.editorial` | The posts of a blog through the stages and gates its config lists, the writer and judge agents that move them between a person's answers, their review rounds with the reviewers' draft comments, and the notebook of the reviewer's feedback with its probes and markdown export ([docs/editorial-plugin.md](docs/editorial-plugin.md)) |
| `okr` | `evo_core_plugins.okr` | A project's strategy as a tree of business lines, objectives, key results and deliverables, linked to the hub's tasks, use cases, plans and goals, with how far each part has come computed on read and the gaps, the import of a source's items by ref, and the page OKR ([docs/okr-plugin.md](docs/okr-plugin.md)) |
| `jev` | `evo_core_plugins.jev` | Decisions put to Jev, TypeSafe's System One model, through a pinned and budgeted egress sink: the tools `jev__decide` and `jev__usage`, a ledger of cost and acts, the page Jev and `evo-agents hub jev`; every feature is off until a project turns it on ([docs/jev-plugin.md](docs/jev-plugin.md)) |

Each left evo-ak unchanged for its users: the same id, publisher (`evo-agents`) and entry point name, the same routes,
MCP tool names, pages, commands (`evo-agents hub pm|crm|marketing`), variables (`EVO_HUB_TELEGRAM_*`) and knowledge
graph item ids (`plugin.chats:...`, `plugin.crm:...`). Their manifests moved to version 1.1.0, so the hub's store
records a new version of the image's plugins.

pm, crm and marketing carry their own tables (`tables.py`, the `schema.metadata` of the manifest) and their own chain
of Alembic migrations (`migrations/`, version table `alembic_version_<id>`), whose first revision adopts the tables the
hub's migrations made before, rows and all. Their pages are files under `ui/pages`, which the hub frames, and their
commands a `cli.json` the CLI reads without importing the plugin, with the words without `--json` from `cli_text.py`.

### The Telegram group bridge

Before you bridge a group, read [docs/telegram-plugin.md](docs/telegram-plugin.md). In short:

- **Turn privacy mode off** with @BotFather (*Bot Settings*, then *Group Privacy*, then *Turn off*), then add the bot
  to the group again. With privacy mode on, the members' messages never reach the hub.
- **Anyone in the group reads what goes out**, at the level the chat's label and the project's `telegram` channel sink
  allow, whether or not they are a member of the hub.
- **The group's admins manage its members** in Telegram. The hub does not know who is in the group.
- The project enables `telegram` with `chats:read` and `chats:write` and declares a sink of kind `channel` named
  `telegram` in `knowledge.yaml`. A hub admin runs `evo-agents hub admin telegram --set-webhook` again after the
  upgrade, so the bot learns when it is taken out of a group.

## How the hub installs it

One distribution, `evo-agents-core-plugins`, with one entry point per plugin in group `evo_agents.plugins`. The hub's
image installs it from PyPI with `--no-deps --require-hashes`, from the line `deploy/hub/core-plugins.txt` of
evo-agents pins:

```
evo-agents-core-plugins==2.0.0 --hash=sha256:<the hash the release prints>
```

The wheel declares no dependency: the plugins use only what the image of the hub already holds (evo-ak with its
`hub-server` extra: FastAPI, pydantic, httpx, SQLAlchemy, Alembic). Declaring evo-ak would let a resolver pull evo-ak from PyPI over the
one the image builds from evo-agents' main. `plugin_tests/test_packaging.py` keeps both.

## The API of core plugins

A plugin imports `evo_agents.hub.server.core_plugin_api` and nothing else of evo_agents, and uses SQLAlchemy Core on
its own tables alone: nothing takes `text` from SQLAlchemy or calls `exec_driver_sql` (`plugin_tests/test_api_imports.py`,
a copy of evo-agents' `tests/plugins/test_core_plugin_imports.py` as API 1.3 has it). No plugin imports another (`lint-imports`, contract
`plugins-own-package`). Neither the plugins nor their tests hold raw SQL (`plugin_tests/test_no_raw_sql.py`).

Each plugin's entry point names `manifest()`, which calls `hub.require(*API)` with the version of the API the plugin
is written for. A hub serves exactly one `major.minor`: a hub that serves another leaves the plugin out with the reason
(`core plugin not loaded`), and the `check` its Dockerfile runs fails the build. Every plugin of one release asks for
the same version, which `python -m evo_core_plugins api` prints; `python -m evo_agents.hub.server.core_plugin_api
version` prints the one a checkout of evo-agents serves. `docs/plugins.md` of evo-agents has the rules and the table of
versions.

| This distribution | API it asks for | evo-agents commit that serves it |
|---|---|---|
| 1.0.0 | 1.1 | `ad12d3ccbee695a6915b22f4512f11794f7944fb` (pull request #106) |
| 1.1.0 | 1.1 | the same; the files of notifications come from a hub that gives channels `extra.outputs` (plan run-outputs) |
| 1.2.0 | 1.2 | `86ff2f64f988081aa22b02cb5967d6fa8b207832` (pull request #174) |
| 2.0.0 | 1.3 | `884b2c62c80175de1c0ecd47d34802035f006f97` (branch feat/lean-core-features, plan plugin-market) |
| 2.1.0 | 1.4 | `3e42aad7d4c626f43d6cf86a529e188b9fb1e76f` (pull request #270) |
| 2.1.1 | 1.4 | the same |
| 2.1.2 | 1.4 | the same |
| 2.2.0 | 1.5 | `49359c9ba0e5aca315f62520f03aeb127b05ac93` (pull request #293, plan chat-bridges) |
| 2.3.0 | 1.5 | the same |
| 2.4.0 | 1.6 | `64207689e8a3ed6709c873f5d7d94f01365c9f77` (pull request #297, plan jev-decisions) |
| 2.4.1 | 1.6 | the same |
| 2.5.0 | 1.7 | `105882621becad32331d60b86a151a034c1a6406` (pull request #314) |
| 2.5.1 | 1.7 | `c4e1a884f751cdc2111c4aad3f5bf56ac0de28a9` (pull request #327, plan kg-retrieval-quality) |

### Releases

- **2.5.1**: the tests of `telegram` follow evo-agents 0.51, whose push, merge, plan_finished and run_outputs notices only
  report: a run's files stay on the hub. No plugin changes.
- **2.5.0**: jev's KG review reads the rules it can judge (`possible_duplicate`, `ambiguous_match`) with the filter
  `rules` of `read_review_queue`, so the long head of another rule no longer hides them; every plugin asks API 1.7.
  The plugin `jev` is 1.4.0.
- **2.4.1**: the release of 2.4.0 stopped at its test of the installed plugins, which pinned every manifest to 1.1.0; nothing was
  published as 2.4.0. The content is that of 2.4.0 (the plugin `jev`, API 1.6).
- **2.4.0**: the new plugin `jev`: asks the decision model Jev of TypeSafe through the tool `jev__decide`, keeps a cost
  ledger and a list of what Jev did on a page and in the CLI, and, per project and per feature (off, suggest or apply),
  classifies the cause of failed runs, reviews the knowledge graph queue, spots repeated corrections and reranks
  `history_search` and `kg_search`. Above its threshold a result is applied (undoable), below it it is a suggestion.
  Needs the sink `jev@typesafe` in the project's policy and an API key. Every plugin now asks for API 1.6, so this
  release needs a hub that serves 1.6. Migration chain `jev_0001`, `jev_0002`.
- **2.3.0**: the new plugin `okr`: a project's strategy as a tree (business line, objective, key result,
  deliverable) in its own tables, a deliverable linked to the hub's tasks, use cases and plans and a key result to its
  goal, each link checked against what the project holds. The roll-up is computed on read: a deliverable's progress
  from its tasks, use cases and plan steps, a key result's goal met or not from the latest value of its signal, and the
  gaps of the tree. A source writes its items through `POST /v1/x/okr/<project>/import`, upserted by ref, with a dry
  run and prune to archived; the page OKR, `evo-agents hub okr` and the tools `okr__tree`, `okr__item`, `okr__link` and
  `okr__unlink`. API 1.5, as 2.2.0; the chain `okr_0001` makes the plugin's tables on `evo-agents hub migrate`. The
  other plugins are unchanged.
- **2.2.0**: `telegram` bridges a Telegram group with a chat of the hub through the chat bridge of API 1.5:
  `/link <code>` in the group, linked members' messages come in as theirs (`@<bot>` mentions an agent), the chat's
  messages go out when their label is cleared for the project's `channel` sink, with photos, documents, run progress
  as one edited message and an agent's ✅ and ❌ as reactions. The 1:1 channel is unchanged. Every plugin asks for API
  1.5; hub admins run `evo-agents hub admin telegram --set-webhook` again for `my_chat_member`. No migration.
- **2.1.2**: `editorial` hands the writer a task on a gate's answer only when it came through the hub (`via` hub,
  the default); an answer from inside a session (`claude-code`, `codex`) is kept and hands none, as that session goes
  on itself. API 1.4, no migration.
- **2.1.1**: `editorial` sets a post that is there without a stage (a title, links, figures) and keeps its stage,
  where 2.1.0 answered 500; a new post without a stage is still refused with 422. API 1.4, no migration.
- **2.1.0**: the new plugin `editorial`: the posts of a blog through the stages and gates its config lists, a writer
  agent that works on the post's branch between a person's answers, a judge agent that scores each review round in a
  fresh context, reviewers' draft comments pulled into the round, and the notebook of the reviewer's feedback with its
  recall, markdown export and probes. Every plugin asks for API 1.4, the version that lets a task work on a named
  branch for up to 120 agent minutes and lets a core plugin add probes for its own rules; a hub that serves 1.3 leaves
  them all out with that reason. What the other five plugins do is that of 2.0.0.
- **2.0.0**: `pm`, `crm` and `marketing` out of evo-agents, on the API alone, with their tables, migrations, pages,
  commands, tests and docs; unchanged for their users. Every plugin asks for API 1.3, the version that gives a core
  plugin its own tables and migrations, pages and commands; a hub that serves 1.2 leaves them all out with that reason.
  The major version is new because the distribution now holds the tables of three plugins, which a hub must not also
  hold: evo-agents drops its copies in the same move as it pins 2.0.0.
- **1.2.0**: both plugins ask for API 1.2, the version in which a core plugin asks its agent types questions
  (`ask_agent_type`); a hub that serves 1.1 leaves them out with that reason. What they do is that of 1.1.0, and the
  manifests stay 1.1.0.
- **1.1.0**: the channel `telegram` sends the files of a decision that waits and of a notice `run_outputs` (the files
  a run's agent sent) for a project that is not restricted, from the presigned GETs the hub's prepare gives in
  `extra.outputs` and `extra.outputs_count`. It fetches each file and uploads it with its name (Telegram takes a
  document by URL only as a PDF or a ZIP): one message, or one group of at most 10, as photos when each file is a PNG,
  JPEG or WebP of 10 MiB at most, as documents otherwise; at most 20 MiB a notification, each file within Telegram's
  50 MiB, the rest counted on the hub. A notice's text is the caption, with the run's link; a decision's files go
  first, and then its message with its buttons as a reply to them. A restricted project's message holds no file and no
  file's name, as before, and its notice `run_outputs` says `Files from a run`. Without these keys the channel sends
  text, as 1.0.0 did; the API it asks for stays 1.1, and the manifests stay 1.1.0.
- **1.0.0**: `telegram` and `chats` out of evo-agents, unchanged for their users.

### A change of the API

1. A pull request of evo-agents changes the API and its version. Its CI fails where the pinned release asks for the
   old one.
2. A pull request here moves `API` of every plugin to the new version, uses what changed, and sets `evo-agents.lock` to
   the head commit of that evo-agents pull request, so CI runs against it. evo-agents merges with merge commits, so the
   commit stays in main's history.
3. Merge, bump `evo_core_plugins.__version__`, tag `v<version>`: the release publishes it.
4. The evo-agents pull request pins the new release with its hash; its CI turns green.

The nightly `compat` job tells early when main serves a version these plugins do not ask for.

## Development

You need `uv`, git and, for the tests that start a hub, Postgres.

```sh
make setup   # evo-agents at the commit of evo-agents.lock in .evo-agents, a venv in .venv with both, editable
make check   # ruff, import-linter, the import, raw SQL and packaging checks
make test    # every test; the hub's need EVO_HUB_TEST_DSN, such as postgresql://postgres:test@localhost:5432/postgres
```

`make setup EVO_AGENTS_URL=~/github/evo-agents` fetches from a local clone instead of GitHub, `EVO_AGENTS_REF=main`
checks out main instead of the lock, and `make lock` says whether `.evo-agents` is at the lock.

## Tests

`plugin_tests/test_telegram.py`, `test_telegram_model.py`, `fake_telegram.py` and `test_chats_kg_source.py` are the
tests telegram and chats had in evo-agents; `test_pm_*.py`, `test_hub_pm_cli.py`, `test_crm_*.py`, `test_marketing_*.py`
and `test_growth_*.py` the tests of pm, crm and marketing there (`tests/hub`). `test_telegram_files.py` sends the files of notifications through the channel
alone, `test_telegram_bridge.py` drives the group bridge through a hub and the fake Bot API, and `test_telegram_outputs.py` through a hub that gives them; it skips with evo-agents at a commit whose hub
gives channels no files. They use evo-agents' test helpers from the checkout at the lock: `tests.hub.pg`,
`tests.hub.live`, the fixtures of `tests/hub/conftest.py` and functions of its test modules (`conftest.py` puts the
checkout on `sys.path` and loads them). **These helpers are not part of the API of core plugins.** No wheel holds them
and no version covers them: evo-agents may change one without changing the API's version, and the tests here then
break at the next move of the lock or in the compat job, never on a hub.

The directory is `plugin_tests`, not `tests`, so that evo-agents' `tests` package stays importable. Until evo-agents
drops its own copies of `pm`, `crm` and `marketing`, the evo-ak the tests install declares entry points of the same
names; `plugin_tests/conftest.py` leaves those out, for the hub and for the commands the CLI lists, so both use this
checkout's plugins, and `plugin_tests/test_installed.py` checks that they do.

## CI and releases

- `ci.yml`, on pull requests and main: `make check`, and `make test` against a Postgres service, with evo-agents at the
  lock.
- `compat.yml`, every night and by hand: the same tests against evo-agents' main, after comparing the API main serves
  with the one the plugins ask for. A failure opens an issue labelled `compat`, or comments on the open one.
- `release.yml`, on a tag `v<version>` that matches `evo_core_plugins.__version__`: `ci.yml`, then the wheel and sdist,
  published to PyPI by trusted publishing in the environment `pypi` (a reviewer approves it). The run's summary holds
  the line to pin in evo-agents, with the wheel's sha256.

## Names

This repository is public, like evo-agents: tests, fixtures, docs and commit messages use made-up names only (such as
northwind and lumen), never a customer's.

## License

Apache-2.0, as evo-agents.
