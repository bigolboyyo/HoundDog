const elements = {
  notice: document.querySelector("#notice"),
  checkButton: document.querySelector("#check-button"),
  dryRunButton: document.querySelector("#dry-run-button"),
  checkStatus: document.querySelector("#check-status"),
  sourceCount: document.querySelector("#source-count"),
  topicCount: document.querySelector("#topic-count"),
  historyCount: document.querySelector("#history-count"),
  feedsList: document.querySelector("#feeds-list"),
  topicsList: document.querySelector("#topics-list"),
  feedForm: document.querySelector("#feed-form"),
  feedFormTitle: document.querySelector("#feed-form-title"),
  feedName: document.querySelector("#feed-name"),
  feedUrl: document.querySelector("#feed-url"),
  feedInterval: document.querySelector("#feed-interval"),
  topicForm: document.querySelector("#topic-form"),
  topicFormTitle: document.querySelector("#topic-form-title"),
  topicName: document.querySelector("#topic-name"),
  topicKeywords: document.querySelector("#topic-keywords"),
  topicExclude: document.querySelector("#topic-exclude"),
  uiScale: document.querySelector("#ui-scale"),
  uiScaleValue: document.querySelector("#ui-scale-value"),
  autoCheckStatus: document.querySelector("#auto-check-status"),
  showImages: document.querySelector("#show-images"),
  checkInterval: document.querySelector("#check-interval"),
  checkModeOff: document.querySelector("#check-mode-off"),
  checkModeDashboard: document.querySelector("#check-mode-dashboard"),
  checkModeBackground: document.querySelector("#check-mode-background"),
  checkModeStatus: document.querySelector("#check-mode-status"),
  checkModeHint: document.querySelector("#check-mode-hint"),
  dashboardCheckAction: document.querySelector("#dashboard-check-action"),
  backgroundCheckOptions: document.querySelector("#background-check-options"),
  jobBattery: document.querySelector("#job-battery"),
  jobCatchUp: document.querySelector("#job-catch-up"),
  jobNetwork: document.querySelector("#job-network"),
  jobRepair: document.querySelector("#job-repair"),
  jobLogDetails: document.querySelector("#job-log-details"),
  jobLog: document.querySelector("#job-log"),
  jobLogClear: document.querySelector("#job-log-clear"),
  autoCheckAction: document.querySelector("#auto-check-action"),
  notifyNewMatches: document.querySelector("#notify-new-matches"),
  importFile: document.querySelector("#import-file"),
  importConfig: document.querySelector("#import-config"),
  importHistory: document.querySelector("#import-history"),
  importButton: document.querySelector("#import-button"),
  healthList: document.querySelector("#health-list"),
  healthToolButton: document.querySelector('.tool-button[data-tool="health"]'),
  activityList: document.querySelector("#activity-list"),
  testerForm: document.querySelector("#tester-form"),
  testerTopic: document.querySelector("#tester-topic"),
  testerCorpus: document.querySelector("#tester-corpus"),
  testerName: document.querySelector("#tester-name"),
  testerKeywords: document.querySelector("#tester-keywords"),
  testerExclude: document.querySelector("#tester-exclude"),
  testerRefresh: document.querySelector("#tester-refresh"),
  testerSummary: document.querySelector("#tester-summary"),
  testerKeywordReport: document.querySelector("#tester-keyword-report"),
  testerResults: document.querySelector("#tester-results"),
  inboxCount: document.querySelector("#inbox-count"),
  inboxMarkRead: document.querySelector("#inbox-mark-read"),
  historyFilter: document.querySelector("#history-filter"),
  jobRun: document.querySelector("#job-run"),
};

let feeds = [];
let topics = [];
// The feed or topic open in its editor, as it was when opened; null when adding.
let editingFeed = null;
let editingTopic = null;

const themeOptions = Array.from(document.querySelectorAll('input[name="app-theme"]'));
const modeOptions = Array.from(document.querySelectorAll('input[name="color-mode"]'));
const themeStorageKey = "keyword-watcher-theme";
const modeStorageKey = "keyword-watcher-color-mode";
const sizeStorageKey = "keyword-watcher-ui-size";
// Feed images are off by default: loading one tells the publisher your IP address.
const showImagesStorageKey = "keyword-watcher-show-images";
let showImages = window.localStorage.getItem(showImagesStorageKey) === "true";
let nesStylesheetAvailable = false;
const nesThemeCard = document.querySelector("#theme-card-nes");
nesThemeCard.hidden = true;

// NES.css styles html, a, and button globally (cursor, fonts), so it is always
// downloaded to detect availability but only applied while the NES theme is active.
const nesStylesheet = document.createElement("link");
nesStylesheet.rel = "stylesheet";
nesStylesheet.media = "not all";
nesStylesheet.href = "https://unpkg.com/nes.css@2.3.0/css/nes.min.css";
nesStylesheet.integrity = "sha256-wLUnaaQIEYrGypLYlA5326irkul4CcQ2WEhPgeqDt1Y=";
nesStylesheet.crossOrigin = "anonymous";
nesStylesheet.referrerPolicy = "no-referrer";

function applyColorMode(mode) {
  const activeMode = modeOptions.some((option) => option.value === mode) ? mode : "light";
  document.documentElement.dataset.colorMode = activeMode;
  document.documentElement.dataset.theme = activeMode;
  modeOptions.forEach((option) => {
    const active = option.value === activeMode;
    option.checked = active;
    document.querySelector(`#mode-card-${option.value}`).classList.toggle("is-selected", active);
  });
  return activeMode;
}

function applyTheme(theme) {
  const activeTheme = themeOptions.some((option) =>
    option.value === theme && (option.value !== "nes" || nesStylesheetAvailable),
  ) ? theme : "pico";
  const isNes = activeTheme === "nes";
  const isDark = document.documentElement.dataset.colorMode === "dark";
  document.documentElement.dataset.appTheme = activeTheme;
  nesStylesheet.media = isNes ? "all" : "not all";

  themeOptions.forEach((option) => {
    const active = option.value === activeTheme;
    option.checked = active;
    document.querySelector(`#theme-card-${option.value}`).classList.toggle("is-selected", active);
    document.querySelector(`#theme-active-${option.value}`).hidden = !active;
  });

  document.querySelectorAll(".panel, .stat, .item, .editor-form, .theme-option, .tool-flyout").forEach((item) => {
    item.classList.toggle("nes-container", isNes);
    item.classList.toggle("is-dark", isNes && isDark);
  });
  document.querySelectorAll("button.button").forEach((button) => {
    button.classList.toggle("nes-btn", isNes);
    button.classList.toggle(
      "is-primary",
      isNes && button.classList.contains("button-primary"),
    );
  });
  return activeTheme;
}

// Must match the classes applyTheme toggles, or re-rendered cards lose them.
function themeComponentClass() {
  if (document.documentElement.dataset.appTheme !== "nes") return "";
  return document.documentElement.dataset.colorMode === "dark" ? "nes-container is-dark" : "nes-container";
}

function applyUiScale(value) {
  const scale = Number.isFinite(value)
    ? Math.min(120, Math.max(80, Math.round((value - 80) / 5) * 5 + 80))
    : 100;
  elements.uiScale.value = String(scale);
  elements.uiScaleValue.value = `${scale}%`;
  elements.uiScaleValue.textContent = `${scale}%`;
  document.documentElement.style.setProperty("--app-ui-scale", String(scale / 100));
  return scale;
}

const storedMode = window.localStorage.getItem(modeStorageKey);
const activeMode = applyColorMode(storedMode || "light");
if (storedMode !== activeMode) {
  window.localStorage.setItem(modeStorageKey, activeMode);
}
modeOptions.forEach((option) => {
  option.addEventListener("change", () => {
    if (!option.checked) return;
    const selectedMode = applyColorMode(option.value);
    applyTheme(document.documentElement.dataset.appTheme);
    window.localStorage.setItem(modeStorageKey, selectedMode);
    showNotice(`${selectedMode[0].toUpperCase()}${selectedMode.slice(1)} mode selected.`);
  });
});

const storedTheme = window.localStorage.getItem(themeStorageKey);
const activeTheme = applyTheme(storedTheme === "nes" ? "pico" : (storedTheme || "pico"));
if (storedTheme !== "nes" && storedTheme !== activeTheme) {
  window.localStorage.setItem(themeStorageKey, activeTheme);
}
themeOptions.forEach((option) => {
  option.addEventListener("change", () => {
    if (!option.checked) return;
    const selectedTheme = applyTheme(option.value);
    window.localStorage.setItem(themeStorageKey, selectedTheme);
    const themeName = {
      pico: "Pico default",
      dos: "Classic DOS terminal",
      nes: "8-bit NES.css",
    }[selectedTheme];
    showNotice(`${themeName} theme selected.`);
  });
});

