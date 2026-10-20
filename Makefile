# The checks and tests of the core plugins, on this machine as in CI (.github/workflows).
#
#   make setup   a checkout of evo-agents at the commit of evo-agents.lock in .evo-agents, and a venv in .venv with
#                that evo-agents (extras test and hub-server) and this repository, both editable
#   make check   ruff, import-linter and the checks that read the source: plugin_tests/test_api_imports.py (what a
#                plugin imports of evo_agents), plugin_tests/test_no_raw_sql.py, plugin_tests/test_packaging.py
#   make test    every test of plugin_tests; those that start a hub need Postgres (EVO_HUB_TEST_DSN) and skip without
#
# EVO_AGENTS_REF=main checks out evo-agents' main instead of the lock (the compat job); EVO_AGENTS_URL another clone,
# such as a local one.

LOCK := $(shell cat evo-agents.lock)
EVO_AGENTS ?= .evo-agents
EVO_AGENTS_URL ?= https://github.com/maycuatroi1/evo-agents.git
EVO_AGENTS_REF ?= $(LOCK)
VENV ?= .venv
PYTHON_VERSION ?= 3.12
PY := $(VENV)/bin/python
PYTEST_ARGS ?= -n 4
STATIC_TESTS := plugin_tests/test_api_imports.py plugin_tests/test_no_raw_sql.py plugin_tests/test_packaging.py

.PHONY: setup check test lock

setup:
	@test -e $(EVO_AGENTS)/.git || git init -q $(EVO_AGENTS)
	git -C $(EVO_AGENTS) fetch -q --depth 1 $(EVO_AGENTS_URL) $(EVO_AGENTS_REF)
	git -C $(EVO_AGENTS) checkout -q --detach FETCH_HEAD
	uv venv -q --allow-existing --python $(PYTHON_VERSION) $(VENV)
	uv pip install -q --python $(PY) -e '$(EVO_AGENTS)[test,hub-server]'
	uv pip install -q --python $(PY) --no-deps -e .
	@echo "evo-agents at $$(git -C $(EVO_AGENTS) rev-parse HEAD), API $$($(PY) -m evo_agents.hub.server.core_plugin_api version)"

check:
	$(VENV)/bin/ruff check .
	$(VENV)/bin/ruff format --check .
	$(VENV)/bin/lint-imports
	$(PY) -m pytest -q $(STATIC_TESTS)

test:
	@echo "evo-agents at $$(git -C $(EVO_AGENTS) rev-parse HEAD) (evo-agents.lock: $(LOCK))"
	$(PY) -m pytest -q $(PYTEST_ARGS) plugin_tests

# Whether the checkout is at the commit of the lock: the job test of CI runs there, the compat job does not.
lock:
	@test "$$(git -C $(EVO_AGENTS) rev-parse HEAD)" = "$(LOCK)" \
		|| { echo "$(EVO_AGENTS) is at $$(git -C $(EVO_AGENTS) rev-parse HEAD), not at evo-agents.lock's $(LOCK): make setup"; exit 1; }
