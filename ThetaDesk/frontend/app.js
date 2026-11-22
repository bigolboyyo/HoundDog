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

const MAX_HISTORY_DAYS = 365;
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

function setSettingsStatus(message, isError = false) {
  settingsStatus.textContent = message;
  settingsStatus.classList.toggle("error", isError);
}

async function openSettings() {
  settingsDialog.showModal();
  settingsSaveButton.disabled = true;
  setSettingsStatus("Loading saved settings…");

  try {
    const response = await fetch("/api/v1/settings/credentials", {
      headers: { Accept: "application/json" },
      cache: "no-store",
    });
    const result = await response.json();
    if (!response.ok) {
      throw new Error(result.detail || `Request failed (${response.status}).`);
    }

    settingsApiKey.value = result.api_key || "";
    settingsEmail.value = result.email || "";
    settingsPassword.value = result.password || "";
    const configured = Boolean(
      result.api_key || (result.email && result.password),
    );
    setSettingsStatus(
      configured
        ? "Existing credentials loaded from the app folder."
        : "No saved credentials found in the app folder.",
    );
  } catch (error) {
    setSettingsStatus(
      error instanceof Error ? error.message : "Could not load settings.",
      true,
    );
  } finally {
    settingsSaveButton.disabled = false;
  }
}

async function saveSettings(event) {
  event.preventDefault();
  settingsSaveButton.disabled = true;
  setSettingsStatus("Saving settings…");

  try {
    const response = await fetch("/api/v1/settings/credentials", {
      method: "PUT",
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      cache: "no-store",
      body: JSON.stringify({
        api_key: settingsApiKey.value,
        email: settingsEmail.value,
        password: settingsPassword.value,
      }),
    });
    const result = await response.json();
    if (!response.ok) {
      throw new Error(result.detail || `Request failed (${response.status}).`);
    }

    setSettingsStatus(
      result.api_key_configured || result.credentials_configured
        ? "Saved locally. The Python SDK will use these next; restart Terminal for REST backup changes."
        : "Saved. No credentials are configured.",
    );
  } catch (error) {
    setSettingsStatus(
      error instanceof Error ? error.message : "Could not save settings.",
      true,
    );
  } finally {
    settingsSaveButton.disabled = false;
  }
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
    removeButton.addEventListener("click", () => {
      pinnedSummaries.delete(pinned.key);
      renderPins();
      renderSummaryPinButton();
    });
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
  const context = `${data.start_date} — ${data.end_date}`;
  const stats = buildStats(rows);
  const points = rows.map(row => ({ timestamp: Date.parse(row.session_date), price: row.close }));
  resultCount.textContent = `${rows.length.toLocaleString()} ${rows.length === 1 ? "row" : "rows"}`;
  currentSummary = rows.length
    ? {
      key: `${symbol}:${context}`,
      symbol,
      startDate: data.start_date,
      endDate: data.end_date,
      rows: rows.length,
      points,
      metrics: getPinnedMetrics(stats),
    }
    : null;
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
    updateResult(result);
    refreshBarsInput.checked = false;
  } catch (error) {
    resultCount.textContent = "Lookup failed";
    setMessage(error instanceof Error ? error.message : "The lookup failed.", true);
  } finally {
    submitButton.disabled = false;
    submitButton.querySelector("span").textContent = "Load history";
  }
});

pinSummaryButton.addEventListener("click", () => {
  if (!currentSummary || !currentSummary.points.length) {
    return;
  }
  if (pinnedSummaries.has(currentSummary.key)) {
    pinnedSummaries.delete(currentSummary.key);
  } else {
    pinnedSummaries.set(currentSummary.key, currentSummary);
  }
  renderPins();
  renderSummaryPinButton();
});

clearPinsButton.addEventListener("click", () => {
  pinnedSummaries.clear();
  renderPins();
  renderSummaryPinButton();
});

openSettingsButton.addEventListener("click", openSettings);
closeSettingsButton.addEventListener("click", () => settingsDialog.close());
settingsForm.addEventListener("submit", saveSettings);
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
