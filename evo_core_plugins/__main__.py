"""``python -m evo_core_plugins api`` prints the version of the API of core plugins the plugins of this release are
written for, ``major.minor``, as ``python -m evo_agents.hub.server.core_plugin_api version`` prints the version a
checkout of evo-agents serves; the compat job of CI compares the two. It exits 1 when two plugins ask for different
versions, which one release must not do.

The version is read from each plugin's source (the assignment ``API = (major, minor)`` of its ``__init__``), without
importing it, so the command runs where evo-agents is not installed.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

from evo_core_plugins import PLUGINS

USAGE = "usage: python -m evo_core_plugins api"
HERE = Path(__file__).resolve().parent


def required(plugin: str, root: Path = HERE) -> tuple[int, int]:
    """The version of the API plugin ``plugin`` asks for, read from ``API = (major, minor)`` in its ``__init__``."""
    init = root / plugin / "__init__.py"
    for node in ast.parse(init.read_text(encoding="utf-8"), filename=str(init)).body:
        if isinstance(node, ast.Assign) and any(getattr(target, "id", None) == "API" for target in node.targets):
            value = ast.literal_eval(node.value)
            if isinstance(value, tuple) and len(value) == 2 and all(type(part) is int for part in value):
                return value
            raise ValueError(f"{init}: API is {value!r}, not (major, minor)")
    raise ValueError(f"{init} assigns no API = (major, minor)")


def versions(root: Path = HERE) -> dict[str, tuple[int, int]]:
    """plugin -> the version of the API it asks for, for every plugin of PLUGINS."""
    return {plugin: required(plugin, root) for plugin in PLUGINS}


def main(argv: list[str], root: Path | None = None) -> int:
    if argv != ["api"]:
        sys.stderr.write(USAGE + "\n")
        return 2
    found = versions(HERE if root is None else root)
    if len(set(found.values())) != 1:
        listed = ", ".join(f"{plugin} {major}.{minor}" for plugin, (major, minor) in found.items())
        sys.stderr.write(f"the plugins of one release ask for different versions of the API: {listed}\n")
        return 1
    major, minor = next(iter(found.values()))
    sys.stdout.write(f"{major}.{minor}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
