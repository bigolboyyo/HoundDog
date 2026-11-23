"use strict";

const SYMBOL_PATTERN = /^[A-Z0-9.^_-]{1,16}$/;
const SHORT_TICKER = 3; // Shorter tickers ("A", "IT") match ordinary words.
const SVG_NAMESPACE = "http://www.w3.org/2000/svg";
const CHART = { width: 1000, height: 340, left: 80, right: 16, top: 20, bottom: 36 };
const PLOT_WIDTH = CHART.width - CHART.left - CHART.right;
const CHART_PRESETS = {
  "1m": { months: 1, label: "Past month" },
  "3m": { months: 3, label: "Past 3 months" },
  "6m": { months: 6, label: "Past 6 months" },
  "1y": { months: 12, label: "Past year" },
};
const EASTERN_TIME = new Intl.DateTimeFormat(undefined, {
  timeZone: "America/New_York",
  dateStyle: "medium",
  timeStyle: "short",
});
const EASTERN_DATE = new Intl.DateTimeFormat("en", {
  timeZone: "America/New_York", year: "numeric", month: "2-digit", day: "2-digit",
});
const WEEK_DATE = new Intl.DateTimeFormat(undefined, {
  timeZone: "UTC", month: "short", day: "numeric", year: "numeric",
});
const WEEKDAY_DATE = new Intl.DateTimeFormat(undefined, {
  timeZone: "UTC", weekday: "short", month: "short", day: "numeric",
});
const WEEKDAY = new Intl.DateTimeFormat(undefined, { timeZone: "UTC", weekday: "short" });
const EASTERN_CLOCK = new Intl.DateTimeFormat(undefined, { timeZone: "America/New_York", timeStyle: "short" });
const CLOSE_PRICE = new Intl.NumberFormat(undefined, { style: "currency", currency: "USD" });
const SESSION_LABELS = {
  news: "News",
  quiet: "Quiet",
  unwatched: "No qualifying check",
};
const MARKET_LABELS = {
  first_price_session: "First saved close",
  missing_bar: "Missing bar",
  missing_previous_bar: "Previous bar missing",
  invalid_previous_close: "Invalid previous close",
};
const ARTICLE_STATUS_LABELS = {
  in_study: "In study",
  awaiting_close: "Awaiting close",
  first_price_session: "First saved close",
  before_price_history: "Before saved prices",
  no_price_history: "No saved prices",
  outside_coverage: "Closed · no recorded price lookup",
  missing_bar: "Missing daily bar",
  missing_previous_bar: "Missing prior bar",
  invalid_previous_close: "Invalid prior close",
  weekend: "Weekend news",
};
const MARKET_EXCLUSIONS = {
  first_price_session: "This close is the starting point for calculating daily returns.",
  before_price_history: "This session is earlier than the ticker’s first saved close.",
  no_price_history: "This ticker has no saved daily closes yet.",
  missing_bar: "ThetaDesk looked up this session, but its daily bar is missing.",
  missing_previous_bar: "The previous trading session’s bar is missing.",
  invalid_previous_close: "The previous trading session’s close could not be used to calculate a return.",
  outside_coverage: "This session has closed. Bridge has no record of a completed price lookup for that date.",
};
const PLACEMENT_REASONS = {
  before_close: "Found before the close and assigned to that day’s session.",
  at_or_after_close: "Found at or after the close and assigned to the next trading session.",
  market_closed: "The exchange was closed that day, so the article went to the next trading session.",
};
// When all apps start together, HoundDog can take a few seconds longer than the bridge.
const HOUNDDOG_RETRY_MS = 5000;
const HOUNDDOG_RETRIES = 12;

const elements = {
  today: document.querySelector("#today"),
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
  watchLoad: document.querySelector("#watch-load"),
  watchResults: document.querySelector("#watch-results"),
  watchlist: document.querySelector("#watchlist"),
  marketTarget: document.querySelector("#market-target"),
  pinsPanel: document.querySelector("#pins-panel"),
  pinsList: document.querySelector("#pins-list"),
  pinStatus: document.querySelector("#pin-status"),
  studyRows: document.querySelector("#study-rows"),
  studyNotes: document.querySelector("#study-notes"),
  studyNotesPanel: document.querySelector("#study-notes-panel"),
  articleStatusScope: document.querySelector("#article-status-scope"),
  articleStatusList: document.querySelector("#article-status-list"),
  detailTitle: document.querySelector("#detail-title"),
  viewControls: document.querySelector("#view-controls"),
  rangePresets: Array.from(document.querySelectorAll("#range-presets button")),
  viewKind: document.querySelector("#view-kind"),
  currentWeek: document.querySelector("#current-week"),
  newsPeriod: document.querySelector("#news-period"),
  dataFreshness: document.querySelector("#data-freshness"),
  detailClose: document.querySelector("#detail-close"),
  pricesThrough: document.querySelector("#prices-through"),
  lastNewsCheck: document.querySelector("#last-news-check"),
  priceReadiness: document.querySelector("#price-readiness"),
  rangeForm: document.querySelector("#range-form"),
  rangeStart: document.querySelector("#range-start"),
  rangeEnd: document.querySelector("#range-end"),
  rangeReset: document.querySelector("#range-reset"),
  rangeAll: document.querySelector("#range-all"),
  rangeTools: document.querySelector("#range-tools"),
  pinRange: document.querySelector("#pin-range"),
  rangeStatus: document.querySelector("#range-status"),
  detailCounts: document.querySelector("#detail-counts"),
  detailSessions: document.querySelector("#detail-sessions"),
  chart: document.querySelector("#chart"),
  chartKey: document.querySelector("#chart-key"),
  dailyMoves: document.querySelector("#daily-moves"),
  dailyReturns: document.querySelector("#daily-returns"),
  dailyVolumePanel: document.querySelector("#daily-volume-panel"),
  dailyVolume: document.querySelector("#daily-volume"),
  moveComparison: document.querySelector("#move-comparison"),
  moveScale: document.querySelector("#move-scale"),
  moveScaleMax: document.querySelector("#move-scale-max"),
  newsMoveSummary: document.querySelector("#news-move-summary"),
  newsMoveDots: document.querySelector("#news-move-dots"),
  quietMoveSummary: document.querySelector("#quiet-move-summary"),
  quietMoveDots: document.querySelector("#quiet-move-dots"),
  moveComparisonNote: document.querySelector("#move-comparison-note"),
  studyDetails: document.querySelector("#study-details"),
  coverageStrip: document.querySelector("#coverage-strip"),
  coverageKey: document.querySelector("#coverage-key"),
  coverageSpan: document.querySelector("#coverage-span"),
  coverageSummary: document.querySelector("#coverage-summary"),
  sessionEvidence: document.querySelector("#session-evidence"),
  weeklyNews: document.querySelector("#weekly-news"),
  weekPrev: document.querySelector("#week-prev"),
  weekNext: document.querySelector("#week-next"),
  weekDates: document.querySelector("#week-dates"),
  weekdaysNews: document.querySelector("#weekdays-news"),
  fullWeekNews: document.querySelector("#full-week-news"),
  weeklyNewsCount: document.querySelector("#weekly-news-count"),
  weeklyNewsList: document.querySelector("#weekly-news-list"),
  weekendNews: document.querySelector("#weekend-news"),
  weekendNewsList: document.querySelector("#weekend-news-list"),
  detailEvents: document.querySelector("#detail-events"),
};

