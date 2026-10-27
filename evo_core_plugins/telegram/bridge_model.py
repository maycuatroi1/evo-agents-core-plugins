"""The bridge of a Telegram group to a group chat of the hub as the core plugin telegram models it: what a message of
the hub becomes in the group, what a message of the group becomes on the hub, a run's progress, the reactions that
go out, and the pace a group gets. Pure functions on the standard library; ``bridge`` holds the I/O, and
``docs/telegram-plugin.md`` the design.

Out to the group, a message is HTML within MAX_TEXT_CHARS (``outbound``): its author first, then its markdown as
Telegram's HTML takes it: a fenced block or a table becomes ``<pre>`` (a table with its columns padded, since
Telegram has no tables), inline code ``<code>``, ``**bold**`` and a heading ``<b>``, an http(s) link ``<a>``, the
rest escaped. A message cut to fit ends with a link to it on the hub, kept whole. A run's progress is one line
(``progress_text``) that the bridge edits as the run moves. Of the reactions of the hub only the agent's ✅ and ❌
go out (REACTIONS); a bot's reaction is one of the emoji Telegram allows, so they go as 👍 and 👎.

In from the group (``inbound_text``), ``@<bot>`` becomes the mention of the chat's agent and ``@<username>`` of a
Telegram account linked to the hub the mention of its member's login, as the hub reads mentions.

A group gets at most GROUP_MESSAGES messages in GROUP_SECONDS, besides one a second in one chat and 30 a second
overall that the Bot FAQ asks for (``Pace``).
"""

from __future__ import annotations

import html
import re
from collections import deque
from collections.abc import Callable, Mapping

from . import model as telegram

GROUP_MESSAGES, GROUP_SECONDS = 20, 60.0  # Telegram's bound on a bot's messages to one group
GROUP_TYPES = frozenset({"group", "supergroup"})
GROUP_INBOUND_UPDATES = 30  # the updates the webhook takes from one group in INBOUND_SECONDS: a group talks more
TELEGRAM_DOWNLOAD_BYTES = 20 * 1024 * 1024  # what a bot may fetch from Telegram (getFile)
CHECK, CROSS = "✅", "❌"  # the hub's reactions of a run that ended (evo_agents.hub.chats)
REACTIONS = {CHECK: "\U0001f44d", CROSS: "\U0001f44e"}  # what the agent's reaction is in the group
KEEP_IDS = 200  # the hub's messages whose group message the bridge remembers (reactions, progress, dedup)
KEEP_RUNS = 30  # the runs whose progress message it remembers
KEEP_TOLD = 200  # the senders it told how to link
CUT_TAIL = '\n\n<a href="{url}">Read the rest on the hub</a>'
FILES_ON_HUB = "(a file, on the hub)"
PROGRESS_WORDS = {
    "queued": "waits for a worker",
    "leased": "picked up",
    "running": "working",
    "interactive": "working",
    "verifying": "checking its work",
    "waiting": "waits for an answer",
    "review": "in review",
    "parked": "parked",
    "done": "done",
    "failed": "failed",
    "lost": "lost, tried again",
    "cancelled": "cancelled",
}

_FENCE = re.compile(r"^```[^\n`]*\n(.*?)^```[ \t]*$", re.DOTALL | re.MULTILINE)
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
_TABLE_RULE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")
_INLINE_CODE = re.compile(r"`([^`\n]+)`")
_BOLD = re.compile(r"\*\*([^*\n]+)\*\*")
_LINK = re.compile(r"\[([^\]\n]+)\]\((https?://[^\s)]+)\)")
_HEADING = re.compile(r"^#{1,6}\s+(.+)$", re.MULTILINE)
_BULLET = re.compile(r"^(\s*)[-*]\s+", re.MULTILINE)
_USERNAME = re.compile(r"(?<![\w@./-])@([A-Za-z0-9_]{1,64})")  # what a mention in a Telegram message looks like


# Out to the group


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def table_text(lines: list[str]) -> str:
    """A markdown table as text of padded columns, its rule a line of dashes."""
    rows = [_cells(line) for line in lines if not _TABLE_RULE.fullmatch(line)]
    width = max(len(row) for row in rows)
    rows = [row + [""] * (width - len(row)) for row in rows]
    sizes = [max(len(row[column]) for row in rows) for column in range(width)]
    out = [" | ".join(cell.ljust(size) for cell, size in zip(row, sizes, strict=True)).rstrip() for row in rows]
    if len(out) > 1:
        out.insert(1, "-+-".join("-" * size for size in sizes))
    return "\n".join(out)


