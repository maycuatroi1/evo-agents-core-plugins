"""The core plugin chats: the history of the hub's group chats as a source of each project's knowledge graph
(``docs/plugins.md`` of evo-agents, Core plugins).

A project that enables it and grants it ``chats:read`` has in every build of its graph on the hub each message whose
label holds a part of the project, with its thread and its chat (``kg``). A message keeps the label its chat had when
it was sent; in the graph its item carries the project's part of that label and an audience: the chat, and a grant on
each other project the label names, so a reader sees it only while they are in the chat and could read the message
there. Search finds a message by its text, which no tool returns.

When a message is sent, the hub queues a build of each project its label names that has a plugin reading the chats,
which joins a build that waits.

It left evo-agents with the same id, publisher and entry point name, on which the projects that enable it and the ids
``plugin.chats:...`` of their graphs rely. ``kg`` gives the knowledge graph the messages, which it asks the hub for
through the API of core plugins alone (``evo_agents.hub.server.core_plugin_api``, ``chat_history_items``), so the rule
of who reads a message in the graph stays in the hub. The entry point names ``manifest``, which asks for the version of
the API the plugin is written for: a hub that serves another leaves the plugin out with that reason.
"""

from evo_agents.hub.server import core_plugin_api as hub

API = (1, 7)  # the version of the API of core plugins this plugin is written for
KG = "evo_core_plugins.chats.kg"
READS = "chats:read"  # what the source reads: the project's group chats (evo_agents.plugins.manifest.PERMISSIONS)

MANIFEST = {
    "id": "chats",
    "version": "1.1.0",
    "publisher": "evo-agents",
    "tier": "core",
    "name": "Chat history",
    "description": "The messages of the hub's group chats in the project's knowledge graph, for who is in each chat.",
    "engines": {"evo-agents": ">=0.23.1"},
    "plugin_api": 1,
    "permissions": [READS],
    "contributes": {
        "kg_sources": [
            {"name": "history", "title": "The messages of the group chats of the project", "python": f"{KG}:kg_source"}
        ],
    },
}


def manifest() -> dict:
    """The manifest, once this hub serves the version of the API the plugin is written for."""
    hub.require(*API)
    return MANIFEST


__all__ = ["API", "MANIFEST", "READS", "manifest"]
