// Posts routing and review history. Gate writes are isolated in post-actions.js.
(function () {
  "use strict";
  var evo = window.evo;
  var page = window.page;
  var el = page.el;
  var t = page.t;
  var ui = window.editorial;

  /** The badge of a gate's state; its word is always written. */
  var STATE_VARIANT = {
    waiting: "warning",
    answered: "success",
    skipped: "outline",
  };
  var JUDGE_VARIANT = {
    pending: "outline",
    passed: "success",
    below: "warning",
    failed: "danger",
    refused: "danger",
  };
  var AXES = ["slop", "giong", "nguon", "hinh"];

  var root = document.getElementById("page");
  var loading = 0;
  var actions = window.editorialActions(load);
  var action = actions.action,
    errorLine = actions.errorLine;
  var run = actions.run,
    answerForm = actions.answerForm;

  function postsPath(slug) {
    return page.pagePath("editorial", "posts", slug ? encodeURIComponent(slug) : null);
  }

  function stateBadge(state) {
    return page.badge(t("posts.states." + state), STATE_VARIANT[state] || "outline", {
      testid: "editorial-gate-state",
    });
  }

  function links(post) {
    return el("div", { class: "evo-row editorial-links" }, [
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
    ]);
  }

  function judgeLine(round) {
    if (!round.judge && !round.scores) return null;
    var judge = round.judge || {};
    var scores = round.scores || {};
    var shown = AXES.filter(function (axis) {
      return typeof scores[axis] === "number";
    }).map(function (axis) {
      return t("posts.judge.axes." + axis) + " " + scores[axis];
    });
    return el("div", { class: "evo-stack", testid: "editorial-judge" }, [
      el("div", { class: "evo-row" }, [
        el("span", {
          class: "evo-small page-strong",
          text: t("posts.judge.title"),
        }),
        judge.state
          ? page.badge(
              t("posts.judge.states." + judge.state),
              JUDGE_VARIANT[judge.state] || "outline",
            )
          : null,
        shown.length ? el("span", { class: "evo-small", text: shown.join(", ") }) : null,
      ]),
      judge.note ? el("p", { class: "evo-small evo-muted page-wrap", text: judge.note }) : null,
    ]);
  }

  function showList(token) {
    root.setAttribute("data-testid", "editorial-posts-page");
    return page.call("posts").then(
      function (posts) {
        if (token === loading) page.fill(root, window.editorialBoard(posts, load));
      },
      function (error) {
        if (token === loading) page.fill(root, page.failed(error, load));
      },
    );
  }

  function gates(post, waiting) {
    var shown = post.gates.filter(function (gate) {
      return (gate.state === "waiting") === waiting;
    });
    if (!shown.length) return null;
    return page.section(
      waiting ? "editorial-gates" : "editorial-past-gates",
      t(waiting ? "detailUi.next" : "detailUi.pastGates"),
      null,
      el(
        "ul",
        { class: "page-list" },
        shown.map(function (gate) {
          return el("li", { testid: "editorial-gate" }, [
            el("div", { class: "evo-row evo-row-between" }, [
              el("span", {
                class: "page-strong",
                text: ui.label("stages", gate.stage) + " (" + t("posts.kinds." + gate.kind) + ")",
              }),
              stateBadge(gate.state),
            ]),
            gate.answered_at
              ? el("p", { class: "evo-small evo-muted" }, [
                  t("posts.answered", {
                    via: gate.answered_via || "-",
                    by: gate.answered_by || "-",
                  }),
                  " ",
                  page.when(gate.answered_at),
                ])
              : null,
            gate.state === "waiting" && post.run && post.run.state === "running"
              ? el("p", {
                  class: "evo-small evo-muted",
                  text: t("posts.answer.wait"),
                })
              : null,
            gate.state === "waiting" && !page.canWrite()
              ? el("p", { class: "evo-muted", text: t("detailUi.readOnly") })
              : null,
            gate.state === "waiting" &&
            page.canWrite() &&
            !(post.run && post.run.state === "running")
              ? answerForm(post, gate)
              : null,
          ]);
        }),
      ),
    );
  }

  function rounds(post) {
    var reviewing = post.gates.some(function (gate) {
      return gate.kind === "comments";
    });
    if (!post.rounds.length && !reviewing) return null;
    var error = errorLine();
    var pull =
      page.canWrite() && reviewing
        ? action(
            t("posts.pullComments"),
            "editorial-pull-comments",
            function () {
              return page.call("posts/" + encodeURIComponent(post.slug) + "/comments", {
                method: "POST",
              });
            },
            error,
          )
        : null;
    return page.section(
      "editorial-rounds",
      t("posts.roundsTitle"),
      el("div", { class: "evo-row" }, [page.badge(String(post.rounds.length), "outline"), pull]),
      el("div", { class: "evo-stack" }, [
        error,
        el(
          "ul",
          { class: "page-list" },
          post.rounds
            .slice()
            .sort(function (a, b) {
              return b.at.localeCompare(a.at) || b.number - a.number;
            })
            .map(function (round, index) {
              return el(
                "li",
                {},
                el(
                  "details",
                  {
                    class: "editorial-round",
                    open: index === 0,
                    testid: "editorial-round",
                  },
                  [
                    el("summary", {}, [
                      el("span", {
                        class: "page-strong",
                        text: t("posts.round", {
                          number: round.number,
                          stage: ui.label("stages", round.stage),
                        }),
                      }),
                      el("span", {
                        class: "evo-small evo-muted",
                        text: t("detailUi.comments", {
                          count: round.comments.length,
                        }),
                      }),
                      page.when(round.at),
                    ]),
                    el("div", { class: "editorial-round-body evo-stack" }, [
                      round.note ? el("p", { class: "page-wrap", text: round.note }) : null,
                      round.feedback.length
                        ? el("p", {
                            class: "evo-small evo-muted",
                            text: round.feedback.join(", "),
                          })
                        : null,
                      judgeLine(round),
                      el(
                        "ul",
                        { class: "editorial-comments" },
                        round.comments.map(function (comment) {
                          return el("li", { testid: "editorial-comment" }, [
                            comment.quote
                              ? el("blockquote", {
                                  class: "editorial-quote page-wrap",
                                  text: comment.quote,
                                })
                              : null,
                            el("p", { class: "page-wrap" }, [
                              el("span", {
                                class: "page-strong",
                                text: (comment.author || "?") + ": ",
                              }),
                              comment.text,
                            ]),
                          ]);
                        }),
                      ),
                    ]),
                  ],
                ),
              );
            }),
        ),
      ]),
    );
  }

  function history(post) {
    if (!post.history.length) return null;
    return page.section(
      "editorial-history",
      t("posts.history"),
      null,
      el(
        "ul",
        { class: "page-list" },
        post.history.map(function (step) {
          return el("li", { class: "evo-row evo-row-between" }, [
            el("span", { text: ui.label("stages", step.stage) }),
            page.when(step.at),
          ]);
        }),
      ),
    );
  }

  function detail(post) {
    var feedbackPath =
      page.pagePath("editorial", "feedback") + "?post=" + encodeURIComponent(post.slug);
    return [
      el("header", { class: "editorial-detail-head" }, [
        page.badge(ui.label("stages", post.stage), "outline", {
          "aria-label": t("detailUi.currentStage"),
        }),
        el("h1", { class: "page-wrap", text: post.title || post.slug }),
        links(post),
      ]),
      el("div", { class: "editorial-detail-layout" }, [
        el("div", { class: "evo-stack editorial-detail-main" }, [gates(post, true), rounds(post)]),
        el("aside", { class: "evo-stack", "aria-label": t("detailUi.overview") }, [
          run(post),
          page.section(
            "editorial-post-meta",
            t("detailUi.overview"),
            null,
            el("div", { class: "evo-stack" }, [
              el("p", {
                class: "evo-small evo-muted page-wrap",
                text: post.slug,
              }),
              post.branch
                ? el("div", {}, [
                    el("span", {
                      class: "evo-small evo-muted",
                      text: t("detailUi.branch"),
                    }),
                    el("p", {
                      class: "evo-small evo-mono page-wrap",
                      text: post.branch,
                    }),
                  ])
                : null,
              page.link(
                feedbackPath,
                { class: "page-link", testid: "editorial-post-feedback" },
                t("detailUi.feedbackLink"),
              ),
              post.feedback.length
                ? el("p", {
                    class: "evo-small page-wrap",
                    text: post.feedback.join(", "),
                  })
                : null,
            ]),
          ),
          gates(post, false),
          history(post),
        ]),
      ]),
    ];
  }

  function showPost(slug, token) {
    var body = el("div", { class: "evo-stack" }, ui.loading());
    page.fill(root, [
      ui.navigation("posts"),
      page.link(
        postsPath(),
        { class: "evo-small evo-muted page-back", testid: "editorial-back" },
        "← " + t("posts.back"),
      ),
      body,
    ]);
    root.setAttribute("data-testid", "editorial-post-page");
    return page.call("posts/" + encodeURIComponent(slug)).then(
      function (post) {
        if (token === loading) page.fill(body, detail(post));
      },
      function (error) {
        if (token === loading) page.fill(body, page.failed(error, load));
      },
    );
  }

  function slug() {
    var path = (evo.context.location && evo.context.location.path) || "";
    var first = path.replace(/^\/+/, "").split("/")[0];
    return first ? decodeURIComponent(first) : null;
  }

  function load() {
    loading += 1;
    var token = loading;
    var which = slug();
    root.setAttribute("aria-busy", "true");
    var done = which ? showPost(which, token) : showList(token);
    return done.then(function () {
      if (token === loading) root.removeAttribute("aria-busy");
    });
  }

  evo.ready.then(function () {
    document.title = t("posts.title");
    page.fill(root, ui.loading());
    ui.ready().then(load);
    evo.on("location", function () {
      load();
    });
  });
})();