nesStylesheet.addEventListener("load", () => {
  nesStylesheetAvailable = true;
  nesThemeCard.hidden = false;
  if (storedTheme === "nes" && window.localStorage.getItem(themeStorageKey) === "nes") {
    applyTheme("nes");
  }
});
nesStylesheet.addEventListener("error", () => {
  nesThemeCard.hidden = true;
  if (document.documentElement.dataset.appTheme === "nes") {
    applyTheme("pico");
  }
  if (window.localStorage.getItem(themeStorageKey) === "nes") {
    window.localStorage.setItem(themeStorageKey, "pico");
  }
});
document.head.append(nesStylesheet);

const storedSizeValue = window.localStorage.getItem(sizeStorageKey);
const storedSize = storedSizeValue === null ? Number.NaN : Number(storedSizeValue);
const initialSize = Number.isFinite(storedSize) ? storedSize : 100;
const activeSize = applyUiScale(initialSize);
if (storedSize !== activeSize) {
  window.localStorage.setItem(sizeStorageKey, String(activeSize));
}
elements.uiScale.addEventListener("input", () => {
  const selectedSize = applyUiScale(Number(elements.uiScale.value));
  window.localStorage.setItem(sizeStorageKey, String(selectedSize));
});

const htmlEscapes = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
};

// Escapes quotes too: the result is used inside attribute values, which the
// textContent/innerHTML trick does not make safe.
function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => htmlEscapes[character]);
}

function safeHttpUrl(value) {
  const url = typeof value === "string" ? value.trim() : "";
  return /^https?:\/\/\S+$/i.test(url) ? url : "";
}

function formatDate(value) {
  if (!value) return "";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

// Multiples of 12 fill the last row whether the grid has 1, 2, 3, or 4 columns.
const PAGE_SIZE_CHOICES = [
  { value: "12", label: "12" },
  { value: "24", label: "24" },
  { value: "48", label: "48" },
  { value: "all", label: "All (can be slow)" },
];
const DEFAULT_PAGE_SIZE = "12";
const SEARCH_DELAY_MS = 150;
const WORD_PATTERN = /[^\p{L}\p{N}]+/u;

function normalizeSearchText(value) {
  return String(value ?? "").normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();
}

function indexSearchFields(item, fields) {
  return fields.map(({ weight, value }) => {
    const text = normalizeSearchText(value(item));
    return { weight, text, words: text.split(WORD_PATTERN).filter(Boolean) };
  });
}

// Optimal string alignment distance (Levenshtein plus adjacent swaps). Returns
// limit + 1 as soon as the distance is known to exceed limit.
function editDistance(a, b, limit) {
  if (Math.abs(a.length - b.length) > limit) return limit + 1;
  let beforePrevious = [];
  let previous = Array.from({ length: b.length + 1 }, (_, j) => j);
  for (let i = 1; i <= a.length; i += 1) {
    const current = [i];
    let rowMinimum = i;
    for (let j = 1; j <= b.length; j += 1) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1;
      let distance = Math.min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost);
      if (i > 1 && j > 1 && a[i - 1] === b[j - 2] && a[i - 2] === b[j - 1]) {
        distance = Math.min(distance, beforePrevious[j - 2] + 1);
      }
      current[j] = distance;
      rowMinimum = Math.min(rowMinimum, distance);
    }
    if (rowMinimum > limit) return limit + 1;
    beforePrevious = previous;
    previous = current;
  }
  return previous[b.length];
}

// Scores one query term against a field: 3 when a word starts with it, 2 when it
// appears anywhere, 1 when a word (or its prefix) is within a small typo
// distance. Typo checks are cached per word, since the vocabulary repeats.
function termMatcher(term) {
  const limit = term.length >= 8 ? 2 : 1;
  const nearMisses = new Map();
  const isNearMiss = (word) => {
    let result = nearMisses.get(word);
    if (result === undefined) {
      result = editDistance(term, word, limit) <= limit
        || (word.length > term.length && editDistance(term, word.slice(0, term.length), limit) <= limit);
      nearMisses.set(word, result);
    }
    return result;
  };

  return (field) => {
    if (field.words.some((word) => word.startsWith(term))) return 3;
    if (field.text.includes(term)) return 2;
    if (term.length < 4) return 0;
    return field.words.some(isNearMiss) ? 1 : 0;
  };
}

function searchMatchers(query) {
  return normalizeSearchText(query).split(/\s+/).filter(Boolean).map(termMatcher);
}

// Every term must match some field; the best weighted field score per term is summed.
function searchScore(matchers, fields) {
  let total = 0;
  for (const matcher of matchers) {
    const best = Math.max(...fields.map((field) => matcher(field) * field.weight));
    if (best === 0) return 0;
    total += best;
  }
  return total;
}

class PagedList {
  // emptyText is a string, or a function for text that depends on the filter.
  constructor(name, { fields, renderItem, emptyText }) {
    this.list = document.querySelector(`#${name}-list`);
    this.search = document.querySelector(`#${name}-search`);
    this.pager = document.querySelector(`#${name}-pager`);
    this.previousButton = document.querySelector(`#${name}-prev`);
    this.nextButton = document.querySelector(`#${name}-next`);
    this.status = document.querySelector(`#${name}-page-status`);
    this.pageSizeSelect = document.querySelector(`#${name}-page-size`);
    this.pageSizeStorageKey = `keyword-watcher-page-size-${name}`;
    this.fields = fields;
    this.renderItem = renderItem;
    this.emptyText = emptyText;
    this.entries = [];
    this.filter = () => true;
    this.query = "";
    this.page = 1;

    this.search.addEventListener("input", () => {
      window.clearTimeout(this.searchTimer);
      this.searchTimer = window.setTimeout(() => {
        this.query = this.search.value;
        this.page = 1;
        this.render();
      }, SEARCH_DELAY_MS);
    });
    this.previousButton.addEventListener("click", () => this.showPage(this.page - 1));
    this.nextButton.addEventListener("click", () => this.showPage(this.page + 1));

    const storedPageSize = window.localStorage.getItem(this.pageSizeStorageKey);
    this.pageSizeValue = PAGE_SIZE_CHOICES.some((choice) => choice.value === storedPageSize)
      ? storedPageSize
      : DEFAULT_PAGE_SIZE;
    this.pageSizeSelect.innerHTML = PAGE_SIZE_CHOICES
      .map((choice) => `<option value="${choice.value}">${escapeHtml(choice.label)}</option>`)
      .join("");
    this.pageSizeSelect.value = this.pageSizeValue;
    this.pageSizeSelect.addEventListener("change", () => {
      this.pageSizeValue = this.pageSizeSelect.value;
      window.localStorage.setItem(this.pageSizeStorageKey, this.pageSizeValue);
      this.page = 1;
      this.render();
    });
  }

  // null means every result on one page.
  pageSize() {
    return this.pageSizeValue === "all" ? null : Number(this.pageSizeValue);
  }

  setItems(items) {
    this.entries = items.map((item, order) => ({
      item,
      order,
      fields: indexSearchFields(item, this.fields),
    }));
    this.render();
  }

  setFilter(filter) {
    this.filter = filter;
    this.page = 1;
    this.render();
  }

  showPage(page) {
    this.page = page;
    this.render();
    this.list.scrollIntoView({ block: "start" });
  }

  filtered() {
    return this.entries.filter((entry) => this.filter(entry.item));
  }

  // Items matching the filter and the search, best search match first.
  results() {
    const filtered = this.filtered();
    const matchers = searchMatchers(this.query);
    if (!matchers.length) return filtered;
    return filtered
      .map((entry) => ({ entry, score: searchScore(matchers, entry.fields) }))
      .filter(({ score }) => score > 0)
      .sort((a, b) => b.score - a.score || a.entry.order - b.entry.order)
      .map(({ entry }) => entry);
  }

  render() {
    const results = this.results();
    const pageSize = this.pageSize();
    const pageCount = pageSize ? Math.max(1, Math.ceil(results.length / pageSize)) : 1;
    this.page = Math.min(Math.max(1, this.page), pageCount);
    const visible = pageSize ? results.slice((this.page - 1) * pageSize, this.page * pageSize) : results;

    if (!this.filtered().length) {
      const emptyText = typeof this.emptyText === "function" ? this.emptyText() : this.emptyText;
      this.list.innerHTML = `<p class="empty">${escapeHtml(emptyText)}</p>`;
    } else if (!results.length) {
      this.list.innerHTML = `<p class="empty">No results for "${escapeHtml(this.query.trim())}".</p>`;
    } else {
      this.list.innerHTML = visible.map(({ item }) => this.renderItem(item)).join("");
    }

    const noun = this.query.trim() ? "result" : "item";
    const count = `${results.length} ${noun}${results.length === 1 ? "" : "s"}`;
    this.pager.hidden = results.length === 0;
    this.previousButton.disabled = this.page <= 1;
    this.nextButton.disabled = this.page >= pageCount;
    this.status.textContent = pageCount > 1 ? `Page ${this.page} of ${pageCount} · ${count}` : count;
  }
}

