// Existing gate commands, shared by the post detail. The server remains the authority for writes.
window.editorialActions = function (refresh) {
  "use strict";
  var evo = window.evo,
    page = window.page,
    el = page.el,
    t = page.t,
    ui = window.editorial;
  var RUN_VARIANT = {
    running: "info",
    done: "success",
    failed: "danger",
    refused: "danger",
  };
  function runBadge(state) {
    return page.badge(t("posts.run.states." + state), RUN_VARIANT[state] || "outline", {
      testid: "editorial-run-state",
    });
  }

  /** A button that runs `work` (a promise), shows its error under the form, and loads the page again once it is done. */
  function action(label, testid, work, error, props) {
    var button = el(
      "button",
      Object.assign({ type: "button", class: "evo-btn", text: label, testid: testid }, props || {}),
    );
    button.addEventListener("click", function () {
      button.disabled = true;
      button.setAttribute("aria-busy", "true");
      error.hidden = true;
      Promise.resolve()
        .then(work)
        .then(
          function () {
            refresh();
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
    return el("p", {
      class: "evo-error",
      role: "alert",
      hidden: true,
      testid: "editorial-action-error",
    });
  }

  function answerGate(post, gate, answer, more) {
    var body = Object.assign(
      { gate: gate.stage, gate_state: "answered", via: "hub", answer: answer },
      more || {},
    );
    return page.call("posts/" + encodeURIComponent(post.slug), {
      method: "POST",
      body: body,
    });
  }

  function field(label, control) {
    return el("label", { class: "evo-stack editorial-field" }, [
      el("span", { class: "evo-small page-strong", text: label }),
      control,
    ]);
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
          action(
            t("posts.answer.pick", { option: label }),
            "editorial-pick",
            function () {
              return answerGate(post, gate, {
                option: index + 1,
                title: label,
              });
            },
            error,
            { class: "evo-btn page-wrap" },
          ),
        );
      });
      controls.push(field(t("posts.answer.topic"), topic));
      controls.push(
        action(
          t("posts.answer.useTopic"),
          "editorial-topic-send",
          function () {
            if (!topic.value.trim()) return Promise.reject(new Error(t("posts.answer.needTopic")));
            return answerGate(post, gate, { topic: topic.value.trim() });
          },
          error,
        ),
      );
    } else if (gate.kind === "interview") {
      var questions = Array.isArray(ask.questions) ? ask.questions : [];
      var boxes = questions.map(function (question) {
        var box = textArea("editorial-interview-answer");
        controls.push(
          field(typeof question === "string" ? question : JSON.stringify(question), box),
        );
        return box;
      });
      controls.push(
        action(
          t("posts.answer.approveBrief"),
          "editorial-interview-send",
          function () {
            var answers = questions.map(function (question, index) {
              return { question: question, answer: boxes[index].value.trim() };
            });
            return answerGate(post, gate, { answers: answers, approve: true });
          },
          error,
          { class: "evo-btn evo-btn-primary" },
        ),
      );
    } else if (gate.kind === "comments") {
      controls.push(
        el("div", { class: "evo-row" }, [
          action(
            t("posts.answer.commentsDone"),
            "editorial-comments-done",
            function () {
              return answerGate(post, gate, { done: true });
            },
            error,
          ),
          action(
            t("posts.answer.approveDraft"),
            "editorial-approve",
            function () {
              return answerGate(post, gate, { approve: true });
            },
            error,
            { class: "evo-btn evo-btn-primary" },
          ),
        ]),
      );
    } else if (gate.kind === "publish") {
      var url = el("input", {
        class: "evo-input",
        type: "url",
        placeholder: "https://",
        testid: "editorial-publish-url",
      });
      controls.push(field(t("posts.answer.url"), url));
      controls.push(
        action(
          t("posts.answer.published"),
          "editorial-published",
          function () {
            var given = url.value.trim();
            return answerGate(
              post,
              gate,
              { published: true, url: given || null },
              given ? { url: given } : null,
            );
          },
          error,
          { class: "evo-btn evo-btn-primary" },
        ),
      );
    }
    return el(
      "div",
      { class: "evo-stack editorial-answer", testid: "editorial-answer" },
      controls.concat([error]),
    );
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
        current
          ? el("p", { class: "evo-small evo-muted" }, [
              t("posts.run.at", {
                run: current.run_id,
                stage: ui.label("stages", current.stage) || "-",
              }),
              " ",
              current.at ? page.when(current.at) : "",
            ])
          : null,
        current && current.run_id
          ? page.link(
              "/p/" + encodeURIComponent(evo.context.project) + "/runs/" + current.run_id,
              { class: "page-link" },
              t("detailUi.runLink", { run: current.run_id }),
            )
          : null,
        current && current.error
          ? page.banner(
              t("posts.run.error"),
              current.error,
              { testid: "editorial-run-error" },
              "danger",
            )
          : null,
        canRun
          ? action(
              t("posts.run.again"),
              "editorial-run-again",
              function () {
                return page.call("posts/" + encodeURIComponent(post.slug) + "/run", {
                  method: "POST",
                });
              },
              error,
            )
          : null,
        error,
      ]),
    );
  }

  return { action: action, errorLine: errorLine, run: run, answerForm: answerForm };
};