const state = {
  overview: null,
  // Tickers chosen in the watch form, in order, with the keywords typed for each.
  selected: new Map(),
  extraTickers: [],
  priceRequests: new Map(),
  watchBusy: false,
  refreshId: 0,
  detailRequestId: 0,
  detailSymbol: "",
  rangePreset: "week",
  range: null,
  session: "",
  coverageDay: "",
  pinStudy: null,
  pins: [],
  pinsError: "",
  pinsRequestId: 0,
  pinSaveBusy: false,
  detailView: null,
  detailStudy: null,
  weeklyNews: { events: [], weekendEvents: [], week: "", includeWeekend: false },
  hounddogRetry: { timer: null, attempts: 0 },
};

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { Accept: "application/json", "Content-Type": "application/json" },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const retry = response.status === 429 ? response.headers.get("Retry-After") : null;
    const message = errorDetail(data.detail) || `Request failed (${response.status}).`;
    throw new Error(retry && !message.toLowerCase().includes("retry")
      ? `${message} Retry in ${retry} seconds.` : message);
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
  const { symbols, groups } = overview.report;
  const notes = [
    ...symbols.flatMap((study) => study.notes.map((note) => `${study.symbol}: ${note}`)),
    ...groups.flatMap((group) => group.notes.map((note) => `${group.name}: ${note}`)),
  ];
  elements.studyNotes.replaceChildren(...notes.map((note) => element("li", { textContent: note })));
  elements.studyNotes.hidden = !notes.length;
}

function watchedSymbols(overview) {
  return new Set(overview.config.symbols.map((symbol) => symbol.symbol));
}

function renderWatchlist(overview) {
  const target = overview.thetadesk.latest_session;
  elements.marketTarget.textContent = `Latest NYSE close · ${WEEKDAY_DATE.format(dateAtUtcMidnight(target))}`;
  const cards = overview.watchlist.map((item) => {
    const request = state.priceRequests.get(item.symbol);
    const refresh = Boolean(request?.retry || item.missing_bars);
    const stale = !item.price_session || item.price_session < target;
    const date = item.price_session ? WEEKDAY_DATE.format(dateAtUtcMidnight(item.price_session)) : "No saved close";
    const close = item.last_close === null ? "—" : CLOSE_PRICE.format(item.last_close);
    const title = element("button", {
      type: "button", className: "ticker-select", title: `${item.symbol} · ${date}`,
    }, [
      element("strong", { textContent: item.symbol }),
      element("span", { textContent: close }),
    ]);
    title.dataset.symbol = item.symbol;
    title.setAttribute("aria-pressed", String(item.symbol === state.detailSymbol));
    title.addEventListener("click", () => openStudy(item.symbol, false));
    const actions = [];
    if (overview.thetadesk.enabled && (stale || refresh || request?.pending)) {
      const label = !item.price_session ? "Load price history" : refresh ? "Retry missing bars" : "Update through latest close";
      const load = element("button", {
        type: "button", className: "ticker-load", title: label, disabled: Boolean(request?.pending),
        textContent: request?.pending ? "Loading…" : !item.price_session ? "Load" : refresh ? "Retry" : "Update",
      });
      load.setAttribute("aria-label", `${label} for ${item.symbol}`);
      load.addEventListener("click", () => loadPrice(item.symbol, refresh, {
        after: !refresh ? item.price_session : null,
      }));
      actions.push(load);
    }
    const status = item.missing_bars
      ? `${item.missing_bars} price ${item.missing_bars === 1 ? "gap" : "gaps"}`
      : item.price_session ? date : "No saved prices";
    return element("article", { className: "ticker-card" }, [
      title,
      element("div", { className: "ticker-meta" }, [
        element("span", { className: stale || refresh ? "ticker-pending" : "muted", textContent: status }),
        ...actions,
      ]),
      ...(request?.message ? [element("p", {
        className: request.error ? "ticker-message action-error" : "ticker-message muted", textContent: request.message,
      })] : []),
    ]);
  });
  elements.watchlist.replaceChildren(...(cards.length ? cards : [
    element("p", { className: "muted", textContent: "Watch a ticker to track its prices and news coverage here." }),
  ]));
}

function renderWatchButtons(overview) {
  elements.watchSubmit.disabled = state.watchBusy || state.selected.size === 0;
  elements.watchLoad.hidden = !overview.thetadesk.enabled;
  elements.watchLoad.disabled = elements.watchSubmit.disabled;
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
  renderWatchButtons(overview);
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
  if (state.watchBusy) return;
  const load = event.submitter === elements.watchLoad;
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
  state.watchBusy = true;
  renderWatchButtons(state.overview);
  try {
    const result = await api("/api/watch", {
      method: "POST",
      body: JSON.stringify({ tickers, group: elements.groupName.value.trim() || null }),
    });
    const watched = result.results.filter((entry) => entry.status !== "failed");
    elements.watchResults.replaceChildren(...result.results.map((entry) =>
      element("li", { className: entry.status, textContent: `${entry.symbol}: ${entry.detail}` })));
    watched.forEach((entry) => state.selected.delete(entry.symbol));
    if (state.selected.size === 0) elements.groupName.value = "";
    await refresh();
    if (load) {
      for (const { symbol } of watched) await loadPrice(symbol, false, { refreshPage: false });
      await refresh();
    }
  } catch (error) {
    showNotice(error.message);
  } finally {
    state.watchBusy = false;
    renderWatchForm(state.overview);
  }
}

async function loadPrice(symbol, recheck, { refreshPage = true, after = null } = {}) {
  if (state.priceRequests.get(symbol)?.pending) return;
  state.priceRequests.set(symbol, { pending: true });
  renderWatchlist(state.overview);
  try {
    const result = await api(`/api/prices/${encodeURIComponent(symbol)}/fetch`, {
      method: "POST", body: JSON.stringify({ refresh: recheck, after }),
    });
    const missingLatest = !result.latest_bar || result.latest_bar < result.end_date;
    const pendingLatest = missingLatest && (!result.covered_through || result.covered_through < result.end_date);
    const summary = result.bars ? `${result.bars} saved bars · ${result.added} added` : "";
    state.priceRequests.set(symbol, {
      message: [summary, pendingLatest ? `Daily bar for ${result.end_date} is pending.` : ""]
        .filter(Boolean).join(" · ") || "ThetaDesk returned no bars in this range.",
      retry: missingLatest && !pendingLatest,
    });
  } catch (error) {
    state.priceRequests.set(symbol, { error: true, message: error.message });
  }
  renderWatchlist(state.overview);
  if (refreshPage) await refresh();
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
    element("td", { className: "verdict", textContent: study.verdict ?? "" }),
  ]);
}

