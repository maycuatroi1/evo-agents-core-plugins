# The core plugin telegram: the private channel and the group bridge

The plugin **telegram** is the hub's Telegram bot. Its code is `evo_core_plugins/telegram`. evo-agents-core-plugins ships
it as a core plugin, and the hub's image pins it (evo-agents' `docs/plugins.md`, Core plugins). It does two things:

- **The private channel.** A member links a private chat with the bot from the web. The bot sends them decisions,
  proposals and notices, with the files of a run and of a question, and they answer with buttons or replies. This part
  runs for the whole hub and needs no project to enable anything (evo-agents' `docs/notifications.md`, Telegram).
- **The group bridge** (API 1.5, evo-agents' `docs/chat-bridges.md`). A Telegram group is bridged to a group chat of
  the hub, both ways. This part runs only in projects that enable the plugin.

## Setting up the bot

The variables `EVO_HUB_TELEGRAM_*` and the command `evo-agents hub admin telegram [--set-webhook]` stay as they were
for the private channel. The webhook now also asks for `my_chat_member`, so Telegram tells the bot when it is taken out of
a group. After an upgrade, a hub admin runs `evo-agents hub admin telegram --set-webhook` again. Until then, the bot sees no removals: a
group the bot left stays bridged until the next message the hub sends there is refused.

**Turn privacy mode off.** In @BotFather, open `/mybots`, then the bot, then *Bot Settings*, then *Group Privacy*, and
choose *Turn off*. With privacy mode on, Telegram gives a bot in a group only commands and replies to it, and the
members' other messages never reach the hub. Telegram applies the change to the groups the bot joins next. In a group
the bot is already in, remove the bot and add it again.

## Enabling the bridge in a project

```sh
evo-agents hub plugin enable telegram --project evo-agents   # asks for chats:read and chats:write
```

The plugin asks for `chats:read` and `chats:write`, so it can read what goes out and write what comes in. Every project
of the chat's agents must enable it, or the hub refuses the link code (403).

Nothing goes out of a project's chats until the project's `knowledge.yaml` declares a sink of kind `channel` named
`telegram`. Its clearance bounds what may go out: a message whose label is not below the clearance stays in the hub.

```yaml
sinks:
  - id: telegram
    kind: channel
    clearance: {level: internal}
```

## Linking a group

1. Add the bot to the Telegram group.
2. On the hub, a chat admin makes a code for the chat, of kind `telegram`, on the chat's page or with
   `POST /v1/chats/{id}/bridges/code`. The code lives ten minutes.
3. Someone in the group sends `/link <code>`. The bot answers that the group is bridged, or that the code did not work.

A group bridges one chat at a time. A group that is not bridged gets no answer to its messages.

| Taken off by | How |
| --- | --- |
| a group admin | `/unlink` in the group. The bot checks with Telegram that the sender is the group's creator or an administrator |
| Telegram | the bot removed from the group, or a message out refused because the bot is no longer there |
| the hub | a chat admin on the chat's page, `evo-agents hub chat unbridge`, or a hub admin |

When a group becomes a supergroup, Telegram gives it a new id. The bridge moves to the new id, from the service message
or from the error of the next message out.

## In: the group to the hub

A message comes in under the name of the hub member who linked the sender's Telegram account (the private channel's
`/start` link). It enters the chat on that member's rights, with `via: telegram`.

- `@` followed by the bot's username becomes a mention of the chat's agent. That is the agent that last wrote to the
  group, or else the first agent the member may talk to. The Telegram `@username` of a linked member becomes their
  `@login`.
- A reply to a message the bridge carried goes into that message's thread.
- A photo (its largest size) or a document comes in as the member's attachment, with the caption as the text. Telegram
  lets a bot download files of 20 MB at most. A larger file is refused with a reply in the group.
- Someone who has not linked a Telegram account is told once, as a reply, how to link. Nothing they write enters the
  hub.
- A Telegram message that arrives twice is stored once.

## Out: the hub to the group

Every new message of the chat goes out, except the ones that came from the group.

- A message is sent as Telegram HTML, under its author's name: `login`, or `agent (agent)`. Bold, inline code, links
  and code blocks keep their form, and a markdown table becomes a `<pre>` block. A message over 4096 characters is cut
  and ends with a link to the rest on the hub. A reply on the hub replies to the group's message its thread started
  from.
- No file goes out. The hub's API for bridges gives the text alone (evo-agents' `docs/chat-bridges.md`, Out). A message
  that is only files goes out as a link to it on the hub.
- A chat run started by a message from the group shows its progress as one message, sent as a reply and then edited
  (`Run #N: picked up`, then `working`, then `done`).
- ✅ and ❌ that the hub puts on a message the bridge carried become the bot's 👍 and 👎 reactions in the group. Telegram
  does not offer ✅ or ❌ as bot reactions.
- A group gets at most 20 messages a minute. A message that would go past that waits, and the hub delivers it again
  later, in order.

## What the people in a group should know

- **Anyone in the group reads what goes out**, whether or not they are a member of the hub. The hub checks the
  project's `telegram` sink and the chat's label, not each person in the group. Bridge a chat only to a group whose
  people may read everything the chat's level lets out.
- **The group's admins manage its members.** The hub does not know who is in the Telegram group and cannot remove
  anyone. Who reads the group is up to its admins, in Telegram.
- A member's Telegram account writes with that member's rights on the hub. Unlink the account on the hub when it
  changes hands.

## Tests

`plugin_tests/test_telegram_bridge.py` drives the bridge through a hub of evo-agents at the lock and the fake Bot API
of `plugin_tests/fake_telegram.py`. It covers linking, unlinking, migration, mentions, members who have not linked,
photos, HTML and cutting, progress, reactions and the pace of 20 messages a minute. The pure parts are in
`evo_core_plugins/telegram/bridge_model.py`.
