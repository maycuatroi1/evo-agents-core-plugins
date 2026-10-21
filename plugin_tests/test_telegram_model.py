"""The Telegram channel's model: the hub's part (``evo_agents.hub.telegram``: link codes, what may reach a channel, the
URL of a page) and the core plugin's (``evo_core_plugins.telegram.model``: commands, the data of buttons, what a
restricted project's message holds, and the messages of a decision, a proposal and a notice). No database, no
network."""

import re

import pytest

from evo_agents.hub import telegram as hub_telegram
from evo_core_plugins.telegram import model as telegram

OPTIONS = [
    {"key": "sqlite", "label": "Keep SQLite"},
    {"key": "postgres", "label": "Move to Postgres", "description": "One more service.", "recommended": True},
]


def test_a_link_code_is_32_characters_a_start_parameter_takes_and_the_hub_keeps_its_hash():
    code = hub_telegram.new_code()
    assert len(code) == hub_telegram.LINK_CODE_CHARS == 32 and re.fullmatch(r"[A-Za-z0-9_-]{32}", code)
    assert hub_telegram.new_code() != code
    digest = hub_telegram.code_hash(code)
    assert re.fullmatch(r"[0-9a-f]{64}", digest) and code not in digest
    assert telegram.link_url("evo_hub_bot", code) == f"https://t.me/evo_hub_bot?start={code}"
    assert hub_telegram.LINK_SECONDS == 600


@pytest.mark.parametrize(
    ("text", "found"),
    [
        ("/start " + "a" * 32, ("start", "a" * 32)),
        ("/start@evo_hub_bot " + "B-_" + "c" * 29, ("start", "B-_" + "c" * 29)),
        ("/stop", ("stop", None)),
        ("/stop@evo_hub_bot", ("stop", None)),
        ("/start", ("start", None)),
        ("hello", None),
        ("", None),
        (None, None),
    ],
)
def test_commands_are_read_with_or_without_the_bots_name(text, found):
    assert telegram.command(text) == found


def test_only_a_code_of_the_right_shape_is_a_start_code():
    assert telegram.start_code("/start " + "x" * 32) == "x" * 32
    for text in ("/start", "/start " + "x" * 31, "/start " + "x" * 33, "/start " + "x" * 31 + "!", "/stop " + "x" * 32):
        assert telegram.start_code(text) is None


def test_button_data_names_the_item_and_the_choice_within_64_bytes_and_nothing_else_parses():
    data = telegram.decision_callback(123, "postgres")
    assert data == "d:123:postgres"
    assert telegram.parse_callback(data) == telegram.Callback("decision", 123, "postgres")
    longest = telegram.decision_callback(10**17, "k" * 32)
    assert len(longest.encode()) <= telegram.MAX_CALLBACK_BYTES
    assert telegram.parse_callback(telegram.proposal_callback(7, "defer")) == telegram.Callback("proposal", 7, "defer")
    for data in ("p:7:merge", "d:0:a", "x:1:a", "d:1:", "d:1:a b", None, 12, "d:1:" + "a" * 33):
        assert telegram.parse_callback(data) is None


def test_button_data_takes_only_what_an_option_key_may_be():
    # A key starts with a letter or digit, as runs.OPTION_KEY has it: the hub's buttons never carry another.
    for data in ("d:1:-x", "d:1:_x", "d:1:-", "d:1:__", "p:1:-accept"):
        assert telegram.parse_callback(data) is None
    assert telegram.parse_callback("d:1:x-_y") == telegram.Callback("decision", 1, "x-_y")
    assert telegram.parse_callback("d:1:" + "a" * 32) == telegram.Callback("decision", 1, "a" * 32)


def test_a_sent_message_is_kept_by_its_chat_and_its_id():
    assert telegram.message_ref(7001, 1005) == "7001:1005"
    assert telegram.message_ref(-5001, 1005) != telegram.message_ref(7001, 1005)


LEVELS = ["public", "internal", "customer", "secret"]  # evo_agents.kg.policy.DEFAULT_LEVELS
ANY = ["any"]
DOMESTIC = ["any", "domestic-only"]


