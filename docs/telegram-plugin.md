# The core plugin telegram: the private channel and the group bridge

The plugin **telegram** is the hub's Telegram bot. Its code is `evo_core_plugins/telegram`. evo-agents-core-plugins ships
it as a core plugin, and the hub's image pins it (evo-agents' `docs/plugins.md`, Core plugins). It does two things:

- **The private channel.** A member links a private chat with the bot from the web. The bot sends them decisions,
  proposals and notices, with the files of a run and of a question, and they answer with buttons or replies. This part
  runs for the whole hub and needs no project to enable anything (evo-agents' `docs/notifications.md`, Telegram).
- **The group bridge** (API 1.5, evo-agents' `docs/chat-bridges.md`). A Telegram group is bridged to a group chat of
  the hub, both ways. This part runs only in projects that enable the plugin.

## Answering a decision in the private chat

A decision's message has one button per option and one that opens it on the hub. The member answers with a button, or
in words: they reply to the decision's message (Telegram's *Reply*) with a text. Only the private chat answers this
way; a bridged group does not.

- **A reply answers the decision of the message it replies to, and no other**, even when several decisions wait for the
  member. The hub keeps the words whole as the answer, with no option, and records that it came through `telegram`
  (`answered_via`; the web and `evo-agents hub decision show` show it as a free answer). The run gets it in its inbox,
  or resumes. The bot then edits the decision's message: it ends with *Answered in words by <login>*, its option
  buttons go and its *Open on the hub* button stays. It tells the member, as a reply, that the answer went to the run.
- **Words that reply to no message**, or to a message of the bot that is not a decision's (a notice, the link
  message), answer nothing. The bot tells the member to reply to the decision's own message (`NO_BLOCKER`). A
  proposal takes its buttons only (`WORDS_FOR_DECISIONS`). A chat that is not linked gets the help, which says how to
  link it.
- **A decision that has its answer already**, given on Telegram, on the web or with the CLI, changes nothing: the bot
  tells the member so (`ALREADY_ANSWERED`). A reply sent twice, or an update Telegram delivers again, is no second
  answer. A chat that is not linked (`NOT_LINKED`), or the chat of a member the decision was not sent to, answers
  nothing.
- **A decision that was cancelled or expired** takes no answer either: the decision keeps its state, and no inbox or
  audit row is written. The bot tells the member that decision #<id> was cancelled, or expired, naming the state the
  hub's refusal gives (`CLOSED_DECISION`), without repeating the words.
- **A reply to a message that went as the link alone** (a decision of a restricted project, `minimal_message`) answers
  nothing, whatever became of the project's clearance since: the hub keeps such a message with a ref of its own
  (`<chat>:<message>:link`), and the refusal follows that kind of message, not the project. Nothing of the decision is
  read or written: no answer, audit row, inbox message or edit. The bot tells the member to answer it on the hub, with
  the link of that decision, the one its *Open on the hub* button has (`.../inbox?decision=<id>`, `LINK_ONLY_ANSWER`).
  A message sent before this kind of ref existed is still refused by the hub while its project is restricted
  (`RESTRICTED_ANSWER`).
- **Words that look like they hold a secret** (a token, a key or a password: what the hub's `evo_agents.hub.redact`
  masks) are refused by the hub before it keeps anything: the decision stays open, and no inbox, audit row or log
  line holds them. The bot tells the member the answer was not kept because it looks like it holds a secret, without
  repeating it (`HOLDS_SECRET`), and to give a credential on the hub instead. Words longer than the hub takes (4 KiB)
  get `TOO_LONG`.

An answer in words has no label of its own: it is the decision's `answer_text`, read at the decision's label (its
plan's, the project's by default), never at the channel's it came through. The bot's words and log lines never hold
the words of an answer.

The bot's messages are in English. The refusal of secrets and `answered_via` come from evo-agents (plan
dev8-telegram-free-answer step 1); an older hub keeps no channel and filters nothing.

## A decision by its label, and the edit of its message (1.3.0)

From evo-agents `e7f93a86` (pull request #784, API still 1.7) a decision may carry a label, and the hub's `prepare`
judges it by that label against the project's sink of kind `channel` named `telegram` (evo-agents'
`docs/notifications.md`, Decisions on channels). The plugin reads what `prepare` leaves in `extra`:

