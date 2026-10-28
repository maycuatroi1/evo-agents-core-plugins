"""evo-agents-core-plugins: the first-party core plugins of the evo-agents hub, each a package of its own here
(``telegram``, ``chats``, ``pm``, ``crm``, ``marketing``, ``editorial``, ``okr``, ``jev``) and an entry point of group ``evo_agents.plugins``, built on the API of core plugins alone
(``evo_agents.hub.server.core_plugin_api``).

The hub's image installs this distribution with ``--no-deps`` from the line ``deploy/hub/core-plugins.txt`` of
evo-agents pins: it declares no dependency and uses only what the image of the hub already holds. Each plugin asks for
the version of the API it is written for in its ``manifest``; ``python -m evo_core_plugins api`` prints that version,
which every plugin of one release shares.

Nothing here imports another plugin's package: ``PLUGINS`` names them for the checks and the command alone.
"""

__version__ = "2.5.1"

PLUGINS = (
    "telegram",
    "chats",
    "pm",
    "crm",
    "marketing",
    "editorial",
    "okr",
    "jev",
)  # the packages of the plugins, each named as its entry point

__all__ = ["PLUGINS", "__version__"]
