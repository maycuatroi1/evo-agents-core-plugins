# The core plugin okr: a project's strategy as a tree, tied to what the hub delivers

The plugin **okr** keeps, for a project that enabled it, the project's strategy as a tree: business lines, the
objectives under them, the key results that tell whether an objective is reached, and the deliverables that carry each
key result. A deliverable links to the hub's tasks, use cases and plans; a key result links to the goal of the project
that measures it, the Loop's goal with its metric and target. From those links the plugin computes, on every read, how
far each deliverable, key result, objective and business line has come, and what the tree lacks. Its code is
`evo_core_plugins/okr`; evo-agents-core-plugins ships it as a core plugin, which the hub's image pins (evo-agents'
`docs/plugins.md`, Core plugins). It asks for API 1.5 of `core_plugin_api` and does nothing in a project until an admin
of the project enables it there; until then it writes no row and its routes answer 404.

The plugin keeps the tree and the links in its own tables. It reads the hub's tasks, SRS items, plans, goals and signals
through the core plugin API and writes nothing of theirs. It runs no job and contributes no agent type.

## Enabling it

```sh
evo-agents hub plugin enable okr --project northwind      # asks for no permission and takes no config
```

The roll-up reads what the project has: the tasks of the feature tasks (their statuses and prefix from its config), the
use cases of the feature srs, the plans and the goals. A project without one of them simply has nothing of it to link.

## Model

Three tables, made by the plugin's own migration chain (`evo_core_plugins/okr/tables.py`, `okr/migrations/`, first
revision `okr_0001`, version table `alembic_version_okr`):

| Table | What it holds |
| --- | --- |
| `okr_items` | one row for each item of a project's tree: `kind`, its `number` within the project and the kind (which makes its code), `ref`, `title`, `body_md`, `status`, `owner`, `period`, `due`, `baseline`, `target`, `source`, `source_url`, `source_rev`, who made and last changed it and when |
| `okr_parents` | one row for each child and parent |
| `okr_links` | one row for each item, kind and target: `target_kind`, `target`, who made it and when |

| Field | What it holds |
| --- | --- |
| `kind` | `business_line`, `objective`, `key_result` or `deliverable` |
| code | `BL-<n>`, `O-<n>`, `KR-<n>`, `D-<n>`: the next number of its kind in the project, never given again |
| `ref` | the id a source outside the hub gave the item, unique in the project when set: letters, digits and `.`, `_`, `:`, `-`, at most 200, no slash or space |
| `status` | `draft`, `active` (the default), `done`, `dropped` or `archived` |
| `owner` | a login |
| `period` | free text, such as `2026-Q4` |
| `due` | a date |
| `baseline`, `target` | a key result's start and aim, as text |
| `source`, `source_url`, `source_rev` | the import that writes the item, and that source's link and revision of it |

An item is never deleted: drop it, or let its source archive it. An item carries no label of its own: every member with
a grant on the project reads the whole tree. What the tree shows of the hub's items follows their labels (Links).

### The shape of the tree

| Kind | Under |
| --- | --- |
| business line | nothing |
| objective | at most one business line |
| key result | exactly one objective |
| deliverable | one key result or more |

Any other shape is refused with 422, naming the rule it breaks; so is a change of parents that would close a cycle. A
kind sits under the kind above it only, so the shape alone keeps the tree free of cycles; the plugin checks anyway. A
deliverable under two key results counts once for each of them, and once for the objective and line above both.

## Links

| Item | Links to | Target |
| --- | --- | --- |
| deliverable | `task` | the task's code, `T-12`, with the prefix the feature tasks has in the project (`12` alone is taken too) |
| deliverable | `use_case` | `<document slug>:<code>` of a use case of the feature srs, such as `demo-shop:UC ORD-1` |
| deliverable | `plan` | the plan's slug, such as `rollout` |
| key result | `goal` | the goal's code, `G-3`, or its alias |

A link is checked as it is made: a target the project does not hold is refused with 404, a kind the item does not take
with 422, a second goal on a key result with 409 (a key result is measured by one goal). The target is kept in the form
above, so the same target written twice is linked once, and linking it again answers 200 with `made` false.

**The use case's target.** A use case is kept as `<document slug>:<code>`, its code as the document shows it with each
run of whitespace as one space. The slug comes first because a code is shown inside its document, and the hub's own key
of a use case's frame task reads the same way (`srs:<slug>:<version>:<code>`). Written alone, a code is looked up in
every document of the project, compared as the feature srs compares codes (whitespace runs as one space, any case),
which finds one item since srs keeps a code unique in a project; the link then holds the slug too. An SRS item of
another kind, such as a requirement, is refused with 422.

