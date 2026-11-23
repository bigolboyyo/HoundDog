const form = document.querySelector("#lookup-form");
const symbolInput = document.querySelector("#symbol");
const tickerOptions = document.querySelector("#ticker-options");
const startDateInput = document.querySelector("#start-date");
const endDateInput = document.querySelector("#end-date");
const refreshBarsInput = document.querySelector("#refresh-bars");
const browseSymbolsButton = document.querySelector("#browse-symbols");
const symbolsDialog = document.querySelector("#symbols-dialog");
const closeSymbolsButton = document.querySelector("#close-symbols");
const symbolSearch = document.querySelector("#symbol-search");
const symbolsList = document.querySelector("#symbols-list");
const symbolsStatus = document.querySelector("#symbols-status");
const submitButton = document.querySelector("#submit-button");
const requestMessage = document.querySelector("#request-message");
const resultCount = document.querySelector("#result-count");
const statsGrid = document.querySelector("#stats-grid");
const chartCard = document.querySelector("#chart-card");
const chartTitle = document.querySelector("#chart-title");
const chartRange = document.querySelector("#chart-range");
const priceChart = document.querySelector("#price-chart");
const pinSummaryButton = document.querySelector("#pin-summary");
const chartAccessibleTitle = document.querySelector("#chart-accessible-title");
const chartAccessibleDescription = document.querySelector("#chart-accessible-description");
const emptyResults = document.querySelector("#empty-results");
const historyTable = document.querySelector("#history-table");
const tableHead = historyTable.querySelector("thead");
const tableBody = historyTable.querySelector("tbody");
const pinsList = document.querySelector("#pins-list");
const emptyPins = document.querySelector("#empty-pins");
const clearPinsButton = document.querySelector("#clear-pins");
const quotaStatus = document.querySelector("#quota-status");
const openSettingsButton = document.querySelector("#open-settings");
const settingsDialog = document.querySelector("#settings-dialog");
const settingsForm = document.querySelector("#settings-form");
const closeSettingsButton = document.querySelector("#close-settings");
const settingsApiKey = document.querySelector("#settings-api-key");
const settingsEmail = document.querySelector("#settings-email");
const settingsPassword = document.querySelector("#settings-password");
const settingsSaveButton = document.querySelector("#save-settings");
const settingsStatus = document.querySelector("#settings-status");
const clearApiKeyButton = document.querySelector("#clear-api-key");
const clearCredentialsButton = document.querySelector("#clear-credentials");
const loadedList = document.querySelector("#loaded-list");
const emptyLoaded = document.querySelector("#empty-loaded");
const shutdownButton = document.querySelector("#shutdown-button");
const stoppedNotice = document.querySelector("#stopped");

const MAX_HISTORY_DAYS = 365;
const DAY_MS = 24 * 60 * 60 * 1000;
const SVG_NAMESPACE = "http://www.w3.org/2000/svg";
const pinnedSummaries = new Map();
let stockSymbols = null;
let currentSummary = null;

function localDateString(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function setDefaultDates() {
  const today = new Date();
  const endDate = new Date(today.getFullYear(), today.getMonth(), today.getDate() - 1);
  const startDate = new Date(endDate);
  startDate.setDate(startDate.getDate() - MAX_HISTORY_DAYS);
  startDateInput.value = localDateString(startDate);
  endDateInput.value = localDateString(endDate);
}

function setMessage(message, isError = false) {
  requestMessage.textContent = message;
  requestMessage.classList.toggle("error", isError);
}

// JSON from this server; a failure becomes an Error carrying the server's detail.
async function requestJson(url, options = {}) {
  const headers = { Accept: "application/json" };
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  const response = await fetch(url, { cache: "no-store", ...options, headers });
  const result = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(result.detail || `Request failed (${response.status}).`);
  }
  return result;
}

// Both ways of showing a ticker (Load history and Loaded tickers) draw into the
// same result panel; only the most recent one may, so a slow answer cannot
// replace a newer choice.
let latestLookup = 0;

function startLookup() {
  latestLookup += 1;
  return latestLookup;
}

function isoDaysBefore(isoDate, days) {
  return new Date(Date.parse(`${isoDate}T00:00:00Z`) - days * DAY_MS).toISOString().slice(0, 10);
}