function showNotice(message) {
  elements.notice.textContent = message;
  elements.notice.hidden = false;
  window.clearTimeout(showNotice.timeout);
  showNotice.timeout = window.setTimeout(() => {
    elements.notice.hidden = true;
  }, 5000);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers ?? {}),
    },
  });

  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(payload.error || `Request failed (${response.status})`);
    error.status = response.status;
    throw error;
  }
  return payload;
}

// Feeds and topics are addressed by position, which shifts when another tab or a
// hand edit of watch.toml changes the list. So an edit looks up where the entry
// is now, and sends the entry as "expected"; the server refuses with 409 Conflict
// if that position holds something else by the time the request arrives.
const HTTP_CONFLICT = 409;

function feedPosition(feed) {
  return feeds.findIndex((candidate) => candidate.name === feed.name && candidate.url === feed.url);
}

function topicPosition(topic) {
  return topics.findIndex((candidate) => candidate.name === topic.name);
}

async function changeConfigEntry(kind, position, expected, method, entry = {}) {
  if (position === -1) {
    throw new Error(`"${expected.name}" was changed or removed elsewhere; check the list and try again.`);
  }
  return api(`/api/${kind}/${position}`, { method, body: JSON.stringify({ ...entry, expected }) });
}

async function reportConfigError(error) {
  showNotice(error.message);
  if (error.status === HTTP_CONFLICT) await refresh();
}

function setLoading(button, loading) {
  if (loading) {
    button.dataset.idleText = button.textContent;
    button.textContent = "Working...";
  } else {
    button.textContent = button.dataset.idleText;
  }
  button.disabled = loading;
}

function formatMinutes(minutes) {
  if (minutes % 1440 === 0) return `${minutes / 1440} day${minutes === 1440 ? "" : "s"}`;
  if (minutes % 60 === 0) return `${minutes / 60} hour${minutes === 60 ? "" : "s"}`;
  return `${minutes} minute${minutes === 1 ? "" : "s"}`;
}

function renderFeeds() {
  if (!feeds.length) {
    elements.feedsList.innerHTML = '<p class="empty">No feed sources configured.</p>';
    return;
  }

  elements.feedsList.innerHTML = feeds.map((feed, index) => `
    <article class="item ${themeComponentClass()}">
      <div class="item-heading">
        <div>
          <strong>${escapeHtml(feed.name)}</strong>
          <p>${escapeHtml(feed.url)}</p>
          ${feed.check_every_minutes ? `<p>Checked every ${escapeHtml(formatMinutes(feed.check_every_minutes))}</p>` : ""}
        </div>
        <div class="item-actions">
          <button class="text-button" type="button" data-edit-feed="${index}">Edit</button>
          <button class="text-button danger" type="button" data-delete-feed="${index}">Delete</button>
        </div>
      </div>
    </article>
  `).join("");
}

function renderTopics() {
  if (!topics.length) {
    elements.topicsList.innerHTML = '<p class="empty">No topics configured yet.</p>';
    return;
  }

  elements.topicsList.innerHTML = topics.map((topic, index) => {
    const exclude = topic.exclude ?? [];
    return `
      <article class="item ${themeComponentClass()}">
        <div class="item-heading">
          <div>
            <strong>${escapeHtml(topic.name)}</strong>
            <p>Include: ${topic.keywords.map(escapeHtml).join(", ")}</p>
            ${exclude.length ? `<p>Exclude: ${exclude.map(escapeHtml).join(", ")}</p>` : ""}
          </div>
          <div class="item-actions">
            <button class="text-button" type="button" data-edit-topic="${index}">Edit</button>
            <button class="text-button danger" type="button" data-delete-topic="${index}">Delete</button>
          </div>
        </div>
      </article>
    `;
  }).join("");
}

// Shared card for Matches, Inbox, and History: fixed-ratio media area on top (image, or
// the source name as a placeholder), then clamped text so every card in a grid
// lines up.
//
// article.state ({ read, starred }) is set only for saved articles; their cards
// carry the raw link in data-link and get read/star actions.
function renderArticleCard(article) {
  const link = safeHttpUrl(article.link);
  const state = article.state;
  const image = showImages ? safeHttpUrl(article.image) : "";
  const byline = [article.source, article.author].filter(Boolean).join(" · ");
  const dates = [
    article.published ? `Published ${formatDate(article.published)}` : "",
    article.found ? `Found ${formatDate(article.found)}` : "",
  ].filter(Boolean).join(" · ");
  const keywords = article.keywords ?? [];
  const title = article.title || "Untitled item";

  const stateClasses = state
    ? `${state.read ? " is-read" : ""}${state.starred ? " is-starred" : ""}`
    : "";
  const stateAttributes = state
    ? ` data-link="${escapeHtml(article.link)}" data-read="${state.read}" data-starred="${state.starred}"`
    : "";
  // The UI calls starred articles favorites; the data keeps the starred name.
  const favoriteLabel = state?.starred ? "Remove from favorites" : "Add to favorites";
  const actions = state ? `
        <div class="article-actions">
          <button class="text-button" type="button" data-item-action="read">${state.read ? "Mark unread" : "Mark read"}</button>
          <button class="text-button favorite-button" type="button" data-item-action="star" aria-pressed="${state.starred}" aria-label="${favoriteLabel}" title="${favoriteLabel}">${state.starred ? "\u2605" : "\u2606"}</button>
        </div>` : "";

  // The banner opens the article too. It repeats the text link below, so it is
  // kept out of the tab order and hidden from screen readers.
  const media = `
        <span class="article-media-label" aria-hidden="true">${escapeHtml(article.source || article.topic)}</span>
        ${image ? `<img class="article-image" src="${escapeHtml(image)}" alt="" loading="lazy" decoding="async">` : ""}`;
  const banner = link
    ? `<a class="article-media" href="${escapeHtml(link)}" target="_blank" rel="noreferrer" tabindex="-1" aria-hidden="true">${media}</a>`
    : `<div class="article-media">${media}</div>`;

  return `
    <article class="item article-card${stateClasses} ${themeComponentClass()}"${stateAttributes}>
      ${banner}
      <div class="article-content">
        <span class="article-topic">${escapeHtml(article.topic)}</span>
        <strong class="article-title" title="${escapeHtml(title)}">${escapeHtml(title)}</strong>
        ${byline ? `<p class="article-line" title="${escapeHtml(byline)}">${escapeHtml(byline)}</p>` : ""}
        ${dates ? `<p class="article-line" title="${escapeHtml(dates)}">${escapeHtml(dates)}</p>` : ""}
        ${keywords.length ? `<p class="article-line article-keywords">Matched: ${escapeHtml(keywords.join(", "))}</p>` : ""}
        ${article.summary ? `<p class="article-summary">${escapeHtml(article.summary)}</p>` : ""}
        ${link ? `<a class="article-link" href="${escapeHtml(link)}" title="${escapeHtml(link)}" aria-label="Open link: ${escapeHtml(link)}" target="_blank" rel="noreferrer">${escapeHtml(link)}</a>` : ""}${actions}
      </div>
    </article>
  `;
}

// Inbox entries are articles: one per link, with every topic that matched it.
// History entries are rows: one per topic and link.
function renderSavedItem(item) {
  return renderArticleCard({
    topic: (item.topics ?? [item.topic]).join(" · "),
    title: item.title,
    source: item.source,
    author: item.author,
    published: item.published_at || item.published,
    found: item.first_seen,
    summary: item.summary,
    link: item.link,
    image: item.image_url,
    state: { read: Boolean(item.read_at), starred: Boolean(item.starred_at) },
  });
}

function unreadArticles(rows) {
  const byLink = new Map();
  for (const row of rows) {
    if (row.read_at) continue;
    const article = byLink.get(row.link);
    if (article) {
      article.topics.push(row.topic);
    } else {
      byLink.set(row.link, { ...row, topics: [row.topic] });
    }
  }
  return [...byLink.values()];
}

function renderMatchItem(match) {
  return renderArticleCard({
    topic: match.topic,
    title: match.item.title,
    source: match.item.source,
    author: match.item.author,
    published: match.item.published_at || match.item.published,
    keywords: match.keywords,
    summary: match.item.summary,
    link: match.item.link,
    image: match.item.image_url,
  });
}

const matchesView = new PagedList("matches", {
  renderItem: renderMatchItem,
  emptyText: "No new matches.",
  fields: [
    { weight: 3, value: (match) => match.item.title },
    { weight: 2, value: (match) => match.topic },
    { weight: 2, value: (match) => match.item.source },
    { weight: 2, value: (match) => match.keywords.join(" ") },
    { weight: 1, value: (match) => match.item.summary },
    { weight: 1, value: (match) => match.item.link },
  ],
});

