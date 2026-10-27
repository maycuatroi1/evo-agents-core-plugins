"""The core plugin telegram: the hub's Telegram channel of notifications, which members link from the web, with the
webhook that takes their answers and the routes of linking and of the hub admins (``docs/notifications.md`` of
evo-agents).

It left evo-agents as it was there: the same variables (EVO_HUB_TELEGRAM_*), routes and messages, and the same id,
publisher and entry point name, which the hub's store, the members' channels of kind ``telegram`` and the projects
rely on. Its channel is a kind of members' channel (``telegram``); its routes keep the paths they had (the empty
prefix: each router carries its own under /v1); its link codes are the rows of kind telegram of the hub's
channel_link_codes, which it owns no more than any other core plugin does. The channel and the routes run hub-wide
wherever this distribution is installed beside evo-ak, whichever project enables the plugin.

Since API 1.5 it is also the transport of the bridge of a Telegram group to a group chat of the hub (``bridge``,
``docs/telegram-plugin.md``): it asks for chats:read and chats:write and takes the event ``chat.bridge``, so the
hub's store lists it as a plugin projects enable, and a chat whose agents' projects all enable it with both
permissions can be bridged. A member's private chat with the bot does not depend on that.

It reaches the hub through the API of core plugins alone (``evo_agents.hub.server.core_plugin_api``), with relative
imports between its own modules: ``model`` holds its messages, ``server`` its channel and routes, ``bridge_model``
and ``bridge`` the bridge of a group. What the hub keeps
of Telegram for itself (what may reach a channel, the words of a minimal message) stays in ``evo_agents.hub.telegram``.

The entry point names ``manifest``, which asks for the version of the API the plugin is written for: a hub that serves
another leaves the plugin out with that reason, and the build of its image fails.
"""

from evo_agents.hub.server import core_plugin_api as hub

API = (1, 5)  # the version of the API of core plugins this plugin is written for
SERVER = "evo_core_plugins.telegram.server"
BRIDGE = "evo_core_plugins.telegram.bridge"

MANIFEST = {
    "id": "telegram",
    "version": "1.1.0",
    "publisher": "evo-agents",
    "tier": "core",
    "name": "Telegram",
    "description": "The hub's Telegram channel: members link a chat from the web and answer decisions and proposals.",
    "engines": {"evo-agents": ">=0.23.1"},
    "plugin_api": 1,
    "permissions": ["chats:read", "chats:write"],
    "contributes": {
        "channels": [{"name": "telegram", "title": "Telegram", "python": f"{SERVER}:TelegramChannel"}],
        "routes": [
            {"name": "me", "title": "A member's link", "python": f"{SERVER}:me_router", "prefix": ""},
            {"name": "webhook", "title": "Telegram's webhook", "python": f"{SERVER}:webhook_router", "prefix": ""},
            {"name": "admin", "title": "The bot and members' links", "python": f"{SERVER}:admin_router", "prefix": ""},
        ],
        "events": [{"name": "bridge", "on": ["chat.bridge"], "python": f"{BRIDGE}:on_chat_bridge"}],
    },
}


def manifest() -> dict:
    """The manifest, once this hub serves the version of the API the plugin is written for."""
    hub.require(*API)
    return MANIFEST


__all__ = ["API", "MANIFEST", "manifest"]