- **Content.** A decision the sink clears goes to the member's linked private chat, never to a group: the run and its
  plan and step (or the author run's title), the question as a summary, one button per option, the line that says a
  reply answers in words, and the link to the decision. The text stays within 4,096 characters: the question is cut
  first, and the link and the buttons stay whole.
- **The link alone, because of the label.** `restricted: true` with `restricted_by` `label` (its own label keeps it
  off) or `default_label` (it has none, and its project's default label keeps it off) sends the project, that a decision
  waits, one sentence that it must be opened on the hub because of that label (`withheld_line`), and the link: no
  question, option or button. A button pressed with that decision's id, forged or old, is refused by the hub (403)
  before anything is read, and nothing is written. `restricted_by` `project` keeps the message it had.
- **The edit.** Once the decision is answered, cancelled or expired, the hub's outbox gives the channel one more
  delivery whose `extra.edit` names the message (`external_id`) and the decision's `state`. The channel edits that
  message (editMessageText) instead of sending one: its options go, its *Open on the hub* button stays, and it ends with
  *Answered by <login>: <option>* (with *on the hub* or *via <channel>* when it came another way), *Answered in words by
  <login>*, or that the decision was cancelled or expired (`settled_words`). A link-only message gets the state alone.
  Telegram's *message is not modified* counts as done; a message it can no longer edit gets the edit as a new message;
  a message of a chat the member no longer links is left as it is.
- **Errors go back to the hub as what they are.** A 429 is `RetryAfter` with Telegram's `retry_after`, a network error
  or another refusal a failed try that the hub backs off, a blocked bot `ChannelGone`. The hub tries a decision's
  delivery and its edit for 30 minutes from the first try. A failed edit after an answer was kept never answers again:
  the answer is the hub's, and only the edit is tried again.
- **Buttons.** A button answers through `hub.answer_decision` as the member the chat is linked to; the bot answers the
  button and edits the message at once, and the hub's edit follows. A decision answered already, on the web, the CLI or
  another channel (409), keeps its answer: the button says so and the message ends with it (`TAPPED_SETTLED`); the
  hub's edit names who answered it and with which option. A cancelled or expired decision keeps nothing and its message
  says which. A chat not linked, or a member the decision is not asked of, is refused and nothing changes; pressing the
  same button again, or Telegram delivering the same update again, finds the decision answered (409) and is no second
  answer.

The tests are in `plugin_tests/test_telegram.py`, one for each of these branches (`test_label_*`, `test_edit_*`,
`test_button_*`), and the words and the cut of these messages in `plugin_tests/test_telegram_model.py`.

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
- The files a member or agent attached to the message go with it. The hub lists them in `BridgeMessage.files` and
  gives their bytes through `bridge_file`, under the same check of the channel sink (evo-agents' `docs/chat-bridges.md`,
  Out). A JPEG, PNG or WebP image of 10 MB at most goes as a photo (sendPhoto), and any other file of 50 MB at most as
  a document (sendDocument), each as a reply to the message. A photo Telegram refuses goes again as a document. A
  message that is only files goes as its first file, with its author as the caption. A larger file stays on the hub:
  the message names it and links to the message there. One delivery uploads at most 20 MB after its first file, so it
  ends within the hub's 30 seconds. The rest go on the next delivery.
- A chat run started by a message from the group shows its progress as one message, sent as a reply and then edited
  (`Run #N: picked up`, then `working`, then `done`). While the run is picked up or working, the group shows the bot
  as typing (`sendChatAction` every 4 seconds), for at most 30 minutes a run. The typing is not a message and does not
  count toward the 20 messages a minute.
- ✅ and ❌ that the chat's agent puts on a message the bridge carried become the bot's 👍 and 👎 reactions in the
  group. Telegram's list of reactions has neither ✅ nor ❌. A person's reaction on the hub stays on the hub.
- A group gets at most 20 messages a minute. A message that would go past that waits, and the hub delivers it again
  later, in order. The bridge tells the hub how long (`retry_after` of the exception `Later`, from 2.6.3): the
  pace's wait, Telegram's `retry_after` on a 429, or 1 second when a message's files go on the next try. A hub that
  reads it (evo-agents pull request #569) sends the event again within seconds; an older hub waits its own backoff,
  a minute and more.

## What the people in a group should know

- **Anyone in the group reads what goes out**, whether or not they are a member of the hub. The hub checks the
  project's `telegram` sink and the chat's label, not each person in the group. Bridge a chat only to a group whose
  people may read everything the chat's level lets out.
- **The group's admins manage its members.** The hub does not know who is in the Telegram group and cannot remove
  anyone. Who reads the group is up to its admins, in Telegram.
- A member's Telegram account writes with that member's rights on the hub. Unlink the account on the hub when it
  changes hands.

## Tests

`plugin_tests/test_telegram.py` drives the private channel the same way. The answer in words is
`test_a_reply_to_the_decisions_message_answers_it_in_words`, `test_words_that_reply_to_no_blocker_answer_nothing_and_say_how`,
`test_a_reply_to_an_answered_decision_changes_nothing_and_says_so`,
`test_words_that_hold_a_secret_are_refused_and_not_kept`, `test_a_reply_finds_the_decision_of_its_own_chat_only`,
`test_a_reply_to_a_link_only_message_is_refused_with_the_decisions_link`,
`test_a_reply_to_a_cancelled_or_expired_decision_keeps_nothing_and_says_its_state` and
`test_a_free_answer_is_kept_at_the_decisions_label`.

`plugin_tests/test_telegram_bridge.py` drives the bridge through a hub of evo-agents at the lock and the fake Bot API
of `plugin_tests/fake_telegram.py`. It covers linking, unlinking, migration, mentions, members who have not linked,
photos in, files out (photos, documents and files too large for Telegram), HTML and cutting, progress, reactions and the pace of 20 messages a minute. The pure parts are in
`evo_core_plugins/telegram/bridge_model.py`.
