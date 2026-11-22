"use strict";

const SYMBOL_PATTERN = /^[A-Z0-9.^_-]{1,16}$/;
const SHORT_TICKER = 3; // Shorter tickers ("A", "IT") match ordinary words.
const SVG_NAMESPACE = "http://www.w3.org/2000/svg";
const CHART = { width: 1000, height: 280, left: 64, right: 16, top: 16, bottom: 32 };
const MAX_EVENTS_SHOWN = 50;
// When all apps start together, HoundDog can take a few seconds longer than the bridge.
const HOUNDDOG_RETRY_MS = 5000;
const HOUNDDOG_RETRIES = 12;

const elements = {
  updated: document.querySelector("#updated"),
  refresh: document.querySelector("#refresh"),
  shutdown: document.querySelector("#shutdown"),
  stopped: document.querySelector("#stopped"),
  banner: document.querySelector("#banner"),
  notice: document.querySelector("#notice"),
  watchOff: document.querySelector("#watch-off"),
  hounddogLive: document.querySelector("#hounddog-live"),
  hounddogFacts: document.querySelector("#hounddog-facts"),
  thetadeskFacts: document.querySelector("#thetadesk-facts"),
  watchForm: document.querySelector("#watch-form"),
  tickerChoices: document.querySelector("#ticker-choices"),
  otherTicker: document.querySelector("#other-ticker"),
  addOther: document.querySelector("#add-other"),
  keywordRows: document.querySelector("#keyword-rows"),
  groupName: document.querySelector("#group-name"),
  groupNames: document.querySelector("#group-names"),
  watchSubmit: document.querySelector("#watch-submit"),
  watchResults: document.querySelector("#watch-results"),
  studyRows: document.querySelector("#study-rows"),
  studyNotes: document.querySelector("#study-notes"),
  detailSymbol: document.querySelector("#detail-symbol"),
  chart: document.querySelector("#chart"),
  detailEvents: document.querySelector("#detail-events"),
};

const state = {
  overview: null,
  // Tickers chosen in the watch form, in order, with the keywords typed for each.
  selected: new Map(),
  extraTickers: [],
  hounddogRetry: { timer: null, attempts: 0 },
};

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { Accept: "application/json", "Content-Type": "application/json" },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(errorDetail(data.detail) || `Request failed (${response.status}).`);
  }
  return data;
}

// FastAPI sends a string, or a list of validation problems.
function errorDetail(detail) {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((problem) => problem.msg).join("; ");
  return "";
}

function element(name, properties = {}, children = []) {
  const node = document.createElement(name);
  Object.assign(node, properties);
  node.append(...children);
  return node;
}

function percent(value) {
  return value === null || value === undefined ? "–" : `${(value * 100).toFixed(2)}%`;
}

function ratio(value) {
  return value === null || value === undefined ? "–" : `${value.toFixed(2)}×`;
}

function localTime(iso) {
  return iso ? new Date(iso).toLocaleString() : "–";
}

function showNotice(message) {
  elements.notice.textContent = message;
  elements.notice.hidden = !message;
}

function setFacts(list, facts) {
  list.replaceChildren(...facts.flatMap(([term, value]) => [
    element("dt", { textContent: term }),
    element("dd", { textContent: value }),
  ]));
}

function renderSources(overview) {
  const news = overview.status.hounddog;
  const market = overview.status.thetadesk;
  const live = overview.hounddog;
  elements.hounddogLive.className = `pill ${live.reachable ? "ok" : "off"}`;
  elements.hounddogLive.textContent = !live.enabled
    ? "Not connected: this config reads exports only"
    : live.reachable
      ? `Running at ${live.url} · ${live.topics.length} topic(s)`
      : "Not running: start HoundDog to add tickers";
  elements.hounddogLive.title = live.error;
  setFacts(elements.hounddogFacts, [
    ["Export folder", news.found ? news.folder : `${news.folder} (not found)`],
    ["Articles", `${news.events} (${news.live_events} live, the rest backfill)`],
    ["Checks", news.checks ? `${news.checks}, last ${localTime(news.last_check)}` : "none yet"],
    ["Topics in checks", news.topics_watched.join(", ") || "none listed yet"],
  ]);
  setFacts(elements.thetadeskFacts, [
    ["Export folder", market.found ? market.folder : `${market.folder} (not found)`],
    ...(market.symbols.length
      ? market.symbols.map((symbol) => [symbol.symbol, `${symbol.bars} sessions, ${symbol.first} to ${symbol.last}`])
      : [["Prices", "none loaded yet"]]),
  ]);
}