function storedBarsUrl(symbol, startDate, endDate) {
  const query = `start_date=${encodeURIComponent(startDate)}&end_date=${encodeURIComponent(endDate)}`;
  return `/api/v1/stocks/${encodeURIComponent(symbol)}/bars?${query}`;
}

function setSettingsStatus(message, isError = false) {
  settingsStatus.textContent = message;
  settingsStatus.classList.toggle("error", isError);
}

const SAVED_PLACEHOLDER = "Saved. Leave blank to keep it.";

// The server reports what is saved but never the secrets, so the fields start
// blank and a blank field keeps the saved value.
function showCredentialStatus(status) {
  settingsApiKey.value = "";
  settingsPassword.value = "";
  settingsEmail.value = status.email || "";
  settingsApiKey.placeholder = status.api_key_configured ? SAVED_PLACEHOLDER : "Not set";
  settingsPassword.placeholder = status.credentials_configured ? SAVED_PLACEHOLDER : "Not set";
  clearApiKeyButton.hidden = !status.api_key_configured;
  clearCredentialsButton.hidden = !status.credentials_configured;
}

function describeCredentialStatus(status) {
  if (status.api_key_configured && status.credentials_configured) return "An API key and account credentials are saved.";
  if (status.api_key_configured) return "An API key is saved.";
  if (status.credentials_configured) return "Account credentials are saved.";
  return "No saved credentials found in the app folder.";
}

async function openSettings() {
  settingsDialog.showModal();
  settingsSaveButton.disabled = true;
  setSettingsStatus("Loading saved settings…");
  try {
    const status = await requestJson("/api/v1/settings/credentials");
    showCredentialStatus(status);
    setSettingsStatus(describeCredentialStatus(status));
  } catch (error) {
    setSettingsStatus(error instanceof Error ? error.message : "Could not load settings.", true);
  } finally {
    settingsSaveButton.disabled = false;
  }
}

async function changeCredentials(change, doneMessage) {
  settingsSaveButton.disabled = true;
  setSettingsStatus("Saving settings…");
  try {
    const status = await requestJson("/api/v1/settings/credentials", {
      method: "PUT",
      body: JSON.stringify(change),
    });
    showCredentialStatus(status);
    setSettingsStatus(`${doneMessage} ${describeCredentialStatus(status)}`);
  } catch (error) {
    setSettingsStatus(error instanceof Error ? error.message : "Could not save settings.", true);
  } finally {
    settingsSaveButton.disabled = false;
  }
}

function saveSettings(event) {
  event.preventDefault();
  return changeCredentials(
    { api_key: settingsApiKey.value, email: settingsEmail.value, password: settingsPassword.value },
    "Saved locally. The Python SDK will use these next; restart Terminal for REST backup changes.",
  );
}

async function shutDown() {
  if (!window.confirm("Shut down ThetaDesk? This page stops working until you start it again.")) return;
  shutdownButton.disabled = true;
  try {
    const response = await fetch("/api/v1/shutdown", { method: "POST", headers: { Accept: "application/json" } });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(result.detail || `Request failed (${response.status}).`);
    }
  } catch (error) {
    setMessage(`Could not shut down: ${error instanceof Error ? error.message : error}`, true);
    shutdownButton.disabled = false;
    return;
  }
  settingsDialog.close();
  symbolsDialog.close();
  stoppedNotice.hidden = false;
}

function updateQuota(response) {
  const limit = response.headers.get("X-RateLimit-Limit");
  const remaining = response.headers.get("X-RateLimit-Remaining");
  if (limit !== null && remaining !== null) {
    quotaStatus.textContent = `${remaining} / ${limit} API requests available this minute`;
  } else if (response.status === 429) {
    const retryAfter = response.headers.get("Retry-After");
    quotaStatus.textContent = retryAfter
      ? `Rate limit reached · retry in ${retryAfter}s`
      : "Rate limit reached";
  }
}

