const { test } = require("node:test");
const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const { JSDOM } = require("jsdom");
const fixture = require("./editorial-fixture.cjs");
const dir = path.resolve(__dirname, "../../evo_core_plugins/editorial/ui/pages");
const tick = () => new Promise((resolve) => setImmediate(resolve));
async function boot(
  name,
  { role = "writer", location = { path: "", query: {} }, route, locale = "en" } = {},
) {
  const dom = new JSDOM('<main id="page"></main>', {
    runScripts: "outside-only",
    url: "https://hub.example.org",
  });
  const { window } = dom;
  const calls = [],
    navigation = [],
    listeners = {},
    words = {};
  window.evo = {
    context: { project: "northwind", viewer: { role }, locale, location },
    ready: Promise.resolve(),
    messages(lang, value) {
      words[lang] = value;
    },
    t(key, vars) {
      let value = key.split(".").reduce((o, k) => o?.[k], words[locale]) || key;
      for (const [key, val] of Object.entries(vars || {}))
        value = value.replaceAll("{" + key + "}", val);
      return value;
    },
    on(event, fn) {
      listeners[event] = fn;
    },
    navigate(to) {
      navigation.push(to);
      return Promise.resolve();
    },
    toast() {
      return Promise.resolve();
    },
    route(url, options) {
      calls.push({ url, options });
      // Match the hub bridge contract: route paths cannot contain query strings or fragments.
      if (/[?#]/.test(url))
        return Promise.reject(new Error("route query belongs in options.query"));
      const value = route ? route(url, options) : undefined;
      if (value !== undefined) return Promise.resolve(value);
      return Promise.resolve({
        status: 200,
        body:
          url === "workspace"
            ? fixture.workspace
            : url === "posts"
              ? fixture.posts
              : url.startsWith("posts/")
                ? fixture.post
                : fixture.entries,
      });
    },
  };
  for (const file of [
    "i18n/en.js",
    "i18n/vi.js",
    "common.js",
    "workspace.js",
    ...(name === "posts" ? ["post-list.js", "post-actions.js"] : []),
    name + ".js",
  ])
    window.eval(readFileSync(path.join(dir, file), "utf8"));
  await tick();
  await tick();
  return {
    dom,
    window,
    doc: window.document,
    calls,
    navigation,
    listeners,
    find: (id) => window.document.querySelector(`[data-testid="${id}"]`),
  };
}
test("board uses configured labels, status filters, search and stage together", async () => {
  const b = await boot("posts");
  assert.equal(b.doc.querySelectorAll('[data-testid="editorial-post"]').length, 5);
  assert.ok(b.doc.body.textContent.includes("Chờ duyệt"));
  b.doc.querySelector('[data-state="waiting"]').click();
  assert.equal(b.doc.querySelectorAll('[data-testid="editorial-post"]').length, 3);
  const search = b.find("editorial-post-search");
  search.focus();
  search.value = "đơn hàng";
  search.dispatchEvent(new b.window.Event("input"));
  assert.equal(b.doc.querySelectorAll('[data-testid="editorial-post"]').length, 1);
  assert.equal(b.doc.activeElement, search); // Rendering did not replace the input.
  assert.equal(b.find("editorial-post-search"), search);
  b.find("editorial-post-stage").value = "draft";
  b.find("editorial-post-stage").dispatchEvent(new b.window.Event("change"));
  assert.ok(b.find("editorial-empty"));
  assert.equal(b.calls.filter((c) => c.options?.method === "POST").length, 0);
});
test("empty board is distinct from no filter matches, and unknown stages stay visible", async () => {
  const empty = await boot("posts", {
    route: (url) => (url === "posts" ? { status: 200, body: [] } : undefined),
  });
  assert.match(empty.find("editorial-empty").textContent, /No post yet/);
  const unknown = await boot("posts", {
    route: (url) =>
      url === "posts"
        ? {
            status: 200,
            body: [{ ...fixture.posts[0], stage: "custom-stage" }],
          }
        : undefined,
  });
  assert.match(unknown.doc.body.textContent, /custom-stage/);
});
test("feedback is paginated, searchable, sorted and keyboard-expandable without losing filter focus", async () => {
  const b = await boot("feedback");
  assert.equal(b.doc.querySelectorAll('[data-testid="editorial-entry"]').length, 10);
  assert.equal(b.doc.querySelectorAll("details[open]").length, 0);
  const next = [...b.doc.querySelectorAll("button")].find((n) => n.textContent === "Next");
  next.click();
  assert.match(b.find("editorial-entry").textContent, /PH-0011/);
  assert.equal(b.doc.activeElement.tagName, "SUMMARY");
  const q = b.find("editorial-filter-q");
  q.value = "nguồn & date";
  b.find("editorial-filter-notebook").value = "facts";
  b.doc.querySelector("form").dispatchEvent(new b.window.Event("submit", { cancelable: true }));
  await tick();
  assert.equal(b.calls.at(-1).url, "feedback");
  assert.deepEqual(JSON.parse(JSON.stringify(b.calls.at(-1).options.query)), {
    q: "nguồn & date",
    notebook: "facts",
  });
  assert.equal(b.find("editorial-filter-q"), q);
  [...b.doc.querySelectorAll("button")].find((n) => n.textContent === "Expand entries").click();
  assert.equal(b.doc.querySelectorAll("details[open]").length, 10);
  assert.match(b.doc.body.textContent, /Original feedback/);
  assert.equal(b.calls.filter((c) => c.options?.method === "POST").length, 0);
});
test("feedback deep link, reset, empty and failed reads preserve the toolbar", async () => {
  const b = await boot("feedback", {
    location: { query: { post: "northwind-retries" } },
    route: (url) => (url.startsWith("feedback") ? { status: 200, body: [] } : undefined),
  });
  assert.equal(b.calls.at(-1).url, "feedback");
  assert.deepEqual(JSON.parse(JSON.stringify(b.calls.at(-1).options.query)), {
    post: "northwind-retries",
  });
  assert.ok(b.find("editorial-empty"));
  [...b.doc.querySelectorAll("button")].find((n) => n.textContent === "Clear filters").click();
  await tick();
  assert.equal(b.calls.at(-1).url, "feedback");
  const failed = await boot("feedback", {
    route: (url) =>
      url.startsWith("feedback") ? { status: 503, body: { message: "Unavailable" } } : undefined,
  });
  assert.match(failed.find("page-error").textContent, /Unavailable/);
  assert.ok(failed.find("editorial-filter-q"));
});
test("out-of-order reads cannot replace the newest filter results", async () => {
  const pending = [];
  const b = await boot("feedback", {
    route: (url) =>
      url.startsWith("feedback") ? new Promise((resolve) => pending.push(resolve)) : undefined,
  });
  b.find("editorial-filter-q").value = "new";
  b.doc.querySelector("form").dispatchEvent(new b.window.Event("submit", { cancelable: true }));
  pending[1]({ status: 200, body: [fixture.entries[1]] });
  await tick();
  pending[0]({ status: 200, body: [fixture.entries[0]] });
  await tick();
  assert.match(b.find("editorial-entry").textContent, /PH-0002/);
  assert.equal(b.doc.querySelectorAll('[data-testid="editorial-entry"]').length, 1);
});
test("detail puts waiting gates first, newest review open, and retains links and write behavior", async () => {
  const b = await boot("posts", { location: { path: "/northwind-retries" } });
  assert.ok(b.find("editorial-gates").compareDocumentPosition(b.find("editorial-rounds")) & 4);
  const rounds = b.doc.querySelectorAll('[data-testid="editorial-round"]');
  assert.match(rounds[0].textContent, /Round 3/);
  assert.equal(rounds[0].open, true);
  assert.equal(rounds[1].open, false);
  b.find("editorial-post-feedback").click();
  assert.match(b.navigation.at(-1), /feedback\?post=northwind-retries$/);
  b.find("editorial-approve").click();
  await tick();
  const write = b.calls.find((c) => c.options?.method === "POST");
  assert.equal(write.url, "posts/northwind-retries");
  assert.deepEqual(JSON.parse(JSON.stringify(write.options.body)), {
    gate: "review",
    gate_state: "answered",
    via: "hub",
    answer: { approve: true },
  });
});
test("reader and running writer cannot answer a gate", async () => {
  const reader = await boot("posts", {
    role: "reader",
    location: { path: "/northwind-retries" },
  });
  assert.equal(reader.find("editorial-approve"), null);
  assert.equal(reader.find("editorial-pull-comments"), null);
  assert.match(reader.doc.body.textContent, /You have read access/);
  const running = await boot("posts", {
    location: { path: "/northwind-retries" },
    route: (url) =>
      url.startsWith("posts/")
        ? { status: 200, body: { ...fixture.post, run: { state: "running" } } }
        : undefined,
  });
  assert.equal(running.find("editorial-approve"), null);
  assert.match(running.doc.body.textContent, /writer agent is working/);
});
test("workspace failures degrade gracefully and source strings never execute as HTML", async () => {
  const b = await boot("feedback", {
    locale: "vi",
    route: (url) =>
      url === "workspace"
        ? { status: 500, body: {} }
        : url.startsWith("feedback")
          ? {
              status: 200,
              body: [
                {
                  ...fixture.entries[0],
                  title: "<img src=x onerror=alert(1)>",
                },
              ],
            }
          : undefined,
  });
  assert.match(b.doc.body.textContent, /Chưa tải được/);
  assert.equal(b.doc.querySelector("img"), null);
  assert.match(b.find("editorial-entry").textContent, /<img/);
});

test("a refused gate keeps its form, error and retry, without accidental double submission", async () => {
  let writes = 0;
  const b = await boot("posts", {
    location: { path: "/northwind-retries" },
    route: (url, options) => {
      if (options?.method === "POST") {
        writes++;
        return { status: 409, body: { message: "Judge scores are below the threshold" } };
      }
    },
  });
  const approve = b.find("editorial-approve");
  approve.click();
  approve.click();
  await tick();
  assert.equal(writes, 1);
  assert.equal(approve.disabled, false);
  assert.match(b.find("editorial-gates").textContent, /Judge scores are below/);
});

test("choosing a topic, interview answers, publish confirmation and rerun preserve their payloads", async () => {
  for (const kind of ["choose", "interview", "publish"]) {
    const detail = {
      ...fixture.post,
      gates: [
        {
          stage: "review",
          kind,
          state: "waiting",
          ask: { options: ["A topic"], questions: ["Who reads this?"] },
        },
      ],
    };
    const b = await boot("posts", {
      location: { path: "/northwind-retries" },
      route: (url, options) =>
        url.startsWith("posts/") && !options?.method ? { status: 200, body: detail } : undefined,
    });
    if (kind === "choose") {
      b.find("editorial-pick").click();
    }
    if (kind === "interview") {
      b.find("editorial-interview-answer").value = "Developers";
      b.find("editorial-interview-send").click();
    }
    if (kind === "publish") {
      b.find("editorial-publish-url").value = "https://example.org/new-post";
      b.find("editorial-published").click();
    }
    await tick();
    const write = b.calls.find((c) => c.options?.method === "POST");
    assert.ok(write);
    assert.equal(write.options.body.via, "hub");
    const answer = write.options.body.answer;
    if (kind === "choose") assert.equal(answer.option, 1);
    if (kind === "interview") assert.equal(answer.answers[0].answer, "Developers");
    if (kind === "publish") assert.equal(write.options.body.url, "https://example.org/new-post");
  }
  const retry = await boot("posts", {
    location: { path: "/northwind-retries" },
    route: (url, options) =>
      url.startsWith("posts/") && !options?.method
        ? {
            status: 200,
            body: {
              ...fixture.post,
              waiting_gate: null,
              run: { state: "failed", error: "Writer stopped" },
            },
          }
        : undefined,
  });
  retry.find("editorial-run-again").click();
  await tick();
  assert.ok(
    retry.calls.some(
      (c) => c.url === "posts/northwind-retries/run" && c.options?.method === "POST",
    ),
  );
});