function watchedSymbols(overview) {
  return new Set(overview.config.symbols.map((symbol) => symbol.symbol));
}

function choiceSymbols(overview) {
  const priced = overview.status.thetadesk.symbols.map((symbol) => symbol.symbol);
  return [...new Set([...priced, ...state.extraTickers])];
}

function renderWatchForm(overview) {
  const enabled = overview.hounddog.enabled;
  elements.watchForm.hidden = !enabled;
  elements.watchOff.hidden = enabled;
  elements.watchOff.textContent = "Watching tickers is off: this config has no HoundDog connection.";
  const watched = watchedSymbols(overview);
  const topics = new Set(overview.hounddog.topics ?? []);
  const priced = new Set(overview.status.thetadesk.symbols.map((symbol) => symbol.symbol));
  const symbols = choiceSymbols(overview);
  elements.tickerChoices.replaceChildren(...(symbols.length ? symbols.map((symbol) => {
    const box = element("input", { type: "checkbox", value: symbol, checked: state.selected.has(symbol) });
    box.addEventListener("change", () => toggleTicker(symbol, box.checked));
    const tags = [
      !priced.has(symbol) && "no prices yet", watched.has(symbol) && "studied", topics.has(symbol) && "HoundDog topic",
    ].filter(Boolean);
    return element("label", {}, [
      box, ` ${symbol} `, tags.length ? element("span", { className: "tag", textContent: `(${tags.join(", ")})` }) : "",
    ]);
  }) : [element("span", { className: "muted", textContent: "No prices in ThetaDesk yet. Add a ticker below." })]));

  elements.keywordRows.replaceChildren(...[...state.selected].map(([symbol, keywords]) => {
    const input = element("input", { id: `keywords-${symbol}`, value: keywords, placeholder: "e.g. Apple, iPhone" });
    input.addEventListener("input", () => state.selected.set(symbol, input.value));
    const hint = topics.has(symbol)
      ? "HoundDog already has this topic; its keywords stay as they are."
      : symbol.length < SHORT_TICKER
        ? "Short tickers match ordinary words. Use the company name instead."
        : "Comma-separated. Company names catch more headlines than the ticker alone.";
    return element("div", { className: "keyword-row" }, [
      element("label", { htmlFor: input.id, textContent: symbol }),
      input,
      element("span", { className: "hint", textContent: hint }),
    ]);
  }));

  elements.groupNames.replaceChildren(...overview.config.groups.map((group) => element("option", { value: group.name })));
  elements.watchSubmit.disabled = state.selected.size === 0;
}

function toggleTicker(symbol, chosen) {
  if (chosen) {
    state.selected.set(symbol, symbol.length >= SHORT_TICKER ? symbol : "");
  } else {
    state.selected.delete(symbol);
  }
  renderWatchForm(state.overview);
}

function addOtherTicker() {
  const symbol = elements.otherTicker.value.trim().toUpperCase();
  if (!SYMBOL_PATTERN.test(symbol)) {
    showNotice("Enter a ticker of up to 16 letters, digits, or . ^ _ -");
    return;
  }
  showNotice("");
  if (!state.extraTickers.includes(symbol)) state.extraTickers.push(symbol);
  elements.otherTicker.value = "";
  toggleTicker(symbol, true);
}

