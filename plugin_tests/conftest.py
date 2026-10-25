"""This repository's plugins win over a copy of the same plugin another distribution installs.

Until evo-agents drops its own pm, crm and marketing (the commit after the one evo-agents.lock names), the evo-ak these
tests install declares entry points named ``pm``, ``crm`` and ``marketing`` in group ``evo_agents.plugins`` too, and a
hub with two plugins of one id runs either. Here every entry point of that group whose name this distribution also
declares, from any other distribution, is left out of what ``evo_agents.plugins.core`` reads, so the hub the tests start
loads the plugins of this checkout (``test_installed.py`` checks it), and the CLI, which reads the commands of the core
plugins installed with it through the same entry points (``evo_agents.hub.cli_plugin_commands``), lists each plugin
once. Once evo-ak declares no such entry point, this leaves nothing out.
"""

from __future__ import annotations

from importlib.metadata import distribution

from evo_agents.hub import cli_plugin_commands, plugin_calls
from evo_agents.plugins import core

DISTRIBUTION = "evo-agents-core-plugins"

_read = core.entry_points


def _ours(point) -> bool:
    dist = getattr(point, "dist", None)
    return dist is not None and dist.name.replace("_", "-").lower() == DISTRIBUTION


def ours() -> frozenset[str]:
    """The names of the entry points this distribution declares in group evo_agents.plugins."""
    found = distribution(DISTRIBUTION).entry_points.select(group=core.ENTRY_POINT_GROUP)
    return frozenset(point.name for point in found)


def shadowed(points) -> list:
    """The entry points another distribution declares under a name this one declares too."""
    names = ours()
    return [point for point in points if point.name in names and not _ours(point)]


def entry_points(**params):
    """``importlib.metadata.entry_points``, without the entry points of group evo_agents.plugins ``shadowed`` gives."""
    found = list(_read(**params))
    if params.get("group") != core.ENTRY_POINT_GROUP:
        return found
    hidden = {id(point) for point in shadowed(found)}
    return [point for point in found if id(point) not in hidden]


core.entry_points = entry_points
cli_plugin_commands.entry_points = entry_points
plugin_calls.core_registry.cache_clear()