async function loadStockSymbols() {
  if (browseSymbolsButton.disabled) {
    return;
  }
  if (stockSymbols !== null) {
    renderStockSymbols();
    return;
  }

  browseSymbolsButton.disabled = true;
  symbolsStatus.textContent = "Loading symbol list…";
  try {
    const response = await fetch("/api/v1/stocks/symbols", {
      headers: { Accept: "application/json" },
    });
    updateQuota(response);
    // Error pages from the host check or a crash are not JSON.
    const result = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(result.detail || `Request failed (${response.status}).`);
    }

    stockSymbols = Array.isArray(result.symbols) ? result.symbols : [];
    renderStockSymbols();
  } catch (error) {
    symbolsStatus.textContent = error instanceof Error
      ? `Could not load symbols: ${error.message}`
      : "Could not load symbols.";
  } finally {
    browseSymbolsButton.disabled = false;
  }
}

function renderStockSymbols() {
  const query = symbolSearch.value.trim().toUpperCase();
  const matches = (stockSymbols ?? [])
    .filter((symbol) => symbol.includes(query))
    .slice(0, 100);
  const items = matches.map((symbol) => {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.className = "symbol-option";
    button.type = "button";
    button.textContent = symbol;
    button.addEventListener("click", () => {
      symbolInput.value = symbol;
      symbolsDialog.close();
      symbolInput.focus();
    });
    item.append(button);
    return item;
  });
  symbolsList.replaceChildren(...items);
  renderTickerSuggestions();

  if (!stockSymbols?.length) {
    symbolsStatus.textContent = "No symbols were returned.";
  } else if (!matches.length) {
    symbolsStatus.textContent = "No matching symbols.";
  } else {
    symbolsStatus.textContent = query
      ? `Showing ${matches.length} matches${matches.length === 100 ? " (first 100)" : ""}.`
      : `Showing the first ${matches.length} of ${stockSymbols.length.toLocaleString()} symbols. Search to narrow the list.`;
  }
}

function renderTickerSuggestions() {
  const query = symbolInput.value.trim().toUpperCase();
  const matches = query
    ? (stockSymbols ?? [])
      .filter((symbol) => symbol.startsWith(query))
      .slice(0, 20)
    : [];
  tickerOptions.replaceChildren(
    ...matches.map((symbol) => {
      const option = document.createElement("option");
      option.value = symbol;
      return option;
    }),
  );
}

function formatValue(value) {
  if (value === null || value === undefined || value === "") {
    return "—";
  }
  if (typeof value === "number" && Number.isFinite(value)) {
    return new Intl.NumberFormat(undefined, { maximumFractionDigits: 4 }).format(value);
  }
  return String(value);
}

function createStatCard(stat) {
  const card = document.createElement("article");
  card.className = "stat-card";

  const topline = document.createElement("div");
  topline.className = "stat-topline";
  const label = document.createElement("span");
  label.className = "stat-label";
  label.textContent = stat.label;

  topline.append(label);
  const value = document.createElement("p");
  value.className = "stat-value";
  value.textContent = stat.value;
  card.append(topline, value);
  return card;
}

function renderStats(stats) {
  statsGrid.replaceChildren(
    ...stats.map((stat) => createStatCard(stat)),
  );
}

function createPinnedSparkline(points, symbol) {
  const svg = createSvgElement("svg", {
    class: "pinned-sparkline",
    viewBox: "0 0 240 52",
    role: "img",
    "aria-label": `${symbol} closing-price timeline`,
  });
  const prices = points.map((point) => point.price);
  const minimum = Math.min(...prices);
  const maximum = Math.max(...prices);
  const padding = maximum === minimum
    ? Math.max(Math.abs(maximum) * 0.05, 1)
    : (maximum - minimum) * 0.08;
  const lowerBound = minimum - padding;
  const upperBound = maximum + padding;
  const x = (index) => points.length === 1
    ? 120
    : 4 + (index / (points.length - 1)) * 232;
  const y = (price) =>
    46 - ((price - lowerBound) / (upperBound - lowerBound)) * 40;
  const linePoints = points
    .map((point, index) => `${x(index)},${y(point.price)}`)
    .join(" ");

  svg.append(createSvgElement("polyline", {
    points: linePoints,
    class: "pinned-sparkline-line",
  }));
  svg.append(createSvgElement("circle", {
    cx: x(0),
    cy: y(points[0].price),
    r: 3,
    class: "pinned-sparkline-point",
  }));
  if (points.length > 1) {
    svg.append(createSvgElement("circle", {
      cx: x(points.length - 1),
      cy: y(points[points.length - 1].price),
      r: 3,
      class: "pinned-sparkline-point",
    }));
  }
  return svg;
}

