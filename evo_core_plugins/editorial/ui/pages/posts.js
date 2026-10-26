// The page Posts of the core plugin editorial, framed by the hub at /p/<project>/x/editorial/posts: the posts by
// stage, each with the gate that waits for a person, its preview and url and its count of review rounds. Its sub path
// <slug> shows one post: its gates, the stages it entered, its review rounds with their comments and its feedback
// entries. Cards, one under another, so it reads at 375 px. Its words are in i18n/<locale>.js.
// A writer answers the gate that waits on the post's page (the link of its notice): pick a proposal or write a topic,
// answer an interview, say the comments are in or approve the draft, say the post is out. The answer is kept with
// answered_via hub and hands the writer agent its next task. The page shows the agent's run, its error and a button to
// hand the task again, the judge's scores of each round, and a button that reads the reviewers' draft comments.
(function () {
  "use strict";
  var evo = window.evo;
  var page = window.page;
  var el = page.el;
  var t = page.t;

  /** The badge of a gate's state; its word is always written. */
  var STATE_VARIANT = { waiting: "warning", answered: "success", skipped: "outline" };
  var RUN_VARIANT = { running: "warning", done: "success", failed: "danger", refused: "danger" };
  var JUDGE_VARIANT = { pending: "outline", passed: "success", below: "warning", failed: "danger", refused: "danger" };
  var AXES = ["slop", "giong", "nguon", "hinh"];

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

  function runBadge(state) {
    return page.badge(t("posts.run.states." + state), RUN_VARIANT[state] || "outline", { testid: "editorial-run-state" });
  }

  /** A button that runs `work` (a promise), shows its error under the form, and loads the page again once it is done. */
  function action(label, testid, work, error, props) {
    var button = el("button", Object.assign({ type: "button", class: "evo-btn", text: label, testid: testid }, props || {}));
    button.addEventListener("click", function () {
      button.disabled = true;
      button.setAttribute("aria-busy", "true");
      error.hidden = true;
      Promise.resolve()
        .then(work)
        .then(
          function () {
            load();
          },
          function (cause) {
            button.disabled = false;
            button.removeAttribute("aria-busy");
            error.textContent = page.failure(cause);
            error.hidden = false;
          },
        );
    });
    return button;
  }

  function errorLine() {
    return el("p", { class: "evo-error", role: "alert", hidden: true, testid: "editorial-action-error" });
  }

  function answerGate(post, gate, answer, more) {
    var body = Object.assign({ gate: gate.stage, gate_state: "answered", via: "hub", answer: answer }, more || {});
    return page.call("posts/" + encodeURIComponent(post.slug), { method: "POST", body: body });
  }

  function field(label, control) {
    return el("label", { class: "evo-stack editorial-field" }, [el("span", { class: "evo-small page-strong", text: label }), control]);
  }

  function textArea(testid) {
    return el("textarea", { class: "evo-input", rows: 3, testid: testid });
  }

  /** The controls that answer `gate`, by its kind, with what the agent asked in `gate.ask`. */
  function answerForm(post, gate) {
    var error = errorLine();
    var ask = gate.ask || {};
    var controls = [];
    if (gate.kind === "choose") {
      var options = Array.isArray(ask.options) ? ask.options : [];
      var topic = textArea("editorial-topic");
      options.forEach(function (option, index) {
        var label = typeof option === "string" ? option : option.title || JSON.stringify(option);
        controls.push(
          action(t("posts.answer.pick", { option: label }), "editorial-pick", function () {
            return answerGate(post, gate, { option: index + 1, title: label });
          }, error, { class: "evo-btn page-wrap" }),
        );
      });
      controls.push(field(t("posts.answer.topic"), topic));
      controls.push(
        action(t("posts.answer.useTopic"), "editorial-topic-send", function () {
          if (!topic.value.trim()) return Promise.reject(new Error(t("posts.answer.needTopic")));
          return answerGate(post, gate, { topic: topic.value.trim() });
        }, error),
      );
    } else if (gate.kind === "interview") {
      var questions = Array.isArray(ask.questions) ? ask.questions : [];
      var boxes = questions.map(function (question) {
        var box = textArea("editorial-interview-answer");
        controls.push(field(typeof question === "string" ? question : JSON.stringify(question), box));
        return box;
      });
      controls.push(
        action(t("posts.answer.approveBrief"), "editorial-interview-send", function () {
          var answers = questions.map(function (question, index) {
            return { question: question, answer: boxes[index].value.trim() };
          });
          return answerGate(post, gate, { answers: answers, approve: true });
        }, error, { class: "evo-btn evo-btn-primary" }),
      );
    } else if (gate.kind === "comments") {
      controls.push(
        el("div", { class: "evo-row" }, [
          action(t("posts.answer.commentsDone"), "editorial-comments-done", function () {
            return answerGate(post, gate, { done: true });
          }, error),
          action(t("posts.answer.approveDraft"), "editorial-approve", function () {
            return answerGate(post, gate, { approve: true });
          }, error, { class: "evo-btn evo-btn-primary" }),
        ]),
      );
    } else if (gate.kind === "publish") {
      var url = el("input", { class: "evo-input", type: "url", placeholder: "https://", testid: "editorial-publish-url" });
      controls.push(field(t("posts.answer.url"), url));
      controls.push(
        action(t("posts.answer.published"), "editorial-published", function () {
          var given = url.value.trim();
          return answerGate(post, gate, { published: true, url: given || null }, given ? { url: given } : null);
        }, error, { class: "evo-btn evo-btn-primary" }),
      );
    }
    return el("div", { class: "evo-stack editorial-answer", testid: "editorial-answer" }, controls.concat([error]));
  }

  function run(post) {
    var current = post.run;
    var canRun = page.canWrite() && (!current || current.state !== "running") && !post.waiting_gate;
    if (!current && !canRun) return null;
    var error = errorLine();
    return page.section(
      "editorial-run",
      t("posts.run.title"),
      current ? runBadge(current.state) : null,
      el("div", { class: "evo-stack" }, [
        current ? el("p", { class: "evo-small evo-muted" }, [t("posts.run.at", { run: current.run_id, stage: current.stage || "-" }), " ", current.at ? page.when(current.at) : ""]) : null,
        current && current.error ? page.banner(t("posts.run.error"), current.error, { testid: "editorial-run-error" }, "danger") : null,
        canRun
          ? action(t("posts.run.again"), "editorial-run-again", function () {
              return page.call("posts/" + encodeURIComponent(post.slug) + "/run", { method: "POST" });
            }, error)
          : null,
        error,
      ]),
    );
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
        el("span", { class: "evo-small page-strong", text: t("posts.judge.title") }),
        judge.state ? page.badge(t("posts.judge.states." + judge.state), JUDGE_VARIANT[judge.state] || "outline") : null,
        shown.length ? el("span", { class: "evo-small", text: shown.join(", ") }) : null,
      ]),
      judge.note ? el("p", { class: "evo-small evo-muted page-wrap", text: judge.note }) : null,
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
      post.run ? el("p", { class: "evo-small" }, [runBadge(post.run.state)]) : null,
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
            gate.state === "waiting" && post.run && post.run.state === "running"
              ? el("p", { class: "evo-small evo-muted", text: t("posts.answer.wait") })
              : null,
            gate.state === "waiting" && page.canWrite() && !(post.run && post.run.state === "running") ? answerForm(post, gate) : null,
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
    var pull = page.canWrite() && reviewing
      ? action(t("posts.pullComments"), "editorial-pull-comments", function () {
          return page.call("posts/" + encodeURIComponent(post.slug) + "/comments", { method: "POST" });
        }, error)
      : null;
    return page.section(
      "editorial-rounds",
      t("posts.roundsTitle"),
      el("div", { class: "evo-row" }, [page.badge(String(post.rounds.length), "outline"), pull]),
      el(
        "div",
        { class: "evo-stack" },
        [error, el(
        "ul",
        { class: "page-list" },
        post.rounds.map(function (round) {
          return el("li", { testid: "editorial-round" }, [
            el("div", { class: "evo-row evo-row-between" }, [el("span", { class: "page-strong", text: t("posts.round", { number: round.number, stage: round.stage }) }), page.when(round.at)]),
            round.note ? el("p", { class: "page-wrap", text: round.note }) : null,
            round.feedback.length ? el("p", { class: "evo-small evo-muted", text: round.feedback.join(", ") }) : null,
            judgeLine(round),
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
      )],
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
      run(post),
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
