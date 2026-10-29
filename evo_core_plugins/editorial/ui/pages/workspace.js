// Shared editorial controls. Only display labels come from workspace; operational config stays on the server.
(function () {
  "use strict";
  var page = window.page,
    el = page.el,
    t = page.t;
  var data = { stages: [], notebooks: [] },
    unavailable = false;
  function label(kind, name) {
    var found = data[kind].find(function (item) {
      return item.name === name;
    });
    return found ? found.title : name;
  }
  function field(label, control) {
    return el("label", { class: "editorial-control" }, [
      el("span", { class: "evo-label", text: label }),
      control,
    ]);
  }
  function select(items, all, value, props) {
    var node = el("select", Object.assign({ class: "evo-input" }, props), [
      el("option", { value: "", text: all }),
      items.map(function (item) {
        return el("option", { value: item.name, text: item.title });
      }),
    ]);
    if (
      value &&
      !items.some(function (item) {
        return item.name === value;
      })
    )
      node.appendChild(el("option", { value: value, text: value }));
    node.value = value || "";
    return node;
  }
  function navigation(active) {
    return el(
      "nav",
      { class: "editorial-nav", "aria-label": t("workspace.navigation") },
      ["posts", "feedback"].map(function (name) {
        return page.link(
          page.pagePath("editorial", name),
          { "aria-current": name === active ? "page" : null },
          t(name === "posts" ? "posts.title" : "notebook.title"),
        );
      }),
    );
  }
  function intro(active, text, refresh) {
    return el("header", { class: "editorial-intro" }, [
      navigation(active),
      el("div", { class: "page-line" }, [
        el("p", { class: "evo-muted", text: text }),
        el("button", {
          type: "button",
          class: "evo-btn page-end",
          text: t("workspace.refresh"),
          on: { click: refresh },
        }),
      ]),
      unavailable
        ? el("p", {
            class: "evo-small evo-muted",
            role: "status",
            text: t("workspace.unavailable"),
          })
        : null,
    ]);
  }
  function loading() {
    return el("p", {
      class: "evo-muted",
      role: "status",
      text: t("workspace.loading"),
    });
  }
  // The host frame has a 1px border. Measure content, not viewport scrollHeight, so it also shrinks after filtering.
  function followHeight() {
    if (typeof ResizeObserver !== "function") return;
    var observer = new ResizeObserver(function () {
      evo.resize(Math.ceil(document.body.getBoundingClientRect().height) + 2).catch(function () {});
    });
    observer.observe(document.body);
  }
  var evo = window.evo;
  evo.ready.then(followHeight);
  window.editorial = {
    data: function () {
      return data;
    },
    label: label,
    field: field,
    select: select,
    navigation: navigation,
    intro: intro,
    loading: loading,
    ready: function () {
      return page.call("workspace").then(
        function (answer) {
          data = answer;
          unavailable = false;
        },
        function () {
          unavailable = true;
        },
      );
    },
  };
})();