const SAVED_ITEM_FIELDS = [
  { weight: 3, value: (item) => item.title },
  { weight: 2, value: (item) => (item.topics ?? [item.topic]).join(" ") },
  { weight: 2, value: (item) => item.source },
  { weight: 1, value: (item) => item.author },
  { weight: 1, value: (item) => item.summary },
  { weight: 1, value: (item) => item.link },
];

const inboxView = new PagedList("inbox", {
  renderItem: renderSavedItem,
  emptyText: "Nothing unread. New matches from saved checks land here.",
  fields: SAVED_ITEM_FIELDS,
});

const HISTORY_FILTERS = {
  all: { matches: () => true, emptyText: "No history yet." },
  unread: { matches: (item) => !item.read_at, emptyText: "No unread items in History." },
  starred: { matches: (item) => Boolean(item.starred_at), emptyText: "No favorites yet. Favorites are kept past the retention period." },
};
const historyFilterStorageKey = "keyword-watcher-history-filter";

const historyView = new PagedList("history", {
  renderItem: renderSavedItem,
  emptyText: () => HISTORY_FILTERS[historyFilterName(elements.historyFilter.value)].emptyText,
  fields: SAVED_ITEM_FIELDS,
});


// Feed images often fail (hotlink protection, dead links). Removing the <img>
// reveals the source-name placeholder behind it. Error events do not bubble,
// so listen in the capture phase.
function removeBrokenImage(event) {
  if (event.target.tagName === "IMG") event.target.remove();
}
matchesView.list.addEventListener("error", removeBrokenImage, true);
inboxView.list.addEventListener("error", removeBrokenImage, true);
historyView.list.addEventListener("error", removeBrokenImage, true);

// Read and starred belong to the article (its link), wherever its card is shown.
// Requests name the links explicitly, so an article that arrives between render
// and click is never marked read unseen.
async function setItemState(links, flags) {
  await api("/api/items/state", { method: "PUT", body: JSON.stringify({ links, ...flags }) });
}

// Both open the article: the text link and the banner above it.
const ARTICLE_LINKS = "a.article-link, a.article-media";

async function handleSavedItemClick(event) {
  // auxclick also fires for the right button, which opens a menu, not the link.
  if (event.type === "auxclick" && event.button !== 1) return;
  const card = event.target.closest("[data-link]");
  if (!card) return;
  const link = card.dataset.link;
  const action = event.target.closest("[data-item-action]")?.dataset.itemAction;
  try {
    if (action === "read") {
      await setItemState([link], { read: card.dataset.read !== "true" });
    } else if (action === "star") {
      await setItemState([link], { starred: card.dataset.starred !== "true" });
    } else if (event.target.closest(ARTICLE_LINKS) && card.dataset.read !== "true") {
      // Opening an article reads it. The link still opens normally.
      await setItemState([link], { read: true });
    } else {
      return;
    }
    await refresh();
  } catch (error) {
    showNotice(error.message);
  }
}

for (const view of [inboxView, historyView]) {
  view.list.addEventListener("click", handleSavedItemClick);
  // Middle-click opens a link in a new tab without a click event.
  view.list.addEventListener("auxclick", handleSavedItemClick);
}

const MAX_STATE_LINKS = 5000;

elements.inboxMarkRead.addEventListener("click", async () => {
  const links = inboxView.results().map(({ item }) => item.link);
  if (!links.length) return;
  try {
    for (let start = 0; start < links.length; start += MAX_STATE_LINKS) {
      await setItemState(links.slice(start, start + MAX_STATE_LINKS), { read: true });
    }
    showNotice(`Marked ${links.length} article${links.length === 1 ? "" : "s"} read.`);
    await refresh();
  } catch (error) {
    showNotice(error.message);
  }
});

function historyFilterName(value) {
  return Object.hasOwn(HISTORY_FILTERS, value ?? "") ? value : "all";
}

elements.historyFilter.value = historyFilterName(window.localStorage.getItem(historyFilterStorageKey));
historyView.filter = HISTORY_FILTERS[elements.historyFilter.value].matches;
elements.historyFilter.addEventListener("change", () => {
  const name = historyFilterName(elements.historyFilter.value);
  window.localStorage.setItem(historyFilterStorageKey, name);
  historyView.setFilter(HISTORY_FILTERS[name].matches);
});

elements.showImages.checked = showImages;
elements.showImages.addEventListener("change", () => {
  showImages = elements.showImages.checked;
  window.localStorage.setItem(showImagesStorageKey, String(showImages));
  matchesView.render();
  inboxView.render();
  historyView.render();
});

// Desktop notifications for new matches found by auto-check. Each article is
// announced once per session (Preview only keeps finding the same ones), an
// article matching several topics counts once, and articles already shown by a
// manual check are not announced later.
const notificationsStorageKey = "keyword-watcher-notifications";
const notifiedLinks = new Set();

function notificationsAllowed() {
  return "Notification" in window && window.Notification.permission === "granted";
}

elements.notifyNewMatches.checked =
  window.localStorage.getItem(notificationsStorageKey) === "true" && notificationsAllowed();
elements.notifyNewMatches.addEventListener("change", async () => {
  if (elements.notifyNewMatches.checked) {
    if (!("Notification" in window)) {
      elements.notifyNewMatches.checked = false;
      showNotice("This browser does not support desktop notifications.");
    } else if (!notificationsAllowed() && await window.Notification.requestPermission() !== "granted") {
      elements.notifyNewMatches.checked = false;
      showNotice("Notifications are blocked for this page in your browser settings.");
    }
  }
  window.localStorage.setItem(notificationsStorageKey, String(elements.notifyNewMatches.checked));
});

function markAnnounced(matches) {
  matches.forEach((match) => notifiedLinks.add(match.item.link));
}

function notifyNewMatches(matches) {
  const fresh = new Map();
  for (const match of matches) {
    if (!notifiedLinks.has(match.item.link)) fresh.set(match.item.link, match.item);
  }
  markAnnounced(matches);
  if (!fresh.size || !elements.notifyNewMatches.checked || !notificationsAllowed()) return;
  const firstTitle = fresh.values().next().value.title || "Untitled item";
  new window.Notification("HoundDog", {
    body: fresh.size === 1 ? firstTitle : `${fresh.size} new articles, including "${firstTitle}"`,
    tag: "hounddog-new-matches",
  });
}

// The background job's JOB_INTERVALS (scheduled_task.py); the tab offers the same.
const CHECK_INTERVALS = [5, 15, 30, 60, 120, 240, 720, 1440];
const DEFAULT_CHECK_INTERVAL = 15;
const AUTO_CHECK_ACTIONS = ["preview", "save"];
const checkModeStorageKey = "keyword-watcher-check-mode";
const autoCheckIntervalStorageKey = "keyword-watcher-auto-check-interval";
const autoCheckActionStorageKey = "keyword-watcher-auto-check-action";

// Runs a check every N minutes while the dashboard is open (0 = not at all).
// The next check is scheduled only after the previous one finishes, so checks
// never overlap. onChange lets the Check flyout show the next run.
class AutoChecker {
  constructor() {
    this.timer = null;
    this.minutes = 0;
    this.action = "preview";
    this.nextAt = null;
    this.onChange = () => {};
  }

  configure(minutes, action) {
    this.minutes = minutes;
    this.action = action;
    this.schedule();
  }

  schedule() {
    window.clearTimeout(this.timer);
    this.timer = null;
    this.nextAt = null;
    if (this.minutes > 0) {
      const delay = this.minutes * 60_000;
      this.nextAt = new Date(Date.now() + delay);
      this.timer = window.setTimeout(() => this.run(), delay);
    }
    this.onChange();
  }

  async run() {
    // Refresh first, so a job installed elsewhere pauses this tab. If the job
    // cannot be read, go by the last known mode rather than stop checking.
    await checkingMode.loadJob();
    if (checkingMode.mode === "dashboard") {
      const dryRun = this.action === "preview";
      await runCheck(dryRun, dryRun ? elements.dryRunButton : elements.checkButton, { automatic: true });
    }
    this.schedule();
  }
}

const autoChecker = new AutoChecker();