function getPinnedMetrics(stats) {
  const metrics = [
    { key: "latest-close", label: "Latest close" },
    { key: "period-high", label: "Period high" },
    { key: "period-low", label: "Period low" },
  ];
  return metrics.map((metric) => ({
    ...metric,
    value: stats.find((stat) => stat.key === metric.key)?.value ?? "—",
  }));
}

function pinKey(symbol, startDate, endDate) {
  return `${symbol}:${startDate}:${endDate}`;
}

function summarize(symbol, startDate, endDate, rows) {
  return {
    key: pinKey(symbol, startDate, endDate),
    symbol,
    startDate,
    endDate,
    rows: rows.length,
    points: rows.map(row => ({ timestamp: Date.parse(row.session_date), price: row.close })),
    metrics: getPinnedMetrics(buildStats(rows)),
  };
}

// Pins are saved in ThetaDesk's store and redrawn from stored bars, so showing
// them never calls ThetaData.
async function loadPins() {
  try {
    const { pins } = await requestJson("/api/v1/pins");
    const summaries = await Promise.all(pins.map(async (pin) => {
      const result = await requestJson(storedBarsUrl(pin.symbol, pin.start_date, pin.end_date));
      return summarize(pin.symbol, pin.start_date, pin.end_date, result.data);
    }));
    pinnedSummaries.clear();
    summaries.forEach((summary) => pinnedSummaries.set(summary.key, summary));
  } catch (error) {
    setMessage(`Could not load pinned summaries: ${error.message}`, true);
  }
  renderPins();
  renderSummaryPinButton();
}

async function unpin(summary) {
  try {
    const path = [summary.symbol, summary.startDate, summary.endDate].map(encodeURIComponent).join("/");
    await requestJson(`/api/v1/pins/${path}`, { method: "DELETE" });
    pinnedSummaries.delete(summary.key);
  } catch (error) {
    setMessage(`Could not unpin ${summary.symbol}: ${error.message}`, true);
  }
  renderPins();
  renderSummaryPinButton();
}

async function pin(summary) {
  try {
    await requestJson("/api/v1/pins", {
      method: "POST",
      body: JSON.stringify({ symbol: summary.symbol, start_date: summary.startDate, end_date: summary.endDate }),
    });
    pinnedSummaries.set(summary.key, summary);
  } catch (error) {
    setMessage(`Could not pin ${summary.symbol}: ${error.message}`, true);
  }
  renderPins();
  renderSummaryPinButton();
}

async function loadLoadedTickers() {
  try {
    const { symbols } = await requestJson("/api/v1/stocks/loaded");
    renderLoadedTickers(symbols);
  } catch (error) {
    setMessage(`Could not list loaded tickers: ${error.message}`, true);
  }
}

function renderLoadedTickers(symbols) {
  emptyLoaded.hidden = symbols.length > 0;
  loadedList.querySelectorAll(".loaded-ticker").forEach((item) => item.remove());
  for (const loaded of symbols) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "loaded-ticker";
    const symbol = document.createElement("span");
    symbol.className = "loaded-ticker-symbol";
    symbol.textContent = loaded.symbol;
    const detail = document.createElement("span");
    detail.className = "loaded-ticker-detail";
    detail.textContent = `${loaded.first_session} — ${loaded.last_session} · ${loaded.bars.toLocaleString()} bars`;
    button.append(symbol, detail);
    button.setAttribute("aria-label", `Open ${loaded.symbol} from saved data`);
    button.addEventListener("click", () => openLoaded(loaded));
    loadedList.append(button);
  }
}

// Show a loaded ticker's latest year (or all of it, if less) from stored bars.
async function openLoaded(loaded) {
  const last = loaded.last_session;
  const yearBefore = isoDaysBefore(last, MAX_HISTORY_DAYS);
  const first = loaded.first_session > yearBefore ? loaded.first_session : yearBefore;
  symbolInput.value = loaded.symbol;
  startDateInput.value = first;
  endDateInput.value = last;
  setMessage(`Opening ${loaded.symbol} from saved data…`);
  const lookup = startLookup();
  try {
    const result = await requestJson(storedBarsUrl(loaded.symbol, first, last));
    if (lookup !== latestLookup) return;
    updateResult(result);
    setMessage(`Opened ${loaded.symbol} from saved data; ThetaData was not called.`);
  } catch (error) {
    if (lookup !== latestLookup) return;
    setMessage(`Could not open ${loaded.symbol}: ${error.message}`, true);
  }
}

