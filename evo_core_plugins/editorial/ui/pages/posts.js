// The page Posts of the core plugin editorial, framed by the hub at /p/<project>/x/editorial/posts: the posts by
// stage, each with the gate that waits for a person, its preview and url and its count of review rounds. Its sub path
// <slug> shows one post: its gates, the stages it entered, its review rounds with their comments and its feedback
// entries. Cards, one under another, so it reads at 375 px. Its words are in i18n/<locale>.js.
(function () {
  "use strict";
  var evo = window.evo;
  var page = window.page;
  var el = page.el;
  var t = page.t;

  /** The badge of a gate's state; its word is always written. */
  var STATE_VARIANT = { waiting: "warning", answered: "success", skipped: "outline" };

  var root = document.getElementById("page");
  var loading = 0;

  function postsPath(slug) {
    return page.pagePath("editorial", "posts", slug ? encodeURIComponent(slug) : null);
  }

  function stateBadge(state) {
    return page.badge(t("posts.states." + state), STATE_VARIANT[state] || "outline", { testid: "editorial-gate-state" });
  }

  function links(post) {
    return el("div", { class: "evo-row editorial-links" }, [
      post.preview_url ? page.external(post.preview_url, { class: "page-link", testid: "editorial-preview" }, t("posts.preview")) : null,
      post.url ? page.external(post.url, { class: "page-link", testid: "editorial-url" }, t("posts.published")) : null,
    ]);
  }

  function card(post) {
    return el("li", { class: "editorial-card", testid: "editorial-post" }, [
      el("div", { class: "evo-row evo-row-between" }, [
        page.link(postsPath(post.slug), { class: "page-strong page-wrap" }, post.title || post.slug),
        post.waiting_gate ? page.badge(t("posts.waits", { stage: post.waiting_gate }), "warning", { testid: "editorial-waiting" }) : null,
      ]),
      el("p", { class: "evo-small evo-muted page-wrap", text: post.slug }),
      el("p", { class: "evo-small", text: t("posts.rounds", { count: post.rounds }) }),
      links(post),
    ]);
  }

  function list(posts) {
    if (!posts.length) {
      return el("div", { class: "evo-empty", testid: "editorial-empty" }, [
        el("p", { class: "evo-empty-title", text: t("posts.emptyTitle") }),
        el("p", { class: "evo-muted", text: t("posts.emptyText") }),
      ]);
    }
    var stages = [];
    posts.forEach(function (post) {
      if (stages.indexOf(post.stage) < 0) stages.push(post.stage);
    });
    return stages.map(function (stage) {
      var mine = posts.filter(function (post) {
        return post.stage === stage;
      });
      return page.section("editorial-stage-" + stage, stage, page.badge(String(mine.length), "outline"), el("ul", { class: "page-list" }, mine.map(card)));
    });
  }

  function showList(token) {
    root.setAttribute("data-testid", "editorial-posts-page");
    return page.call("posts").then(
      function (posts) {
        if (token === loading) page.fill(root, [el("p", { class: "evo-muted", text: t("posts.sub") }), list(posts)]);
      },
      function (error) {
        if (token === loading) page.fill(root, page.failed(error, load));
      },
    );
  }

  function gates(post) {
    if (!post.gates.length) return null;
    return page.section(
      "editorial-gates",
      t("posts.gates"),
      null,
      el(
        "ul",
        { class: "page-list" },
        post.gates.map(function (gate) {
          return el("li", { testid: "editorial-gate" }, [
            el("div", { class: "evo-row evo-row-between" }, [el("span", { class: "page-strong", text: gate.stage + " (" + t("posts.kinds." + gate.kind) + ")" }), stateBadge(gate.state)]),
            gate.answered_at
              ? el("p", { class: "evo-small evo-muted" }, [t("posts.answered", { via: gate.answered_via || "-", by: gate.answered_by || "-" }), " ", page.when(gate.answered_at)])
              : null,
          ]);
        }),
      ),
    );
  }

  function rounds(post) {
    if (!post.rounds.length) return null;
    return page.section(
      "editorial-rounds",
      t("posts.roundsTitle"),
      page.badge(String(post.rounds.length), "outline"),
      el(
        "ul",
        { class: "page-list" },
        post.rounds.map(function (round) {
          return el("li", { testid: "editorial-round" }, [
            el("div", { class: "evo-row evo-row-between" }, [el("span", { class: "page-strong", text: t("posts.round", { number: round.number, stage: round.stage }) }), page.when(round.at)]),
            round.note ? el("p", { class: "page-wrap", text: round.note }) : null,
            round.feedback.length ? el("p", { class: "evo-small evo-muted", text: round.feedback.join(", ") }) : null,
            el(
              "ul",
              { class: "editorial-comments" },
              round.comments.map(function (comment) {
                return el("li", { testid: "editorial-comment" }, [
                  comment.quote ? el("blockquote", { class: "editorial-quote page-wrap", text: comment.quote }) : null,
                  el("p", { class: "page-wrap" }, [el("span", { class: "page-strong", text: (comment.author || "?") + ": " }), comment.text]),
                ]);
              }),
            ),
          ]);
        }),
      ),
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
          return el("li", { class: "evo-row evo-row-between" }, [el("span", { text: step.stage }), page.when(step.at)]);
        }),
      ),
    );
  }

  function detail(post) {
    return [
      el("div", { class: "page-head" }, [el("h1", { class: "page-wrap", text: post.title || post.slug }), el("p", { class: "evo-muted", text: t("posts.stageIs", { stage: post.stage }) })]),
      links(post),
      post.branch ? el("p", { class: "evo-small evo-mono page-wrap", text: post.branch }) : null,
      gates(post),
      rounds(post),
      history(post),
      post.feedback.length ? el("p", { class: "evo-small", testid: "editorial-post-feedback" }, [t("posts.feedback") + ": ", post.feedback.join(", ")]) : null,
    ];
  }

  function showPost(slug, token) {
    var body = el("div", { class: "evo-stack" });
    page.fill(root, [page.link(postsPath(), { class: "evo-small evo-muted page-back", testid: "editorial-back" }, "← " + t("posts.back")), body]);
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
    load();
    evo.on("location", function () {
      load();
    });
  });
})();
