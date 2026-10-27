"""The bridge of a Telegram group to a group chat of the hub (API 1.5 of core plugins, ``docs/telegram-plugin.md``):
the hub's bot is the group's transport. ``bridge_model`` holds what the messages become; this module the updates of
a group the webhook hands it and the event ``chat.bridge`` the hub sends the plugin.

A chat admin makes a code on the hub (POST /v1/chats/{id}/bridges/code, kind ``telegram``) and sends ``/link <code>``
in the group, the bot a member of it (``hub.bridge_link``); a Telegram admin of the group takes it off with
``/unlink``, and so does the hub (a hub admin, the chat's page, the CLI). The bot taken out of the group (the update
my_chat_member, or a 403 on a message) unlinks it (``hub.bridge_unlink`` by bot); a group that becomes a supergroup
takes the bridge with it to its new chat id (``hub.bridge_move``), from the message that says so or from the 400
that names it.

In from the group: a message of someone who linked their Telegram account to the hub (their private chat with the
bot, ``server``) goes to the chat as theirs (``hub.bridge_send``), its photo or document with it (``hub.bridge_attach``,
within the 20 MB a bot may fetch from Telegram and the hub's own limit), a reply to a message the bridge carried in
its thread; ``@<bot>`` mentions the chat's agent and ``@<username>`` of a linked account its member's login. Someone
who linked nothing is told once how to link, and what they write stays out of the hub. A group that is not bridged
gets no answer: with privacy mode off the bot reads every message there.

Out to the group (the event): a new message of the chat as ``hub.bridge_message`` lets it out (None: nothing goes),
once, as HTML within 4096 characters, cut with a link to the hub when long; a run's progress as one message that is
edited; the agent's ✅ and ❌ on a message the bridge carried as the bot's reaction. The hub lets out no file of a chat
(``hub.bridge_message``), so a message that is a file alone goes as a link to it on the hub. At most 20 messages a
minute go to one group (``bridge_model.Pace``): a message that would wait longer than MAX_WAIT_SECONDS fails its try,
and the hub sends the event again later. A 429 fails it the same way.

The bridge keeps in its state (``hub.bridge_set_state``) the group's message of each of the last hub messages it
carried (``ids``), the progress message of each of the last runs (``runs``), the chat's agent once it spoke
(``agent``) and the senders told how to link (``told``).
"""

from __future__ import annotations

import logging
import time
from typing import Any

from evo_agents.hub.server import core_plugin_api as hub

from . import bridge_model as model
from . import model as telegram
from . import server

log = logging.getLogger(__name__)

MAX_WAIT_SECONDS = 5.0  # how long a message waits for the group's pace within one try of its event
GONE_STATES = frozenset({"left", "kicked"})
ADMIN_STATES = frozenset({"creator", "administrator"})
LINKED = (
    "This group is bridged to a chat of the hub. Messages of people who linked their Telegram account to the hub "
    "go there; the chat's messages come here. /unlink (a group admin) takes the bridge off."
)
LINK_FAILED = (
    "That code did not work: it was used, it expired, or it was not one of the hub's. Make a new one on the hub."
)
NOT_BRIDGED = "This group is not bridged to a chat of the hub."
UNLINKED = "This group is no longer bridged to the hub."
ADMINS_ONLY = "Only an admin of this group takes the bridge off."
HOW_TO_LINK = (
    "{name}, what you write here does not reach the hub until you link your Telegram account: on the hub, open "
    "Inbox, Telegram, and open the link it gives in your private chat with @{bot}."
)
TOO_LARGE = "That file is larger than a bot may fetch from Telegram (20 MB): put it on the hub."

clock = time.monotonic  # what the pace reads; tests move it instead of waiting
PACE = model.Pace(lambda: clock())


def plugin() -> hub.Plugin:
    return server.plugin()


def _int(value) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