def _inline(text: str) -> str:
    """One line of markdown, not in a block, as escaped HTML with code, bold and links."""
    pieces, last = [], 0
    for found in _INLINE_CODE.finditer(text):
        pieces.append(_styled(text[last : found.start()]))
        pieces.append(f"<code>{telegram.escape(found[1])}</code>")
        last = found.end()
    pieces.append(_styled(text[last:]))
    return "".join(pieces)


def _styled(text: str) -> str:
    out, last = [], 0
    for found in _LINK.finditer(text):
        out.append(_bold(text[last : found.start()]))
        url = html.escape(found[2], quote=True)
        out.append(f'<a href="{url}">{_bold(found[1])}</a>')
        last = found.end()
    out.append(_bold(text[last:]))
    return "".join(out)


def _bold(text: str) -> str:
    escaped = telegram.escape(text)
    return _BOLD.sub(lambda found: f"<b>{found[1]}</b>", escaped)


def _prose(text: str) -> str:
    """Markdown outside fenced blocks: tables to ``<pre>``, headings bold, bullets as such, the rest inline."""
    lines, out, index = text.split("\n"), [], 0
    while index < len(lines):
        line = lines[index]
        if _TABLE_ROW.fullmatch(line) and index + 1 < len(lines) and _TABLE_RULE.fullmatch(lines[index + 1]):
            end = index + 2
            while end < len(lines) and _TABLE_ROW.fullmatch(lines[end]):
                end += 1
            out.append(f"<pre>{telegram.escape(table_text(lines[index:end]))}</pre>")
            index = end
            continue
        heading = _HEADING.fullmatch(line)
        if heading:
            out.append(f"<b>{_inline(heading[1].strip())}</b>")
        else:
            out.append(_inline(_BULLET.sub(lambda found: f"{found[1]}• ", line)))
        index += 1
    return "\n".join(out)


def markdown_html(text: str) -> str:
    """Markdown ``text`` as Telegram's HTML takes it."""
    out, last = [], 0
    for found in _FENCE.finditer(text):
        out.append(_prose(text[last : found.start()]))
        out.append(f"<pre>{telegram.escape(found[1].rstrip(chr(10)))}</pre>")
        last = found.end()
    out.append(_prose(text[last:]))
    return "".join(out).strip()


def author_line(author_kind: str, author: str | None) -> str:
    if author_kind == "agent" and author:
        return f"<b>{telegram.escape(author)}</b> (agent)"
    if author_kind == "person" and author:
        return f"<b>{telegram.escape(author)}</b>"
    return "<b>hub</b>"


def outbound(author_kind: str, author: str | None, body: str, url: str | None) -> str:
    """A message of the hub as the group reads it: its author, then its body as HTML, within MAX_TEXT_CHARS; when cut,
    or when it is a file alone, it ends with a link to it on the hub (``url``)."""
    head = author_line(author_kind, author)
    shown = markdown_html(body) if body.strip() else telegram.escape(FILES_ON_HUB)
    whole = f"{head}\n{shown}"
    if not body.strip() and url:
        return telegram.fit(whole, f'\n<a href="{html.escape(url, quote=True)}">Open it on the hub</a>')
    if len(whole) <= telegram.MAX_TEXT_CHARS:
        return whole
    tail = CUT_TAIL.format(url=html.escape(url, quote=True)) if url else ""
    return telegram.fit(whole, tail)


def plain(text: str) -> str:
    """HTML this module built as plain text, for a group that refused it as HTML."""
    return telegram.clip(html.unescape(re.sub(r"<[^<>]*>", "", text)), telegram.MAX_TEXT_CHARS)


def progress_text(run_id: int, state: str) -> str:
    word = PROGRESS_WORDS.get(state, state)
    return f"Run #{run_id}: {telegram.escape(word)}"


def reaction(emoji: str) -> str | None:
    """What the hub's reaction ``emoji`` is in the group, or None for one that does not go out."""
    return REACTIONS.get(emoji)


