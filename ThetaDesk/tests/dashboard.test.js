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
    close() {},
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

function loadPage(fetch, confirm) {
  const document = element();
  const html = readFileSync(path.join(__dirname, "../frontend/index.html"), "utf8");
  const ids = new Set(Array.from(html.matchAll(/\bid="([^"]+)"/g), match => match[1]));
  const query = document.querySelector.bind(document);
  document.querySelector = selector => ids.has(selector.slice(1)) ? query(selector) : null;
  document.createElement = element;
  document.createElementNS = element;
  const script = readFileSync(path.join(__dirname, "../frontend/app.js"), "utf8");
  vm.runInNewContext(script, { document, fetch, window: { confirm } });
  return selector => document.querySelector(selector);
}

test("shut down asks first, then covers the page once the server agrees", async () => {
  const requests = [];
  let answer = false;
  const select = loadPage(async (url, options) => {
    requests.push([url, options.method]);
    return { ok: true, status: 202, json: async () => ({ stopping: true }) };
  }, () => answer);

  await select("#shutdown-button").listeners.click();
  assert.deepEqual(requests, []);
  assert.notEqual(select("#stopped").hidden, false);

  answer = true;
  await select("#shutdown-button").listeners.click();
  assert.deepEqual(requests, [["/api/v1/shutdown", "POST"]]);
  assert.equal(select("#stopped").hidden, false);
});

test("a refused shut down keeps the page and shows the reason", async () => {
  const select = loadPage(async () => ({
    ok: false, status: 409, json: async () => ({ detail: "This server was not started by ThetaDesk; stop it with Ctrl+C." }),
  }), () => true);

  await select("#shutdown-button").listeners.click();
  assert.notEqual(select("#stopped").hidden, false);
  assert.match(select("#request-message").textContent, /Could not shut down: .*Ctrl\+C/);
  assert.equal(select("#shutdown-button").disabled, false);
});
