"""The feedback notebook of the core plugin editorial as markdown (``evo_core_plugins.editorial.ledger``), its config
(``settings``) and its import file (``document``), without a hub: an export prints a notebook in exactly the format
it was kept in, the agent's line and the fixed line where they stood among the person's words, and an entry id reads
as PH-<n>. All names are fictional."""

from __future__ import annotations

import pytest

from evo_core_plugins.editorial import document, ledger, settings

VOICE = """# Voice notebook

What Lumen corrected about the voice of a post.
Read it before a draft.

## PH-0001 No opening question

- Ngày: 2026-09-14
- Bài: northwind-launch
- Lumen: "Do not open with a rhetorical question."
- Agent viết: "Have you ever wondered why stock runs out?" (label in the image)
- Lumen sửa: "Last week the Northwind store ran out of stock at 3 a.m."
- Lumen: "Again an opening question." (2026-09-21, post northwind-pricing)
- Luật: The first sentence is a fact, never a question.
- Kiểm: machine: the first sentence does not end with a question mark
- Lần gặp: 2

## PH-0003 Every figure has a source

- Ngày: 2026-09-20
- Bài: -
- Lumen: "Where does this number come from?"
- Luật: Each figure links its source.
- Lần gặp: 1
"""

ENTRIES = [
    {
        "number": 3,
        "title": "Every figure has a source",
        "date": "2026-09-20",
        "post": None,
        "said": [{"text": "Where does this number come from?", "date": None, "note": None}],
        "rule": "Each figure links its source.",
        "seen": 1,
    },
    {
        "number": 1,
        "title": "No opening question",
        "date": "2026-09-14",
        "post": "northwind-launch",
        "said": [
            {"text": "Do not open with a rhetorical question.", "date": None, "note": None},
            {"text": "Again an opening question.", "date": "2026-09-21", "note": "post northwind-pricing"},
        ],
        "agent_wrote": "Have you ever wondered why stock runs out?",
        "agent_note": "label in the image",
        "agent_after": 1,
        "person_fixed": "Last week the Northwind store ran out of stock at 3 a.m.",
        "fixed_after": 1,
        "rule": "The first sentence is a fact, never a question.",
        "check": "machine: the first sentence does not end with a question mark",
        "seen": 2,
    },
]

INTRO = "What Lumen corrected about the voice of a post.\nRead it before a draft."


def test_editorial_a_notebook_prints_exactly_as_it_was_kept():
    assert ledger.notebook_markdown("Voice notebook", INTRO, ENTRIES, "Lumen") == VOICE


def test_editorial_the_agent_and_fixed_lines_stand_after_all_said_lines_unless_placed():
    entry = {**ENTRIES[1], "agent_after": None, "fixed_after": None}
    lines = ledger.entry_markdown(entry, "Lumen").splitlines()
    assert [line.split(":")[0] for line in lines[4:8]] == ["- Lumen", "- Lumen", "- Agent viết", "- Lumen sửa"]
    alone = ledger.notebook_markdown("Empty", "", [], "Lumen")
    assert alone == "# Empty\n"


def test_editorial_entry_ids_read_as_ph_numbers():
    assert ledger.entry_id(42) == "PH-0042" and ledger.entry_id(12345) == "PH-12345"
    assert [ledger.entry_number(text) for text in ("PH-0042", "ph-42", "42", "PH-0", "x", "")] == [
        42,
        42,
        42,
        None,
        None,
        None,
    ]


def test_editorial_config_names_no_stage_and_reads_what_a_project_lists():
    assert settings.parse({}).stages == () and settings.parse({}).person == settings.DEFAULT_PERSON
    cfg = settings.parse(
        {
            "stages": [
                {"name": "idea", "gate": "choose", "recall": ["voice"]},
                {"name": "draft", "recall": ["voice", "facts"]},
                {"name": "idea", "gate": "publish"},
                {"name": "Bad Name"},
            ],
            "notebooks": [
                {"name": "voice", "title": "Voice notebook"},
                {"name": "facts", "title": "Facts"},
                {"name": "style", "title": "Style", "always": True},
            ],
            "person": "Lumen",
            "daily_usd": 3,
        }
    )
    assert cfg.stage_names == ("idea", "draft") and cfg.stage("idea").gate == "choose"
    assert cfg.recall("idea") == ("voice", "style") and cfg.recall("draft") == ("voice", "facts", "style")
    assert cfg.order("draft") == 1 and cfg.order("gone") == 2 and cfg.daily_usd == 3.0


def test_editorial_an_import_file_is_checked_against_the_config_before_anything_is_written():
    cfg = settings.parse(
        {"stages": [{"name": "idea", "gate": "choose"}], "notebooks": [{"name": "voice", "title": "Voice"}]}
    )
    doc = document.parse(
        None,
        {
            "posts": [{"slug": "northwind-launch", "stage": "nowhere", "gates": [{"stage": "idea", "state": "gone"}]}],
            "entries": [
                {"id": "PH-0001", "notebook": "facts", "title": "t", "date": "2026-09-14", "rule": "r"},
                {"id": "PH-1", "notebook": "voice", "title": "t", "date": "2026-09-14", "rule": "r"},
            ],
        },
    )
    wrong = " ".join(document.problems(cfg, doc))
    assert "nowhere" in wrong and "gone" in wrong and "PH-0001 is there twice" in wrong and "'facts'" in wrong
    with pytest.raises(ValueError, match="an entry id is PH-<number>"):
        document.parse(None, {"entries": [{"id": "X", "notebook": "voice", "title": "t", "date": "2026-09-14"}]})
    with pytest.raises(ValueError, match="no JSON"):
        document.parse("{", None)
