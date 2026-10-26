// The page Feedback notebook of the core plugin editorial, framed by the hub at /p/<project>/x/editorial/feedback:
// the entries of the notebook, filtered by notebook, by the stage that reads them, by post and by how many times they
// were seen. Each entry is a card with the person's words, the rule and how it is checked, so it reads at 375 px.
// Its words are in i18n/<locale>.js.
(function () {
  "use strict";
  var evo = window.evo;
  var page = window.page;
  var el = page.el;
  var t = page.t;

  var root = document.getElementById("page");
  var filters = { notebook: "", stage: "", post: "", seen: "" };
  var loading = 0;

  function query() {
    var parts = Object.keys(filters)
      .filter(function (name) {
        return filters[name];
      })
      .map(function (name) {
        return name + "=" + encodeURIComponent(filters[name]);
      });
    return parts.length ? "?" + parts.join("&") : "";
  }

  function line(label, text) {
    if (!text) return null;
    return el("p", { class: "page-wrap" }, [el("span", { class: "page-strong", text: label + ": " }), text]);
  }

  function card(entry) {
    return el("li", { class: "editorial-card", testid: "editorial-entry" }, [
      el("div", { class: "evo-row evo-row-between" }, [
        el("span", { class: "page-strong page-wrap", text: entry.id + " " + entry.title }),
        page.badge(t("notebook.seen", { count: entry.seen }), entry.seen > 1 ? "warning" : "outline", { testid: "editorial-seen" }),
      ]),
      el("p", { class: "evo-small evo-muted page-wrap", text: [entry.notebook, entry.date, entry.post || ""].filter(Boolean).join(", ") }),
      el(
        "ul",
        { class: "editorial-said" },
        entry.said.map(function (said) {
          return el("li", { class: "page-wrap" }, ['"' + said.text + '"', said.date || said.note ? el("span", { class: "evo-small evo-muted", text: " (" + [said.date, said.note].filter(Boolean).join(", ") + ")" }) : null]);
        }),
      ),
      line(t("notebook.agentWrote"), entry.agent_wrote),
      line(t("notebook.personFixed"), entry.person_fixed),
      line(t("notebook.rule"), entry.rule),
      line(t("notebook.check"), entry.check),
    ]);
  }

  function input(name, label, type) {
    return el("label", { class: "evo-stack-sm" }, [
      el("span", { class: "evo-label", text: label }),
      el("input", {
        class: "evo-input",
        type: type || "text",
        min: type === "number" ? "1" : null,
        value: filters[name],
        testid: "editorial-filter-" + name,
        on: {
          change: function (event) {
            filters[name] = event.target.value.trim();
            load();
          },
        },
      }),
    ]);
  }

  function form() {
    return el("div", { class: "editorial-filters", role: "search" }, [
      input("notebook", t("notebook.filters.notebook")),
      input("stage", t("notebook.filters.stage")),
      input("post", t("notebook.filters.post")),
      input("seen", t("notebook.filters.seen"), "number"),
    ]);
  }

  function render(entries) {
    var body = entries.length
      ? el("ul", { class: "page-list" }, entries.map(card))
      : el("div", { class: "evo-empty", testid: "editorial-empty" }, [el("p", { class: "evo-empty-title", text: t("notebook.emptyTitle") })]);
    return page.section("editorial-entries", t("notebook.entries"), page.badge(String(entries.length), "outline"), body);
  }

  function load() {
    loading += 1;
    var token = loading;
    root.setAttribute("aria-busy", "true");
    root.setAttribute("data-testid", "editorial-feedback-page");
    return page.call("feedback" + query()).then(
      function (entries) {
        if (token !== loading) return;
        page.fill(root, [el("p", { class: "evo-muted", text: t("notebook.sub") }), form(), render(entries)]);
        root.removeAttribute("aria-busy");
      },
      function (error) {
        if (token !== loading) return;
        page.fill(root, [form(), page.failed(error, load)]);
        root.removeAttribute("aria-busy");
      },
    );
  }

  evo.ready.then(function () {
    document.title = t("notebook.title");
    load();
  });
})();
