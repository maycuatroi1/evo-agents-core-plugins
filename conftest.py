"""The tests of the plugins run against a checkout of evo-agents, at the commit evo-agents.lock names in CI: they use
the test helpers of its tests package (``tests.hub.pg``, ``tests.hub.live``, the fixtures of ``tests/hub/conftest.py``
and functions of its test modules), which no wheel holds and no version covers. Those helpers are not part of the API
of core plugins: a change to them in evo-agents may break these tests without changing the API's version
(README.md, Tests).

The checkout is the one evo-agents is installed from, editable (``make setup``): its root goes first on sys.path, as
evo-agents' own ``pythonpath = ["."]`` puts it, so ``tests`` is evo-agents' tests package. This repository's tests
live in ``plugin_tests`` so that nothing here hides it. EVO_AGENTS_CHECKOUT names another checkout.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest


def _checkout() -> Path:
    named = os.environ.get("EVO_AGENTS_CHECKOUT", "").strip()
    if named:
        return Path(named).expanduser().resolve()
    spec = importlib.util.find_spec("evo_agents")
    if spec is None or not spec.origin:
        raise pytest.UsageError("evo-agents is not installed: make setup")
    return Path(spec.origin).resolve().parent.parent


CHECKOUT = _checkout()
if not (CHECKOUT / "tests" / "hub" / "conftest.py").is_file():
    raise pytest.UsageError(
        f"{CHECKOUT} is not a checkout of evo-agents with its tests: install evo-agents editable from one "
        "(make setup), or name one with EVO_AGENTS_CHECKOUT"
    )
if str(CHECKOUT) not in sys.path:
    sys.path.insert(0, str(CHECKOUT))

# evo-agents' fixtures and hooks: hub_db, github, s3, the autouse guards of the machine's hub login and worker
# variables, and EVO_TEST_SHARD.
pytest_plugins = ["tests.conftest", "tests.hub.conftest"]