function renderPins() {
  const pinnedItems = [...pinnedSummaries.values()];
  emptyPins.hidden = pinnedItems.length > 0;
  clearPinsButton.hidden = pinnedItems.length === 0;
  pinsList.querySelectorAll(".pinned-summary").forEach((item) => item.remove());

  for (const pinned of pinnedItems) {
    const card = document.createElement("article");
    card.className = "pinned-summary";
    const heading = document.createElement("div");
    heading.className = "pinned-summary-heading";
    const symbol = document.createElement("p");
    symbol.className = "pinned-summary-symbol";
    symbol.textContent = pinned.symbol;
    const context = document.createElement("p");
    context.className = "pinned-summary-range";
    context.textContent = `${pinned.startDate} — ${pinned.endDate}`;
    const removeButton = document.createElement("button");
    removeButton.className = "remove-summary";
    removeButton.type = "button";
    removeButton.textContent = "×";
    removeButton.setAttribute("aria-label", `Remove ${pinned.symbol} timeline summary`);
    removeButton.addEventListener("click", () => unpin(pinned));
    heading.append(symbol, removeButton);
    card.append(heading, context);
    if (pinned.points.length) {
      card.append(createPinnedSparkline(pinned.points, pinned.symbol));
    }

    const metrics = document.createElement("div");
    metrics.className = "pinned-summary-metrics";
    for (const metric of pinned.metrics) {
      const item = document.createElement("div");
      item.className = "pinned-summary-metric";
      const label = document.createElement("span");
      label.className = "pinned-summary-label";
      label.textContent = metric.label;
      const value = document.createElement("span");
      value.className = "pinned-summary-value";
      value.textContent = metric.value;
      item.append(label, value);
      metrics.append(item);
    }
    const rowCount = document.createElement("p");
    rowCount.className = "pinned-summary-rows";
    rowCount.textContent = `${pinned.rows.toLocaleString()} daily bars`;
    card.append(metrics, rowCount);
    pinsList.append(card);
  }
}

function renderSummaryPinButton() {
  const canPin = currentSummary && currentSummary.points.length > 0;
  pinSummaryButton.hidden = !canPin;
  if (!canPin) {
    return;
  }
  const isPinned = pinnedSummaries.has(currentSummary.key);
  pinSummaryButton.textContent = isPinned ? "Unpin summary" : "Pin summary";
  pinSummaryButton.setAttribute("aria-pressed", String(isPinned));
}

function buildStats(rows) {
  const stats = [{ key: "rows", label: "Rows returned", value: formatValue(rows.length) }];
  if (!rows.length) {
    return stats;
  }
  stats.push(
    { key: "latest-close", label: "Latest close", value: formatValue(rows.at(-1).close) },
    { key: "period-high", label: "Period high", value: formatValue(Math.max(...rows.map(row => row.high))) },
    { key: "period-low", label: "Period low", value: formatValue(Math.min(...rows.map(row => row.low))) },
  );
  return stats;
}

function renderTable(rows) {
  tableHead.replaceChildren();
  tableBody.replaceChildren();
  const columns = ["session_date", "open", "high", "low", "close", "volume", "provider"];

  const headingRow = document.createElement("tr");
  for (const column of columns) {
    const heading = document.createElement("th");
    heading.scope = "col";
    heading.textContent = column.replaceAll("_", " ");
    headingRow.append(heading);
  }
  tableHead.append(headingRow);

  for (const row of rows) {
    const tableRow = document.createElement("tr");
    for (const column of columns) {
      const cell = document.createElement("td");
      cell.textContent = formatValue(row[column]);
      tableRow.append(cell);
    }
    tableBody.append(tableRow);
  }

  emptyResults.hidden = rows.length > 0;
  historyTable.hidden = rows.length === 0;
}

function createSvgElement(name, attributes = {}, text = "") {
  const element = document.createElementNS(SVG_NAMESPACE, name);
  for (const [attribute, value] of Object.entries(attributes)) {
    element.setAttribute(attribute, String(value));
  }
  element.textContent = text;
  return element;
}