@pytest.mark.parametrize(
    ("clearance", "locations", "restricted"),
    [
        ({"level": "internal"}, ANY, False),
        ({"level": "internal", "location": "any"}, DOMESTIC, False),
        ({"level": "customer", "location": "any"}, DOMESTIC, True),
        ({"level": "internal", "location": "domestic-only"}, DOMESTIC, True),
        ({"level": "customer", "location": "domestic-only"}, DOMESTIC, True),
        (None, ANY, True),  # no hub sink: fail closed
    ],
)
def test_a_project_cleared_for_customer_or_domestic_only_is_restricted(clearance, locations, restricted):
    assert hub_telegram.restricted(clearance, LEVELS, locations) is restricted


@pytest.mark.parametrize(
    ("clearance", "levels", "locations"),
    [
        ({"level": "secret", "location": "any"}, LEVELS, DOMESTIC),  # above customer
        ({"level": "secret"}, LEVELS, ANY),
        ({"level": "top-secret"}, [*LEVELS, "top-secret"], ANY),  # a custom level above customer
        ({"location": "any"}, LEVELS, DOMESTIC),  # no level
        ({"level": None}, LEVELS, ANY),
        ({"level": "galaxy"}, LEVELS, ANY),  # a level the ladder lacks
        ({"level": "Internal"}, LEVELS, ANY),
        ({"level": "internal", "location": "moon"}, LEVELS, DOMESTIC),  # a location the ladder lacks
        ({"level": "internal"}, LEVELS, DOMESTIC),  # no location: it may receive any, domestic-only included
        ({"level": "internal", "location": "on-premises"}, LEVELS, [*DOMESTIC, "on-premises"]),  # stricter still
        ({"level": "confidential"}, ["public", "confidential"], ANY),  # no customer: above the lowest is restricted
        ({"level": "internal", "location": "eu-only"}, LEVELS, ["any", "eu-only"]),  # no domestic-only: the same
        ({"level": "internal"}, None, ANY),  # no ladder at all
        ({"level": "internal"}, [], ANY),
        ("customer", LEVELS, ANY),  # not a clearance
        ([], LEVELS, ANY),
    ],
)
def test_restricted_compares_ranks_on_the_projects_ladder_and_fails_closed(clearance, levels, locations):
    assert hub_telegram.restricted(clearance, levels, locations) is True


@pytest.mark.parametrize(
    ("clearance", "levels", "locations"),
    [
        ({"level": "public"}, LEVELS, ANY),
        ({"level": "internal", "location": "any"}, LEVELS, DOMESTIC),
        ({"level": "public"}, ["public", "confidential"], ANY),  # the lowest rung of a ladder without customer
        ({"level": "internal"}, ["public", "internal", "restricted", "customer"], ANY),
    ],
)
def test_below_customer_and_domestic_only_on_the_ladder_is_not_restricted(clearance, levels, locations):
    assert hub_telegram.restricted(clearance, levels, locations) is False


# A channel of any clearance (restricted_for, the API of core plugins' restricted and prepare)


@pytest.mark.parametrize(
    ("clearance", "level", "location", "kept"),
    [
        ({"level": "internal", "location": "any"}, "internal", None, False),
        ({"level": "public"}, "internal", "any", True),  # a sink without a location may receive any: above any
        ({"level": "internal", "location": "domestic-only"}, "internal", None, False),  # None receives any location
        ({"level": "internal", "location": "domestic-only"}, "internal", "any", True),
        ({"level": "customer", "location": "any"}, "internal", None, True),  # above the channel's level
        ({"level": "customer", "location": "any"}, "customer", None, False),
        ({"level": "secret"}, "secret", None, False),
        (None, "secret", None, True),  # no hub sink
        ({"location": "any"}, "secret", None, True),  # a sink without a level
        ({"level": "galaxy"}, "secret", None, True),  # a level the ladder lacks
        ({"level": "internal"}, "galaxy", None, True),  # a channel's level the ladder lacks
        ({"level": "internal", "location": "moon"}, "internal", None, True),
        ({"level": "internal", "location": "any"}, "internal", "moon", True),
    ],
)
def test_restricted_for_keeps_a_sink_above_the_channels_clearance_and_fails_closed(clearance, level, location, kept):
    assert hub_telegram.restricted_for(clearance, LEVELS, DOMESTIC, level, location) is kept


