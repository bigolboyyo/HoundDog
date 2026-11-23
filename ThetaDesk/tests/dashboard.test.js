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
    showModal() {},
  };
}

const BAR = { session_date: "2024-01-02", open: 187.03, high: 188.44, low: 183.88,
  close: 185.64, volume: 80680243, provider: "sdk" };
const STORED = { symbol: "AAPL", start_date: "2024-01-02", end_date: "2024-01-05", data: [BAR] };

// Runs app.js against a fake DOM built from index.html's ids. answer(url, method, body)
// returns [status, payload] for each request; requests are recorded in order.
async function loadPage(answer, { confirm = () => true } = {}) {
  const document = element();
  const html = readFileSync(path.join(__dirname, "../frontend/index.html"), "utf8");
  const ids = new Set(Array.from(html.matchAll(/\bid="([^"]+)"/g), match => match[1]));
  const query = document.querySelector.bind(document);
  document.querySelector = selector => ids.has(selector.slice(1)) ? query(selector) : null;
  document.createElement = element;
  document.createElementNS = element;
  const requests = [];
  const script = readFileSync(path.join(__dirname, "../frontend/app.js"), "utf8");
  vm.runInNewContext(script, {
    document,
    window: { confirm },
    async fetch(url, options = {}) {
      const body = options.body === undefined ? undefined : JSON.parse(options.body);
      const method = options.method ?? "GET";
      requests.push([url, method, body]);
      const [status, payload] = await answer(url, method, body);
      return { ok: status < 400, status, headers: new Map(), json: async () => payload };
    },
  });
  await new Promise((resolve) => setImmediate(resolve));
  return { select: selector => document.querySelector(selector), requests };
}

// A ThetaDesk with nothing saved, plus any routes a test overrides.
function server(routes = {}) {
  return (url, method, body) => {
    const key = `${method} ${url.split("?")[0]}`;
    if (key in routes) return routes[key](url, body);
    if (key === "GET /api/v1/pins") return [200, { pins: [] }];
    if (key === "GET /api/v1/stocks/loaded") return [200, { symbols: [] }];
    return [404, { detail: `no route for ${key}` }];
  };
}

test("history uses stored bars, renders session dates, and sends a one-time refresh", async () => {
  const { select, requests } = await loadPage(server({
    "POST /api/v1/stocks/AAPL/bars/fetch": () => [200, STORED],
  }));

  select("#symbol").value = " aapl ";
  select("#start-date").value = "2024-01-02";
  select("#end-date").value = "2024-01-05";
  select("#refresh-bars").checked = true;
  await select("#lookup-form").listeners.submit({ preventDefault() {} });
  assert.deepEqual(requests.filter(([url]) => url.includes("/bars/fetch")), [[
    "/api/v1/stocks/AAPL/bars/fetch", "POST",
    { start_date: "2024-01-02", end_date: "2024-01-05", refresh: true },
  ]]);
  assert.equal(select("#refresh-bars").checked, false);
  assert.equal(select("#chart-card").hidden, false);
  assert.match(select("#chart-accessible-description").textContent, /2024/);
  assert.equal(select("#history-table").querySelector("tbody").children[0].children[0].textContent, "2024-01-02");
  // The loaded tickers list is refreshed after a lookup.
  assert.equal(requests.filter(([url]) => url === "/api/v1/stocks/loaded").length, 2);
});

test("saved pins are redrawn from stored bars when the page opens", async () => {
  const { select, requests } = await loadPage(server({
    "GET /api/v1/pins": () => [200, { pins: [{ symbol: "AAPL", start_date: "2024-01-02", end_date: "2024-01-05" }] }],
    "GET /api/v1/stocks/AAPL/bars": () => [200, STORED],
  }));

  assert.ok(requests.some(([url]) => url === "/api/v1/stocks/AAPL/bars?start_date=2024-01-02&end_date=2024-01-05"));
  assert.ok(!requests.some(([url]) => url.includes("/bars/fetch")), "opening the page must not call ThetaData");
  const [card] = select("#pins-list").children;
  assert.equal(card.className, "pinned-summary");
  assert.equal(select("#empty-pins").hidden, true);
  assert.equal(select("#clear-pins").hidden, false);
});

test("pinning saves the summary's ticker and dates, and unpinning removes it", async () => {
  const { select, requests } = await loadPage(server({
    "POST /api/v1/stocks/AAPL/bars/fetch": () => [200, STORED],
    "POST /api/v1/pins": (url, body) => [201, body],
    "DELETE /api/v1/pins/AAPL/2024-01-02/2024-01-05": () => [200, { removed: 1 }],
  }));
  select("#symbol").value = "AAPL";
  select("#start-date").value = "2024-01-02";
  select("#end-date").value = "2024-01-05";
  await select("#lookup-form").listeners.submit({ preventDefault() {} });

  await select("#pin-summary").listeners.click();
  assert.deepEqual(requests.at(-1), ["/api/v1/pins", "POST", { symbol: "AAPL", start_date: "2024-01-02", end_date: "2024-01-05" }]);
  assert.equal(select("#pin-summary").textContent, "Unpin summary");
  assert.equal(select("#pins-list").children.length, 1);

  await select("#pin-summary").listeners.click();
  assert.deepEqual(requests.at(-1), ["/api/v1/pins/AAPL/2024-01-02/2024-01-05", "DELETE", undefined]);
  assert.equal(select("#pin-summary").textContent, "Pin summary");
});

test("a pin the server refuses is not shown as pinned", async () => {
  const { select } = await loadPage(server({
    "POST /api/v1/stocks/AAPL/bars/fetch": () => [200, STORED],
    "POST /api/v1/pins": () => [403, { detail: "Pin changes are available only from this device." }],
  }));
  select("#symbol").value = "AAPL";
  select("#start-date").value = "2024-01-02";
  select("#end-date").value = "2024-01-05";
  await select("#lookup-form").listeners.submit({ preventDefault() {} });

  await select("#pin-summary").listeners.click();
  assert.equal(select("#pin-summary").textContent, "Pin summary");
  assert.match(select("#request-message").textContent, /Could not pin AAPL: .*this device/);
});

test("loaded tickers are listed and open their latest year from stored bars", async () => {
  const { select, requests } = await loadPage(server({
    "GET /api/v1/stocks/loaded": () => [200, { symbols: [
      { symbol: "AAPL", interval: "1d", bars: 500, first_session: "2023-01-03", last_session: "2024-12-31" },
      { symbol: "MSFT", interval: "1d", bars: 3, first_session: "2024-01-02", last_session: "2024-01-05" },
    ] }],
    "GET /api/v1/stocks/AAPL/bars": () => [200, { ...STORED, start_date: "2024-01-01", end_date: "2024-12-31" }],
    "GET /api/v1/stocks/MSFT/bars": () => [200, { ...STORED, symbol: "MSFT" }],
  }));
  const [aapl, msft] = select("#loaded-list").children;
  assert.equal(select("#empty-loaded").hidden, true);
  assert.equal(aapl.children[0].textContent, "AAPL");
  assert.equal(aapl.children[1].textContent, "2023-01-03 — 2024-12-31 · 500 bars");

  await aapl.listeners.click();
  assert.equal(requests.at(-1)[0], "/api/v1/stocks/AAPL/bars?start_date=2024-01-01&end_date=2024-12-31");
  assert.equal(select("#symbol").value, "AAPL");
  assert.equal(select("#start-date").value, "2024-01-01");
  assert.match(select("#request-message").textContent, /ThetaData was not called/);

  await msft.listeners.click();
  assert.equal(requests.at(-1)[0], "/api/v1/stocks/MSFT/bars?start_date=2024-01-02&end_date=2024-01-05");
  assert.ok(!requests.some(([url]) => url.includes("/bars/fetch")));
});

test("shut down asks first, then covers the page once the server agrees", async () => {
  let answer = false;
  const { select, requests } = await loadPage(server({
    "POST /api/v1/shutdown": () => [202, { stopping: true }],
  }), { confirm: () => answer });
  const shutdowns = () => requests.filter(([url]) => url === "/api/v1/shutdown");

  await select("#shutdown-button").listeners.click();
  assert.equal(shutdowns().length, 0);
  assert.notEqual(select("#stopped").hidden, false);

  answer = true;
  await select("#shutdown-button").listeners.click();
  assert.deepEqual(shutdowns(), [["/api/v1/shutdown", "POST", undefined]]);
  assert.equal(select("#stopped").hidden, false);
});

test("a refused shut down keeps the page and shows the reason", async () => {
  const { select } = await loadPage(server({
    "POST /api/v1/shutdown": () => [409, { detail: "This server was not started by ThetaDesk; stop it with Ctrl+C." }],
  }));

  await select("#shutdown-button").listeners.click();
  assert.notEqual(select("#stopped").hidden, false);
  assert.match(select("#request-message").textContent, /Could not shut down: .*Ctrl\+C/);
  assert.equal(select("#shutdown-button").disabled, false);
});

test("a lookup that answers late does not replace a newer choice", async () => {
  let answerAapl;
  const aaplAnswered = new Promise((resolve) => { answerAapl = resolve; });
  const { select } = await loadPage(server({
    "POST /api/v1/stocks/AAPL/bars/fetch": () => aaplAnswered,
    "GET /api/v1/stocks/loaded": () => [200, { symbols: [
      { symbol: "MSFT", interval: "1d", bars: 3, first_session: "2024-01-02", last_session: "2024-01-05" },
    ] }],
    "GET /api/v1/stocks/MSFT/bars": () => [200, { ...STORED, symbol: "MSFT" }],
  }));
  select("#symbol").value = "AAPL";
  select("#start-date").value = "2024-01-02";
  select("#end-date").value = "2024-01-05";
  const lookup = select("#lookup-form").listeners.submit({ preventDefault() {} });

  await select("#loaded-list").children[0].listeners.click();
  answerAapl([200, STORED]);
  await lookup;

  assert.equal(select("#symbol").value, "MSFT");
  assert.match(select("#request-message").textContent, /Opened MSFT/);
  assert.equal(select("#chart-title").textContent, "MSFT closing price");
});

test("settings show what is saved without the secrets, and blanks keep them", async () => {
  const saved = { api_key_configured: true, credentials_configured: true, email: "user@example.test" };
  const { select, requests } = await loadPage(server({
    "GET /api/v1/settings/credentials": () => [200, saved],
    "PUT /api/v1/settings/credentials": () => [200, { saved: true, ...saved }],
  }));

  await select("#open-settings").listeners.click();
  assert.equal(select("#settings-api-key").value, "");
  assert.equal(select("#settings-password").value, "");
  assert.equal(select("#settings-email").value, "user@example.test");
  assert.match(select("#settings-api-key").placeholder, /Leave blank to keep/);
  assert.equal(select("#clear-api-key").hidden, false);
  assert.equal(select("#clear-credentials").hidden, false);

  await select("#settings-form").listeners.submit({ preventDefault() {} });
  assert.deepEqual(requests.at(-1), ["/api/v1/settings/credentials", "PUT",
    { api_key: "", email: "user@example.test", password: "" }]);
});

test("removing a saved key asks the server to clear it", async () => {
  const { select, requests } = await loadPage(server({
    "GET /api/v1/settings/credentials": () => [200, { api_key_configured: true, credentials_configured: false, email: "" }],
    "PUT /api/v1/settings/credentials": () => [200,
      { saved: true, api_key_configured: false, credentials_configured: false, email: "" }],
  }));
  await select("#open-settings").listeners.click();
  assert.equal(select("#clear-credentials").hidden, true);

  await select("#clear-api-key").listeners.click();

  assert.deepEqual(requests.at(-1), ["/api/v1/settings/credentials", "PUT", { clear_api_key: true }]);
  assert.equal(select("#clear-api-key").hidden, true);
  assert.equal(select("#settings-api-key").placeholder, "Not set");
  assert.match(select("#settings-status").textContent, /Removed the API key\. No saved credentials/);
});
