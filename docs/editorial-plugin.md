# The core plugin editorial: posts through their stages, and the feedback notebook

The plugin **editorial** keeps, for a project that enabled it, the posts the project writes and the stage each one is
at, the gates where a post waits for a person, the review rounds of a draft with their comments, and the feedback
notebook: what the person corrected, in their own words, with the rule it gives and how often it came back. Agents
read the notebook before a stage so the same correction is not needed twice. Its code is `evo_core_plugins/editorial`;
evo-agents-core-plugins ships it as a core plugin, which the hub's image pins (evo-agents' `docs/plugins.md`, Core
plugins). It asks for API 1.4 of `core_plugin_api` and does nothing in a project until an admin of the project enables
it there; until then it writes no row and its routes answer 404.

Without `repo` in its config the plugin only stores what its routes, CLI and tools are told. With it, the plugin runs
the flow of a post (The flow below): it hands the agent type `writer` its tasks, asks `editor-judge` to score a draft,
reads the reviewers' draft comments, and tells the gatekeepers when a post waits for them. It acts on a person's
answer, a button, and the hub's events, never on a clock: it contributes no job. It holds no credential, never calls
the blog's admin API, and publishes nothing; a person publishes and says so at the publish gate.

## Enabling it

```sh
evo-agents hub plugin enable editorial --project northwind      # asks for no permission
evo-agents hub plugin config editorial --project northwind --file editorial.json
```

For the flow, an admin also enables the two agent types on the project's Agent types page (or
`PUT /v1/projects/<project>/agent-types/editorial/<type>`), naming the member their runs go under and the cap of their
cost per day: `writer` with the config's `daily_usd`, and `editor-judge`.

The config is a JSON Schema (`evo_core_plugins/editorial/settings.py`, `CONFIG`). The plugin knows no stage by name:
each project lists its own.