@pytest.mark.parametrize(
    ("clearance", "levels", "level", "location", "kept"),
    [
        ({"level": "internal", "location": "any"}, LEVELS, "customer", "domestic-only", False),
        ({"level": "customer", "location": "any"}, LEVELS, "customer", "domestic-only", True),  # at the level
        ({"level": "internal", "location": "domestic-only"}, LEVELS, "customer", "domestic-only", True),
        ({"level": "customer"}, LEVELS, "secret", None, False),  # None: any location
        ({"level": "secret"}, LEVELS, "secret", None, True),
        ({"level": "internal", "location": "moon"}, LEVELS, "secret", None, True),  # a location the ladder lacks
        ({"level": "public"}, ["public", "confidential"], "customer", None, False),  # no customer: the lowest rung
        ({"level": "confidential"}, ["public", "confidential"], "customer", None, True),
        (None, LEVELS, "secret", None, True),  # no hub sink
    ],
)
def test_restricted_for_below_keeps_a_sink_at_or_above_the_channels_clearance(clearance, levels, level, location, kept):
    """``Clearance(level, location, below=True)`` of the API of core plugins: what sits under the rungs, not at them;
    ``restricted`` is customer and domestic-only, below."""
    assert hub_telegram.restricted_for(clearance, levels, DOMESTIC, level, location, below=True) is kept


def test_a_restricted_message_holds_the_project_the_kind_and_the_link_only():
    url = "https://hub.test/inbox?decision=5"
    message = telegram.minimal_message("northwind", "decision", None, url, "/inbox?decision=5")
    assert message.text == f"<b>northwind</b>: A decision waits for your answer.\n\n{url}"
    assert message.buttons == [[{"text": "Open on the hub", "url": url}]]
    brief = telegram.minimal_message("northwind", "notice", "curator_brief", None, "/p/northwind/curator")
    assert brief.text == "<b>northwind</b>: Morning brief.\n\n/p/northwind/curator" and brief.buttons == []


def test_a_decision_has_a_button_per_option_and_one_for_the_web_and_escapes_what_the_agent_wrote():
    message = telegram.decision_message(
        decision_id=9,
        project="evo-agents",
        run_id=4,
        plan_id="fleet",
        step_key="2",
        category="architecture",
        question="Use <b>Postgres</b> & drop SQLite?",
        options=OPTIONS,
        url="https://hub.test/inbox?decision=9",
        link="/inbox?decision=9",
    )
    assert "Run #4 of evo-agents asks a decision</b> (architecture, plan fleet, step 2)" in message.text
    assert "Use &lt;b&gt;Postgres&lt;/b&gt; &amp; drop SQLite?" in message.text
    assert "postgres: Move to Postgres (recommended)" in message.text
    assert "One more service." not in message.text  # an option's description stays on the hub
    assert message.buttons == [
        [{"text": "Keep SQLite", "callback_data": "d:9:sqlite"}],
        [{"text": "Move to Postgres (recommended)", "callback_data": "d:9:postgres"}],
        [{"text": "Open on the hub", "url": "https://hub.test/inbox?decision=9"}],
    ]
    assert message.reply_markup() == {"inline_keyboard": message.buttons}
    long = telegram.decision_message(
        decision_id=9,
        project="p",
        run_id=None,
        plan_id=None,
        step_key=None,
        category="scope",
        question="q" * 5000,
        options=OPTIONS,
        url=None,
        link=None,
    )
    assert len(long.text) <= telegram.MAX_TEXT_CHARS and "q" * (telegram.QUESTION_CHARS - 3) + "..." in long.text


def test_a_telegram_decision_of_an_author_run_without_a_plan_names_the_run_and_its_title():
    def message(plan_id, run_title, step_key=None):
        return telegram.decision_message(
            decision_id=9,
            project="evo-agents",
            run_id=4,
            plan_id=plan_id,
            step_key=step_key,
            category="scope",
            question="Poll, or subscribe?",
            options=OPTIONS,
            url="https://hub.test/inbox?decision=9",
            link="/inbox?decision=9",
            run_kind="author",
            run_title=run_title,
        )

    titled = message(None, "A wait\nhelper <for> tests")
    assert "<b>Author run #4 of evo-agents asks a decision</b> (scope, A wait helper &lt;for&gt; tests)" in titled.text
    assert "None" not in titled.text and len(titled.buttons) == len(OPTIONS) + 1
    assert "(scope, no plan yet)" in message(None, None).text
    long = message(None, "t" * 500).text
    assert "t" * (telegram.RUN_TITLE_CHARS - 3) + "..." in long and "t" * telegram.RUN_TITLE_CHARS not in long
    planned = message("wait-helper", "A wait helper", "2").text
    assert "<b>Author run #4 of evo-agents asks a decision</b> (scope, plan wait-helper, step 2)" in planned