// Forms for the shared [settings] table in watch.toml. A form the user is
// editing is not overwritten by a dashboard refresh until it is saved.
class SettingsForm {
  constructor(form, fields, savedMessage) {
    this.form = form;
    this.fields = fields;
    this.dirty = false;
    form.addEventListener("input", () => {
      this.dirty = true;
    });
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      this.save(savedMessage);
    });
  }

  fill(settings, defaults) {
    for (const [key, input] of Object.entries(this.fields)) {
      if (input.type === "checkbox") {
        if (!this.dirty) input.checked = Boolean(settings[key]);
        continue;
      }
      if (defaults) input.placeholder = String(defaults[key]);
      if (!this.dirty) input.value = String(settings[key]);
    }
  }

  async save(savedMessage) {
    const changes = Object.fromEntries(Object.entries(this.fields).map(([key, input]) => {
      if (input.type === "checkbox") return [key, input.checked];
      if (input.type !== "number") return [key, input.value.trim()];
      return [key, input.value === "" ? null : Number(input.value)];
    }));
    try {
      const settings = await api("/api/settings", { method: "PUT", body: JSON.stringify(changes) });
      this.dirty = false;
      settingsForms.forEach((form) => form.fill(settings));
      showNotice(savedMessage);
    } catch (error) {
      showNotice(error.message);
    }
  }
}

const settingsForms = [
  new SettingsForm(document.querySelector("#feed-settings-form"), {
    fetch_timeout_seconds: document.querySelector("#setting-fetch-timeout"),
    max_feed_megabytes: document.querySelector("#setting-max-feed-size"),
    user_agent: document.querySelector("#setting-user-agent"),
    max_item_age_days: document.querySelector("#setting-max-item-age"),
  }, "Feed settings saved."),
  new SettingsForm(document.querySelector("#retention-form"), {
    history_retention_days: document.querySelector("#setting-history-retention"),
  }, "History retention saved."),
  new SettingsForm(document.querySelector("#event-export-form"), {
    event_export: document.querySelector("#setting-event-export"),
  }, "Event export setting saved."),
];

const MAX_IMPORT_BYTES = 25 * 1024 * 1024;

elements.importButton.addEventListener("click", async () => {
  const file = elements.importFile.files[0];
  const replaceConfig = elements.importConfig.checked;
  const mergeHistory = elements.importHistory.checked;
  if (!file) {
    showNotice("Choose a HoundDog backup file first.");
    return;
  }
  if (file.size > MAX_IMPORT_BYTES) {
    showNotice("That file is larger than 25 MB.");
    return;
  }
  const effects = [
    replaceConfig ? "replace your feeds, topics, and settings" : "",
    mergeHistory ? "merge its history into yours" : "",
  ].filter(Boolean);
  if (!effects.length) {
    showNotice("Choose what to import.");
    return;
  }
  let data;
  try {
    data = JSON.parse(await file.text());
  } catch {
    showNotice("That file is not valid JSON.");
    return;
  }
  if (!window.confirm(`Import ${file.name}? This will ${effects.join(" and ")}.`)) return;
  try {
    const result = await api("/api/import", {
      method: "POST",
      body: JSON.stringify({ data, replace_config: replaceConfig, merge_history: mergeHistory }),
    });
    settingsForms.forEach((form) => {
      form.dirty = false;
    });
    elements.importFile.value = "";
    showNotice(`Imported ${result.sources} feeds, ${result.topics} topics, and ${result.history_added} new history items.`);
    await refresh();
  } catch (error) {
    showNotice(error.message);
  }
});

// Refreshes can overlap (an auto-check finishing while a feed is deleted); only
// the newest one renders, so an older response cannot overwrite newer data.
let refreshRequestId = 0;

async function refresh() {
  const requestId = ++refreshRequestId;
  try {
    const data = await api("/api/dashboard");
    if (requestId !== refreshRequestId) return;
    feeds = data.sources;
    topics = data.topics;
    elements.sourceCount.textContent = data.sources.length;
    elements.topicCount.textContent = data.topics.length;
    elements.historyCount.textContent = data.seen_count;
    renderFeeds();
    renderTopics();
    populateTesterTopics();
    historyView.setItems(data.seen_items);
    const unread = unreadArticles(data.seen_items);
    inboxView.setItems(unread);
    elements.inboxCount.textContent = unread.length ? String(unread.length) : "";
    elements.inboxMarkRead.disabled = unread.length === 0;
    if (data.settings) {
      settingsForms.forEach((form) => form.fill(data.settings, data.setting_defaults));
      const defaults = data.setting_defaults;
      document.querySelector("#feed-settings-defaults").textContent =
        `Defaults: ${defaults.fetch_timeout_seconds} seconds, ${defaults.max_feed_megabytes} MB, ` +
        `user agent "${defaults.user_agent}".`;
    } else {
      // The page was updated but the old server process is still running.
      showNotice("The dashboard server is out of date. Restart watcher_server.py, then reload this page.");
    }
  } catch (error) {
    if (requestId !== refreshRequestId) return;
    showNotice(error.message);
  }
  await loadHealth();
  if (toolbar.openTool === "log") await loadActivity();
}

const HEALTH_LABELS = {
  ok: "OK",
  empty: "No items",
  failing: "Failing",
  unchecked: "Not checked yet",
};

function renderHealthRow(source) {
  const items = source.not_modified
    ? "Unchanged since the last download"
    : source.item_count === null ? "" : `${source.item_count} item${source.item_count === 1 ? "" : "s"}`;
  const details = [
    source.last_checked ? `Checked ${formatDate(source.last_checked)}` : "",
    items,
    source.duration_ms === null ? "" : `${source.duration_ms} ms`,
  ].filter(Boolean).join(" · ");
  // Known only after a saved check has downloaded the feed (null before).
  let conditional = "";
  if (source.conditional === true) {
    conditional = "Can answer \"unchanged\" (sends ETag or Last-Modified), so unchanged checks skip the download.";
  } else if (source.conditional === false) {
    conditional = "Sends no ETag or Last-Modified, so every check downloads it in full.";
  }
  const lastMatch = source.last_new_match
    ? `Last new match ${formatDate(source.last_new_match)}`
    : source.last_checked ? "No new matches yet" : "";
  const streak = source.failure_streak > 1
    ? `Failed ${source.failure_streak} checks in a row` +
      (source.last_success ? `; last worked ${formatDate(source.last_success)}.` : "; no successful check in the log.")
    : "";
  return `
    <li class="tool-row health-${source.status}">
      <div class="tool-row-heading">
        <strong>${escapeHtml(source.name)}</strong>
        <span class="status-pill">${HEALTH_LABELS[source.status]}</span>
      </div>
      <p class="tool-row-url">${escapeHtml(source.url)}</p>
      ${details ? `<p>${escapeHtml(details)}</p>` : ""}
      ${lastMatch ? `<p>${escapeHtml(lastMatch)}</p>` : ""}
      ${conditional ? `<p>${escapeHtml(conditional)}</p>` : ""}
      ${source.status === "failing" ? `<p class="tool-row-error">${escapeHtml(source.error)}</p>` : ""}
      ${source.status === "failing" && streak ? `<p class="tool-row-error">${escapeHtml(streak)}</p>` : ""}
    </li>
  `;
}

async function loadHealth() {
  try {
    const { sources } = await api("/api/health");
    elements.healthToolButton.classList.toggle("has-alert", sources.some((source) => source.status === "failing"));
    elements.healthList.innerHTML = sources.length
      ? sources.map(renderHealthRow).join("")
      : '<li class="empty">No feeds configured.</li>';
  } catch (error) {
    elements.healthList.innerHTML = `<li class="empty">${escapeHtml(error.message)}</li>`;
  }
}

const TRIGGER_LABELS = { cli: "Command line", scheduled: "Background job", dashboard: "Dashboard", auto: "Auto-check" };

function renderActivityRow(check) {
  const summary = [
    `${check.new_matches} new`,
    check.pruned ? `${check.pruned} removed by retention` : "",
    `${check.source_count} feed${check.source_count === 1 ? "" : "s"}`,
    check.duration_ms < 1000 ? `${check.duration_ms} ms` : `${(check.duration_ms / 1000).toFixed(1)} s`,
  ].filter(Boolean).join(" · ");
  const failed = check.failed
    .map((source) => `<span title="${escapeHtml(source.error)}">${escapeHtml(source.name)}</span>`)
    .join(", ");
  return `
    <li class="tool-row${check.failed.length ? " has-failures" : ""}">
      <div class="tool-row-heading">
        <strong>${escapeHtml(formatDate(check.started_at))}</strong>
        <span class="status-pill">${escapeHtml(TRIGGER_LABELS[check.trigger] ?? check.trigger)} · ${check.saved ? "Saved" : "Preview"}</span>
      </div>
      <p>${escapeHtml(summary)}</p>
      ${failed ? `<p class="tool-row-error">Failed: ${failed}</p>` : ""}
    </li>
  `;
}

async function loadActivity() {
  try {
    const { checks } = await api("/api/activity");
    elements.activityList.innerHTML = checks.length
      ? checks.map(renderActivityRow).join("")
      : '<li class="empty">No checks yet.</li>';
  } catch (error) {
    elements.activityList.innerHTML = `<li class="empty">${escapeHtml(error.message)}</li>`;
  }
}

function splitTerms(value) {
  return value.split(",").map((term) => term.trim()).filter(Boolean);
}