function articlePriceStatus(event) {
  if (event.price_status) return event.price_status;
  // Static assets can update before the running Bridge process is restarted.
  if (event.has_move) return "in_study";
  if (event.session > state.overview.thetadesk.latest_session) return "awaiting_close";
  return event.exclusion;
}

function countArticleStatus(events) {
  const counts = new Map();
  for (const event of events) {
    const status = articlePriceStatus(event);
    counts.set(status, (counts.get(status) ?? 0) + 1);
  }
  return counts;
}

function renderArticleStatus(studies) {
  const last = state.overview.thetadesk.latest_session;
  elements.articleStatusScope.textContent =
    `All saved live detections · Latest NYSE close ${WEEK_DATE.format(dateAtUtcMidnight(last))}`;
  const totals = studies.map((study) => study.events.length + (study.weekend_events?.length ?? 0));
  const scale = Math.max(1, ...totals);
  elements.articleStatusList.replaceChildren(...studies.map((study, index) => {
    const counts = countArticleStatus(study.events);
    counts.set("weekend", study.weekend_events?.length ?? 0);
    const awaitingDates = [...new Set(study.events
      .filter((event) => articlePriceStatus(event) === "awaiting_close")
      .map((event) => event.session))].sort();
    const afterClose = study.events.filter((event) => event.placement === "at_or_after_close").length;
    const total = totals[index];
    const bar = svg("svg", { viewBox: `0 0 ${scale} 10`, preserveAspectRatio: "none", "aria-hidden": true });
    const labels = [];
    let offset = 0;
    for (const [status, name] of Object.entries(ARTICLE_STATUS_LABELS)) {
      const count = counts.get(status);
      if (!count) continue;
      const segment = svg("rect", {
        x: offset, y: 0, width: count, height: 10, class: `article-status-color ${status}`,
      });
      segment.append(svg("title", {}, `${name} · ${count}`));
      bar.append(segment);
      offset += count;
      const dates = status === "awaiting_close"
        ? ` · ${awaitingDates.map((day) => WEEK_DATE.format(dateAtUtcMidnight(day))).join(", ")}`
        : "";
      const swatch = element("span", { className: `article-status-color ${status}` });
      swatch.setAttribute("aria-hidden", "true");
      labels.push(element("li", { className: "article-status-label" }, [
        swatch, element("strong", { textContent: count }), ` ${name}${dates}`,
      ]));
    }
    return element("li", { className: "article-status-row" }, [
      element("div", { className: "article-status-ticker" }, [
        element("strong", { textContent: study.symbol }),
        element("span", { className: "muted", textContent: `${total} live ${total === 1 ? "article" : "articles"}` }),
      ]),
      ...(total ? [
        bar,
        element("ul", { className: "article-status-labels" }, labels),
      ] : []),
      ...(afterClose ? [element("small", {
        className: "article-status-after-close",
        title: "These weekday detections are included in the status bar above.",
      }, [element("strong", { textContent: afterClose }), " after close → next trading session"])] : []),
    ]);
  }));
}

function renderStudy(report) {
  const rows = [
    ...report.symbols.map((study) => studyRow(study.symbol, study)),
    ...report.groups.map((group) => studyRow(`${group.name} (${group.symbols.join(", ")})`, group, "group")),
  ];
  elements.studyRows.replaceChildren(...(rows.length ? rows : [element("tr", {}, [
    element("td", { colSpan: 8, textContent: "No tickers studied yet. Watch one above." }),
  ])]));
  renderArticleStatus(report.symbols);
  elements.studyNotesPanel.hidden = !report.symbols.length;
}

function svg(name, attributes = {}, text = "") {
  const node = document.createElementNS(SVG_NAMESPACE, name);
  for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, String(value));
  if (text) node.textContent = text;
  return node;
}

function makeDetailView(study) {
  if (!study) return null;
  const weekly = isWeeklyView();
  const range = chartRange();
  const within = (day) => day >= range.first && day <= range.last;
  const pin = state.pinStudy;
  const pinRange = state.range && pin?.study.symbol === study.symbol &&
    range.first === pin.range.first && range.last === pin.range.last;
  const prices = (pinRange ? pin.prices : study.prices).filter((point) => within(point.session));
  const detail = { ...study,
    range,
    weekly,
    prices,
    sessions: study.sessions.filter((point) => within(point.session)),
    excluded_sessions: study.excluded_sessions.filter((point) => within(point.session)),
    missing_bars: study.missing_bars.filter(within),
    events: study.events.filter((event) => within(event.session)),
  };
  const timeline = new Map(prices.map((point) => [point.session, point]));
  for (const point of detail.excluded_sessions) {
    const price = timeline.get(point.session);
    timeline.set(point.session, { ...point, close: price?.close ?? point.close });
  }
  for (const point of detail.sessions) timeline.set(point.session, point);
  if (!weekly) {
    detail.points = [...timeline.values()].sort((left, right) => left.session.localeCompare(right.session));
  } else {
    const prior = study.prices.findLast((point) => point.session < range.first);
    detail.baseline = prior ? { ...prior, baseline: true } : null;
    detail.points = [
      ...(detail.baseline ? [detail.baseline] : []),
      ...Array.from({ length: 5 }, (_, offset) => {
        const day = shiftDay(range.first, offset);
        return timeline.get(day) ?? { session: day, close: null };
      }),
    ];
  }
  return detail;
}

function easternDate(iso) {
  const parts = EASTERN_DATE.formatToParts(new Date(iso));
  const names = Object.fromEntries(parts.map(({ type, value }) => [type, value]));
  return `${names.year}-${names.month}-${names.day}`;
}

function dateAtUtcMidnight(day) {
  return new Date(`${day}T00:00:00Z`);
}

function shiftDay(day, days) {
  const date = dateAtUtcMidnight(day);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

function shiftMonths(day, months) {
  const date = dateAtUtcMidnight(day);
  const originalDay = date.getUTCDate();
  date.setUTCDate(1);
  date.setUTCMonth(date.getUTCMonth() + months);
  const lastDay = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth() + 1, 0)).getUTCDate();
  date.setUTCDate(Math.min(originalDay, lastDay));
  return date.toISOString().slice(0, 10);
}

function weekStart(day) {
  const weekday = dateAtUtcMidnight(day).getUTCDay();
  return shiftDay(day, -((weekday + 6) % 7));
}

function currentNewsWeek() {
  return weekStart(easternDate(new Date().toISOString()));
}

function activeWeek() {
  return state.weeklyNews.week || currentNewsWeek();
}

function isWeeklyView() {
  return !state.range && state.rangePreset === "week";
}