def test_a_proposal_has_accept_reject_defer_and_the_web_and_no_summary():
    message = telegram.proposal_message(
        proposal_id=3,
        project="evo-agents",
        title="A wait helper instead of sleep and tail",
        tier=2,
        kind="feature",
        lens="environment",
        evidence=4,
        url="https://hub.test/inbox?proposal=3",
        link="/inbox?proposal=3",
    )
    assert "Proposal #3 of evo-agents" in message.text and "tier 2, kind feature, lens environment" in message.text
    assert [button["callback_data"] for button in message.buttons[0]] == ["p:3:accept", "p:3:reject", "p:3:defer"]
    assert message.buttons[1] == [{"text": "Open on the hub", "url": "https://hub.test/inbox?proposal=3"}]


def test_a_notice_keeps_the_bold_of_its_body_and_escapes_the_rest():
    message = telegram.notice_message(
        project="p",
        notice_kind="curator_brief",
        title="t",
        body="**Night of 2026-10-08** <x> & **",
        url=None,
        link=None,
    )
    assert message.text.endswith("<b>Night of 2026-10-08</b> &lt;x&gt; &amp; **")


def test_a_notice_names_its_kind_and_cuts_its_body():
    message = telegram.notice_message(
        project="evo-agents", notice_kind="curator_brief", title="Morning brief", body="x" * 9000, url=None, link="/p"
    )
    assert message.text.startswith("<b>Morning brief</b> in evo-agents\nMorning brief\n\n")
    assert len(message.text) <= telegram.MAX_TEXT_CHARS and message.buttons == []


def test_an_answered_message_keeps_its_web_button_only():
    markup = {
        "inline_keyboard": [
            [{"text": "Keep SQLite", "callback_data": "d:9:sqlite"}],
            [{"text": "Open on the hub", "url": "https://hub.test/inbox?decision=9"}],
        ]
    }
    assert telegram.url_buttons(markup) == [[{"text": "Open on the hub", "url": "https://hub.test/inbox?decision=9"}]]
    assert telegram.url_buttons(None) == [] and telegram.url_buttons({"inline_keyboard": "no"}) == []
    assert telegram.answered_text("Pick <one>", "Answered by owner: Keep SQLite") == (
        "Pick &lt;one&gt;\n\n<b>Answered by owner: Keep SQLite</b>"
    )


def test_web_url_needs_the_public_url_and_a_path_of_the_hub():
    assert hub_telegram.web_url("https://hub.test/", "/inbox?decision=1") == "https://hub.test/inbox?decision=1"
    assert hub_telegram.web_url(None, "/inbox") is None
    assert hub_telegram.web_url("https://hub.test", "//evil.example") is None
    assert hub_telegram.web_url("https://hub.test", "https://evil.example") is None


# What a message holds when its text runs long, and when what it was about closed

ENTITY_OR_TAG = re.compile(r"&[A-Za-z#0-9]*;|</?b>")


def well_formed(text: str) -> bool:
    """No entity or tag cut in two: every & starts a whole entity, every < a whole <b> or </b>, and they pair up."""
    rest = ENTITY_OR_TAG.sub("", text)
    opened = 0
    for tag in re.findall(r"</?b>", text):
        opened += -1 if tag.startswith("</") else 1
        if opened not in (0, 1):
            return False
    return "&" not in rest and "<" not in rest and ">" not in rest and opened == 0


def test_clip_html_cuts_between_entities_and_tags_and_closes_what_it_left_open():
    text = "<b>" + "a&amp;" * 50 + "</b> tail"
    for limit in range(5, len(text)):
        cut = telegram.clip_html(text, limit)
        assert len(cut) <= limit and well_formed(cut), (limit, cut)
        assert cut.endswith("...</b>") or cut.endswith("...")
    assert telegram.clip_html(text, len(text)) == text
    assert telegram.clip_html("&lt;" * 10, 9) == "&lt;..."  # not "&lt;&l..."