// Adds a topic when original is null, otherwise replaces original wherever it
// is now. Used by both the Setup tab's topic form and the topic tester.
async function saveTopic(original, name, keywords, exclude) {
  const topic = { name, keywords: splitTerms(keywords), exclude: splitTerms(exclude) };
  if (original === null) {
    await api("/api/topics", { method: "POST", body: JSON.stringify(topic) });
    showNotice(`Topic "${name}" added.`);
  } else {
    await changeConfigEntry("topics", topicPosition(original), original, "PUT", topic);
    showNotice(`Topic "${name}" updated.`);
  }
}

// A keyword hitting at least this share of a reasonably sized sample is flagged.
const BROAD_KEYWORD_SHARE = 0.25;
const BROAD_KEYWORD_MIN_ITEMS = 20;
const TESTER_DELAY_MS = 400;
let testerTimer = null;
let testerRequestId = 0;

// Options are keyed by topic name (names are unique), so a refresh that shifts
// positions keeps the same topic selected.
function selectedTesterTopic() {
  return topics.find((topic) => topic.name === elements.testerTopic.value) ?? null;
}

function populateTesterTopics() {
  const selected = elements.testerTopic.value;
  elements.testerTopic.innerHTML = '<option value="">New topic</option>' + topics
    .map((topic) => `<option value="${escapeHtml(topic.name)}">${escapeHtml(topic.name)}</option>`)
    .join("");
  elements.testerTopic.value = topics.some((topic) => topic.name === selected) ? selected : "";
}

function loadTesterTopic() {
  const topic = selectedTesterTopic();
  elements.testerName.value = topic?.name ?? "";
  elements.testerKeywords.value = (topic?.keywords ?? []).join(", ");
  elements.testerExclude.value = (topic?.exclude ?? []).join(", ");
  runTopicTest();
}

function renderTopicTest(result) {
  const corpus = result.corpus === "history" ? "history items" : "latest feed items";
  if (!result.total_items) {
    elements.testerSummary.textContent = result.corpus === "history"
      ? "History is empty."
      : "No feed items loaded yet. Use Fetch latest items, or run a check.";
  } else {
    const excluded = result.excluded_count ? ` · ${result.excluded_count} excluded` : "";
    const fetched = result.fetched_at ? ` (fetched ${formatDate(result.fetched_at)})` : "";
    const failed = result.failed_sources.length ? ` Failed to load: ${result.failed_sources.join(", ")}.` : "";
    elements.testerSummary.textContent =
      `${result.matched_count} of ${result.total_items} ${corpus} match${excluded}${fetched}.${failed}`;
  }
  elements.testerKeywordReport.innerHTML = result.total_items ? result.keyword_hits.map(({ keyword, items }) => {
    const share = items / result.total_items;
    const broad = result.total_items >= BROAD_KEYWORD_MIN_ITEMS && share >= BROAD_KEYWORD_SHARE;
    return `
      <li>
        <code>${escapeHtml(keyword)}</code>
        <span>${items} item${items === 1 ? "" : "s"} (${Math.round(share * 100)}%)</span>
        ${broad ? '<span class="tester-flag">Very broad</span>' : ""}
        ${items === 0 ? '<span class="tester-flag is-muted">No hits</span>' : ""}
      </li>
    `;
  }).join("") : "";
  const more = result.matched_count > result.matches.length
    ? `<li class="tester-more">Showing the first ${result.matches.length} of ${result.matched_count}.</li>`
    : "";
  elements.testerResults.innerHTML = result.matches.map((match) => {
    const link = safeHttpUrl(match.link);
    const title = escapeHtml(match.title || "Untitled item");
    return `
      <li>
        ${link ? `<a href="${escapeHtml(link)}" target="_blank" rel="noreferrer">${title}</a>` : `<strong>${title}</strong>`}
        <span>${escapeHtml(match.source)} · matched: ${escapeHtml(match.keywords.join(", "))}</span>
      </li>
    `;
  }).join("") + more;
}

async function runTopicTest({ fetchLatest = false } = {}) {
  window.clearTimeout(testerTimer);
  const requestId = ++testerRequestId;
  const keywords = splitTerms(elements.testerKeywords.value);
  if (!keywords.length) {
    elements.testerSummary.textContent = "Enter at least one include keyword to test.";
    elements.testerKeywordReport.innerHTML = "";
    elements.testerResults.innerHTML = "";
    return;
  }
  try {
    const result = await api("/api/topic-test", {
      method: "POST",
      body: JSON.stringify({
        keywords,
        exclude: splitTerms(elements.testerExclude.value),
        corpus: elements.testerCorpus.value,
        refresh: fetchLatest,
      }),
    });
    if (requestId === testerRequestId) renderTopicTest(result);
  } catch (error) {
    if (requestId === testerRequestId) elements.testerSummary.textContent = error.message;
  }
}

function scheduleTopicTest() {
  window.clearTimeout(testerTimer);
  testerRequestId += 1;
  testerTimer = window.setTimeout(() => runTopicTest(), TESTER_DELAY_MS);
}

elements.testerTopic.addEventListener("change", loadTesterTopic);
elements.testerCorpus.addEventListener("change", () => runTopicTest());
elements.testerKeywords.addEventListener("input", scheduleTopicTest);
elements.testerExclude.addEventListener("input", scheduleTopicTest);
elements.testerRefresh.addEventListener("click", async () => {
  setLoading(elements.testerRefresh, true);
  elements.testerCorpus.value = "latest";
  await runTopicTest({ fetchLatest: true });
  setLoading(elements.testerRefresh, false);
});
elements.testerForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const name = elements.testerName.value.trim();
  try {
    await saveTopic(selectedTesterTopic(), name, elements.testerKeywords.value, elements.testerExclude.value);
    await refresh();
    elements.testerTopic.value = topics.some((topic) => topic.name === name) ? name : "";
  } catch (error) {
    await reportConfigError(error);
  }
});

let checkInProgress = false;

async function runCheck(dryRun, button, { automatic = false } = {}) {
  if (checkInProgress) return;
  checkInProgress = true;
  const checkButtons = [elements.checkButton, elements.dryRunButton];
  checkButtons.forEach((checkButton) => {
    checkButton.disabled = true;
  });
  setLoading(button, true);
  try {
    const data = await api("/api/check", {
      method: "POST",
      body: JSON.stringify({ dry_run: dryRun, trigger: automatic ? "auto" : "dashboard" }),
    });
    matchesView.setItems(data.matches);
    const count = `${data.matches.length} new match${data.matches.length === 1 ? "" : "es"} found`;
    const result = dryRun
      ? `${count}. Nothing was saved to History.`
      : data.matches.length
        ? `${count}. Saved to History.`
        : `${count}. History is up to date.`;
    const failed = data.failed_sources ?? [];
    const skipped = data.skipped_sources ?? [];
    const pruned = data.pruned
      ? ` Removed ${data.pruned} item${data.pruned === 1 ? "" : "s"} past the retention period.`
      : "";
    const skippedText = skipped.length
      ? ` Skipped: ${skipped.map((source) => source.name).join(", ")}.`
      : "";
    const exportText = data.export_error ? ` Event export not written yet: ${data.export_error}.` : "";
    showNotice(`${automatic ? "Auto-check: " : ""}${result}${pruned}${failed.length ? ` Failed to load: ${failed.join(", ")}.` : ""}${skippedText}${exportText}`);
    if (automatic) {
      notifyNewMatches(data.matches);
    } else {
      markAnnounced(data.matches);
    }
    const checkedAt = new Date().toLocaleTimeString(undefined, { timeStyle: "short" });
    elements.checkStatus.textContent = [
      `${dryRun ? "Previewed" : "Checked"} ${checkedAt}`,
      `${data.matches.length} new`,
      failed.length ? `${failed.length} failed` : "",
    ].filter(Boolean).join(" · ");
    await refresh();
  } catch (error) {
    showNotice(error.message);
  } finally {
    setLoading(button, false);
    checkButtons.forEach((checkButton) => {
      checkButton.disabled = false;
    });
    checkInProgress = false;
  }
}

// Editor-style tool strip: each .tool-button[data-tool="name"] toggles the
// #tool-name flyout beside it. One flyout is open at a time; Escape closes it.
class Toolbar {
  // onOpen maps a tool name to a function run each time that tool opens.
  constructor(onOpen = {}) {
    this.buttons = Array.from(document.querySelectorAll(".tool-button"));
    this.onOpen = onOpen;
    this.openTool = null;
    this.buttons.forEach((button) => {
      button.addEventListener("click", () => this.toggle(button.dataset.tool));
    });
    document.querySelectorAll("[data-close-tool]").forEach((button) => {
      button.addEventListener("click", () => this.show(null));
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && this.openTool) this.show(null);
    });
  }

  toggle(name) {
    this.show(this.openTool === name ? null : name);
  }

  show(name) {
    this.openTool = name;
    this.buttons.forEach((button) => {
      const open = button.dataset.tool === name;
      button.classList.toggle("is-active", open);
      button.setAttribute("aria-expanded", String(open));
      document.querySelector(`#tool-${button.dataset.tool}`).hidden = !open;
    });
    if (name && this.onOpen[name]) this.onOpen[name]();
  }
}