What the hub holds of a target is read again on every read. A task, a plan, a use case's document and a signal carry a
label, and the caller sees them through the sink `X-Evo-Sink` names, else the project's hub sink: a target the caller may
not read shows its code and `visible` false, without its title or status, and still counts in the figures. A link
whose target the hub no longer holds shows `gone` true.

## Roll-up

Computed on read; it writes nothing. Dropped and archived items count for nothing, nor do the items below them unless
an open item also holds them.

| Item | How far it has come |
| --- | --- |
| deliverable | the mean of what each of its links has done: a task 1 when its status is in the group `done` and 0 otherwise, a cancelled one nothing; a use case the share of done tasks among the tasks that link it (cancelled ones left out), 0 with none, a retired one nothing; a plan its steps `done` over its steps that are not `descoped`. With nothing to count, a deliverable whose status is `done` is 1 and any other has no progress (`null`) |
| key result | the mean of its deliverables', and its goal's state |
| objective, business line | the mean over the distinct deliverables below it, with the key results met among those below |

Each item's roll-up also counts the distinct tasks its deliverables link (cancelled ones left out): done, late (due
before today, UTC, and not done or cancelled) and blocked (not done, with an open blocker or an open decision of one of
its runs).

A use case's state: `retired` once a version of its document that drops it was approved, `approved` once a version that
holds it was approved (or approved and then superseded), `in_review` while one is in review, `draft` otherwise.