function formatChartDate(timestamp) {
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  }).format(new Date(timestamp));
}

function formatChartPrice(value) {
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  }).format(value);
}

function renderPriceChart(points, symbol, startDate, endDate) {
  chartCard.hidden = points.length === 0;
  if (!points.length) {
    return;
  }

  chartTitle.textContent = `${symbol} closing price`;
  chartRange.textContent = `${startDate} — ${endDate}`;
  priceChart.replaceChildren(chartAccessibleTitle, chartAccessibleDescription);

  priceChart.hidden = false;
  chartAccessibleTitle.textContent = `${symbol} closing-price timeline`;
  chartAccessibleDescription.textContent =
    `${points.length} daily closing prices from ${formatChartDate(points[0].timestamp)} `
    + `to ${formatChartDate(points[points.length - 1].timestamp)}.`;

  const height = 230;
  const plot = { left: 76, right: 704, top: 14, bottom: 184 };
  const prices = points.map((point) => point.price);
  const minimum = Math.min(...prices);
  const maximum = Math.max(...prices);
  const padding = maximum === minimum
    ? Math.max(Math.abs(maximum) * 0.05, 1)
    : (maximum - minimum) * 0.08;
  const lowerBound = minimum - padding;
  const upperBound = maximum + padding;
  const x = (index) => points.length === 1
    ? (plot.left + plot.right) / 2
    : plot.left + (index / (points.length - 1)) * (plot.right - plot.left);
  const y = (price) =>
    plot.bottom - ((price - lowerBound) / (upperBound - lowerBound))
      * (plot.bottom - plot.top);

  for (const fraction of [0, 0.5, 1]) {
    const position = plot.top + fraction * (plot.bottom - plot.top);
    const value = upperBound - fraction * (upperBound - lowerBound);
    priceChart.append(
      createSvgElement("line", {
        x1: plot.left,
        x2: plot.right,
        y1: position,
        y2: position,
        class: "chart-grid-line",
      }),
      createSvgElement(
        "text",
        {
          x: plot.left - 10,
          y: position + 3,
          class: "chart-axis-label",
          "text-anchor": "end",
        },
        formatChartPrice(value),
      ),
    );
  }

  const linePoints = points
    .map((point, index) => `${x(index)},${y(point.price)}`)
    .join(" ");
  priceChart.append(
    createSvgElement("polyline", {
      points: linePoints,
      class: "chart-price-line",
    }),
    createSvgElement("circle", {
      cx: x(0),
      cy: y(points[0].price),
      r: 4,
      class: "chart-price-point",
    }),
    createSvgElement("circle", {
      cx: x(points.length - 1),
      cy: y(points[points.length - 1].price),
      r: 4,
      class: "chart-price-point",
    }),
    createSvgElement(
      "text",
      {
        x: plot.left,
        y: height - 8,
        class: "chart-axis-label",
        "text-anchor": "start",
      },
      formatChartDate(points[0].timestamp),
    ),
    createSvgElement(
      "text",
      {
        x: plot.right,
        y: height - 8,
        class: "chart-axis-label",
        "text-anchor": "end",
      },
      formatChartDate(points[points.length - 1].timestamp),
    ),
  );
}