function chartRange() {
  if (state.range) return state.range;
  if (isWeeklyView()) {
    const week = activeWeek();
    return { first: week, last: shiftDay(week, 4) };
  }
  const today = easternDate(new Date().toISOString());
  return { first: shiftMonths(today, -CHART_PRESETS[state.rangePreset].months), last: today };
}

function dateSpan(first, last) {
  return WEEK_DATE.formatRange(dateAtUtcMidnight(first), dateAtUtcMidnight(last));
}

function sessionX(index, count) {
  return CHART.left + ((index + 0.5) / count) * PLOT_WIDTH;
}

function renderChart(view) {
  const points = view?.points ?? [];
  const closes = points.flatMap((point) => point.close === null ? [] : [point.close]);
  const news = points.filter((point) => point.kind === "news" && point.close !== null);
  elements.chartKey.hidden = !news.length;
  if (!closes.length) {
    elements.chart.replaceChildren(element("p", {
      className: "chart-empty muted",
      textContent: view ? "No saved prices for this range." : "Watch a ticker to see its prices and news here.",
    }));
    return;
  }
  const root = svg("svg", { viewBox: `0 0 ${CHART.width} ${view.weekly ? CHART.height - 20 : CHART.height}` });
  const low = closes.reduce((best, value) => Math.min(best, value));
  const high = closes.reduce((best, value) => Math.max(best, value));
  const span = high - low;
  const plotHeight = CHART.height - CHART.top - CHART.bottom;
  const y = (close) => CHART.top + (span ? 1 - (close - low) / span : 0.5) * plotHeight;

  root.append(
    svg("line", { x1: CHART.left, x2: CHART.width - CHART.right, y1: y(high), y2: y(high), class: "grid" }),
    svg("text", { x: CHART.left - 8, y: y(high) + 4, "text-anchor": "end", class: "axis" }, high.toFixed(2)),
  );
  if (span) root.append(
    svg("line", { x1: CHART.left, x2: CHART.width - CHART.right, y1: y(low), y2: y(low), class: "grid" }),
    svg("text", { x: CHART.left - 8, y: y(low) + 4, "text-anchor": "end", class: "axis" }, low.toFixed(2)),
  );
  if (view.weekly) {
    for (const [index, point] of points.entries()) {
      if (point.baseline) continue;
      const x = sessionX(index, points.length);
      root.append(svg("line", {
        x1: x, x2: x, y1: CHART.top, y2: CHART.height - CHART.bottom, class: "week-guide",
      }));
    }
  } else {
    root.append(svg("text", { x: CHART.left, y: CHART.height - 8, class: "axis" }, points[0].session));
    if (points.length > 1) root.append(svg("text", {
      x: CHART.width - CHART.right, y: CHART.height - 8, "text-anchor": "end", class: "axis",
    }, points.at(-1).session));
  }
  let segment = [];
  const drawSegment = () => {
    if (segment.length === 1) {
      const [cx, cy] = segment[0];
      root.append(svg("circle", { cx, cy, r: 2.5, class: "price-point" }));
    } else if (segment.length > 1) {
      root.append(svg("polyline", { points: segment.map((point) => point.join(",")).join(" "), class: "line" }));
    }
    segment = [];
  };
  for (const [index, point] of points.entries()) {
    if (point.baseline) {
      const marker = svg("circle", {
        cx: sessionX(index, points.length), cy: y(point.close), r: 4, class: "prior-close",
      });
      marker.append(svg("title", {}, `Prior saved close · ${point.session} · ${CLOSE_PRICE.format(point.close)}`));
      const first = points.findIndex((entry) => !entry.baseline && entry.close !== null);
      if (first >= 0 && Number.isFinite(points[first].change)) {
        root.append(svg("line", {
          x1: sessionX(index, points.length), y1: y(point.close),
          x2: sessionX(first, points.length), y2: y(points[first].close), class: "prior-link",
        }));
      }
      root.append(marker);
    } else if (point.close === null) drawSegment();
    else segment.push([sessionX(index, points.length), y(point.close)]);
  }
  drawSegment();
  for (const [index, point] of points.entries()) {
    if (point.kind !== "news" || point.close === null) continue;
    const marker = svg("circle", {
      cx: sessionX(index, points.length), cy: y(point.close), r: 5.5, class: "news",
      role: "button", tabindex: 0, "aria-label": `See news on ${point.session}`,
      "aria-controls": "session-evidence", "data-session": point.session,
    });
    const toggle = () => showSessionNews(state.session === point.session ? "" : point.session);
    marker.addEventListener("click", toggle);
    marker.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        toggle();
      }
    });
    root.append(marker);
  }
  if (!view.weekly) {
    elements.chart.replaceChildren(root);
  } else {
    const labels = points.map((point) => {
      const day = dateAtUtcMidnight(point.session);
      return element("span", {
        className: "week-axis", textContent: point.baseline ? "Prior close" : `${WEEKDAY.format(day)} ${day.getUTCDate()}`,
      });
    });
    elements.chart.replaceChildren(root, element("div", {
      className: view.baseline ? "week-dates-axis with-prior" : "week-dates-axis",
    }, labels));
  }
}

function dailyStrip(points, returns) {
  const field = returns ? "change" : "volume_ratio";
  const values = points.map((point) => point[field]).filter(Number.isFinite);
  if (!values.length) {
    return element("p", {
      className: "analytics-empty muted",
      textContent: returns ? "No daily returns in this range." : "No volume ratios in this range.",
    });
  }

  const largest = values.reduce((max, value) => Math.max(max, Math.abs(value)), 0);
  const high = returns ? Math.max(0.0001, largest) : Math.max(1, Math.ceil(largest));
  const low = returns ? -high : 0;
  const top = 21;
  const bottom = 101;
  const y = (value) => top + ((high - value) / (high - low)) * (bottom - top);
  const baseline = y(0);
  const barWidth = Math.min(24, PLOT_WIDTH / points.length * 0.76);
  const root = svg("svg", {
    viewBox: `0 0 ${CHART.width} 114`,
    role: "img",
    "aria-label": returns ? "Daily returns by trading session" : "Daily volume as a multiple of the ticker median",
  });
  const format = (value) => returns ? `${value > 0 ? "+" : ""}${percent(value)}` : ratio(value);
  const guides = returns ? [high, 0, low] : [...new Set([high, 1])];
  for (const value of guides) {
    const level = y(value);
    root.append(
      svg("line", {
        x1: CHART.left, x2: CHART.width - CHART.right, y1: level, y2: level,
        class: value === (returns ? 0 : 1) ? "strip-reference" : "grid",
      }),
      svg("text", {
        x: CHART.left - 8, y: level + 5, "text-anchor": "end", class: "axis",
      }, returns ? format(value) : `${value}×`),
    );
  }

  for (const [index, point] of points.entries()) {
    const value = point[field];
    if (!Number.isFinite(value)) continue;
    const x = sessionX(index, points.length);
    const height = Math.max(1, Math.abs(y(value) - baseline));
    const bar = svg("rect", {
      x: x - barWidth / 2, y: value < 0 ? baseline : baseline - height,
      width: barWidth, height,
      class: returns ? `return-bar ${value > 0 ? "gain" : value < 0 ? "loss" : "flat"}` : "volume-bar",
      "data-session": point.session,
    });
    bar.append(svg("title", {}, `${point.session} · ${format(value)}`));
    root.append(bar);
    if (returns && point.kind === "news") {
      const marker = svg("circle", { cx: x, cy: 8, r: 5, class: "news", "data-session": point.session });
      marker.append(svg("title", {}, `${point.session} · News session · ${format(value)}`));
      root.append(marker);
    }
  }
  return root;
}