// Task Scheduler's own result codes, and the exit codes of watcher.py --scheduled.
const JOB_RESULTS = new Map([
  [0, "OK"],
  [1, "every feed failed"],
  [2, "configuration error; see the messages below"],
  [3, "crashed; see the messages below"],
  [0x41301, "running"],
  [0x41303, "not run yet"],
  [0x41306, "stopped before it finished"],
  [0x8004131f, "skipped: the previous run was still going"],
  [0x800710e0, "not started: on battery or offline, as the settings below require"],
  [0x80070002, "Python or watcher.py was not found"],
  [0x80070005, "access denied"],
  [0xc000013a, "stopped: Windows was shutting down or the run was closed"],
]);

function jobResultText(code) {
  const unsigned = code >>> 0;
  return JOB_RESULTS.get(unsigned) ?? `result 0x${unsigned.toString(16).toUpperCase()}`;
}

const CHECK_MODE_HINTS = {
  off: "Use Check in the toolbar to check by hand.",
  dashboard: "Runs only while this dashboard is open. Saved in this browser.",
  background: "A Windows scheduled task runs a saved check, with no window, while you are signed in to Windows, " +
    "even when this dashboard is closed. New matches land in the Inbox. Choosing another option removes the task.",
};

// Who runs automatic checks: nobody, this tab, or the background job. The job
// is Task Scheduler's (shared by every browser): while its task exists the
// mode is "background" and this tab's auto-check stays paused. Otherwise the
// mode is this browser's choice (localMode: "off" or "dashboard"). Changing
// the mode is an explicit transition: install or remove the task, then store
// the browser's choice. Choosing the job sets the browser to "off", so
// removing the task elsewhere does not quietly restart checks here.
class CheckingMode {
  constructor() {
    this.job = null;
    this.jobRequestId = 0;
    this.jobError = "";
    this.busy = false;
    this.radios = { off: elements.checkModeOff, dashboard: elements.checkModeDashboard, background: elements.checkModeBackground };
    this.jobToggles = [elements.jobBattery, elements.jobCatchUp, elements.jobNetwork];

    elements.checkInterval.innerHTML = CHECK_INTERVALS
      .map((minutes) => `<option value="${minutes}">${escapeHtml(formatMinutes(minutes))}</option>`)
      .join("");
    this.localMode = this.readStoredMode();
    elements.checkInterval.value = String(this.storedInterval());
    const storedAction = window.localStorage.getItem(autoCheckActionStorageKey);
    elements.autoCheckAction.value = AUTO_CHECK_ACTIONS.includes(storedAction) ? storedAction : "preview";
    this.jobToggles.forEach((toggle) => {
      toggle.checked = true;
    });

    for (const [mode, radio] of Object.entries(this.radios)) {
      radio.addEventListener("change", () => {
        if (radio.checked) this.select(mode);
      });
    }
    elements.checkInterval.addEventListener("change", () => this.settingsChanged());
    // The action only applies to this tab's checks; the job always saves.
    elements.autoCheckAction.addEventListener("change", () => {
      window.localStorage.setItem(autoCheckActionStorageKey, elements.autoCheckAction.value);
      this.render();
    });
    this.jobToggles.forEach((toggle) => toggle.addEventListener("change", () => this.settingsChanged()));
    elements.jobRun.addEventListener("click", () => this.jobRequest(
      "/api/schedule/run", { method: "POST" }, "Background check started; its results appear in the Inbox and Log.",
    ));
    elements.jobRepair.addEventListener("click", () => this.jobRequest(
      "/api/schedule", { method: "PUT", body: JSON.stringify(this.jobOptions()) }, "Background job repaired.",
    ));
    elements.jobLogClear.addEventListener("click", async () => {
      try {
        const { log } = await api("/api/schedule/log", { method: "DELETE" });
        if (this.job) this.job = { ...this.job, log };
      } catch (error) {
        showNotice(error.message);
      }
      this.render();
    });
    autoChecker.onChange = () => this.renderFlyoutStatus();
    this.render();
  }

  // Before the mode existed, an interval of "0" meant off; carry that over once.
  readStoredMode() {
    const stored = window.localStorage.getItem(checkModeStorageKey);
    if (stored === "off" || stored === "dashboard") return stored;
    const legacyInterval = Number(window.localStorage.getItem(autoCheckIntervalStorageKey));
    const mode = legacyInterval > 0 ? "dashboard" : "off";
    window.localStorage.setItem(checkModeStorageKey, mode);
    return mode;
  }

  storedInterval() {
    const minutes = Number(window.localStorage.getItem(autoCheckIntervalStorageKey));
    return CHECK_INTERVALS.includes(minutes) ? minutes : DEFAULT_CHECK_INTERVAL;
  }

  get mode() {
    return this.job?.installed ? "background" : this.localMode;
  }

  setLocalMode(mode) {
    this.localMode = mode;
    window.localStorage.setItem(checkModeStorageKey, mode);
  }

  jobOptions() {
    return {
      interval_minutes: Number(elements.checkInterval.value),
      run_on_battery: elements.jobBattery.checked,
      catch_up: elements.jobCatchUp.checked,
      require_network: elements.jobNetwork.checked,
    };
  }

  async loadJob() {
    if (this.busy) return false;
    const requestId = ++this.jobRequestId;
    try {
      const job = await api("/api/schedule");
      if (requestId !== this.jobRequestId) return false;
      this.job = job;
      this.jobError = "";
      this.render();
      return true;
    } catch (error) {
      if (requestId !== this.jobRequestId) return false;
      this.jobError = `Could not read the background job: ${error.message}`;
      this.render();
      return false;
    }
  }

  async select(mode) {
    if (mode === this.mode) return;
    await this.withBusy(async () => {
      if (mode === "background") {
        this.job = await api("/api/schedule", { method: "PUT", body: JSON.stringify(this.jobOptions()) });
        this.setLocalMode("off");
      } else {
        if (this.job?.installed) this.job = await api("/api/schedule", { method: "DELETE" });
        this.setLocalMode(mode);
      }
      showNotice({
        off: "Automatic checks are off.",
        dashboard: "This dashboard tab now checks automatically.",
        background: "The background job is on.",
      }[mode]);
    });
  }

  // The interval or a job condition changed: apply it to whoever checks.
  async settingsChanged() {
    if (this.mode !== "background") {
      window.localStorage.setItem(autoCheckIntervalStorageKey, elements.checkInterval.value);
      this.render();
      return;
    }
    await this.jobRequest("/api/schedule", { method: "PUT", body: JSON.stringify(this.jobOptions()) }, "Background job updated.");
  }

  async jobRequest(path, options, doneMessage) {
    await this.withBusy(async () => {
      this.job = await api(path, options);
      showNotice(doneMessage);
    });
  }

  // On failure the job is read again, so the panel shows what Task Scheduler
  // really has rather than what was asked for.
  async withBusy(action) {
    this.jobRequestId += 1;
    this.busy = true;
    this.render();
    try {
      await action();
      this.jobError = "";
    } catch (error) {
      this.jobError = error.message;
      showNotice(error.message);
      try {
        this.job = await api("/api/schedule");
      } catch {
        // Keep the last known job; jobError already says what failed.
      }
    } finally {
      this.busy = false;
      this.render();
    }
  }

  jobProblems() {
    const job = this.job;
    if (!job?.installed) return [];
    return [
      job.state === "Disabled" ? "It is disabled in Task Scheduler." : "",
      job.command_found ? "" : `Its program no longer exists (${job.command}); Python may have moved or been upgraded.`,
      job.runs_this_folder ? "" : `It runs a different HoundDog folder or Python (${job.command}).`,
      job.options ? "" : "Its schedule was changed in Task Scheduler to something this panel cannot show.",
    ].filter(Boolean);
  }