# In from the group


def usernames(text: str) -> list[str]:
    """The Telegram usernames ``text`` mentions, in order, once each."""
    seen: dict[str, None] = {}
    for found in _USERNAME.finditer(text):
        seen.setdefault(found[1], None)
    return list(seen)


def inbound_text(text: str, bot: str | None, agent: str | None, logins: Mapping[str, str]) -> str:
    """``text`` of the group as the hub reads it: ``@<bot>`` the mention of ``agent`` (left out without one), and
    ``@<username>`` of ``logins`` the mention of its login; other mentions stay as they are."""

    def swap(found: re.Match) -> str:
        name = found[1]
        if bot and name.lower() == bot.lower():
            return f"@{agent}" if agent else ""
        login = logins.get(name) or logins.get(name.lower())
        return f"@{login}" if login else found[0]

    return re.sub(r"[ \t]{2,}", " ", _USERNAME.sub(swap, text)).strip()


def file_of(message: Mapping) -> dict | None:
    """The file a group's message carries, as {id, name, media_type, size}: its largest photo or its document; None
    without one."""
    photos = message.get("photo")
    if isinstance(photos, list) and photos:
        largest = photos[-1] if isinstance(photos[-1], dict) else {}
        if isinstance(largest.get("file_id"), str):
            name = f"photo-{message.get('message_id')}.jpg"
            return {
                "id": largest["file_id"],
                "name": name,
                "media_type": "image/jpeg",
                "size": largest.get("file_size"),
            }
    document = message.get("document")
    if isinstance(document, dict) and isinstance(document.get("file_id"), str):
        name = document.get("file_name") if isinstance(document.get("file_name"), str) else None
        media = document.get("mime_type") if isinstance(document.get("mime_type"), str) else None
        size = document.get("file_size")
        return {
            "id": document["file_id"],
            "name": name or f"file-{message.get('message_id')}",
            "media_type": media,
            "size": size,
        }
    return None


# What the bridge keeps


def remembered(state: Mapping, key: str, items: Mapping, keep: int) -> dict:
    """``state`` with ``items`` added to its map ``key``, keeping the last ``keep``."""
    kept = dict(state.get(key) or {})
    for name, value in items.items():
        kept.pop(str(name), None)
        kept[str(name)] = value
    return {**state, key: dict(list(kept.items())[-keep:])}


def told(state: Mapping, user_id: int) -> dict:
    """``state`` with ``user_id`` among the senders told how to link."""
    kept = [user for user in state.get("told") or [] if user != user_id]
    return {**state, "told": [*kept, user_id][-KEEP_TOLD:]}


# The pace of a group


class Pace:
    """At most GROUP_MESSAGES in GROUP_SECONDS to one group, one a second to one chat and 30 a second overall."""

    MAX_CHATS = 10_000

    def __init__(self, clock: Callable[[], float]):
        self.clock = clock
        self._sent: dict[int, deque[float]] = {}
        self._recent: deque[float] = deque(maxlen=telegram.MESSAGES_PER_SECOND)

    def wait(self, chat_id: int) -> float:
        """How long the next message to ``chat_id`` waits; 0 when it may go now."""
        now = self.clock()
        sent = self._sent.get(chat_id) or deque()
        while sent and now - sent[0] >= GROUP_SECONDS:
            sent.popleft()
        waits = [0.0]
        if len(sent) >= GROUP_MESSAGES:
            waits.append(sent[0] + GROUP_SECONDS - now)
        if sent:
            waits.append(sent[-1] + telegram.CHAT_INTERVAL_SECONDS - now)
        if len(self._recent) == self._recent.maxlen:
            waits.append(self._recent[0] + 1.0 - now)
        return max(waits)

    def took(self, chat_id: int) -> None:
        """A message went to ``chat_id`` now."""
        now = self.clock()
        if len(self._sent) > self.MAX_CHATS:
            self._sent = {key: sent for key, sent in self._sent.items() if sent and now - sent[-1] < GROUP_SECONDS}
        sent = self._sent.setdefault(chat_id, deque())
        while sent and now - sent[0] >= GROUP_SECONDS:
            sent.popleft()
        sent.append(now)
        self._recent.append(now)