function renderDailyMoves(view) {
  elements.dailyMoves.hidden = !view;
  if (!view) return;
  elements.dailyReturns.replaceChildren(dailyStrip(view.points, true));
  elements.dailyVolumePanel.hidden = !view.sessions.length;
  elements.dailyVolume.replaceChildren(dailyStrip(view.points, false));
}

function renderMoveDots(container, summary, sessions, limit, kind) {
  if (!sessions.length) {
    summary.textContent = "0 sessions";
    container.replaceChildren();
    return;
  }

  const middle = Math.floor(sessions.length / 2);
  const median = (sessions[middle].move + sessions[Math.floor((sessions.length - 1) / 2)].move) / 2;
  const count = `${sessions.length} ${sessions.length === 1 ? "session" : "sessions"}`;
  summary.textContent = `${count} · Median ${percent(median)}`;
  const width = 800;
  const inset = 10;
  const x = (move) => inset + (move / limit) * (width - inset * 2);
  const lanes = [36, 26, 46, 16, 56, 6, 66];
  const lastPosition = lanes.map(() => -Infinity);
  const plot = svg("svg", {
    viewBox: `0 0 ${width} 72`, role: "img",
    "aria-label": `${count}, one dot per session, median absolute move ${percent(median)}`,
    class: kind,
  });
  const medianLine = svg("line", { x1: x(median), x2: x(median), y1: 4, y2: 68, class: "median-line" });
  medianLine.append(svg("title", {}, `Median ${percent(median)}`));
  plot.append(
    svg("line", { x1: inset, x2: width - inset, y1: 36, y2: 36, class: "dot-guide" }),
    medianLine,
  );
  for (const [index, point] of sessions.entries()) {
    const cx = x(point.move);
    const openLane = lastPosition.findIndex((last) => cx - last >= 9);
    const lane = openLane < 0 ? index % lanes.length : openLane;
    lastPosition[lane] = cx;
    const dot = svg("circle", {
      cx, cy: lanes[lane], r: 4.5, class: "move-dot", "data-session": point.session,
    });
    dot.append(svg("title", {}, `${point.session} · ${percent(point.move)} absolute move`));
    plot.append(dot);
  }
  container.replaceChildren(plot);
}

function renderMoveComparison(view) {
  elements.moveComparison.hidden = !view;
  if (!view) return;
  const moves = view.sessions
    .filter((point) => Number.isFinite(point.change) && (point.kind === "news" || point.kind === "quiet"))
    .map((point) => ({ session: point.session, kind: point.kind, move: Math.abs(point.change) }))
    .sort((left, right) => left.move - right.move);
  const limit = Math.max(0.0001, moves.at(-1)?.move ?? 0);
  const news = moves.filter((point) => point.kind === "news");
  const quiet = moves.filter((point) => point.kind === "quiet");
  renderMoveDots(elements.newsMoveDots, elements.newsMoveSummary, news, limit, "news");
  renderMoveDots(elements.quietMoveDots, elements.quietMoveSummary, quiet, limit, "quiet");
  elements.moveScale.hidden = !moves.length;
  elements.moveScaleMax.textContent = percent(limit);
  elements.moveComparisonNote.textContent = !news.length || !quiet.length
    ? "A comparison needs both news and quiet sessions."
    : Math.min(news.length, quiet.length) < 10
      ? "Small sample. Each dot is one session."
      : "Each dot is one session.";
}

function checkKind(entry) {
  if (!entry) return "no-check";
  if (entry.feeds_failed) return entry.feeds_read ? "partial" : "failed";
  return entry.feeds_read ? "checked" : "skipped";
}

function describeChecks(entry) {
  if (!entry) return "No check recorded";
  const count = entry.checks === 1 ? "1 check" : `${entry.checks} checks`;
  const attempts = entry.feeds_read + entry.feeds_failed;
  const reads = attempts ? `${entry.feeds_read}/${attempts} feed attempts succeeded` : "No feeds attempted";
  return [
    count, reads,
    entry.feeds_failed ? `${entry.feeds_failed} failed` : "",
    entry.feeds_skipped ? `${entry.feeds_skipped} skipped` : "",
  ].filter(Boolean).join(" · ");
}

function renderCoverage(view) {
  if (!view.check_days) {
    elements.coverageStrip.hidden = true;
    elements.coverageKey.hidden = true;
    elements.coverageSpan.textContent = "";
    elements.coverageSummary.textContent = "Restart Bridge to see daily HoundDog activity.";
    return;
  }
  const today = easternDate(new Date().toISOString());
  const firstCheck = view.check_days[0]?.day;
  const started = firstCheck ?? today;
  const first = view.range.first > started ? view.range.first : started;
  const last = view.range.last < today ? view.range.last : today;
  const end = new Date(`${last}T00:00:00Z`);
  const days = [];
  for (const day = new Date(`${first}T00:00:00Z`); day <= end; day.setUTCDate(day.getUTCDate() + 1)) {
    days.push(day.toISOString().slice(0, 10));
  }

  elements.coverageStrip.hidden = !days.length;
  elements.coverageKey.hidden = !days.length;
  elements.coverageSpan.textContent = days.length > 1 ? `${first} to ${last}` : "";
  if (!days.length) {
    elements.coverageSummary.textContent = firstCheck
      ? `Checks began ${firstCheck}. No activity in this range.`
      : "No checks recorded for this ticker yet.";
    elements.coverageStrip.replaceChildren();
    return;
  }

  const records = new Map(view.check_days.map((entry) => [entry.day, entry]));
  const root = svg("svg", { viewBox: `0 0 ${CHART.width} 24`, preserveAspectRatio: "none" });
  const width = CHART.width / days.length;
  const gap = Math.min(1, width * 0.15);
  const bands = [];
  const explain = (day) => `${day === today ? "Today" : day} · ${describeChecks(records.get(day))}`;
  function highlight(index) {
    for (const [position, band] of bands.entries()) {
      const active = position === index;
      band.setAttribute("tabindex", active ? 0 : -1);
      band.setAttribute("aria-pressed", String(active));
      band.classList.toggle("active-day", active);
    }
    elements.coverageSummary.textContent = explain(days[index]);
  }
  for (const [index, day] of days.entries()) {
    const entry = records.get(day);
    const kind = checkKind(entry);
    const bounds = { x: index * width + gap / 2, y: 1, width: width - gap, height: 22 };
    const band = svg("g", { class: "coverage-day", role: "button", "aria-label": explain(day) });
    if (kind === "partial") {
      const passed = bounds.width * entry.feeds_read / (entry.feeds_read + entry.feeds_failed);
      band.append(
        svg("rect", { ...bounds, width: passed, class: "checked" }),
        svg("rect", { ...bounds, x: bounds.x + passed, width: bounds.width - passed, class: "failed" }),
      );
    } else {
      band.append(svg("rect", { ...bounds, class: kind }));
    }
    band.append(svg("rect", { ...bounds, class: "day-outline" }));
    const select = (position) => {
      state.coverageDay = days[position];
      highlight(position);
      bands[position].focus();
    };
    band.append(svg("title", {}, explain(day)));
    band.addEventListener("click", () => select(index));
    band.addEventListener("keydown", (event) => {
      const target = {
        ArrowLeft: Math.max(0, index - 1), ArrowRight: Math.min(days.length - 1, index + 1),
        Home: 0, End: days.length - 1, Enter: index, " ": index,
      }[event.key];
      if (target === undefined) return;
      event.preventDefault();
      select(target);
    });
    bands.push(band);
    root.append(band);
  }
  elements.coverageStrip.replaceChildren(root);
  const selected = days.indexOf(state.coverageDay);
  highlight(selected < 0 ? days.length - 1 : selected);
}

