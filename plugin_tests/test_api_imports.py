"""The core plugins of this repository import nothing of evo_agents but the API module, and no SQLAlchemy:
``python -m pytest plugin_tests/test_api_imports.py`` reads every ``.py`` of evo_core_plugins with ``ast``, without
importing it. A copy of evo-agents' tests/plugins/test_core_plugin_imports.py, which ``docs/plugins.md`` of evo-agents
asks a repository of core plugins to keep (The core plugin API).

- ``import`` and ``from ... import`` of ``evo_agents`` or below name ``evo_agents.hub.server.core_plugin_api`` alone
  (``from evo_agents.hub.server import core_plugin_api`` included), and what they take from it is a name of its
  ``__all__``, read from the source of the evo-agents installed (the checkout at the commit of evo-agents.lock);
- nothing imports ``sqlalchemy``: a plugin reads the hub through the API, never with SQL of its own;
- a call of ``importlib.import_module`` or ``__import__`` names no module of evo_agents.

import-linter cannot keep this: it analyses the package evo_core_plugins, and of a package outside it sees the top-level
name alone; it keeps each plugin in its own package instead (pyproject.toml, plugins-own-package). Standard library
only, and evo_agents is found, not imported.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path

from evo_core_plugins import PLUGINS

ROOT = Path(__file__).resolve().parent.parent
API = "evo_agents.hub.server.core_plugin_api"
PACKAGE = ROOT / "evo_core_plugins"


def api_init() -> Path:
    """The ``__init__.py`` of the API module of the evo-agents this environment has, found without importing it."""
    spec = importlib.util.find_spec("evo_agents")
    assert spec is not None and spec.origin, "evo-agents is not installed: make setup"
    found = Path(spec.origin).parent / "hub" / "server" / "core_plugin_api" / "__init__.py"
    assert found.is_file(), f"{found} does not exist: this evo-agents has no API of core plugins"
    return found


DYNAMIC = {("importlib", "import_module"), (None, "import_module"), (None, "__import__")}


def public_names(init: Path | None = None) -> frozenset[str]:
    """The names of the API's ``__all__``, read from its source."""
    init = api_init() if init is None else init
    for node in ast.parse(init.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "__all__" for t in node.targets):
            return frozenset(ast.literal_eval(node.value))
    raise AssertionError(f"{init} declares no __all__")


def _of_evo_agents(module: str) -> bool:
    return module == "evo_agents" or module.startswith("evo_agents.")


def _call_name(func) -> tuple[str | None, str | None]:
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        return func.value.id, func.attr
    if isinstance(func, ast.Name):
        return None, func.id
    return None, None


def problems(source: str, where: str, names: frozenset[str]) -> list[str]:
    """What the module ``source`` (at ``where``) imports that a plugin on the API may not."""
    found = []
    for node in ast.walk(ast.parse(source, filename=where)):
        line = f"{where}:{getattr(node, 'lineno', 0)}"
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "sqlalchemy" or alias.name.startswith("sqlalchemy."):
                    found.append(f"{line} imports {alias.name}: read the hub through the API, not with SQL")
                elif _of_evo_agents(alias.name) and alias.name != API:
                    found.append(f"{line} imports {alias.name}: import {API} alone")
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            module = node.module
            if module == "sqlalchemy" or module.startswith("sqlalchemy."):
                found.append(f"{line} imports from {module}: read the hub through the API, not with SQL")
            elif module == API:
                found += [
                    f"{line} takes {alias.name} from the API, which is not in its __all__"
                    for alias in node.names
                    if alias.name not in names
                ]
            elif _of_evo_agents(module):
                taken = [f"{module}.{alias.name}" for alias in node.names]
                found += [f"{line} imports {name}: import {API} alone" for name in taken if name != API]
        elif isinstance(node, ast.Call) and _call_name(node.func) in DYNAMIC and node.args:
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str) and _of_evo_agents(first.value):
                found.append(f"{line} imports {first.value} by name: import {API} alone")
    return found


def package_problems(package: Path, names: frozenset[str]) -> list[str]:
    found = []
    for path in sorted(package.rglob("*.py")):
        found += problems(path.read_text(encoding="utf-8"), path.relative_to(ROOT).as_posix(), names)
    return found


def test_the_core_plugins_import_the_api_module_alone_and_no_sqlalchemy():
    names = public_names()
    for plugin in PLUGINS:
        assert list((PACKAGE / plugin).rglob("*.py")), f"{PACKAGE / plugin} holds no module"
    assert package_problems(PACKAGE, names) == []


def test_the_check_finds_every_other_import():
    names = public_names()
    assert "require" in names and "plugin" in names and "API_VERSION" in names
    source = "\n".join(
        [
            "import sqlalchemy",
            "from sqlalchemy.ext.asyncio import AsyncConnection",
            "import evo_agents.hub.tables",
            "from evo_agents.hub import tables",
            "from evo_agents.hub.server import core_plugin_api, security",
            "from evo_agents.hub.server.core_plugin_api import _types, require",
            "from evo_agents.hub.server.core_plugin_api._types import Member",
            "import importlib",
            "importlib.import_module('evo_agents.hub.tables')",
            "__import__('evo_agents.hub')",
            "from . import server",
            "import evo_agents.hub.server.core_plugin_api as hub",
            "import httpx",
        ]
    )
    found = problems(source, "bad.py", names)
    assert [entry.split(" ", 1)[0] for entry in found] == [
        "bad.py:1",
        "bad.py:2",
        "bad.py:3",
        "bad.py:4",
        "bad.py:5",
        "bad.py:6",
        "bad.py:7",
        "bad.py:9",
        "bad.py:10",
    ]
    assert "security" in found[4] and "_types" in found[5]
