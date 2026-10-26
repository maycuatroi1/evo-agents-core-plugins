# The core plugin editorial: posts through their stages, and the feedback notebook

The plugin **editorial** keeps, for a project that enabled it, the posts the project writes and the stage each one is
at, the gates where a post waits for a person, the review rounds of a draft with their comments, and the feedback
notebook: what the person corrected, in their own words, with the rule it gives and how often it came back. Agents
read the notebook before a stage so the same correction is not needed twice. Its code is `evo_core_plugins/editorial`;
evo-agents-core-plugins ships it as a core plugin, which the hub's image pins (evo-agents' `docs/plugins.md`, Core
plugins). It asks for API 1.4 of `core_plugin_api` and does nothing in a project until an admin of the project enables
it there; until then it writes no row and its routes answer 404.

The plugin runs no job, sends no message and calls no outside service: it stores what its routes, CLI and tools are
told. Publishing, previews and chat replies stay with whoever drives the posts; they report back with `set`.

## Enabling it

```sh
evo-agents hub plugin enable editorial --project northwind      # asks for no permission
evo-agents hub plugin config editorial --project northwind --file editorial.json
```

The config is a JSON Schema (`evo_core_plugins/editorial/settings.py`, `CONFIG`). The plugin knows no stage by name:
each project lists its own.

| Field | What it holds | When left out |
| --- | --- | --- |
| `stages` | the stages a post goes through, in order: `name`, `title`, the kind of its `gate` (`choose`, `interview`, `comments`, `publish`) when a person decides there, and `recall`, the notebooks to read before it | no stage: no post can be made |
| `notebooks` | the notebooks of feedback: `name`, the `title` and `intro` their markdown starts with, and `always` when every stage reads it | no notebook: no entry can be added |
| `person` | the name the notebook's lines give the person whose words they keep | `Owner` |
| `reviewers` | the reviewers whose comments on a draft count | none |
| `daily_usd` | the most the agents of a post spend in a day, for whoever drives them | no cap |

An example with fictional names:

```json
{
  "stages": [
    {"name": "idea", "title": "Idea", "gate": "choose", "recall": ["voice"]},
    {"name": "draft", "title": "Draft", "recall": ["voice", "facts"]},
    {"name": "review", "title": "Review", "gate": "comments"},
    {"name": "ship", "title": "Ship", "gate": "publish"}
  ],
  "notebooks": [
    {"name": "voice", "title": "Voice notebook", "intro": "What Lumen corrected about the voice of a post."},
    {"name": "facts", "title": "Facts notebook"},
    {"name": "style", "title": "Style notebook", "always": true}
  ],
  "person": "Lumen"
}
```

A value that breaks the schema, or a post or entry that names a stage or notebook the config does not list, is
refused with 422.

## Model

Six tables, made by the plugin's own migration chain (`evo_core_plugins/editorial/tables.py`, `editorial/migrations/`):

| Table | What it holds |
| --- | --- |
| `editorial_posts` | one row for each post of a project, by slug: title, stage, branch, preview and published links, publish time, the figures 7 and 28 days after, label |
| `editorial_stage_history` | each stage a post entered, when, and what showed it |
| `editorial_gates` | the gate of a post at each stage the config gives one: kind, state (`waiting`, `answered`, `skipped`), when it opened and was answered, through what (`hub` when unsaid), by whom, and the answer |
| `editorial_rounds` | the review rounds of a post at a stage, numbered from 1: when, a note, the entries the round wrote |
| `editorial_comments` | the comments of a round, each once by its id: author, quoted text, text |
| `editorial_feedback` | the notebook: one row for each entry `PH-<n>` of a project, in a notebook of the config, with the person's words, what the agent wrote and what the person changed it to, the rule, its check, the times seen, label |

A row carries the label of its project's default when it is made, and reads follow it like the rest of the hub: a
caller whose grant or sink is below a row's label does not see it.

Entering a stage that has a gate opens that gate (state `waiting`). A post's `waiting_gate` is its current stage's gate
when that waits, otherwise the first waiting gate in stage order, otherwise none.

## Roles

| Action | Role |
| --- | --- |
| read posts, the notebook, recall, export | reader |
| set a post, add an entry, record a repeat | writer |
| import | admin |

## Routes

All under `/v1/x/editorial/{project}/`. Each answers JSON; with `?render=text` it answers `{"text": ...}`, what the CLI
prints without `--json`.