function safeLink(link) {
  try {
    const url = new URL(link);
    return url.protocol === "http:" || url.protocol === "https:" ? url.href : null;
  } catch {
    return null;
  }
}

function articleTitle(event) {
  const href = safeLink(event.link);
  const textContent = event.title || event.link;
  return href
    ? element("a", { href, textContent, target: "_blank", rel: "noopener noreferrer" })
    : element("span", { textContent });
}

function renderWeeklyNews() {
  const { events, weekendEvents, includeWeekend } = state.weeklyNews;
  const first = state.range || isWeeklyView() ? activeWeek() : currentNewsWeek();
  const friday = shiftDay(first, 4);
  const sunday = shiftDay(first, 6);
  function entriesForWeek(articles, through) {
    return articles.filter((event) => {
      const day = easternDate(event.detected_at);
      return day >= first && day <= through;
    });
  }
  const weekdays = entriesForWeek(events, friday);
  const weekend = entriesForWeek(weekendEvents, sunday);

  elements.newsPeriod.hidden = isWeeklyView() && !includeWeekend;
  elements.newsPeriod.textContent = dateSpan(first, includeWeekend ? sunday : friday);
  elements.weekdaysNews.setAttribute("aria-pressed", String(!includeWeekend));
  elements.fullWeekNews.setAttribute("aria-pressed", String(includeWeekend));
  elements.fullWeekNews.textContent = weekend.length ? `Full week · ${weekend.length} weekend` : "Full week";
  elements.weeklyNewsCount.textContent = weekdays.length
    ? `${weekdays.length} weekday ${weekdays.length === 1 ? "article" : "articles"} · Detected in ET`
    : "No live weekday articles found.";
  elements.weekendNews.hidden = !includeWeekend || !weekend.length;
  renderWeeklyEntries(elements.weeklyNewsList, weekdays);
  renderWeeklyEntries(elements.weekendNewsList, includeWeekend ? weekend : []);
}

function renderWeeklyEntries(list, entries) {
  const byDay = new Map();
  for (const event of entries) {
    const day = event.session || easternDate(event.detected_at);
    if (!byDay.has(day)) byDay.set(day, []);
    byDay.get(day).push(event);
  }
  const groups = [...byDay].sort(([left], [right]) => right.localeCompare(left)).map(([day, articles]) => {
    const statuses = new Set(articles.map((event) => event.session && !event.has_move
      ? ARTICLE_STATUS_LABELS[articlePriceStatus(event)] : ""));
    const shared = statuses.size === 1 ? [...statuses][0] : "";
    const items = articles.reverse().map((event) => {
      const detectedAt = new Date(event.detected_at);
      const detectedDay = easternDate(event.detected_at);
      const label = detectedDay === day ? EASTERN_CLOCK.format(detectedAt) : EASTERN_TIME.format(detectedAt);
      const status = !shared && event.session && !event.has_move
        ? ARTICLE_STATUS_LABELS[articlePriceStatus(event)] : "";
      const meta = [
        element("time", { dateTime: event.detected_at, textContent: label, title: "Detected in ET" }),
      ];
      if (event.placement === "at_or_after_close") meta.push(" · After close");
      if (status) meta.push(` · ${status}`);
      return element("li", { className: "weekly-article" }, [
        articleTitle(event),
        element("div", { className: "weekly-news-meta muted" }, meta),
      ]);
    });
    const heading = [element("time", { dateTime: day, textContent: WEEKDAY_DATE.format(dateAtUtcMidnight(day)) })];
    if (shared) {
      const pending = articles.every((event) => articlePriceStatus(event) === "awaiting_close");
      heading.push(element("span", { className: pending ? "ticker-pending" : "muted", textContent: shared }));
    }
    return element("li", { className: "weekly-group" }, [
      element("div", { className: "weekly-day" }, heading),
      element("ul", {}, items),
    ]);
  });
  list.replaceChildren(...groups);
}

function openWeek(week) {
  state.weeklyNews.week = week >= currentNewsWeek() ? "" : week;
  state.rangePreset = "week";
  setChartRange(null);
}

function changeWeek(days) {
  openWeek(shiftDay(activeWeek(), days));
}

function articleOutcome(event) {
  if (event.has_move) return "Counts toward a news session.";
  const status = articlePriceStatus(event);
  if (status === "awaiting_close") return "The assigned trading session is still awaiting its close.";
  return MARKET_EXCLUSIONS[status] ?? "Price data pending.";
}

function showSessionNews(day) {
  const view = state.detailView;
  const point = view?.sessions.find((entry) => entry.session === day && entry.kind === "news");
  state.session = point ? day : "";
  elements.sessionEvidence.hidden = !point;
  for (const marker of elements.chart.querySelectorAll("[data-session]")) {
    marker.classList.toggle("selected-session", marker.dataset.session === state.session);
    marker.setAttribute("aria-pressed", String(marker.dataset.session === state.session));
  }
  if (!point) return;
  const stats = element("dl", { className: "facts" });
  setFacts(stats, [
    ["Close", point.close === null ? "—" : point.close.toFixed(2)],
    ["Price move", percent(point.change)],
    ["Volume vs. median", ratio(point.volume_ratio)],
  ]);
  const articles = view.events.filter((event) => event.session === day);
  const articleList = element("ul", { className: "session-articles" }, articles.map((event) =>
    element("li", {}, [articleTitle(event)])));
  elements.sessionEvidence.replaceChildren(
    element("h3", { textContent: day }),
    stats, articleList,
  );
}

