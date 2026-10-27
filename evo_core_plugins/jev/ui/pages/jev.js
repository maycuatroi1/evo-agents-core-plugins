// The page Jev of the core plugin jev, framed by the hub at /p/<project>/x/jev/jev: whether Jev is set up in the
// project and what stops it, what it cost against the daily budget in the last 24 hours and 7 days, what each feature
// is set to, and the acts it made with the hub's command that undoes the applied ones. Its words are in i18n/<locale>.js.
(function () {
  "use strict";
  var evo = window.evo;
  var page = window.page;
  var el = page.el;
  var t = page.t;

  var root = document.getElementById("page");
  var MODE_VARIANT = { off: "outline", suggest: "info", apply: "success", on: "success" };

  function figure(label, value, testid) {
    return el("div", null, [el("dt", { class: "evo-small", text: label }), el("dd", { testid: testid, text: value })]);
  }

  function statusSection(status) {
    var ready = !status.problems.length;
    var head = page.badge(ready ? t("status.ready") : t("status.notReady"), ready ? "success" : "warning", { testid: "jev-ready" });
    var body = [
      el("dl", { class: "jev-figures" }, [
        figure(t("status.model"), status.model || t("status.none"), "jev-model"),
        figure(t("status.key"), status.key_set ? t("status.set") : t("status.notSet"), "jev-key"),
        figure(t("status.sink"), status.sink_declared ? t("status.declared") : t("status.notDeclared"), "jev-sink"),
        figure(t("status.price"), t("status.perMillion", { price: status.price_usd_per_million_tokens }), "jev-price"),
      ]),
    ];
    if (!ready) {
      body.unshift(
        page.banner(
          t("status.problems"),
          null,
          { testid: "jev-problems" },
          null,
        ),
      );
      body.push(
        el(
          "ul",
          { class: "page-list", "aria-label": t("status.problems") },
          status.problems.map(function (problem) {
            return el("li", { testid: "jev-problem" }, el("span", { class: "evo-small page-wrap", text: problem }));
          }),
        ),
      );
    }
    return page.section("jev-status", t("status.title"), head, el("div", { class: "evo-stack" }, body));
  }

  function budget(usage) {
    var limit = usage.daily_usd;
    var spent = usage.spent_today_usd;
    var share = limit > 0 ? Math.min(Math.max(spent / limit, 0), 1) : spent > 0 ? 1 : 0;
    var shown = Math.round(share * 100);
    var tone = share >= 1 ? "danger" : share >= 0.8 ? "warning" : "normal";
    return el("div", { class: "jev-budget" }, [
      el("span", { id: "jev-budget-text", class: "evo-small page-num", testid: "jev-budget", text: t("cost.budget", { spent: page.money(spent), limit: page.money(limit) }) }),
      el(
        "div",
        { class: "page-meter page-meter-" + tone, role: "progressbar", "aria-valuemin": "0", "aria-valuemax": "100", "aria-valuenow": String(shown), "aria-label": t("cost.budgetLabel"), "aria-describedby": "jev-budget-text" },
        el("span", { style: "width: " + shown + "%" }),
      ),
    ]);
  }

  function windowFigures(window, label, testid) {
    return figure(label, t("cost.window", { cost: page.money(window.cost_usd), calls: window.calls }), testid);
  }

  function costSection(usage) {
    var body = el("div", { class: "evo-stack" }, [
      el("dl", { class: "jev-figures" }, [
        windowFigures(usage.last_24h, t("cost.day"), "jev-cost-24h"),
        windowFigures(usage.last_7d, t("cost.week"), "jev-cost-7d"),
        figure(t("cost.tokens"), page.number(usage.last_7d.input_tokens), "jev-tokens-7d"),
        figure(t("cost.failed"), page.number(usage.last_7d.failed), "jev-failed-7d"),
      ]),
      budget(usage),
    ]);
    return page.section("jev-cost", t("cost.title"), null, body);
  }

  function featureSection(status) {
    var rows = status.features.map(function (feature) {
      var line = [
        el("span", { class: "evo-small page-strong", text: t("features." + feature.name) }),
        page.badge(t("modes." + feature.mode), MODE_VARIANT[feature.mode] || "outline", { testid: "jev-mode" }),
      ];
      if (feature.threshold !== null && feature.threshold !== undefined) line.push(el("span", { class: "evo-small evo-muted", text: t("features.threshold", { value: feature.threshold }) }));
      if (feature.cap !== null && feature.cap !== undefined) line.push(el("span", { class: "evo-small evo-muted", text: t("features.cap", { done: feature.applied_today || 0, cap: feature.cap }) }));
      return el("li", { testid: "jev-feature" }, el("div", { class: "page-line" }, line));
    });
    return page.section("jev-features", t("features.title"), null, el("ul", { class: "page-list", "aria-label": t("features.title") }, rows));
  }

  function actState(act) {
    if (act.undone) return page.badge(t("acts.undone"), "outline", { testid: "jev-act-state" });
    return act.applied ? page.badge(t("acts.applied"), "success", { testid: "jev-act-state" }) : page.badge(t("acts.suggested"), "info", { testid: "jev-act-state" });
  }

  function actItem(act) {
    var line = [
      el("span", { class: "evo-small page-strong", text: act.feature }),
      el("span", { class: "evo-mono evo-small page-wrap", text: act.target }),
      el("span", { class: "evo-small page-wrap", text: act.outcome }),
    ];
    if (act.confidence !== null && act.confidence !== undefined) line.push(el("span", { class: "evo-small evo-muted", text: t("acts.confidence", { value: page.number(act.confidence, { maximumFractionDigits: 2 }) }) }));
    line.push(actState(act));
    line.push(el("span", { class: "evo-small evo-muted page-end" }, page.when(act.created_at)));
    return el("li", { testid: "jev-act", "data-act": act.id }, [
      el("div", { class: "page-line" }, line),
      act.undo
        ? el("div", { class: "evo-stack-sm" }, [
            el("span", { class: "evo-small evo-muted", text: t("acts.undoWith") }),
            el("code", { class: "evo-mono evo-small jev-undo", testid: "jev-undo", text: act.undo.command }),
            el("span", { class: "evo-small evo-muted evo-mono page-wrap", text: act.undo.method + " " + act.undo.path }),
          ])
        : null,
    ]);
  }

  function actSection(found) {
    var body = found.acts.length
      ? el("ul", { class: "page-list", "aria-label": t("acts.title"), testid: "jev-acts" }, found.acts.map(actItem))
      : el("div", { class: "evo-empty", testid: "jev-no-acts" }, [el("p", { class: "evo-empty-title", text: t("acts.emptyTitle") }), el("p", { class: "evo-muted", text: t("acts.emptyText") })]);
    return page.section("jev-acts-section", t("acts.title"), el("span", { class: "page-count", text: String(found.acts.length) }), body);
  }

  function matchItem(match) {
    var line = [
      el("span", { class: "evo-mono evo-small page-wrap", text: match.evidence }),
      el("span", { class: "evo-mono evo-small page-wrap", text: match.candidate }),
      el("span", { class: "evo-small evo-muted", text: t("matches.confidence", { value: page.number(match.confidence, { maximumFractionDigits: 2 }) }) }),
      page.badge(match.state === "match" ? t("matches.match") : t("matches.suggestion"), match.state === "match" ? "success" : "info", { testid: "jev-match-state" }),
      el("span", { class: "evo-small evo-muted page-end" }, page.when(match.created_at)),
    ];
    return el("li", { testid: "jev-match", "data-match": match.id }, el("div", { class: "page-line" }, line));
  }

  function matchSection(found) {
    var body = found.matches.length
      ? el("ul", { class: "page-list", "aria-label": t("matches.title"), testid: "jev-matches" }, found.matches.map(matchItem))
      : el("div", { class: "evo-empty", testid: "jev-no-matches" }, [el("p", { class: "evo-empty-title", text: t("matches.emptyTitle") }), el("p", { class: "evo-muted", text: t("matches.emptyText") })]);
    return page.section("jev-matches-section", t("matches.title"), el("span", { class: "page-count", text: String(found.matches.length) }), body);
  }

  function load() {
    page.fill(root, el("p", { class: "evo-muted", text: t("sub") }));
    root.setAttribute("data-testid", "jev-page");
    root.setAttribute("aria-busy", "true");
    return Promise.all([page.call("status"), page.call("usage"), page.call("acts", { query: { limit: 20 } }), page.call("matches", { query: { limit: 20 } })]).then(
      function (found) {
        page.fill(root, [el("p", { class: "evo-muted", text: t("sub") }), statusSection(found[0]), costSection(found[1]), featureSection(found[0]), actSection(found[2]), matchSection(found[3])]);
        root.removeAttribute("aria-busy");
      },
      function (error) {
        page.fill(root, [el("p", { class: "evo-muted", text: t("sub") }), page.failed(error, load)]);
        root.removeAttribute("aria-busy");
      },
    );
  }

  evo.ready.then(function () {
    document.title = t("title");
    load();
  });
})();
