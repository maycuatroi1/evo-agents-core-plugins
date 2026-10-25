"""The distribution as the hub's image installs it (``--no-deps``, from the line evo-agents pins): no Requires-Dist, so
no resolver pulls evo-ak from PyPI over the one the image builds; one entry point per plugin of PLUGINS in group
evo_agents.plugins, named as in evo-ak; a version the tag of a release names. No database."""

from __future__ import annotations

import ast
import sys
import tomllib
from importlib.metadata import distribution
from pathlib import Path

import evo_core_plugins
from evo_core_plugins import PLUGINS

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
DISTRIBUTION = "evo-agents-core-plugins"
GROUP = "evo_agents.plugins"
# What the plugins import outside the standard library and evo_agents: the hub's image has each, from evo-ak's
# hub-server extra (pyproject.toml of evo-agents). sqlalchemy and alembic are for a plugin's own tables and its chain of
# migrations (API 1.3).
IMAGE_LIBRARIES = frozenset({"alembic", "fastapi", "httpx", "pydantic", "sqlalchemy"})


def test_the_distribution_declares_no_dependency():
    project = PYPROJECT["project"]
    assert project["name"] == DISTRIBUTION
    assert project["dependencies"] == [] and "optional-dependencies" not in project
    assert not distribution(DISTRIBUTION).requires  # the installed metadata: no Requires-Dist


def test_one_entry_point_per_plugin_named_as_its_package():
    declared = PYPROJECT["project"]["entry-points"][GROUP]
    assert declared == {name: f"evo_core_plugins.{name}:manifest" for name in PLUGINS}
    installed = distribution(DISTRIBUTION).entry_points.select(group=GROUP)
    assert {point.name: point.value for point in installed} == declared
    packages = {path.parent.name for path in (ROOT / "evo_core_plugins").glob("*/__init__.py")}
    assert packages == set(PLUGINS)


def test_the_version_is_the_packages():
    assert distribution(DISTRIBUTION).version == evo_core_plugins.__version__


def _top_level_imports(path: Path) -> set[str]:
    found = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
        if isinstance(node, ast.Import):
            found.update(alias.name.partition(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module.partition(".")[0])
    return found


def test_the_package_data_holds_every_file_a_plugin_reads_beside_its_python():
    # cli.json, which the CLI reads without importing the plugin, and the files of its pages (ui/pages): a wheel
    # without them gives a hub with no commands and no pages for the plugin.
    patterns = PYPROJECT["tool"]["setuptools"]["package-data"]["*"]
    files = [
        path
        for path in (ROOT / "evo_core_plugins").rglob("*")
        if path.is_file() and path.suffix not in (".py", ".pyc") and "__pycache__" not in path.parts
    ]
    assert files
    for path in files:
        relative = path.relative_to(ROOT / "evo_core_plugins")
        inner = Path(*relative.parts[1:])  # below the plugin's package
        assert any(inner.match(pattern) and len(inner.parts) == len(Path(pattern).parts) for pattern in patterns), (
            f"{relative} is not in [tool.setuptools.package-data] of pyproject.toml"
        )


def test_the_plugins_import_only_what_the_hubs_image_has():
    imported = set().union(*(_top_level_imports(path) for path in (ROOT / "evo_core_plugins").rglob("*.py")))
    outside = imported - {"evo_agents", "evo_core_plugins", "__future__"}
    assert outside - set(sys.stdlib_module_names) <= IMAGE_LIBRARIES