function renderDetailRows(body, rows, renderRow, columns, emptyMessage) {
  const fragment = document.createDocumentFragment();
  for (const row of rows) fragment.append(renderRow(row));
  if (!rows.length) fragment.append(element("tr", {}, [
    element("td", { colSpan: columns, className: "muted", textContent: emptyMessage }),
  ]));
  body.replaceChildren(fragment);
}

function renderSessions(study) {
  const afterFirstCheck = (day) => study.first_check_session && day >= study.first_check_session;
  const included = study.sessions.filter((point) => point.kind !== "unwatched" || afterFirstCheck(point.session));
  const exclusions = study.excluded_sessions.filter((point) =>
    point.reason === "missing_bar" || point.reason === "first_price_session" || afterFirstCheck(point.session));
  const counts = [
    ["News", included.filter((point) => point.kind === "news").length],
    ["Quiet", included.filter((point) => point.kind === "quiet").length],
    ["Missing daily bar", study.missing_bars.length],
  ];
  elements.detailCounts.replaceChildren(...counts.map(([label, count]) => element("div", {}, [
    element("dt", { textContent: label }),
    element("dd", { textContent: count }),
  ])));
  const sessions = [...included, ...exclusions];
  sessions.sort((left, right) => right.session.localeCompare(left.session));
  renderDetailRows(elements.detailSessions, sessions, (session) => {
    return element("tr", {}, [
      element("td", { textContent: session.session }),
      element("td", { className: "explanation", textContent: SESSION_LABELS[session.kind] ?? MARKET_LABELS[session.reason] }),
      element("td", { textContent: session.close === null ? "–" : session.close.toFixed(2) }),
      element("td", { textContent: percent(session.change) }),
      element("td", { textContent: ratio(session.volume_ratio) }),
    ]);
  }, 5, "No study sessions or missing bars in this range.");
}

function renderEvents(study) {
  const events = [...study.events];
  events.sort((left, right) => Date.parse(right.detected_at) - Date.parse(left.detected_at));
  renderDetailRows(elements.detailEvents, events, (event) => {
    return element("tr", {}, [
      element("td", {}, [
        element("time", { dateTime: event.detected_at, textContent: EASTERN_TIME.format(new Date(event.detected_at)) }),
      ]),
      element("td", { className: "explanation" }, [
        articleTitle(event),
        element("span", { className: "topic muted", textContent: event.topic }),
      ]),
      element("td", { textContent: event.session }),
      element("td", { className: "explanation" }, [
        event.placement ? element("div", { textContent: PLACEMENT_REASONS[event.placement] }) : "",
        element("div", { className: "muted", textContent: articleOutcome(event) }),
      ]),
    ]);
  }, 4, "No articles assigned to a session in this range.");
}

function renderStudyDetails() {
  const view = state.detailView;
  if (!elements.studyDetails.open || !view) return;
  renderCoverage(view);
  renderSessions(view);
  renderEvents(view);
}

function renderDetail(report) {
  const studies = [...report.symbols];
  const pinned = state.pinStudy?.study;
  if (pinned && !studies.some((study) => study.symbol === pinned.symbol)) studies.push(pinned);
  const study = studies.find((entry) => entry.symbol === state.detailSymbol) ?? studies[0];
  state.detailSymbol = study?.symbol ?? "";
  state.detailStudy = study ?? null;
  elements.detailTitle.textContent = study ? `${study.symbol} study` : "Ticker study";
  for (const ticker of elements.watchlist.querySelectorAll(".ticker-select")) {
    ticker.setAttribute("aria-pressed", String(ticker.dataset.symbol === state.detailSymbol));
  }
  const view = makeDetailView(study);
  state.detailView = view;
  const lastPrice = view?.prices.at(-1) ?? view?.baseline;
  const lastCheck = state.overview.status.hounddog.last_check;
  const week = activeWeek();
  const current = currentNewsWeek();
  const latestSession = state.overview.thetadesk.latest_session;
  const latestSaved = study?.prices.at(-1)?.session;
  const weekly = isWeeklyView();
  const firstClosePending = weekly && latestSession < week;
  const needsPrices = !latestSaved || latestSaved < latestSession;
  const readiness = firstClosePending ? "First close pending" : needsPrices ? "Close not saved" : "Up to date";
  elements.dataFreshness.hidden = !view;
  elements.detailClose.textContent = lastPrice ? CLOSE_PRICE.format(lastPrice.close) : "—";
  elements.pricesThrough.textContent = lastPrice
    ? WEEKDAY_DATE.format(dateAtUtcMidnight(lastPrice.session))
    : "None saved in view";
  elements.lastNewsCheck.textContent = lastCheck ? EASTERN_TIME.format(new Date(lastCheck)) : "No checks recorded";
  elements.priceReadiness.parentElement.hidden = Boolean(state.range) || (weekly && week !== current);
  elements.priceReadiness.textContent = readiness;
  elements.priceReadiness.className = firstClosePending || needsPrices ? "ticker-pending" : "prices-current";
  elements.viewControls.hidden = !view;
  elements.viewKind.textContent = state.range ? "Custom range"
    : weekly ? (week === current ? "Current week" : "Study week")
      : CHART_PRESETS[state.rangePreset].label;
  elements.weekDates.textContent = view ? dateSpan(view.range.first, view.range.last) : "";
  for (const button of elements.rangePresets) {
    button.setAttribute("aria-pressed", String(!state.range && button.dataset.preset === state.rangePreset));
  }
  elements.weekPrev.hidden = !weekly;
  elements.weekNext.hidden = !weekly;
  elements.weekPrev.disabled = !study || !(
    study.prices[0]?.session < week || study.check_days?.[0]?.day < week ||
    study.events.some((event) => easternDate(event.detected_at) < week) ||
    (study.weekend_events ?? []).some((event) => easternDate(event.detected_at) < week)
  );
  elements.weekNext.disabled = week >= current;
  elements.currentWeek.hidden = !state.range && (!weekly || week === current);
  elements.rangeStart.value = view?.range.first ?? "";
  elements.rangeEnd.value = view?.range.last ?? "";
  elements.rangeReset.hidden = !state.range;
  elements.rangeAll.hidden = !study?.prices.length;
  elements.pinRange.hidden = !state.overview.thetadesk.enabled || !view?.prices.length;
  elements.pinRange.disabled = state.pinSaveBusy;
  elements.studyDetails.hidden = !view;
  elements.weeklyNews.hidden = !study;
  if (study) {
    state.weeklyNews.events = study.events;
    state.weeklyNews.weekendEvents = study.weekend_events ?? [];
    renderWeeklyNews();
  }
  renderChart(view);
  renderDailyMoves(view);
  renderMoveComparison(view);
  renderStudyDetails();
  showSessionNews(state.session);
}