def test_an_answered_message_keeps_its_outcome_whole_however_long_the_original():
    outcome = "Answered by owner: Move to Postgres"
    for original in ("<&>" * 2000, "x" * 5000, "a&b " * 1500):
        edited = telegram.answered_text(original, outcome)
        assert len(edited) <= telegram.MAX_TEXT_CHARS and well_formed(edited)
        assert edited.endswith(f"\n\n<b>{outcome}</b>")
    long_outcome = telegram.answered_text("short", "o" * 1000)
    assert long_outcome.endswith("...</b>") and len(long_outcome) < 400


def test_a_long_message_of_escaped_text_stays_whole_html_and_keeps_its_link():
    heavy = "<&>" * 2000
    options = [{"key": f"k{index}", "label": "&" * 200} for index in range(6)]
    url = "https://hub.test/inbox?decision=9"
    decision = telegram.decision_message(
        decision_id=9,
        project="p",
        run_id=1,
        plan_id="fleet",
        step_key="2",
        category="scope",
        question=heavy,
        options=options,
        url=url,
        link="/inbox?decision=9",
    )
    proposal = telegram.proposal_message(
        proposal_id=3,
        project="p",
        title=heavy,
        tier=2,
        kind="feature",
        lens=None,
        evidence=1,
        url=url,
        link="/inbox?proposal=3",
    )
    notice = telegram.notice_message(
        project="p", notice_kind="curator_brief", title="t", body="**a & b** " * 900, url=url, link="/p"
    )
    for message in (decision, proposal, notice):
        assert len(message.text) <= telegram.MAX_TEXT_CHARS and well_formed(message.text)
        assert message.text.endswith(f"\n\n{url}")
    assert "Tap an option, or reply to this message with your answer in words." in decision.text
    assert "tier 2, kind feature, 1 piece of evidence" in proposal.text


def test_a_decision_or_proposal_closed_before_its_message_says_so_and_nothing_else():
    url = "https://hub.test/inbox?proposal=3"
    closed = telegram.closed_message("evo-agents", "proposal", 3, url, "/inbox?proposal=3")
    assert closed.text == f"<b>evo-agents</b>: Proposal #3 no longer waits for your answer.\n\n{url}"
    assert closed.buttons == [[{"text": "Open on the hub", "url": url}]]
    decision = telegram.closed_message("p&q", "decision", 9, None, "/inbox?decision=9")
    assert decision.text == "<b>p&amp;q</b>: Decision #9 no longer waits for your answer.\n\n/inbox?decision=9"
    assert decision.buttons == []


# The files of a notification


def output(file_id: int, name: str, media_type: str = "image/png", size: int = 100, **changes) -> dict:
    """One of ``extra.outputs`` as the hub's prepare gives it, with a URL standing in for a presigned GET."""
    url = f"https://store.test/blobs/{file_id:064x}?X-Amz-Signature=fake"
    found = {"id": file_id, "name": name, "media_type": media_type, "viewer": "image", "size": size, "caption": None}
    return {**found, "url": url, **changes}


def test_a_message_goes_with_the_files_that_are_whole_with_a_url_and_within_telegrams_bounds():
    extra = {
        "restricted": False,
        "outputs": [
            output(1, "settings.png"),
            output(2, "no-url.png", url=None),  # the hub's pass had no store to sign with
            output(3, "empty.png", size=0),
            output(4, "odd.bin", media_type="not a type"),
            output(5, "huge.mp4", media_type="video/mp4", size=telegram.MAX_DOCUMENT_BYTES + 1),
            "not an object",
            output(7, "x.png", id="7"),
            output(8, "out/report.md", media_type="text/markdown", caption="What changed"),
        ],
        "outputs_count": 12,
    }
    found = telegram.files_of(extra)
    assert [(file.id, file.name, file.caption) for file in found.files] == [
        (1, "settings.png", None),
        (8, "out/report.md", "What changed"),
    ]
    assert (found.total, found.more, found.photos) == (12, 10, False)
    for nothing in (
        None,
        {"restricted": True},
        {"outputs": []},
        {"outputs": "x"},
        {"outputs": [output(2, "a", url=None)]},
    ):
        assert telegram.files_of(nothing) is None, nothing


