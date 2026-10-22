# evo-agents-core-plugins

The first-party core plugins of the [evo-agents](https://github.com/maycuatroi1/evo-agents) hub, out of evo-agents
and built on its API of core plugins alone (`evo_agents.hub.server.core_plugin_api`):

| Plugin | Package | What it does |
|---|---|---|
| `telegram` | `evo_core_plugins.telegram` | The hub's Telegram channel: a member links a private chat from the web, gets decisions, proposals and notices there, with the files of a run and of a question as photos or documents, and answers them with buttons or replies |
| `chats` | `evo_core_plugins.chats` | The messages of the hub's group chats in each project's knowledge graph, for who is in each chat |

Both left evo-ak unchanged for their users: the same id, publisher (`evo-agents`) and entry point name, the same
routes, webhook path and variables (`EVO_HUB_TELEGRAM_*`), the same item ids (`plugin.chats:...`). Their manifests
moved to version 1.1.0, so the hub's store records a new version of the image's plugins.

## How the hub installs it

One distribution, `evo-agents-core-plugins`, with one entry point per plugin in group `evo_agents.plugins`. The hub's
image installs it from PyPI with `--no-deps --require-hashes`, from the line `deploy/hub/core-plugins.txt` of
evo-agents pins:

```
evo-agents-core-plugins==1.2.0 --hash=sha256:<the hash the release prints>
```

The wheel declares no dependency: the plugins use only what the image of the hub already holds (evo-ak with its
`hub-server` extra: FastAPI, pydantic, httpx). Declaring evo-ak would let a resolver pull evo-ak from PyPI over the
one the image builds from evo-agents' main. `plugin_tests/test_packaging.py` keeps both.

## The API of core plugins

A plugin imports `evo_agents.hub.server.core_plugin_api` and nothing else of evo_agents, imports no SQLAlchemy, and
reaches its own modules with relative imports (`plugin_tests/test_api_imports.py`, a copy of evo-agents'
`tests/plugins/test_core_plugin_imports.py`). No plugin imports another (`lint-imports`, contract
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

### Releases

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
tests these plugins had in evo-agents. `test_telegram_files.py` sends the files of notifications through the channel
alone, and `test_telegram_outputs.py` through a hub that gives them; it skips with evo-agents at a commit whose hub
gives channels no files. They use evo-agents' test helpers from the checkout at the lock: `tests.hub.pg`,
`tests.hub.live`, the fixtures of `tests/hub/conftest.py` and functions of its test modules (`conftest.py` puts the
checkout on `sys.path` and loads them). **These helpers are not part of the API of core plugins.** No wheel holds them
and no version covers them: evo-agents may change one without changing the API's version, and the tests here then
break at the next move of the lock or in the compat job, never on a hub.

The directory is `plugin_tests`, not `tests`, so that evo-agents' `tests` package stays importable. Until evo-agents
drops its own copies of `telegram` and `chats`, the evo-ak the tests install declares entry points of the same names;
`plugin_tests/conftest.py` leaves those out, so the hub the tests start loads this checkout's plugins, and
`plugin_tests/test_installed.py` checks that it does.

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
