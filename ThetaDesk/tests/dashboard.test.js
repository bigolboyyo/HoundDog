const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

function element() {
  const childrenBySelector = new Map();
  return {
    children: [],
    listeners: {},
    classList: { toggle() {} },
    addEventListener(name, callback) { this.listeners[name] = callback; },
    append(...children) { this.children.push(...children); },
    replaceChildren(...children) { this.children = children; },
    querySelector(selector) {
      if (!childrenBySelector.has(selector)) childrenBySelector.set(selector, element());
      return childrenBySelector.get(selector);
    },
    querySelectorAll() { return []; },
    setAttribute() {},
  };
}

test("history uses stored bars, renders session dates, and sends a one-time refresh", async () => {
  const document = element();
  const html = readFileSync(path.join(__dirname, "../frontend/index.html"), "utf8");
  const ids = new Set(Array.from(html.matchAll(/\bid="([^"]+)"/g), match => match[1]));
  const query = document.querySelector.bind(document);
  document.querySelector = selector => ids.has(selector.slice(1)) ? query(selector) : null;
  document.createElement = element;
  document.createElementNS = element;
  const select = selector => document.querySelector(selector);
  const requests = [];
  const response = {
    symbol: "AAPL", start_date: "2024-01-02", end_date: "2024-01-05",
    data: [{ session_date: "2024-01-02", open: 187.03, high: 188.44, low: 183.88,
      close: 185.64, volume: 80680243, provider: "sdk" }],
  };
  const script = readFileSync(path.join(__dirname, "../frontend/app.js"), "utf8");
  vm.runInNewContext(script, {
    document,
    async fetch(url, options) {
      requests.push([url, options.method, JSON.parse(options.body)]);
      return { ok: true, headers: new Map(), json: async () => response };
    },
  });

  select("#symbol").value = " aapl ";
  select("#start-date").value = "2024-01-02";
  select("#end-date").value = "2024-01-05";
  select("#refresh-bars").checked = true;
  await select("#lookup-form").listeners.submit({ preventDefault() {} });
  assert.deepEqual(requests, [[
    "/api/v1/stocks/AAPL/bars/fetch", "POST",
    { start_date: "2024-01-02", end_date: "2024-01-05", refresh: true },
  ]]);
  assert.equal(select("#refresh-bars").checked, false);
  assert.equal(select("#chart-card").hidden, false);
  assert.match(select("#chart-accessible-description").textContent, /2024/);
  assert.equal(select("#history-table").querySelector("tbody").children[0].children[0].textContent, "2024-01-02");
});