function rangeStatus(message) {
  elements.rangeStatus.textContent = message;
  elements.rangeStatus.hidden = !message;
}

function openStudy(symbol, moveFocus = true) {
  if (symbol === state.detailSymbol) return;
  state.detailRequestId += 1;
  state.detailSymbol = symbol;
  if (state.pinStudy?.study.symbol !== symbol) state.pinStudy = null;
  state.range = null;
  state.session = "";
  state.coverageDay = "";
  rangeStatus("");
  renderDetail(state.overview.report);
  if (moveFocus) elements.detailTitle.focus();
}

function setChartRange(range) {
  state.detailRequestId += 1;
  state.range = range;
  if (range) {
    const week = weekStart(range.last);
    state.weeklyNews.week = week >= currentNewsWeek() ? "" : week;
  }
  state.session = "";
  state.coverageDay = "";
  rangeStatus("");
  renderDetail(state.overview.report);
}

function closeRangeTools() {
  elements.rangeTools.open = false;
  elements.rangeTools.querySelector("summary").focus();
}

function applyRange(event) {
  event.preventDefault();
  const first = elements.rangeStart.value;
  const last = elements.rangeEnd.value;
  if (!first || !last || first > last) {
    rangeStatus("Choose a start date on or before the end date.");
    return;
  }
  setChartRange({ first, last });
  closeRangeTools();
}

function renderPins() {
  elements.pinsPanel.hidden = !state.overview.thetadesk.enabled;
  elements.pinStatus.textContent = state.pinsError || (state.pins.length ? "" : "No ranges pinned yet.");
  elements.pinsList.replaceChildren(...state.pins.map((pin) => {
    const open = element("button", { type: "button" }, [
      element("strong", { textContent: pin.symbol }),
      element("span", { className: "muted", textContent: `${pin.start_date} to ${pin.end_date}` }),
    ]);
    open.addEventListener("click", () => openPin(pin));
    return element("li", {}, [open]);
  }));
}

async function refreshPins() {
  const requestId = ++state.pinsRequestId;
  if (!state.overview.thetadesk.enabled) {
    state.pins = [];
    state.pinsError = "";
    renderPins();
    return;
  }
  try {
    const result = await api("/api/pins");
    if (requestId !== state.pinsRequestId) return;
    state.pins = result.pins;
    state.pinsError = "";
  } catch (error) {
    if (requestId !== state.pinsRequestId) return;
    state.pinsError = error.message;
  }
  renderPins();
}

async function openPin(pin) {
  const requestId = ++state.detailRequestId;
  const range = { first: pin.start_date, last: pin.end_date };
  elements.pinStatus.textContent = `Opening ${pin.symbol}…`;
  try {
    const query = new URLSearchParams({ start_date: range.first, end_date: range.last });
    const data = await api(`/api/tickers/${encodeURIComponent(pin.symbol)}?${query}`);
    if (requestId !== state.detailRequestId) return;
    state.pinStudy = { ...data, range };
    state.detailSymbol = data.study.symbol;
    setChartRange(range);
    elements.rangeTools.open = false;
    rangeStatus(`Opened shared pin · ${range.first} to ${range.last}`);
    elements.detailTitle.focus();
  } catch (error) {
    if (requestId === state.detailRequestId) showNotice(error.message);
  } finally {
    if (elements.pinStatus.textContent === `Opening ${pin.symbol}…`) renderPins();
  }
}

async function savePin() {
  const view = state.detailView;
  if (state.pinSaveBusy || !view?.prices.length) return;
  const { first, last } = view.range;
  state.pinSaveBusy = true;
  elements.pinRange.disabled = true;
  try {
    await api("/api/pins", {
      method: "POST", body: JSON.stringify({ symbol: view.symbol, start_date: first, end_date: last }),
    });
    await refreshPins();
    rangeStatus(`Pinned ${view.symbol} · ${first} to ${last}`);
  } catch (error) {
    rangeStatus(error.message);
  } finally {
    state.pinSaveBusy = false;
    elements.pinRange.disabled = false;
  }
}

function render() {
  const overview = state.overview;
  const today = easternDate(new Date().toISOString());
  elements.today.dateTime = today;
  elements.today.textContent = `${WEEKDAY_DATE.format(dateAtUtcMidnight(today))} · ET`;
  elements.banner.textContent = overview.display.banner;
  elements.banner.hidden = !overview.display.banner;
  renderWatchlist(overview);
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
  const requestId = ++state.refreshId;
  elements.refresh.disabled = true;
  try {
    const overview = await api("/api/overview");
    if (requestId !== state.refreshId) return;
    state.overview = overview;
    render();
    scheduleHoundDogRetry();
    elements.updated.textContent = `Bridge refreshed ${EASTERN_TIME.format(new Date())} ET`;
    await refreshPins();
  } catch (error) {
    if (requestId === state.refreshId) showNotice(error.message);
  } finally {
    if (requestId === state.refreshId) elements.refresh.disabled = false;
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
document.querySelector("#open-sources").addEventListener("click", (event) => {
  event.currentTarget.closest("details").open = false;
  document.querySelector("#source-connections").open = true;
});
elements.addOther.addEventListener("click", addOtherTicker);
elements.otherTicker.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    addOtherTicker();
  }
});
elements.watchForm.addEventListener("submit", submitWatch);
elements.rangeForm.addEventListener("submit", applyRange);
elements.rangeReset.addEventListener("click", () => {
  openWeek(activeWeek());
  closeRangeTools();
});
elements.rangeAll.addEventListener("click", () => {
  const prices = state.detailStudy?.prices;
  if (!prices?.length) return;
  setChartRange({ first: prices[0].session, last: prices.at(-1).session });
  closeRangeTools();
});
elements.pinRange.addEventListener("click", savePin);
elements.studyDetails.addEventListener("toggle", renderStudyDetails);
elements.weekPrev.addEventListener("click", () => changeWeek(-7));
elements.weekNext.addEventListener("click", () => changeWeek(7));
elements.currentWeek.addEventListener("click", () => openWeek(currentNewsWeek()));
for (const button of elements.rangePresets) {
  button.addEventListener("click", () => {
    state.rangePreset = button.dataset.preset;
    setChartRange(null);
  });
}
elements.weekdaysNews.addEventListener("click", () => {
  state.weeklyNews.includeWeekend = false;
  renderWeeklyNews();
});
elements.fullWeekNews.addEventListener("click", () => {
  state.weeklyNews.includeWeekend = true;
  renderWeeklyNews();
});
for (const menu of document.querySelectorAll(".toolbar-menu")) {
  menu.addEventListener("keydown", (event) => {
    if (event.key !== "Escape" || !menu.open) return;
    menu.open = false;
    menu.querySelector("summary").focus();
  });
}
document.addEventListener("click", (event) => {
  for (const menu of document.querySelectorAll(".toolbar-menu[open]")) {
    if (!menu.contains(event.target)) menu.open = false;
  }
});

refresh();
