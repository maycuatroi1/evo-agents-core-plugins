// Search and status filters stay in this page, without writing to a post or dispatching an agent.
(function () {
  "use strict";
  var page = window.page,
    el = page.el,
    t = page.t,
    ui = window.editorial;
  var selected = "all",
    search = "",
    stage = "";
  var states = ["all", "waiting", "running", "failed", "published"];
  function matches(post, state) {
    if (state === "waiting") return !!post.waiting_gate;
    if (state === "running") return !!post.run && post.run.state === "running";
    if (state === "failed") return !!post.run && ["failed", "refused"].indexOf(post.run.state) >= 0;
    if (state === "published") return !!post.url;
    return true;
  }
  function fold(text) {
    return text
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .replace(/đ/g, "d")
      .toLowerCase();
  }
  function card(post) {
    return el("li", { class: "editorial-post-card", testid: "editorial-post" }, [
      el(
        "h3",
        {},
        page.link(
          page.pagePath("editorial", "posts", encodeURIComponent(post.slug)),
          { class: "editorial-post-title" },
          post.title || post.slug,
        ),
      ),
      el("p", {
        class: "evo-small evo-muted editorial-slug",
        text: post.slug,
      }),
      el("div", { class: "editorial-tags" }, [
        post.waiting_gate
          ? page.badge(
              t("posts.waits", {
                stage: ui.label("stages", post.waiting_gate),
              }),
              "warning",
              { testid: "editorial-waiting" },
            )
          : null,
        post.run
          ? page.badge(
              t("posts.run.states." + post.run.state),
              {
                running: "info",
                done: "success",
                failed: "danger",
                refused: "danger",
              }[post.run.state],
              { testid: "editorial-run-state" },
            )
          : null,
      ]),
      el("div", { class: "editorial-post-footer" }, [
        el("span", {
          class: "evo-small evo-muted",
          text: t("posts.rounds", { count: post.rounds }),
        }),
        post.preview_url
          ? page.external(
              post.preview_url,
              { class: "page-link", testid: "editorial-preview" },
              t("posts.preview"),
            )
          : null,
        post.url
          ? page.external(
              post.url,
              { class: "page-link", testid: "editorial-url" },
              t("posts.published"),
            )
          : null,
      ]),
    ]);
  }
  window.editorialBoard = function (posts, refresh) {
    var body = el("div", { class: "editorial-board" }),
      count = el("p", { class: "evo-small evo-muted", role: "status" });
    var tabs = el("div", {
      class: "editorial-status-filters",
      role: "group",
      "aria-label": t("board.status"),
    });
    function reset() {
      selected = "all";
      search = "";
      stage = "";
      searchBox.value = "";
      stageBox.value = "";
      render();
    }
    var clear = el("button", {
      type: "button",
      class: "evo-btn",
      text: t("workspace.clear"),
      on: { click: reset },
    });
    var searchBox = el("input", {
      type: "search",
      class: "evo-input",
      value: search,
      placeholder: t("board.placeholder"),
      testid: "editorial-post-search",
      on: {
        input: function (event) {
          search = event.target.value;
          render();
        },
      },
    });
    var choices = ui.data().stages.slice();
    posts.forEach(function (post) {
      if (
        !choices.some(function (item) {
          return item.name === post.stage;
        })
      )
        choices.push({ name: post.stage, title: post.stage });
    });
    var stageBox = ui.select(choices, t("workspace.allStages"), stage, {
      testid: "editorial-post-stage",
      on: {
        change: function (event) {
          stage = event.target.value;
          render();
        },
      },
    });
    var buttons = states.map(function (state) {
      var button = el(
        "button",
        {
          type: "button",
          "data-state": state,
          on: {
            click: function () {
              selected = state;
              render();
            },
          },
        },
        [
          t("board." + state),
          el("span", {
            class: "editorial-filter-number",
            text: String(
              posts.filter(function (post) {
                return matches(post, state);
              }).length,
            ),
          }),
        ],
      );
      tabs.appendChild(button);
      return button;
    });
    function render() {
      buttons.forEach(function (button, index) {
        button.setAttribute("aria-pressed", String(states[index] === selected));
      });
      var found = posts.filter(function (post) {
        return (
          matches(post, selected) &&
          (!stage || post.stage === stage) &&
          fold(post.title + " " + post.slug).indexOf(fold(search.trim())) >= 0
        );
      });
      clear.hidden = !search && !stage && selected === "all";
      count.textContent = t("board.results", { count: found.length });
      if (!found.length) {
        page.fill(
          body,
          el("div", { class: "evo-empty", testid: "editorial-empty" }, [
            el("p", {
              class: "evo-empty-title",
              text: t(posts.length ? "board.noMatch" : "posts.emptyTitle"),
            }),
            el("p", {
              class: "evo-muted",
              text: t(posts.length ? "board.noMatchText" : "posts.emptyText"),
            }),
          ]),
        );
        return;
      }
      page.fill(
        body,
        choices
          .filter(function (choice) {
            return found.some(function (post) {
              return post.stage === choice.name;
            });
          })
          .map(function (choice) {
            var mine = found.filter(function (post) {
              return post.stage === choice.name;
            });
            return page.section(
              "editorial-stage-" + choice.name,
              choice.title,
              page.badge(String(mine.length), "outline"),
              el("ul", { class: "editorial-post-list" }, mine.map(card)),
              { class: "editorial-stage" },
            );
          }),
      );
    }
    render();
    return [
      ui.intro("posts", t("posts.sub"), refresh),
      tabs,
      el("div", { class: "editorial-toolbar", role: "search" }, [
        ui.field(t("board.search"), searchBox),
        ui.field(t("board.stage"), stageBox),
        clear,
      ]),
      count,
      body,
    ];
  };
})();
