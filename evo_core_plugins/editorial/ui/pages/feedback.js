// A searchable notebook with stable filters and paginated disclosures, not fifty fully expanded transcripts.
(function () {
  "use strict";
  var evo = window.evo,
    page = window.page,
    el = page.el,
    t = page.t,
    ui = window.editorial;
  var root = document.getElementById("page"),
    loading = 0,
    currentPage = 1,
    size = 10,
    entries = [],
    sort = "id";
  var filters = { q: "", notebook: "", stage: "", post: "", seen: "" },
    controls = {},
    output,
    status,
    expandAll = false,
    pending = false;
  function query() {
    return Object.keys(filters)
      .filter(function (key) {
        return filters[key];
      })
      .map(function (key) {
        return key + "=" + encodeURIComponent(filters[key]);
      })
      .join("&");
  }
  function line(label, value) {
    return value
      ? el("div", { class: "editorial-rule-block" }, [
          el("h3", { text: label }),
          el("p", { class: "page-wrap", text: value }),
        ])
      : null;
  }
  function card(entry) {
    var details = el(
      "details",
      { class: "editorial-entry", open: expandAll, testid: "editorial-entry" },
      [
        el("summary", {}, [
          el("div", { class: "editorial-entry-heading" }, [
            el("span", { class: "editorial-entry-id", text: entry.id }),
            el("span", { class: "editorial-entry-title", text: entry.title }),
            page.badge(
              t("notebook.seen", { count: entry.seen }),
              entry.seen > 1 ? "warning" : "outline",
              { testid: "editorial-seen" },
            ),
          ]),
          el("div", { class: "editorial-entry-meta evo-small evo-muted" }, [
            el("span", { text: ui.label("notebooks", entry.notebook) }),
            el("time", { datetime: entry.date, text: entry.date }),
            entry.post ? el("span", { class: "editorial-slug", text: entry.post }) : null,
          ]),
          el("p", { class: "editorial-rule-preview", text: entry.rule }),
        ]),
        el("div", { class: "editorial-entry-body" }, [
          el("div", { class: "evo-stack" }, [
            line(t("feedbackUi.rule"), entry.rule),
            line(t("feedbackUi.check"), entry.check),
            entry.post
              ? page.link(
                  page.pagePath("editorial", "posts", encodeURIComponent(entry.post)),
                  { class: "page-link" },
                  t("board.open"),
                )
              : null,
          ]),
          el("div", { class: "editorial-evidence evo-stack" }, [
            el("h3", { text: t("feedbackUi.evidence") }),
            entry.said.map(function (said) {
              return el("blockquote", { class: "editorial-quote" }, [
                el("p", { class: "page-wrap", text: said.text }),
                said.date || said.note
                  ? el("footer", {
                      class: "evo-small evo-muted",
                      text: [said.date, said.note].filter(Boolean).join(", "),
                    })
                  : null,
              ]);
            }),
            line(t("notebook.agentWrote"), entry.agent_wrote),
            line(t("feedbackUi.note"), entry.agent_note),
            line(t("notebook.personFixed"), entry.person_fixed),
            line(t("feedbackUi.fixedNote"), entry.fixed_note),
          ]),
        ]),
      ],
    );
    return el("li", {}, details);
  }
  function render() {
    if (pending) return;
    var sorted = entries.slice().sort(function (a, b) {
      if (sort === "recent") return b.date.localeCompare(a.date) || a.id.localeCompare(b.id);
      if (sort === "repeated") return b.seen - a.seen || a.id.localeCompare(b.id);
      return a.id.localeCompare(b.id, undefined, { numeric: true });
    });
    var pages = Math.max(1, Math.ceil(sorted.length / size));
    currentPage = Math.min(currentPage, pages);
    status.textContent = t("feedbackUi.count", { count: sorted.length });
    var list = sorted.length
      ? el(
          "ul",
          { class: "editorial-entry-list" },
          sorted.slice((currentPage - 1) * size, currentPage * size).map(card),
        )
      : el("div", { class: "evo-empty", testid: "editorial-empty" }, [
          el("p", { class: "evo-empty-title", text: t("notebook.emptyTitle") }),
          el("p", { class: "evo-muted", text: t("feedbackUi.emptyText") }),
        ]);
    function move(delta) {
      currentPage += delta;
      render();
      output.querySelector("summary").focus();
    }
    page.fill(output, [
      list,
      pages > 1
        ? el(
            "nav",
            {
              class: "editorial-pagination",
              "aria-label": t("notebook.entries"),
            },
            [
              el("button", {
                type: "button",
                class: "evo-btn",
                disabled: currentPage === 1,
                text: t("workspace.previous"),
                on: {
                  click: function () {
                    move(-1);
                  },
                },
              }),
              el("span", {
                class: "evo-small",
                role: "status",
                text: t("workspace.page", { page: currentPage, pages: pages }),
              }),
              el("button", {
                type: "button",
                class: "evo-btn",
                disabled: currentPage === pages,
                text: t("workspace.next"),
                on: {
                  click: function () {
                    move(1);
                  },
                },
              }),
            ],
          )
        : null,
    ]);
  }
  function load() {
    var token = ++loading;
    pending = true;
    output.setAttribute("aria-busy", "true");
    status.textContent = t("workspace.loading");
    // Do not let stale results look like the newly applied filters while a request is in flight.
    page.fill(output, ui.loading());
    return page.call("feedback" + (query() ? "?" + query() : "")).then(
      function (found) {
        if (token !== loading) return;
        pending = false;
        entries = found;
        currentPage = 1;
        render();
        output.removeAttribute("aria-busy");
      },
      function (error) {
        if (token !== loading) return;
        pending = false;
        status.textContent = "";
        page.fill(output, page.failed(error, load));
        output.removeAttribute("aria-busy");
      },
    );
  }
  function form() {
    function control(name, title, node) {
      controls[name] = node;
      node.value = filters[name];
      return ui.field(title, node);
    }
    return el(
      "form",
      {
        class: "editorial-feedback-filters",
        role: "search",
        on: {
          submit: function (event) {
            event.preventDefault();
            Object.keys(controls).forEach(function (key) {
              filters[key] = controls[key].value.trim();
            });
            load();
          },
        },
      },
      [
        control(
          "q",
          t("feedbackUi.search"),
          el("input", {
            type: "search",
            class: "evo-input",
            placeholder: t("feedbackUi.placeholder"),
            maxlength: 200,
            testid: "editorial-filter-q",
          }),
        ),
        control(
          "notebook",
          t("notebook.filters.notebook"),
          ui.select(ui.data().notebooks, t("workspace.allNotebooks"), filters.notebook, {
            testid: "editorial-filter-notebook",
          }),
        ),
        control(
          "stage",
          t("notebook.filters.stage"),
          ui.select(ui.data().stages, t("workspace.allStages"), filters.stage, {
            testid: "editorial-filter-stage",
          }),
        ),
        control(
          "post",
          t("notebook.filters.post"),
          el("input", {
            class: "evo-input",
            placeholder: t("feedbackUi.postPlaceholder"),
            testid: "editorial-filter-post",
          }),
        ),
        control(
          "seen",
          t("notebook.filters.seen"),
          ui.select(
            [
              { name: "2", title: t("feedbackUi.twice") },
              { name: "3", title: t("feedbackUi.three") },
              { name: "5", title: t("feedbackUi.five") },
            ],
            t("feedbackUi.allSeen"),
            filters.seen,
            { testid: "editorial-filter-seen" },
          ),
        ),
        el("div", { class: "editorial-filter-actions" }, [
          el("button", {
            type: "submit",
            class: "evo-btn evo-btn-primary",
            text: t("workspace.apply"),
          }),
          el("button", {
            type: "button",
            class: "evo-btn",
            text: t("workspace.clear"),
            on: {
              click: function () {
                Object.keys(filters).forEach(function (key) {
                  filters[key] = "";
                  controls[key].value = "";
                });
                load();
              },
            },
          }),
        ]),
      ],
    );
  }
  function mount() {
    var query = (evo.context.location && evo.context.location.query) || {};
    Object.keys(filters).forEach(function (key) {
      filters[key] = typeof query[key] === "string" ? query[key] : "";
    });
    output = el("div", { testid: "editorial-entries" });
    status = el("p", { class: "evo-small evo-muted", role: "status" });
    var sortBox = ui.select(
      [
        { name: "recent", title: t("feedbackUi.recent") },
        { name: "repeated", title: t("feedbackUi.repeated") },
      ],
      t("feedbackUi.id"),
      "",
      {
        on: {
          change: function (event) {
            sort = event.target.value || "id";
            currentPage = 1;
            render();
          },
        },
      },
    );
    var expand = el("button", {
      type: "button",
      class: "evo-btn",
      text: t("feedbackUi.expand"),
      on: {
        click: function () {
          expandAll = !expandAll;
          expand.textContent = t(expandAll ? "feedbackUi.collapse" : "feedbackUi.expand");
          output.querySelectorAll("details").forEach(function (node) {
            node.open = expandAll;
          });
        },
      },
    });
    page.fill(root, [
      ui.intro("feedback", t("notebook.sub"), load),
      form(),
      el("div", { class: "editorial-results-head" }, [
        status,
        ui.field(t("feedbackUi.sort"), sortBox),
        expand,
      ]),
      output,
    ]);
    root.setAttribute("data-testid", "editorial-feedback-page");
    root.removeAttribute("aria-busy");
    load();
  }
  evo.ready
    .then(function () {
      document.title = t("notebook.title");
      page.fill(root, ui.loading());
      return ui.ready();
    })
    .then(function () {
      mount();
      evo.on("location", mount);
    });
})();