| Route | What it does |
| --- | --- |
| `GET posts?stage=` | the posts in stage order: slug, title, stage, waiting_gate, gates (stage, kind, state, answered_at, answered_via), rounds (a count), preview_url, url |
| `GET posts/{slug}` | one post with its gates, rounds and comments, history and feedback ids |
| `POST posts/{slug}` | set its stage, title, links, figures, or a gate's state (`gate`, `gate_state`, `via`, `answer`); a new slug needs a stage |
| `GET recall?stage=&post=&q=` | what to read before a stage: the entries of the stage's notebooks and those about the post, seen most first |
| `GET feedback?notebook=&post=&stage=&seen=&q=` | the entries, filtered |
| `POST feedback?notebook=&post=` | add an entry (title, said and rule required); answers a list of the one entry, 201 |
| `POST feedback/{entry}/repeat` | the entry came back: its count goes up and the new words join its lines |
| `POST import` | write a JSON document's posts and entries, keeping their ids; a second run adds nothing |
| `GET export?notebook=&format=` | the notebooks as markdown files, or with `format=json` the document import takes |

## Command line

Every command takes `--project` and `--json`.

```sh
evo-agents hub editorial posts --project northwind [--stage review] [--json]
evo-agents hub editorial show northwind-launch --project northwind
evo-agents hub editorial set northwind-launch --stage draft --evidence "draft pushed" --project northwind
evo-agents hub editorial set northwind-launch --gate idea --gate-state answered --via chat --project northwind
evo-agents hub editorial recall --stage draft --post northwind-launch --project northwind
evo-agents hub editorial feedback list --notebook voice --seen 2 --keyword question --project northwind
evo-agents hub editorial feedback add --notebook voice --title "No opening question" \
  --said "Do not open with a rhetorical question." --rule "The first sentence is a fact." --project northwind
evo-agents hub editorial feedback repeat PH-0001 --said "Again a question." --project northwind
evo-agents hub editorial import editorial.json --project northwind
evo-agents hub editorial export --notebook voice --project northwind > voice.md
```

`export` without `--json` prints the markdown exactly as the notebook keeps it, so `export --notebook voice` gives back
the file the entries came from.

## Tools

| MCP tool | What it does |
| --- | --- |
| `editorial__state` | the posts, or one post by `slug`; with `set`, what `POST posts/{slug}` takes (writer) |
| `editorial__recall` | what `GET recall` answers, by `stage`, `post` and `keyword` |
| `editorial__feedback` | `action` `add` an entry or `repeat` one (`entry`, PH-<n>) (writer) |

A tool answers JSON text; a refusal answers `refused: ...` as an error.

## Knowledge graph

The source `plugin.editorial` gives one item per entry (`plugin.editorial:feedback:PH-0001`, its markdown block as the
notebook prints it, with its notebook, post, rule and times seen) and one per post
(`plugin.editorial:post:<slug>`, its stage, links and the state of each gate), each with its row's label.

## The import document

```json
{
  "posts": [
    {
      "slug": "northwind-launch", "title": "How Northwind ships at night", "stage": "review",
      "preview_url": "https://preview.example.org/northwind-launch",
      "history": [{"stage": "idea", "at": "2026-09-10T08:00:00Z"}],
      "gates": [{"stage": "idea", "state": "answered", "answered_at": "2026-09-11T09:00:00Z", "answered_via": "chat"}],
      "rounds": [{"stage": "review", "number": 1, "feedback": ["PH-0001"],
                  "comments": [{"id": "c-1", "author": "lumen", "text": "No question."}]}]
    }
  ],
  "entries": [
    {
      "id": "PH-0001", "notebook": "voice", "title": "No opening question", "date": "2026-09-14",
      "post": "northwind-launch", "said": [{"text": "Do not open with a rhetorical question."}],
      "agent_wrote": "Have you ever wondered why stock runs out?", "agent_after": 1,
      "person_fixed": "Last week the Northwind store ran out of stock at 3 a.m.", "fixed_after": 1,
      "rule": "The first sentence is a fact, never a question.", "seen": 1
    }
  ]
}
```

The whole document is checked against the config before anything is written; a problem refuses all of it. Posts are
matched by slug, entries by id, gates by stage, rounds by stage and number, comments by id, so a second import updates
and adds nothing. `export --format json` prints this document.

## The markdown format

One file per notebook, `<name>.md`: its title, its intro, then one block per entry in number order. The line labels
are the notebook's own (Vietnamese), and the person's lines carry the configured name:

```markdown
# Voice notebook

What Lumen corrected about the voice of a post.

## PH-0001 No opening question

- Ngày: 2026-09-14
- Bài: northwind-launch
- Lumen: "Do not open with a rhetorical question."
- Agent viết: "Have you ever wondered why stock runs out?"
- Lumen sửa: "Last week the Northwind store ran out of stock at 3 a.m."
- Luật: The first sentence is a fact, never a question.
- Lần gặp: 1
```

`Ngày` is the date, `Bài` the post (`-` when none), `Agent viết` what the agent wrote, `Lumen sửa` what the person
changed it to, `Luật` the rule, `Kiểm` its check and `Lần gặp` the times seen. A repeat adds a line of the person's
words with its date and note in parentheses. The agent's and the fixed lines stand where they stood among the
person's words (`agent_after`, `fixed_after`), after all of them when unsaid.