function updateResult(data) {
  const rows = Array.isArray(data.data) ? data.data : [];
  const symbol = data.symbol || symbolInput.value.trim().toUpperCase();
  const stats = buildStats(rows);
  const points = rows.map(row => ({ timestamp: Date.parse(row.session_date), price: row.close }));
  resultCount.textContent = `${rows.length.toLocaleString()} ${rows.length === 1 ? "row" : "rows"}`;
  currentSummary = rows.length ? summarize(symbol, data.start_date, data.end_date, rows) : null;
  renderSummaryPinButton();
  renderPriceChart(points, symbol, data.start_date, data.end_date);
  renderTable(rows);
  renderStats(stats);
  setMessage(rows.length ? `Loaded ${rows.length.toLocaleString()} rows for ${symbol}.` : `No rows found for ${symbol}.`);
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const symbol = symbolInput.value.trim().toUpperCase();
  const startDate = startDateInput.value;
  const endDate = endDateInput.value;

  if (!/^[A-Z0-9.^_-]{1,16}$/.test(symbol)) {
    setMessage("Enter a valid ticker symbol.", true);
    symbolInput.focus();
    return;
  }
  if (!startDate || !endDate || startDate > endDate) {
    setMessage("Choose a valid date range.", true);
    return;
  }
  const rangeDays = (
    Date.parse(`${endDate}T00:00:00Z`) - Date.parse(`${startDate}T00:00:00Z`)
  ) / (24 * 60 * 60 * 1000);
  if (rangeDays > MAX_HISTORY_DAYS) {
    setMessage(`Choose a date range of no more than ${MAX_HISTORY_DAYS} days.`, true);
    return;
  }

  symbolInput.value = symbol;
  submitButton.disabled = true;
  submitButton.querySelector("span").textContent = "Loading…";
  setMessage(`Looking up ${symbol}…`);
  const lookup = startLookup();
  try {
    const response = await fetch(
      `/api/v1/stocks/${encodeURIComponent(symbol)}/bars/fetch`,
      {
        method: "POST",
        headers: { Accept: "application/json", "Content-Type": "application/json" },
        body: JSON.stringify({ start_date: startDate, end_date: endDate, refresh: refreshBarsInput.checked }),
      },
    );
    updateQuota(response);
    // Error pages from the host check or a crash are not JSON.
    const result = await response.json().catch(() => ({}));
    if (!response.ok) {
      const retryAfter = response.headers.get("Retry-After");
      const detail = result.detail || `Request failed (${response.status}).`;
      throw new Error(
        response.status === 429 && retryAfter
          ? `${detail} Try again in ${retryAfter} seconds.`
          : detail,
      );
    }
    refreshBarsInput.checked = false;
    loadLoadedTickers();
    if (lookup !== latestLookup) return;
    updateResult(result);
  } catch (error) {
    if (lookup !== latestLookup) return;
    resultCount.textContent = "Lookup failed";
    setMessage(error instanceof Error ? error.message : "The lookup failed.", true);
  } finally {
    submitButton.disabled = false;
    submitButton.querySelector("span").textContent = "Load history";
  }
});

pinSummaryButton.addEventListener("click", async () => {
  if (!currentSummary || !currentSummary.points.length) {
    return;
  }
  const summary = currentSummary;
  pinSummaryButton.disabled = true;
  await (pinnedSummaries.has(summary.key) ? unpin(summary) : pin(summary));
  pinSummaryButton.disabled = false;
});

clearPinsButton.addEventListener("click", async () => {
  try {
    await requestJson("/api/v1/pins", { method: "DELETE" });
    pinnedSummaries.clear();
  } catch (error) {
    setMessage(`Could not clear pinned summaries: ${error.message}`, true);
  }
  renderPins();
  renderSummaryPinButton();
});

openSettingsButton.addEventListener("click", openSettings);
shutdownButton.addEventListener("click", shutDown);
closeSettingsButton.addEventListener("click", () => settingsDialog.close());
settingsForm.addEventListener("submit", saveSettings);
clearApiKeyButton.addEventListener("click", () => changeCredentials({ clear_api_key: true }, "Removed the API key."));
clearCredentialsButton.addEventListener("click", () => changeCredentials({ clear_credentials: true }, "Removed the account."));
settingsDialog.addEventListener("click", (event) => {
  if (event.target === settingsDialog) {
    settingsDialog.close();
  }
});
settingsDialog.addEventListener("close", () => {
  settingsForm.reset();
  setSettingsStatus("");
});

browseSymbolsButton.addEventListener("click", async () => {
  symbolSearch.value = "";
  symbolsDialog.showModal();
  await loadStockSymbols();
  symbolSearch.focus();
});

closeSymbolsButton.addEventListener("click", () => symbolsDialog.close());
symbolSearch.addEventListener("input", renderStockSymbols);
symbolsDialog.addEventListener("click", (event) => {
  if (event.target === symbolsDialog) {
    symbolsDialog.close();
  }
});

symbolInput.addEventListener("input", () => {
  symbolInput.value = symbolInput.value.toUpperCase();
  renderTickerSuggestions();
});

setDefaultDates();
loadPins();
loadLoadedTickers();