| Field | What it holds | When left out |
| --- | --- | --- |
| `stages` | the stages a post goes through, in order: `name`, `title`, the kind of its `gate` (`choose`, `interview`, `comments`, `publish`) when a person decides there, and `recall`, the notebooks to read before it | no stage: no post can be made |
| `notebooks` | the notebooks of feedback: `name`, the `title` and `intro` their markdown starts with, and `always` when every stage reads it | no notebook: no entry can be added |
| `person` | the name the notebook's lines give the person whose words they keep | `Owner` |
| `reviewers` | the reviewers whose comments on a draft count | none |
| `daily_usd` | the most the writer spends in a day: enable the agent type `writer` with this cap, which the hub enforces | no cap |
| `repo` | the project's repo of posts: the writer's tasks run on its branch `post/<slug>`, and probes run in it | the flow is off: no task, no judge |
| `skill` | the writing skill the writer follows from a stage to the next gate | `writing` |
| `minutes` | the agent time of one writer task, 1 to 120 | 60 |
| `gatekeepers` | the logins the notices of a gate go to | the project's admins |
| `comments` | the comment service of the drafts: the Firebase `project_id`, its web `api_key` and the `collection` (`marginalia_comments`). These are public values the blog's pages carry, no credential | no comment is read |

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
  "person": "Lumen",
  "reviewers": ["Lumen"],
  "repo": "lumen-blog",
  "daily_usd": 3,
  "comments": {"project_id": "lumen-comments", "api_key": "<the web API key the blog's pages carry>"}
}
```

A value that breaks the schema, or a post or entry that names a stage or notebook the config does not list, is
refused with 422.

## Model

Six tables, made by the plugin's own migration chain (`evo_core_plugins/editorial/tables.py`, `editorial/migrations/`):

| Table | What it holds |
| --- | --- |
| `editorial_posts` | one row for each post of a project, by slug: title, stage, branch, preview and published links, the draft's `comment_id`, publish time, the figures 7 and 28 days after, label, and the writer's latest run: its id, state (`running`, `done`, `failed`, `refused`), stage, error, when, and how many ran since a person's answer |
| `editorial_stage_history` | each stage a post entered, when, and what showed it |
| `editorial_gates` | the gate of a post at each stage the config gives one: kind, state (`waiting`, `answered`, `skipped`), when it opened and was answered, through what (`hub` when unsaid), by whom, the answer, and what the agent asked (`ask`) |
| `editorial_rounds` | the review rounds of a post at a stage, numbered from 1: when, a note, the entries the round wrote, the judge's question, state, note and scores |
| `editorial_comments` | the comments of a round, each once by its id: author, quoted text, text |
| `editorial_feedback` | the notebook: one row for each entry `PH-<n>` of a project, in a notebook of the config, with the person's words, what the agent wrote and what the person changed it to, the rule, its check, the times seen, label, and its probe (id, task, verify) |

A row carries the label of its project's default when it is made, and reads follow it like the rest of the hub: a
caller whose grant or sink is below a row's label does not see it.

Entering a stage that has a gate opens that gate (state `waiting`). A post's `waiting_gate` is its current stage's gate
when that waits, otherwise the first waiting gate in stage order, otherwise none. Migration `editorial_0002` adds the
columns of the flow to the tables of `editorial_0001`.

## The flow

The flow runs once the config names `repo`.

1. **A gate opens.** Entering a stage with a gate (the writer does it through `editorial__state`, with what it asks the
   person in `ask`: the proposals of a choose gate, the questions of an interview) sends the notice `editorial_gate` to
   the gatekeepers, in their Inbox and on each channel of theirs that is on, with the link of the post's page
   (`/p/<project>/x/editorial/posts/<slug>`).
2. **The person answers on the page.** A choose gate takes a proposal or a topic, an interview its answers and the
   approval of the brief, a comments gate "my comments are in" (`{"done": true}`) or the approval of the draft
   (`{"approve": true}`), a publish gate "the post is out" with its link. The answer is kept with `answered_via` hub.
3. **The writer runs.** An answer through the hub (`via` hub, the default when unsaid) hands the agent type `writer`
   a task on the branch `post/<slug>` of `repo`, for `minutes` of agent time: follow the writing skill from the stage the post is at to the next gate, then stop. A post
   has one task at a time: while its run runs, an answer is refused (409) and no other task goes out. At the last
   stage no task goes out. An answer given from inside a session (`via` another value, such as `claude-code`, `codex`
   or `chat`) is kept but hands no task: that session goes on writing itself.
4. **The run ends** (the event `task.result`). At a waiting gate, the post waits for the person. Short of a gate, the
   next task goes out, within the type's daily cap; after 6 runs in a row without a person's answer the post stops in
   the error state. After "my comments are in", the end of the run opens the next review round.
5. **Nothing fails silently.** A failed or cancelled run, or a task the hub refuses (the daily cap, a branch another run
   works on, the type turned off), puts the post in the error state, shown on its page with the reason, and sends the
   notice `editorial_failed` to the gatekeepers. The page's "Hand the next task" (`POST posts/{slug}/run`) tries again.

## The judge

When a post enters a stage with a comments gate, the plugin opens the next review round and asks the agent type
`editor-judge` to score the draft. The judge runs as a question run (`ask_agent_type`), not a task: a question run is
read-only, starts in a fresh context and answers in text, which is what a judge does, where a task would push to a
branch. The question names the draft's preview and its branch, never the writer, and its ref is the round
(`round:<id>`), so a round is asked once.

The judge answers one JSON object with four axes from 0 to 5: `slop` (no filler, no stock phrases), `giong` (the voice
of the blog), `nguon` (every claim and figure has its source) and `hinh` (the images and their captions). The answer
comes back as the event `agent.answer`; the scores go into the round, with the judge's state (`pending`, `passed`,
`below`, `failed`, `refused`). The machine gate of the review stage passes only when every axis is 4 or more: until
then an approval of the draft is refused with 409 and the scores it lacks. An answer that holds no such object passes
nothing.

## Draft comments

Reviewers comment on the draft's preview with Marginalia, which keeps each comment in Firestore under the post's key
`draft:<comment_id>`, with the highlighted sentence, the text, the author and the time. The plugin reads them with
Firestore's REST API (`runQuery`) and the blog's public web API key, with no credential, keeps those of the configured
`reviewers` (by their name in the service) and writes each into the post's latest round once, by its id, with the
highlighted sentence as its quote; a reply is marked `(reply)`. It reads them when the post enters a stage with a
comments gate and when a person presses "Read the comments" (`POST posts/{slug}/comments`, `editorial__comments`),
never on a schedule. A post needs its `comment_id` (set with `set`).

## Probes

An entry of the notebook can carry a curator probe of its rule (admin): a `task` an agent does in `repo` and a `verify`,
one shell line that exits 0 when the agent kept the rule. The plugin renders the notebook's rule file, the skill
`.claude/skills/editorial-<notebook>/SKILL.md`, twice: arm on with every rule of the notebook, arm off without this
entry's rule, and gives both to `add_probe` with the ref `editorial:PH-<n>`. Giving the probe again replaces the active
one; `remove` retires it with `remove_probe`, keeping its weeks in the curator's report. The verify is the answer key:
the entry shows the probe's task, never its verify.

## Roles

| Action | Role |
| --- | --- |
| read posts, the notebook, recall, export | reader |
| set a post, answer a gate, read the draft comments, hand the next task, add an entry, record a repeat | writer |
| import, give or remove a probe | admin |

## Routes

All under `/v1/x/editorial/{project}/`. Each answers JSON; with `?render=text` it answers `{"text": ...}`, what the CLI
prints without `--json`.

| Route | What it does |
| --- | --- |
| `GET posts?stage=` | the posts in stage order: slug, title, stage, waiting_gate, run, gates (stage, kind, state, answered_at, answered_via), rounds (a count), preview_url, url |
| `GET posts/{slug}` | one post with its gates (and their `ask`), rounds with comments and the judge's scores, its run, history and feedback ids |
| `POST posts/{slug}` | set its stage, title, links, `comment_id`, figures, a gate's state (`gate`, `gate_state`, `via`, `answer`) or what is asked at a gate (`ask`); a new slug needs a stage, a post that is there keeps its stage when none is given |
| `POST posts/{slug}/comments` | read the reviewers' draft comments into the latest round (writer); 502 when the service does not answer |
| `POST posts/{slug}/run` | hand the writer the next task now (writer); 409 while a run of the post runs |
| `GET recall?stage=&post=&q=` | what to read before a stage: the entries of the stage's notebooks and those about the post, seen most first |
| `GET feedback?notebook=&post=&stage=&seen=&q=` | the entries, filtered |
| `POST feedback?notebook=&post=` | add an entry (title, said and rule required); answers a list of the one entry, 201 |
| `POST feedback/{entry}/repeat` | the entry came back: its count goes up and the new words join its lines |
| `POST feedback/{entry}/probe` | give the entry its probe (`task`, `verify`) or retire it (`remove`) (admin) |
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
| `editorial__feedback` | `action` `add` an entry or `repeat` one (`entry`, PH-<n>) (writer), or `probe` one with `probe_task` and `probe_verify`, or `remove` (admin) |
| `editorial__comments` | read the reviewers' draft comments of the post `slug` into its latest round (writer) |

## Agent types, events and notices

| Contribution | What it is |
| --- | --- |
| agent type `writer` | follows the writing skill from a post's stage to the next gate, then stops; mentioned by admins; takes `results` |
| agent type `editor-judge` | scores a draft blind on the four axes, changes nothing; mentioned by admins; takes `answers` |
| event `results` | `task.result` of a writer's run: the flow goes on |
| event `answers` | `agent.answer` of the judge: the round's scores |
| notice `editorial_gate` | a post waits for you at a gate |
| notice `editorial_failed` | a post's writer run failed or was refused |

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