async function submitWatch(event) {
  event.preventDefault();
  const tickers = [...state.selected].map(([symbol, keywords]) => ({
    symbol,
    keywords: keywords.split(",").map((keyword) => keyword.trim()).filter(Boolean),
  }));
  const empty = tickers.find((ticker) => ticker.keywords.length === 0);
  if (empty) {
    showNotice(`Add at least one keyword for ${empty.symbol}.`);
    return;
  }
  showNotice("");
  elements.watchSubmit.disabled = true;
  try {
    const result = await api("/api/watch", {
      method: "POST",
      body: JSON.stringify({ tickers, group: elements.groupName.value.trim() || null }),
    });
    elements.watchResults.replaceChildren(...result.results.map((entry) =>
      element("li", { className: entry.status, textContent: `${entry.symbol}: ${entry.detail}` })));
    state.selected.clear();
    elements.groupName.value = "";
    await refresh();
  } catch (error) {
    showNotice(error.message);
    elements.watchSubmit.disabled = state.selected.size === 0;
  }
}

function studyRow(name, study, className = "") {
  return element("tr", { className }, [
    element("td", { textContent: name }),
    element("td", { textContent: String(study.news.sessions) }),
    element("td", { textContent: String(study.quiet.sessions) }),
    element("td", { textContent: percent(study.news.mean_abs_change) }),
    element("td", { textContent: percent(study.quiet.mean_abs_change) }),
    element("td", { textContent: ratio(study.news.mean_volume_ratio) }),
    element("td", { textContent: ratio(study.quiet.mean_volume_ratio) }),
    element("td", { textContent: String(study.unwatched_sessions) }),
  ]);
}

function renderStudy(report) {
  const rows = [
    ...report.symbols.map((study) => studyRow(study.symbol, study)),
    ...report.groups.map((group) => studyRow(`${group.name} (${group.symbols.join(", ")})`, group, "group")),
  ];
  elements.studyRows.replaceChildren(...(rows.length ? rows : [element("tr", {}, [
    element("td", { colSpan: 8, textContent: "No tickers studied yet. Watch one above." }),
  ])]));
  const notes = [
    ...report.symbols.flatMap((study) => study.notes.map((note) => `${study.symbol}: ${note}`)),
    ...report.groups.flatMap((group) => group.notes.map((note) => `${group.name}: ${note}`)),
  ];
  elements.studyNotes.replaceChildren(...notes.map((note) => element("li", { textContent: note })));
}

function svg(name, attributes = {}, text = "") {
  const node = document.createElementNS(SVG_NAMESPACE, name);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, String(value));
  if (text) node.textContent = text;
  return node;
}

function renderChart(study) {
  const root = svg("svg", { viewBox: `0 0 ${CHART.width} ${CHART.height}` });
  const points = study ? study.sessions : [];
  if (points.length < 2) {
    root.append(svg("text", { x: CHART.width / 2, y: CHART.height / 2, "text-anchor": "middle", class: "empty" },
      study ? "Not enough prices to chart yet." : "No ticker selected."));
    elements.chart.replaceChildren(root);
    return;
  }
  const closes = points.map((point) => point.close);
  const low = Math.min(...closes);
  const high = Math.max(...closes);
  const span = high - low || 1;
  const plotWidth = CHART.width - CHART.left - CHART.right;
  const plotHeight = CHART.height - CHART.top - CHART.bottom;
  const x = (index) => CHART.left + (index / (points.length - 1)) * plotWidth;
  const y = (close) => CHART.top + (1 - (close - low) / span) * plotHeight;

  root.append(
    svg("line", { x1: CHART.left, x2: CHART.width - CHART.right, y1: y(high), y2: y(high), class: "grid" }),
    svg("line", { x1: CHART.left, x2: CHART.width - CHART.right, y1: y(low), y2: y(low), class: "grid" }),
    svg("text", { x: CHART.left - 8, y: y(high) + 4, "text-anchor": "end", class: "axis" }, high.toFixed(2)),
    svg("text", { x: CHART.left - 8, y: y(low) + 4, "text-anchor": "end", class: "axis" }, low.toFixed(2)),
    svg("text", { x: CHART.left, y: CHART.height - 8, class: "axis" }, points[0].session),
    svg("text", { x: CHART.width - CHART.right, y: CHART.height - 8, "text-anchor": "end", class: "axis" },
      points[points.length - 1].session),
    svg("polyline", { points: points.map((point, index) => `${x(index)},${y(point.close)}`).join(" "), class: "line" }),
  );
  // News last, so its markers sit on top.
  const order = { unwatched: 0, quiet: 1, news: 2 };
  points
    .map((point, index) => ({ point, index }))
    .sort((left, right) => order[left.point.kind] - order[right.point.kind])
    .forEach(({ point, index }) => {
      const marker = svg("circle", {
        cx: x(index), cy: y(point.close), r: point.kind === "news" ? 4.5 : 1.8, class: point.kind,
      });
      marker.append(svg("title", {}, `${point.session}: ${point.close.toFixed(2)} (${percent(point.change)}, ${point.kind})`));
      root.append(marker);
    });
  elements.chart.replaceChildren(root);
}