def test_one_notification_uploads_at_most_ten_files_and_twenty_mib_in_all():
    eleven = telegram.files_of({"outputs": [output(n, f"{n}.png") for n in range(1, 12)], "outputs_count": 11})
    assert len(eleven.files) == telegram.MEDIA_GROUP_SIZE == 10 and eleven.more == 1
    mib = telegram.MiB
    big = [output(1, "a.mp4", "video/mp4", 9 * mib), output(2, "b.mp4", "video/mp4", 9 * mib)]
    big += [output(3, "c.mp4", "video/mp4", 9 * mib), output(4, "d.png", size=mib)]
    found = telegram.files_of({"outputs": big, "outputs_count": 4})
    assert [file.id for file in found.files] == [1, 2, 4] and found.more == 1  # the third would pass 20 MiB


def test_files_go_as_photos_when_each_may_be_one_and_as_documents_otherwise():
    def files(*outputs) -> telegram.Files:
        return telegram.files_of({"outputs": list(outputs)})

    assert files(output(1, "a.png"), output(2, "b.jpg", "image/jpeg"), output(3, "c.webp", "IMAGE/WEBP")).photos
    for other in (
        output(4, "d.svg", "image/svg+xml"),
        output(5, "e.gif", "image/gif"),
        output(6, "f.png", size=telegram.MAX_PHOTO_BYTES + 1),
        output(7, "g.md", "text/markdown"),
    ):
        assert not files(output(1, "a.png"), other).photos, other["name"]
    assert telegram.media_group(["After <b>the</b> fix", None], photos=True) == [
        {"type": "photo", "media": "attach://file0", "caption": "After <b>the</b> fix", "parse_mode": "HTML"},
        {"type": "photo", "media": "attach://file1"},
    ]
    assert [item["type"] for item in telegram.media_group([None, None], photos=False)] == ["document", "document"]


def test_a_decisions_file_has_its_own_caption_cut_to_fit_and_the_last_counts_the_rest():
    shown = telegram.files_of(
        {"outputs": [output(1, "a.png", caption="After the fix & <b>"), output(2, "b.png")], "outputs_count": 4}
    )
    assert telegram.file_captions(shown) == ["After the fix &amp; &lt;b&gt;", "2 more files on the hub."]
    long = telegram.files_of({"outputs": [output(1, "a.png", caption="& " * 2000)], "outputs_count": 2})
    (caption,) = telegram.file_captions(long)
    assert len(caption) <= telegram.MAX_CAPTION_CHARS and caption.endswith("...\n\n1 more file on the hub.")
    assert "&am..." not in caption  # cut between entities, never inside one
    alone = telegram.files_of({"outputs": [output(1, "a.png")]})
    assert telegram.file_captions(alone) == [None]


def test_a_notices_caption_keeps_its_link_and_counts_the_files_left_out():
    message = telegram.notice_message(
        project="lumen",
        notice_kind="run_outputs",
        title="Local run #7 sent 12 files",
        body="- report.md (1.2 KiB): what changed\n" * 200,
        url="https://hub.test/p/lumen/runs/7",
        link="/p/lumen/runs/7",
        limit=telegram.MAX_CAPTION_CHARS,
        more=2,
    )
    assert len(message.text) <= telegram.MAX_CAPTION_CHARS
    assert message.text.startswith("<b>Files from a run</b> in lumen\nLocal run #7 sent 12 files\n\n- report.md")
    assert message.text.endswith("\n\n2 more files on the hub.\n\nhttps://hub.test/p/lumen/runs/7")
    assert message.buttons == [[{"text": "Open on the hub", "url": "https://hub.test/p/lumen/runs/7"}]]
    restricted = telegram.minimal_message("lumen", "notice", "run_outputs", None, "/p/lumen/runs/7")
    assert restricted.text == "<b>lumen</b>: Files from a run.\n\n/p/lumen/runs/7"


def test_a_file_is_uploaded_with_the_last_part_of_its_name_without_quotes_or_control_characters():
    assert telegram.upload_name('out/dir/re"port\n.md') == "re_port_.md"
    assert telegram.upload_name("bảng giá.png") == "bảng giá.png"
    assert telegram.upload_name("") == telegram.upload_name("out/") == "file"
    long = telegram.upload_name("x" * 300 + ".tar.gz")
    assert len(long) == telegram.UPLOAD_NAME_CHARS and long.endswith("x.gz")
