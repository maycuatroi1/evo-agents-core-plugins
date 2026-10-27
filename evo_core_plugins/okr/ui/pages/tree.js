// The page OKR of the core plugin okr, framed by the hub at /p/<project>/x/okr/tree: the project's business lines,
// objectives, key results and deliverables as a tree whose nodes open and close, each with how far it has come, a
// key result's goal and the links of a deliverable, then what the tree lacks. Filters show one business line or one
// status; the roll-up always counts the whole tree. Its words are in i18n/<locale>.js.
(function () {
  "use strict";
  var evo = window.evo;
  var page = window.page;
  var el = page.el;
  var t = page.t;

  /** The kinds from the top of the tree down, and the statuses of an item (evo_core_plugins.okr.tables). */
  var KINDS = ["business_line", "objective", "key_result", "deliverable"];
  var STATUSES = ["draft", "active", "done", "dropped", "archived"];
  var LINKS = ["task", "use_case", "plan", "goal"];
  var GAPS = ["no_link", "no_goal", "no_kr", "late", "gone"];
  /** The badge of each status and goal state; its word is always written beside the colour. */
  var STATUS_VARIANT = { draft: "outline", active: "info", done: "success", dropped: "outline", archived: "outline" };
  var GOAL_VARIANT = { met: "success", not_met: "danger", no_signal: "warning", no_metric: "outline" };
  var GAP_VARIANT = { no_link: "warning", no_goal: "warning", no_kr: "warning", late: "danger", gone: "danger" };

  var root = document.getElementById("page");
  var filters = { line: "", status: "" };
  var lines = [];
  var loading = 0;
  var meters = 0;

  function word(group, key, known) {
    return known.indexOf(key) >= 0 ? t(group + "." + key) : key;
  }

  function statusBadge(status) {
    return page.badge(word("statuses", status, STATUSES), STATUS_VARIANT[status] || "outline", { testid: "okr-status" });
  }

  function percent(progress) {
    return progress === null || progress === undefined ? null : Math.round(progress * 100);
  }

  /** How far an item has come: a meter with its figure written beside it, or a dash when nothing below counts. */
  function meter(rollup, code) {
    var shown = percent(rollup.progress);
    if (shown === null) {
      return el("div", { class: "okr-progress" }, el("span", { class: "evo-small evo-muted", testid: "okr-progress", text: t("noProgress") }));
    }
    meters += 1;
    var id = "okr-progress-" + meters;
    var tone = shown >= 100 ? "normal" : rollup.tasks_late ? "warning" : "normal";
    return el("div", { class: "okr-progress" }, [
      el("span", { id: id, class: "evo-small page-num", testid: "okr-progress", text: t("progress", { percent: shown }) }),
      el(
        "div",
        { class: "page-meter page-meter-" + tone, role: "progressbar", "aria-valuemin": "0", "aria-valuemax": "100", "aria-valuenow": String(shown), "aria-label": t("progressOf", { code: code }), "aria-describedby": id },
        el("span", { style: "width: " + Math.min(Math.max(shown, 0), 100) + "%" }),
      ),
    ]);
  }

  function goalBadge(goal) {
    if (!goal) return page.badge(t("goal.none"), "outline", { testid: "okr-goal" });
    var said = t("goal." + goal.state, { code: goal.code });
    if (goal.value !== null && goal.value !== undefined) said += " (" + page.number(goal.value) + ")";
    return page.badge(said, GOAL_VARIANT[goal.state] || "outline", { testid: "okr-goal", title: goal.metric });
  }

  /** The figures on a node's line: key results met, the goal, tasks done, late and blocked. */
  function facts(node) {
    var rollup = node.rollup;
    var found = [];
    if ((node.kind === "business_line" || node.kind === "objective") && rollup.krs_total) {
      found.push(el("span", { class: "evo-small evo-muted", text: t("krsMet", { met: rollup.krs_met, total: rollup.krs_total }) }));
    }
    if (node.kind === "key_result") found.push(goalBadge(rollup.goal));
    if (rollup.tasks_total) found.push(el("span", { class: "evo-small evo-muted", text: t("tasksDone", { done: rollup.tasks_done, total: rollup.tasks_total }) }));
    if (rollup.tasks_late) found.push(page.badge(t("tasksLate", { count: rollup.tasks_late }), "danger"));
    if (rollup.tasks_blocked) found.push(page.badge(t("tasksBlocked", { count: rollup.tasks_blocked }), "warning"));
    if (node.owner) found.push(el("span", { class: "evo-small evo-muted", text: t("owner", { login: node.owner }) }));
    if (node.due) found.push(el("span", { class: "evo-small evo-muted", text: t("due", { day: page.day(node.due) }) }));
    return found.length ? el("div", { class: "okr-facts" }, found) : null;
  }

  function linkState(link) {
    if (link.gone) return page.badge(t("link.gone"), "danger");
    var parts = [];
    if (link.status) parts.push(link.kind === "goal" ? t("goal." + link.status, { code: link.target }) : link.status);
    if (link.total && link.kind !== "task") parts.push(t("link.done", { done: link.done, total: link.total }));
    var found = [el("span", { class: "evo-small evo-muted", text: parts.join(", ") })];
    if (link.late) found.push(page.badge(t("link.late"), "danger"));
    if (link.blocked) found.push(page.badge(t("link.blocked"), "warning"));
    return found;
  }

  function linkList(node) {
    if (!node.links.length) return null;
    return el(
      "ul",
      { class: "page-list okr-links", "aria-label": t("linksOf", { code: node.code }) },
      node.links.map(function (link) {
        var title = link.title || (link.visible ? "" : t("link.hidden"));
        return el("li", { testid: "okr-link" }, el("div", { class: "page-line" }, [
          el("span", { class: "evo-small page-strong", text: word("links", link.kind, LINKS) }),
          el("span", { class: "evo-mono evo-small", text: link.target }),
          title ? el("span", { class: "evo-small page-wrap", text: title }) : null,
          el("span", { class: "page-end okr-facts" }, linkState(link)),
        ]));
      }),
    );
  }

  function nodeItem(node) {
    var leaf = !node.children.length && !node.links.length;
    var head = el("span", { class: "okr-head" }, [
      el("span", { class: "evo-mono evo-small", text: node.code }),
      el("span", { class: "okr-title", text: node.title }),
      statusBadge(node.status),
      el("span", { class: "evo-small evo-muted", text: word("kinds", node.kind, KINDS) }),
    ]);
    var summary = el("summary", { testid: "okr-node-summary" }, [el("span", { class: "evo-stack-sm" }, [head, facts(node)]), meter(node.rollup, node.code)]);
    var body = el("div", { class: "okr-body" }, [
      node.target || node.baseline
        ? el("p", { class: "evo-small evo-muted", text: t("target", { baseline: node.baseline || "-", target: node.target || "-" }) })
        : null,
      linkList(node),
    ]);
    var children = node.children.length ? el("ul", { "aria-label": t("childrenOf", { code: node.code }) }, node.children.map(nodeItem)) : null;
    var details = el("details", { open: node.kind !== "deliverable" }, [summary, body, children]);
    return el("li", { class: "okr-node" + (leaf ? " okr-leaf" : ""), "data-code": node.code, testid: "okr-node" }, details);
  }

  function gapList(gaps) {
    if (!gaps.length) return el("p", { class: "evo-small evo-muted", testid: "okr-no-gaps", text: t("gaps.none") });
    return el(
      "ul",
      { class: "page-list", testid: "okr-gaps" },
      gaps.map(function (gap) {
        return el("li", { testid: "okr-gap" }, el("div", { class: "page-line" }, [
          page.badge(word("gaps", gap.kind, GAPS), GAP_VARIANT[gap.kind] || "outline"),
          el("span", { class: "evo-mono evo-small", text: gap.item }),
          el("span", { class: "evo-small page-wrap", text: gap.title }),
          el("span", { class: "evo-small evo-muted page-end", text: gap.detail }),
        ]));
      }),
    );
  }

  function select(id, label, options, value, onChange) {
    var input = el(
      "select",
      { id: id, class: "evo-input", testid: id, on: { change: function (event) { onChange(event.target.value); } } },
      options.map(function (option) {
        return el("option", { value: option.value, selected: option.value === value, text: option.label });
      }),
    );
    return el("label", { for: id }, [el("span", { class: "evo-label", text: label }), input]);
  }

  function toggleAll(open) {
    root.querySelectorAll(".okr-tree details").forEach(function (node) {
      node.open = open;
    });
  }

  function filterBar() {
    var lineOptions = [{ value: "", label: t("filters.allLines") }].concat(
      lines.map(function (line) {
        return { value: line.code, label: line.code + " " + line.title };
      }),
    );
    var statusOptions = [{ value: "", label: t("filters.notArchived") }].concat(
      STATUSES.map(function (status) {
        return { value: status, label: t("statuses." + status) };
      }),
    );
    return el("div", { class: "okr-filters", role: "group", "aria-label": t("filters.label") }, [
      select("okr-line", t("filters.line"), lineOptions, filters.line, function (value) {
        filters.line = value;
        load();
      }),
      select("okr-status", t("filters.status"), statusOptions, filters.status, function (value) {
        filters.status = value;
        load();
      }),
      el("div", { class: "evo-row" }, [
        el("button", { type: "button", class: "evo-btn evo-btn-ghost", testid: "okr-open-all", text: t("openAll"), on: { click: function () { toggleAll(true); } } }),
        el("button", { type: "button", class: "evo-btn evo-btn-ghost", testid: "okr-close-all", text: t("closeAll"), on: { click: function () { toggleAll(false); } } }),
      ]),
    ]);
  }

  function counts(data) {
    return el(
      "p",
      { class: "evo-small evo-muted", testid: "okr-counts" },
      KINDS.map(function (kind) {
        return t("counts." + kind, { count: data.counts[kind] || 0 });
      }).join(", "),
    );
  }

  function show(data) {
    if (!filters.line) {
      lines = data.roots.filter(function (node) {
        return node.kind === "business_line";
      });
    }
    var body;
    if (!data.roots.length) {
      body = el("div", { class: "evo-empty", testid: "okr-empty" }, [
        el("p", { class: "evo-empty-title", text: filters.line || filters.status ? t("emptyFiltered") : t("emptyTitle") }),
        el("p", { class: "evo-muted", text: t("emptyText") }),
      ]);
    } else {
      body = el("ul", { class: "okr-tree", "aria-label": t("treeLabel"), testid: "okr-tree" }, data.roots.map(nodeItem));
    }
    return [
      filterBar(),
      counts(data),
      page.section("okr-tree-section", t("treeLabel"), null, body),
      page.section("okr-gaps-section", t("gaps.title"), el("span", { class: "page-count", text: String(data.gaps.length) }), gapList(data.gaps)),
    ];
  }

  function load() {
    loading += 1;
    var token = loading;
    var body = el("div", { class: "evo-stack" });
    page.fill(root, [el("p", { class: "evo-muted", text: t("sub") }), body]);
    root.setAttribute("data-testid", "okr-tree-page");
    root.setAttribute("aria-busy", "true");
    var query = {};
    if (filters.line) query.line = filters.line;
    if (filters.status) query.status = filters.status;
    return page.call("tree", { query: query }).then(
      function (data) {
        if (token !== loading) return;
        page.fill(body, show(data));
        root.removeAttribute("aria-busy");
      },
      function (error) {
        if (token !== loading) return;
        page.fill(body, page.failed(error, load));
        root.removeAttribute("aria-busy");
      },
    );
  }

  evo.ready.then(function () {
    document.title = t("title");
    load();
  });
})();