async def _keep(conn, bridge: hub.Bridge, state: dict) -> None:
    await hub.bridge_set_state(conn, plugin(), bridge.id, state)


# In from the group


class Group:
    """What the webhook does with one message of a group."""

    def __init__(self, updates: server.Updates, message: dict, chat_id: int):
        self.updates = updates
        self.request = updates.request
        self.message = message
        self.chat_id = chat_id
        self.sender = server._object(message.get("from"))
        text = message.get("text") if isinstance(message.get("text"), str) else message.get("caption")
        self.text = text if isinstance(text, str) else ""

    async def handle(self) -> str:
        moved = await self.migrated()
        if moved is not None:
            return moved
        found = telegram.command(self.text)
        if found is not None and found[0] == "start":  # a private chat's link, as before: it does not link a group
            return await self.updates.text(self.message, self.chat_id)
        if found is not None and found[0] == "link":
            return await self.link(found[1])
        if found is not None and found[0] == "unlink":
            return await self.unlink()
        if self.sender.get("is_bot") is True or not isinstance(self.message.get("message_id"), int):
            return "ignored"
        async with hub.begin(self.request) as conn:
            bridge = await hub.bridge_find(conn, plugin(), server.KIND, self.chat_id)
        if bridge is None:
            return "ignored"
        return await self.bridged(bridge)

    async def migrated(self) -> str | None:
        """A group that became a supergroup: the bridge follows it to its new id. None for another message."""
        to, came_from = _int(self.message.get("migrate_to_chat_id")), _int(self.message.get("migrate_from_chat_id"))
        if to is None and came_from is None:
            return None
        old, new = (self.chat_id, to) if to is not None else (came_from, self.chat_id)
        async with hub.begin(self.request) as conn:
            if await move(conn, old, new):
                log.info("telegram bridge moved to a supergroup")
        return "moved"

    async def link(self, code: str | None) -> str:
        found = None
        if code is not None and telegram.LINK_CODE.fullmatch(code):
            config = {"by": self.sender["id"]} if _int(self.sender.get("id")) is not None else {}
            try:
                async with hub.begin(self.request) as conn:
                    found = await hub.bridge_link(conn, plugin(), server.KIND, code, self.chat_id, config=config)
            except hub.Refused as exc:
                await self.updates.say(self.chat_id, f"The hub did not bridge this group: {exc.detail}")
                return "refused"
        if found is None:
            await self.updates.say(self.chat_id, LINK_FAILED)
            return "bridge_failed"
        log.info("telegram group bridged", extra={"bridge": found.id, "chat": found.chat_id})
        await self.updates.say(self.chat_id, LINKED)
        return "bridged"

    async def unlink(self) -> str:
        async with hub.begin(self.request) as conn:
            found = await hub.bridge_find(conn, plugin(), server.KIND, self.chat_id)
        if found is None:
            await self.updates.say(self.chat_id, NOT_BRIDGED)
            return "not_bridged"
        if not await self.admin():
            await self.updates.say(self.chat_id, ADMINS_ONLY)
            return "refused"
        async with hub.begin(self.request) as conn:
            await hub.bridge_unlink(conn, plugin(), found.id, by="bot")
        log.info("telegram group unbridged", extra={"bridge": found.id, "by": "group"})
        await self.updates.say(self.chat_id, UNLINKED)
        return "unbridged"

    async def admin(self) -> bool:
        """Whether the sender is an admin of the group, as Telegram says now."""
        sender_id = _int(self.sender.get("id"))
        if sender_id is None:
            return False
        try:
            found = await self.updates.bot.call("getChatMember", chat_id=self.chat_id, user_id=sender_id)
        except server.BotApiError as exc:
            log.warning("telegram getChatMember failed", extra={"code": exc.code})
            return False
        return isinstance(found, dict) and found.get("status") in ADMIN_STATES

    async def bridged(self, bridge: hub.Bridge) -> str:
        """A message of the bridged group: in as its sender's member, or a word once to a sender not linked."""
        sender_id = _int(self.sender.get("id"))
        if sender_id is None:
            return "ignored"
        async with hub.begin(self.request) as conn:
            member = await hub.find_member(conn, plugin(), server.KIND, {"user_id": sender_id})
            if member is None:
                fresh = await hub.bridge_read(conn, plugin(), bridge.id)
                state = dict(fresh.state) if fresh is not None else dict(bridge.state)
                if sender_id in (state.get("told") or []):
                    return "not_linked"
                await _keep(conn, bridge, model.told(state, sender_id))
        if member is None:
            bot = await server.bot_username(self.request.app)
            name = str(self.sender.get("first_name") or self.sender.get("username") or "Hello")[:64]
            await self.updates.say(
                self.chat_id, HOW_TO_LINK.format(name=name, bot=bot), reply_to=self.message.get("message_id")
            )
            return "not_linked"
        files = []
        found = model.file_of(self.message)
        if found is not None:
            attached = await self.attach(member, bridge, found)
            if attached is None and not self.text.strip():
                return "refused"
            files += [attached] if attached is not None else []
        if not self.text.strip() and not files:
            return "ignored"
        bot = await server.bot_username(self.request.app)
        try:
            async with hub.begin(self.request) as conn:
                body = await self.body(conn, member, bridge, bot)
                replied = server._object(self.message.get("reply_to_message")).get("message_id")
                sent = await hub.bridge_send(
                    conn,
                    member,
                    bridge.id,
                    body,
                    external_id=self.message["message_id"],
                    reply_to=_int(replied),
                    attachment_ids=files,
                )
                fresh = await hub.bridge_read(conn, plugin(), bridge.id)
                state = dict(fresh.state) if fresh is not None else {}
                await _keep(
                    conn, bridge, model.remembered(state, "ids", {sent.id: self.message["message_id"]}, model.KEEP_IDS)
                )
        except hub.Refused as exc:
            await self.updates.say(
                self.chat_id, f"The hub did not take that: {exc.detail}", reply_to=self.message.get("message_id")
            )
            return "refused"
        return "bridged_in"

    async def body(self, conn, member: hub.Member, bridge: hub.Bridge, bot: str) -> str:
        """The text as the hub reads it: its mentions of the bot and of linked accounts made the hub's."""
        names = [name for name in model.usernames(self.text) if name.lower() != bot.lower()]
        logins = {}
        for name in names[:20]:
            found = await hub.find_member(conn, plugin(), server.KIND, {"username": name})
            if found is not None:
                logins[name] = found.login
        agent = bridge.state.get("agent") if isinstance(bridge.state.get("agent"), str) else None
        if agent is None and f"@{bot}".lower() in self.text.lower():
            known = await hub.agents(conn, member)
            agent = known[0].handle if known else None
        return model.inbound_text(self.text, bot, agent, logins)

    async def attach(self, member: hub.Member, bridge: hub.Bridge, found: dict) -> int | None:
        """The file of the message kept on the hub: its id there, or None, the group told why."""
        reply_to = self.message.get("message_id")
        size = _int(found.get("size"))
        if size is not None and size > model.TELEGRAM_DOWNLOAD_BYTES:
            await self.updates.say(self.chat_id, TOO_LARGE, reply_to=reply_to)
            return None
        try:
            data = await self.updates.bot.download(found["id"], model.TELEGRAM_DOWNLOAD_BYTES)
        except server.BotApiError as exc:
            log.warning("telegram file not fetched", extra={"code": exc.code})
            await self.updates.say(
                self.chat_id,
                TOO_LARGE if exc.code == 413 else "That file did not come from Telegram: send it again.",
                reply_to=reply_to,
            )
            return None
        try:
            return await hub.bridge_attach(self.request, member, bridge.id, found["name"], data, found["media_type"])
        except hub.Refused as exc:
            await self.updates.say(self.chat_id, f"The hub did not take that file: {exc.detail}", reply_to=reply_to)
            return None