function safeLink(link) {
  try {
    const url = new URL(link);
    return url.protocol === "http:" || url.protocol === "https:" ? url.href : null;
  } catch {
    return null;
  }
}

function renderEvents(study) {
  const events = study ? [...study.events].reverse().slice(0, MAX_EVENTS_SHOWN) : [];
  elements.detailEvents.replaceChildren(...(events.length ? events.map((event) => {
    const href = safeLink(event.link);
    const title = href
      ? element("a", { href, textContent: event.title || event.link, target: "_blank", rel: "noopener noreferrer" })
      : element("span", { textContent: event.title || event.link });
    return element("li", {}, [
      element("time", { dateTime: event.detected_at, textContent: localTime(event.detected_at) }),
      element("span", { className: "topic", textContent: `[${event.topic}] session ${event.session}` }),
      title,
    ]);
  }) : [element("li", { className: "muted", textContent: "No live articles for this ticker yet." })]));
}

function renderDetail(report) {
  const current = elements.detailSymbol.value;
  elements.detailSymbol.replaceChildren(...report.symbols.map((study) =>
    element("option", { value: study.symbol, textContent: study.symbol })));
  if (report.symbols.some((study) => study.symbol === current)) elements.detailSymbol.value = current;
  const study = report.symbols.find((entry) => entry.symbol === elements.detailSymbol.value);
  renderChart(study);
  renderEvents(study);
}

function render() {
  const overview = state.overview;
  elements.banner.textContent = overview.display.banner;
  elements.banner.hidden = !overview.display.banner;
  renderSources(overview);
  renderWatchForm(overview);
  renderStudy(overview.report);
  renderDetail(overview.report);
}

// Recheck a HoundDog that is not reachable yet, unless the user is filling in the form.
function scheduleHoundDogRetry() {
  const retry = state.hounddogRetry;
  window.clearTimeout(retry.timer);
  retry.timer = null;
  if (state.overview.hounddog.reachable || !state.overview.hounddog.enabled) {
    retry.attempts = 0;
    return;
  }
  if (retry.attempts >= HOUNDDOG_RETRIES) return;
  retry.attempts += 1;
  retry.timer = window.setTimeout(() => {
    if (state.selected.size === 0) refresh();
  }, HOUNDDOG_RETRY_MS);
}

async function refresh() {
  elements.refresh.disabled = true;
  try {
    state.overview = await api("/api/overview");
    render();
    scheduleHoundDogRetry();
    elements.updated.textContent = `Updated ${new Date().toLocaleTimeString()}`;
  } catch (error) {
    showNotice(error.message);
  } finally {
    elements.refresh.disabled = false;
  }
}

async function shutDown() {
  if (!window.confirm("Shut down the bridge? This page stops working until you start it again.")) return;
  elements.shutdown.disabled = true;
  try {
    await api("/api/shutdown", { method: "POST", body: "{}" });
  } catch (error) {
    showNotice(`Could not shut down: ${error.message}`);
    elements.shutdown.disabled = false;
    return;
  }
  window.clearTimeout(state.hounddogRetry.timer);
  state.hounddogRetry.attempts = HOUNDDOG_RETRIES;
  elements.stopped.hidden = false;
}

elements.refresh.addEventListener("click", () => {
  showNotice("");
  refresh();
});
elements.shutdown.addEventListener("click", shutDown);
elements.addOther.addEventListener("click", addOtherTicker);
elements.otherTicker.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    addOtherTicker();
  }
});
elements.watchForm.addEventListener("submit", submitWatch);
elements.detailSymbol.addEventListener("change", () => renderDetail(state.overview.report));

refresh();