**A goal's state** comes from `read_goals`, which gives each goal at its current revision with its `metric` (`key`,
`aggregate`, `window_days`, `comparator`, `target`, `tenant`), its `metric_text` and its own `status`, and from
`read_signals`, which gives the values of the metric's key newest first, each with its tenant and label. The state
compares the newest value the caller may read (of the metric's tenant when it names one) with the target:

| State | When |
| --- | --- |
| `met` | the comparator holds for the value and the target |
| `not_met` | it does not |
| `no_signal` | the key has no value yet that the caller may read |
| `no_metric` | the goal has no metric, or one whose comparator or target cannot compare |

It is the newest value, not the metric's aggregate over its window as the Loop measures it: a goal whose metric sums
up a window, such as `p50 over 30 days`, may read differently here than on the Loop's page. The roll-up shows the value
and when it was measured beside the state.

### Gaps

| Gap | When |
| --- | --- |
| `no_link` | an active deliverable links nothing |
| `no_goal` | an active key result links no goal |
| `no_kr` | an objective in draft or active has no open key result |
| `late` | an open item's `due` is before today and its status is not done |
| `gone` | an open item links a target the hub no longer holds |

## Roles

| Action | Role |
| --- | --- |
| read the tree and an item | reader (a grant on the project) |
| add, change, link, unlink, import | writer |

## Routes

All under `/v1/x/okr/{project}/`. Each answers JSON; with `?render=text` it answers `{"text": ...}`, what the CLI prints
without `--json`. An item is named by its code (in any case) or its ref; a code wins over a ref that looks like one.

| Route | What it does |
| --- | --- |
| `GET tree?status=&line=` | the tree from its roots (the business lines, then the objectives without one), each node with its roll-up, links and children, the count of each kind shown, and the gaps. Without `status`, every item but the archived ones; with it, the items of that status and those above them. `line` shows one business line, by code or ref (422 for an item of another kind). The roll-up counts the whole tree whatever the filters show |
| `GET items/{item}` | one item with its parents, children, links, roll-up and gaps |
| `POST items` | a new item: `kind`, `title`, `parents` (codes or refs), and any of `ref`, `body_md`, `status`, `owner`, `period`, `due`, `baseline`, `target`; 201 |
| `PATCH items/{item}` | change the fields given; `null` or an empty string clears `ref`, `body_md`, `owner`, `period`, `due`, `baseline` or `target`; `parents` replaces the parents. 409 for an item a source writes |
| `POST items/{item}/links` | `{"kind": ..., "target": ...}`: 201 with `made` true, 200 with `made` false when it was linked |
| `DELETE items/{item}/links/{link_id}` | take the link off; the answer holds the link as it was. Links of an item a source writes stay editable |
| `POST import` | a source's bundle (The import bundle) |

## Command line

Every command takes `--project` and `--json`.

```sh
evo-agents hub okr tree --project northwind [--status active] [--line BL-1]
evo-agents hub okr show KR-1 --project northwind
evo-agents hub okr add business_line --title "Northwind wholesale" --project northwind
evo-agents hub okr add objective --title "Win ten stores" --parent BL-1 --period 2026-Q4 --project northwind
evo-agents hub okr add key_result --title "Ten stores order weekly" --parent O-1 --baseline 2 --target 10 \
  --project northwind
evo-agents hub okr add deliverable --title "Store portal" --parent KR-1 --parent KR-2 --project northwind
evo-agents hub okr set KR-1 --owner lumen --due 2026-12-31 --project northwind
evo-agents hub okr set KR-1 --due "" --project northwind        # an empty value clears a field
evo-agents hub okr link D-1 task T-12 --project northwind
evo-agents hub okr link D-1 use_case "demo-shop:UC ORD-1" --project northwind
evo-agents hub okr link D-1 plan rollout --project northwind
evo-agents hub okr link KR-1 goal G-3 --project northwind
evo-agents hub okr unlink D-1 7 --project northwind              # the link's id, as show lists it
evo-agents hub okr import --file okr.json [--dry-run] [--prune] --project northwind
```

## Tools

| MCP tool | What it does |
| --- | --- |
| `okr__tree` | what `GET tree` answers, by `status` and `line` |
| `okr__item` | what `GET items/{item}` answers, for `item` |
| `okr__link` | link `item` to `target` of `kind` (writer) |
| `okr__unlink` | take the link `link` (its id) off `item` (writer) |

A tool acts for the member at the origin of the call, with that member's role and sink; it answers JSON text, and a
refusal answers `refused: ...` as an error.

## Page

The page **OKR** (`/p/<project>/x/okr/tree`) shows the tree with nodes that open and close, each with a progress bar and
its figure, a key result's goal state, the tasks done, late and blocked, and a deliverable's links; then the gaps. It
filters by business line and by status, in English and Vietnamese, and reads the plugin's own route through the bridge
evo-plugin/1.

## The import bundle

A source outside the hub, such as a planning sheet, writes its part of the tree with one bundle:

```json
{
  "source": "northwind-sheet",
  "dry_run": false,
  "prune": false,
  "items": [
    {"ref": "nw-line", "kind": "business_line", "title": "Northwind wholesale"},
    {"ref": "nw-o1", "kind": "objective", "title": "Win ten stores", "body_md": "Stores outside the city first.",
     "status": "active", "owner": "lumen", "period": "2026-Q4", "due": "2026-12-31", "parents": ["nw-line"],
     "source_url": "https://sheets.example.org/northwind#o1", "source_rev": "r12"},
    {"ref": "nw-kr1", "kind": "key_result", "title": "Ten stores order weekly", "baseline": "2", "target": "10",
     "parents": ["nw-o1"]},
    {"ref": "nw-d1", "kind": "deliverable", "title": "Store portal", "parents": ["nw-kr1"]}
  ],
  "links": [
    {"item": "nw-d1", "kind": "task", "target": "T-74"},
    {"item": "nw-kr1", "kind": "goal", "target": "G-3"}
  ]
}
```

- **Items are upserted by `ref`** within the project. An item the bundle names is the whole of it: a field left out is
  empty, and `status` is `active` when left out. A ref the project holds keeps its code; a new one takes the next code
  of its kind. An item made by hand with that ref is taken over by the source. A ref that another source writes, or
  that names an item of another kind, refuses the bundle.
- **Parents** are refs of items in the same bundle or of items the project holds (a code of an item the project holds
  is taken too). Every item is checked against the shape of the tree before anything is written.
- **Links are added, never removed.** A link the item has already is left alone (`exists`); a target the project does
  not hold is reported (`not_found`) and so is a link the item does not take (`refused`), and the rest of the bundle
  goes on. A key result keeps one goal.
- **`missing`** lists the items of that source the bundle no longer names (not yet archived); with `prune` they go to
  `archived`, never deleted, and their links stay.
- **`dry_run`** writes nothing and answers the same report.
- **A bundle with a problem** (two items of one ref, a parent not found, a shape the tree does not take, a ref of
  another source or kind, no `source`) is refused with 422 naming each problem, and nothing is written.

The answer:

| Key | What it holds |
| --- | --- |
| `source`, `dry_run`, `prune` | as the bundle had them |
| `created`, `updated`, `unchanged` | the items of the bundle, each `{ref, code, kind, fields}`; `fields` names what an update changed (`title`, `parents`, `source_rev`, ...) |
| `missing` | the source's items the bundle no longer names, each `{ref, code, kind, archived}` |
| `links` | each link of the bundle, `{item, kind, target, result, detail, id}`: `result` is `added`, `exists`, `not_found` or `refused`, `target` as the link holds it once found |

**Fields a source owns.** An item with a `source` refuses `PATCH` of any field (409, naming the source): its title,
text, status, owner, period, due date, baseline, target, ref and parents change through the next import. Its links stay
editable on the hub. The route also takes the bundle as the text of a JSON file in `file` (what `import --file` sends),
with `dry_run` and `prune` beside it.

An import that writes is audited as `okr.import`, with the source and the counts.