async def move(conn, old: int, new: int) -> bool:
    """The bridge of group ``old`` follows it to ``new``; whether there was one."""
    found = await hub.bridge_find(conn, plugin(), server.KIND, old)
    if found is None:
        return False
    try:
        return await hub.bridge_move(conn, plugin(), found.id, new)
    except hub.Refused:  # the new id is bridged already: the old bridge goes
        await hub.bridge_unlink(conn, plugin(), found.id, by="bot")
        return False


async def member_changed(updates: server.Updates, change: dict) -> str:
    """The bot's own membership of a chat changed: out of a bridged group, the bridge goes."""
    chat = server._object(change.get("chat"))
    new = server._object(change.get("new_chat_member"))
    chat_id = _int(chat.get("id"))
    if chat_id is None or chat.get("type") not in model.GROUP_TYPES:
        return "ignored"
    gone = new.get("status") in GONE_STATES or (new.get("status") == "restricted" and new.get("is_member") is False)
    if not gone:
        return "ignored"
    async with hub.begin(updates.request) as conn:
        found = await hub.bridge_find(conn, plugin(), server.KIND, chat_id)
        if found is None:
            return "ignored"
        await hub.bridge_unlink(conn, plugin(), found.id, by="bot")
    log.info("telegram group unbridged", extra={"bridge": found.id, "by": "removed"})
    return "unbridged"