  render() {
    const mode = this.mode;
    const job = this.job;
    const supported = job?.supported !== false;
    for (const [name, radio] of Object.entries(this.radios)) {
      radio.checked = name === mode;
      radio.disabled = this.busy || (name === "background" && !supported);
    }
    elements.checkInterval.disabled = this.busy;
    this.jobToggles.forEach((toggle) => {
      toggle.disabled = this.busy;
    });
    elements.dashboardCheckAction.hidden = mode !== "dashboard";
    elements.backgroundCheckOptions.hidden = mode !== "background";
    elements.checkModeHint.textContent = supported
      ? CHECK_MODE_HINTS[mode]
      : `${CHECK_MODE_HINTS[mode]} The background job is only available on Windows.`;

    if (mode === "background") {
      if (job.options) {
        elements.checkInterval.value = String(job.options.interval_minutes);
        elements.jobBattery.checked = job.options.run_on_battery;
        elements.jobCatchUp.checked = job.options.catch_up;
        elements.jobNetwork.checked = job.options.require_network;
      }
      const problems = this.jobProblems();
      elements.jobRepair.hidden = problems.length === 0;
      elements.jobRepair.disabled = this.busy;
      elements.jobRun.disabled = this.busy;
      const result = job.last_result === null || job.last_result === undefined ? "" : ` (${jobResultText(job.last_result)})`;
      const summary = [
        job.options ? `Every ${formatMinutes(job.options.interval_minutes)}` : "On",
        job.next_run ? `next ${formatDate(job.next_run)}` : "",
        job.last_run ? `last run ${formatDate(job.last_run)}${result}` : "",
      ].filter(Boolean).join(" · ");
      const repair = problems.length ? " Repair task re-creates it with the settings shown here." : "";
      elements.checkModeStatus.textContent = [`${summary}.`, ...problems].join(" ") + repair;
    } else {
      elements.checkInterval.value = String(this.storedInterval());
      elements.checkModeStatus.textContent = "";
    }
    if (this.jobError) {
      elements.checkModeStatus.textContent = `${this.jobError} ${elements.checkModeStatus.textContent}`.trim();
    }

    const log = job?.log ?? [];
    elements.jobLogDetails.hidden = log.length === 0;
    elements.jobLog.textContent = log.join("\n");

    // Reschedule only on a real change, so re-rendering keeps the pending timer.
    const minutes = mode === "dashboard" ? this.storedInterval() : 0;
    if (autoChecker.minutes !== minutes || autoChecker.action !== elements.autoCheckAction.value) {
      autoChecker.configure(minutes, elements.autoCheckAction.value);
    } else {
      this.renderFlyoutStatus();
    }
  }

  renderFlyoutStatus() {
    const mode = this.mode;
    if (mode === "background") {
      const next = this.job?.next_run ? ` · next ${formatDate(this.job.next_run)}` : "";
      const every = this.job?.options ? ` every ${formatMinutes(this.job.options.interval_minutes)}` : "";
      elements.autoCheckStatus.textContent = `Background job${every}${next}`;
    } else if (mode === "dashboard" && autoChecker.nextAt) {
      const actionLabel = autoChecker.action === "save" ? "Check & save" : "Preview only";
      const nextAt = autoChecker.nextAt.toLocaleTimeString(undefined, { timeStyle: "short" });
      elements.autoCheckStatus.textContent =
        `Auto-check every ${formatMinutes(autoChecker.minutes)} (${actionLabel}) · next ${nextAt}`;
    } else {
      elements.autoCheckStatus.textContent = "Automatic checks are off";
    }
  }
}

const checkingMode = new CheckingMode();
checkingMode.loadJob();

const toolbar = new Toolbar({
  tester: () => {
    populateTesterTopics();
    runTopicTest();
  },
  health: loadHealth,
  log: loadActivity,
  settings: () => checkingMode.loadJob(),
});

// Buttons with data-panel="name" show one panel each and hide the rest; the
// choice is remembered. Unknown or missing names fall back to the first button.
class TabGroup {
  constructor(buttons, storageKey, panelSelector) {
    this.buttons = buttons;
    this.storageKey = storageKey;
    this.panelSelector = panelSelector;
    this.buttons.forEach((button) => {
      button.addEventListener("click", () => {
        window.localStorage.setItem(this.storageKey, this.show(button.dataset.panel));
      });
    });
    this.show(window.localStorage.getItem(this.storageKey));
  }

  show(name) {
    const activeButton = this.buttons.find((button) => button.dataset.panel === name) ?? this.buttons[0];
    this.buttons.forEach((button) => {
      const active = button === activeButton;
      button.classList.toggle("is-active", active);
      document.querySelector(this.panelSelector(button.dataset.panel)).hidden = !active;
    });
    return activeButton.dataset.panel;
  }
}

new TabGroup(
  Array.from(document.querySelectorAll(".tab")),
  "keyword-watcher-tab",
  (name) => `#${name}-panel`,
);
new TabGroup(
  Array.from(document.querySelectorAll(".settings-nav-button")),
  "keyword-watcher-settings-section",
  (name) => `#settings-${name}`,
);

elements.checkButton.addEventListener("click", (event) => {
  runCheck(false, event.currentTarget);
});

elements.dryRunButton.addEventListener("click", (event) => {
  runCheck(true, event.currentTarget);
});

function openFeedEditor(feed = null) {
  editingFeed = feed;
  elements.feedFormTitle.textContent = feed ? "Edit feed" : "Add a feed";
  elements.feedName.value = feed?.name ?? "";
  elements.feedUrl.value = feed?.url ?? "";
  elements.feedInterval.value = feed?.check_every_minutes ? String(feed.check_every_minutes) : "";
  elements.feedForm.hidden = false;
  elements.feedName.focus();
}

function openTopicEditor(topic = null) {
  editingTopic = topic;
  elements.topicFormTitle.textContent = topic ? "Edit topic" : "Add a topic";
  elements.topicName.value = topic?.name ?? "";
  elements.topicKeywords.value = topic?.keywords.join(", ") ?? "";
  elements.topicExclude.value = (topic?.exclude ?? []).join(", ");
  elements.topicForm.hidden = false;
  elements.topicName.focus();
}

function closeFeedEditor() {
  editingFeed = null;
  elements.feedForm.reset();
  elements.feedForm.hidden = true;
}

function closeTopicEditor() {
  editingTopic = null;
  elements.topicForm.reset();
  elements.topicForm.hidden = true;
}

document.querySelector("#add-feed-button").addEventListener("click", () => openFeedEditor());
document.querySelector("#add-topic-button").addEventListener("click", () => openTopicEditor());
document.querySelector('[data-cancel-editor="feed"]').addEventListener("click", closeFeedEditor);
document.querySelector('[data-cancel-editor="topic"]').addEventListener("click", closeTopicEditor);

elements.feedsList.addEventListener("click", async (event) => {
  const editButton = event.target.closest("[data-edit-feed]");
  const deleteButton = event.target.closest("[data-delete-feed]");

  if (editButton) {
    openFeedEditor(feeds[Number(editButton.dataset.editFeed)]);
  }

  if (deleteButton) {
    const index = Number(deleteButton.dataset.deleteFeed);
    const feed = feeds[index];
    if (!window.confirm(`Delete "${feed.name}"?`)) return;
    try {
      await changeConfigEntry("feeds", index, feed, "DELETE");
      showNotice("Feed deleted.");
      await refresh();
    } catch (error) {
      await reportConfigError(error);
    }
  }
});

elements.topicsList.addEventListener("click", async (event) => {
  const editButton = event.target.closest("[data-edit-topic]");
  const deleteButton = event.target.closest("[data-delete-topic]");

  if (editButton) {
    openTopicEditor(topics[Number(editButton.dataset.editTopic)]);
  }

  if (deleteButton) {
    const index = Number(deleteButton.dataset.deleteTopic);
    const topic = topics[index];
    if (!window.confirm(`Delete topic "${topic.name}"?`)) return;
    try {
      await changeConfigEntry("topics", index, topic, "DELETE");
      showNotice("Topic deleted.");
      await refresh();
    } catch (error) {
      await reportConfigError(error);
    }
  }
});

elements.feedForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const interval = elements.feedInterval.value.trim();
  const feed = {
    name: elements.feedName.value.trim(),
    url: elements.feedUrl.value.trim(),
    check_every_minutes: interval === "" ? null : Number(interval),
  };

  try {
    if (editingFeed === null) {
      await api("/api/feeds", { method: "POST", body: JSON.stringify(feed) });
      showNotice("Feed added.");
    } else {
      await changeConfigEntry("feeds", feedPosition(editingFeed), editingFeed, "PUT", feed);
      showNotice("Feed updated.");
    }
    closeFeedEditor();
    await refresh();
  } catch (error) {
    await reportConfigError(error);
  }
});

elements.topicForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await saveTopic(
      editingTopic,
      elements.topicName.value.trim(),
      elements.topicKeywords.value,
      elements.topicExclude.value,
    );
    closeTopicEditor();
    await refresh();
  } catch (error) {
    await reportConfigError(error);
  }
});

document.querySelector("#reset-history-button").addEventListener("click", async () => {
  if (!window.confirm("Clear all history? Items already found will be reported as new on the next check.")) return;
  try {
    await api("/api/seen", { method: "DELETE" });
    showNotice("History cleared.");
    await refresh();
  } catch (error) {
    showNotice(error.message);
  }
});

refresh();