# Out to the group


class Later(Exception):  # noqa: N818 (a try of the event that waits for the group, not an error of the hub)
    """The group's pace or Telegram's 429 holds the message: the event's try fails, and the hub tries it again."""


async def _paced(chat_id: int) -> None:
    wait = PACE.wait(chat_id)
    if wait > MAX_WAIT_SECONDS:
        raise Later(f"the group's pace holds the message for {wait:.0f}s")
    if wait > 0:
        await server.pause(wait)


async def _send(context: hub.Context, bot: server.BotApi, bridge: hub.Bridge, method: str, **params) -> Any:
    """``method`` to the bridge's group, paced; None when the group is gone (the bridge unlinked). A group that became
    a supergroup gets it there, the bridge moved."""
    chat_id = int(bridge.external_id)
    for _ in range(2):
        if method != "setMessageReaction":
            await _paced(chat_id)
        try:
            sent = await bot.call(method, chat_id=chat_id, **params)
        except server.BotApiError as exc:
            if exc.migrate_to is not None:
                async with hub.transaction(context) as conn:
                    await hub.bridge_move(conn, plugin(), bridge.id, exc.migrate_to)
                chat_id = exc.migrate_to
                continue
            if exc.code == 429:
                raise Later(f"Telegram asked to wait {exc.retry_after or 0:.0f}s") from None
            if server._gone(exc):
                async with hub.transaction(context) as conn:
                    await hub.bridge_unlink(conn, plugin(), bridge.id, by="bot")
                log.info("telegram group unbridged", extra={"bridge": bridge.id, "by": "gone"})
                return None
            raise
        if method != "setMessageReaction":
            PACE.took(chat_id)
        return sent
    return None


def _reply(message_id: int | None) -> dict | None:
    return {"message_id": message_id, "allow_sending_without_reply": True} if message_id else None


async def _message(context: hub.Context, bot: server.BotApi, bridge: hub.Bridge, payload: dict) -> None:
    message_id = payload["message_id"]
    if str(message_id) in (bridge.state.get("ids") or {}):
        return  # it went already, or came from this group
    async with hub.transaction(context) as conn:
        read = await hub.bridge_message(conn, plugin(), bridge.id, message_id)
    if read is None:
        return
    url = hub.web_url(context.config, read.link)
    text = model.outbound(read.author_kind, read.author, read.body, url)
    reply_to = int(read.reply_to) if read.reply_to and read.reply_to.lstrip("-").isdigit() else None
    common = {"reply_parameters": _reply(reply_to), "link_preview_options": {"is_disabled": True}}
    try:
        sent = await _send(context, bot, bridge, "sendMessage", text=text, parse_mode=telegram.PARSE_MODE, **common)
    except server.BotApiError as exc:
        if exc.code != 400:
            raise
        log.warning("telegram group refused the HTML: sent as text", extra={"code": exc.code})
        sent = await _send(context, bot, bridge, "sendMessage", text=model.plain(text), **common)
    group_id = server._sent_id(sent)
    if group_id is None:
        return
    async with hub.transaction(context) as conn:
        await hub.bridge_sent(conn, plugin(), bridge.id, message_id, group_id)
        fresh = await hub.bridge_read(conn, plugin(), bridge.id)
        if fresh is None:
            return
        state = model.remembered(fresh.state, "ids", {message_id: group_id}, model.KEEP_IDS)
        if read.author_kind == "agent" and read.author:
            state["agent"] = read.author
        await _keep(conn, bridge, state)


async def _progress(context: hub.Context, bot: server.BotApi, bridge: hub.Bridge, payload: dict) -> None:
    run_id, state = payload["run_id"], str(payload.get("state") or "")
    text = model.progress_text(run_id, state)
    shown = (bridge.state.get("runs") or {}).get(str(run_id))
    if isinstance(shown, int):
        try:
            await _send(context, bot, bridge, "editMessageText", message_id=shown, text=text)
        except server.BotApiError as exc:
            if exc.code != 400:  # "message is not modified", or one deleted in the group: nothing to do
                raise
        return
    started = (bridge.state.get("ids") or {}).get(str(payload.get("message_id")))
    sent = await _send(
        context,
        bot,
        bridge,
        "sendMessage",
        text=text,
        reply_parameters=_reply(started if isinstance(started, int) else None),
        disable_notification=True,
    )
    group_id = server._sent_id(sent)
    if group_id is None:
        return
    async with hub.transaction(context) as conn:
        fresh = await hub.bridge_read(conn, plugin(), bridge.id)
        if fresh is not None:
            await _keep(conn, bridge, model.remembered(fresh.state, "runs", {run_id: group_id}, model.KEEP_RUNS))


async def _reaction(context: hub.Context, bot: server.BotApi, bridge: hub.Bridge, payload: dict) -> None:
    emoji = model.reaction(str(payload.get("emoji") or ""))
    target = (bridge.state.get("ids") or {}).get(str(payload.get("message_id")))
    if emoji is None or not isinstance(target, int):
        return
    on = payload.get("added") is True or (payload.get("count") or 0) > 0
    reaction = [{"type": "emoji", "emoji": emoji}] if on else []
    try:
        await _send(context, bot, bridge, "setMessageReaction", message_id=target, reaction=reaction)
    except server.BotApiError as exc:
        if exc.code != 400:  # a group that allows no such reaction, or a message deleted there
            raise
        log.info("telegram reaction refused", extra={"code": exc.code})


async def on_chat_bridge(params: dict, context: hub.Context) -> dict:
    """What a bridged chat of the hub carries out to its Telegram group (the event ``chat.bridge``)."""
    payload = params["payload"]
    bot = server.BotApi.from_settings(server.settings())
    if bot is None:
        log.warning("telegram bridge event dropped: the channel is not set up")
        return {}
    async with hub.transaction(context) as conn:
        bridge = await hub.bridge_read(conn, plugin(), payload["bridge_id"])
    if bridge is None:
        return {}
    what = payload.get("what")
    if what == "message":
        await _message(context, bot, bridge, payload)
    elif what == "progress":
        await _progress(context, bot, bridge, payload)
    elif what == "reaction":
        await _reaction(context, bot, bridge, payload)
    return {}
