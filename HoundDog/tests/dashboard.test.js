const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

async function loadDashboard({
  omitSettings = false,
  storedTheme,
  storedMode,
  storedTab,
  storedSettingsSection,
  storedPageSizes = {},
  storedPreferences = {},
  historyItems,
  checkResult = { matches: [] },
  apiResponses = {},
  notification,
} = {}) {
  const elements = new Map();
  const documentElement = {
    dataset: {},
    style: {
      properties: {},
      setProperty(name, value) {
        this.properties[name] = value;
      },
    },
  };
  const storage = new Map();
  if (storedTheme !== undefined) {
    storage.set("keyword-watcher-theme", storedTheme);
  }
  if (storedMode !== undefined) {
    storage.set("keyword-watcher-color-mode", storedMode);
  }
  if (storedTab !== undefined) {
    storage.set("keyword-watcher-tab", storedTab);
  }
  if (storedSettingsSection !== undefined) {
    storage.set("keyword-watcher-settings-section", storedSettingsSection);
  }
  for (const [name, size] of Object.entries(storedPageSizes)) {
    storage.set(`keyword-watcher-page-size-${name}`, size);
  }
  for (const [key, value] of Object.entries(storedPreferences)) {
    storage.set(`keyword-watcher-${key}`, value);
  }
  const dashboard = {
    settings: {
      fetch_timeout_seconds: 20,
      max_feed_megabytes: 5,
      user_agent: "HoundDog/1.0",
      history_retention_days: 0,
      event_export: true,
    },
    setting_defaults: {
      fetch_timeout_seconds: 15,
      max_feed_megabytes: 5,
      user_agent: "keyword-watcher/0.1",
      history_retention_days: 90,
      event_export: true,
    },
    sources: [{ name: "Example feed", url: "https://example.com/feed.xml" }],
    topics: [
      { name: "AI tooling", keywords: ["agent*", "LLM"], exclude: ["spam"] },
      { name: "Policy", keywords: ["privacy"] },
    ],
    seen_count: 0,
    seen_items: [
      {
        topic: "AI tooling",
        link: "https://example.com/articles/a-very-long-article-url",
        first_seen: "2026-04-03T10:00:00+00:00",
        source: "Example feed",
        title: "Useful article",
        summary: "A brief description of the article.",
        published: "2026-04-02T09:00:00+00:00",
        author: "Editor",
        image_url: "https://example.com/article.jpg",
      },
      {
        topic: "Legacy topic",
        link: "https://example.com/legacy-article",
        first_seen: "2026-04-01T10:00:00+00:00",
        image_url: "javascript:alert(1)",
      },
      {
        topic: "Hostile",
        link: 'https://example.com/"onmouseover="alert(1)',
        first_seen: "2026-04-01T09:00:00+00:00",
        title: '<img src=x onerror="alert(1)">',
      },
    ],
  };
  if (omitSettings) delete dashboard.settings;
  if (historyItems !== undefined) {
    dashboard.seen_items = historyItems;
    dashboard.seen_count = historyItems.length;
  }

  function element(selector) {
    if (!elements.has(selector)) {
      elements.set(selector, {
        value: {
          "#theme-pico": "pico",
          "#theme-dos": "dos",
          "#theme-nes": "nes",
          "#mode-dark": "dark",
          "#mode-light": "light",
          "#ui-scale": "100",
        }[selector] ?? "",
        type: { "#setting-event-export": "checkbox" }[selector],
        dataset: {},
        classList: {
          toggle() {},
          contains() {
            return false;
          },
        },
        listeners: {},
        addEventListener(type, listener) {
          this.listeners[type] = listener;
        },
        focus() {
          this.focused = true;
        },
        scrollIntoView() {
          this.scrolled = true;
        },
        attributes: {},
        setAttribute(name, value) {
          this.attributes[name] = value;
        },
        close() {},
        showModal() {},
      });
    }
    return elements.get(selector);
  }

  const documentListeners = {};
  const document = {
    listeners: documentListeners,
    addEventListener(type, listener) {
      documentListeners[type] = listener;
    },
    documentElement,
    querySelector: element,
    querySelectorAll: (selector) => {
      if (selector === 'input[name="app-theme"]') {
        return [element("#theme-pico"), element("#theme-dos"), element("#theme-nes")];
      }
      if (selector === 'input[name="color-mode"]') {
        return [element("#mode-dark"), element("#mode-light")];
      }
      if (selector === ".tool-button") {
        return ["check", "tester", "health", "log", "settings", "shutdown"].map((name) => {
          const tool = element(`#tool-button-${name}`);
          tool.dataset.tool = name;
          return tool;
        });
      }
      if (selector === "[data-close-tool]") {
        return [element("#tool-close-check"), element("#tool-close-shutdown"), element("#tool-close-settings")];
      }
      if (selector === ".tab") {
        return ["inbox", "matches", "history", "feeds"].map((panel) => {
          const tab = element(`#tab-${panel}`);
          tab.dataset.panel = panel;
          return tab;
        });
      }
      if (selector === ".settings-nav-button") {
        return ["appearance", "display"].map((panel) => {
          const button = element(`#settings-nav-${panel}`);
          button.dataset.panel = panel;
          return button;
        });
      }
      return [];
    },
    head: {
      append(element) {
        element.appended = true;
      },
    },
    createElement: (tagName) => {
      if (tagName === "link") {
        const link = {
          listeners: {},
          addEventListener(type, listener) {
            this.listeners[type] = listener;
          },
        };
        elements.set("#nes-stylesheet", link);
        return link;
      }
      let text = "";
      return {
        set textContent(value) {
          text = String(value);
        },
        get innerHTML() {
          return text;
        },
      };
    },
  };

  // Short timers (search debounce) run at once; long ones (notices, auto-check)
  // are recorded so a test can fire them explicitly.
  const timers = [];
  const requests = [];
  const window = {
    clearTimeout(id) {
      if (id) timers[id - 1].cleared = true;
    },
    setTimeout(callback, delay) {
      if (delay > 1000) {
        timers.push({ callback, delay, cleared: false });
        return timers.length;
      }
      callback();
      return 0;
    },
      localStorage: {
        getItem(key) {
          return storage.get(key) ?? null;
        },
        setItem(key, value) {
          storage.set(key, value);
        },
      },
  };
  if (notification) window.Notification = notification;

  const context = {
    document,
    window,
    fetch: async (requestPath, options = {}) => {
      requests.push({ path: requestPath, ...options });
      const responses = {
        "/api/dashboard": dashboard,
        "/api/check": checkResult,
        "/api/health": { sources: [] },
        "/api/activity": { checks: [] },
        ...apiResponses,
      };
      const canned = responses[requestPath];
      const payload = typeof canned === "function" ? canned(options) : canned ?? dashboard;
      const status = payload.status ?? 200;
      return {
        ok: status < 400,
        status,
        json: async () => payload,
      };
    },
  };

  const appPath = path.join(__dirname, "..", "app.js");
  vm.runInNewContext(readFileSync(appPath, "utf8"), context);
  await new Promise((resolve) => setImmediate(resolve));
  elements.set("documentElement", documentElement);
  elements.set("storage", storage);
  elements.set("context", context);
  elements.set("document", document);
  elements.set("timers", timers);
  elements.set("requests", requests);
  elements.set("dashboard", dashboard);
  return elements;
}

test("dashboard renders topics with and without exclude keywords", async () => {
  const elements = await loadDashboard();
  const rendered = elements.get("#topics-list").innerHTML;
  assert.match(rendered, /AI tooling/);
  assert.match(rendered, /Include: agent\*, LLM/);
  assert.match(rendered, /Exclude: spam/);
  assert.match(rendered, /Policy/);
  assert.match(rendered, /data-edit-topic="1"/);
});

test("history cards show metadata and optional images with compact links", async () => {
  const elements = await loadDashboard({ storedPreferences: { "show-images": "true" } });
  const rendered = elements.get("#history-list").innerHTML;

  assert.match(rendered, /Useful article/);
  assert.match(rendered, /Example feed/);
  assert.match(rendered, /Editor/);
  assert.match(rendered, /Published/);
  assert.match(rendered, /Found/);
  assert.match(rendered, /A brief description of the article\./);
  assert.match(rendered, /src="https:\/\/example\.com\/article\.jpg"/);
  assert.match(rendered, /class="article-link"/);
  assert.match(rendered, /title="https:\/\/example\.com\/articles\/a-very-long-article-url"/);
  assert.match(rendered, /Untitled item/);
  assert.doesNotMatch(rendered, /src="javascript:/);
});

test("match links only render for http(s) URLs", async () => {
  const match = (link) => ({
    topic: "AI tooling",
    keywords: ["agent*"],
    item: { source: "Example feed", title: "Story", link },
  });
  const elements = await loadDashboard({
    checkResult: {
      matches: [match("javascript:alert(1)"), match("https://example.com/safe")],
    },
  });
  const button = elements.get("#check-button");
  button.listeners.click({ currentTarget: button });
  await new Promise((resolve) => setImmediate(resolve));

  const rendered = elements.get("#matches-list").innerHTML;
  assert.doesNotMatch(rendered, /javascript:/);
  assert.match(rendered, /href="https:\/\/example\.com\/safe"/);
});

test("feed values cannot break out of HTML attributes", async () => {
  const elements = await loadDashboard();
  const rendered = elements.get("#history-list").innerHTML;

  assert.doesNotMatch(rendered, /"onmouseover=/);
  assert.match(rendered, /&quot;onmouseover=&quot;/);
  assert.doesNotMatch(rendered, /<img src=x/);
});

test("checks report feeds that failed to load", async () => {
  const elements = await loadDashboard({
    checkResult: { matches: [], failed_sources: ["BBC News", "arXiv cs.LG"] },
  });
  const button = elements.get("#check-button");
  button.listeners.click({ currentTarget: button });
  await new Promise((resolve) => setImmediate(resolve));

  assert.match(elements.get("#notice").textContent, /Failed to load: BBC News, arXiv cs\.LG\./);
  assert.match(elements.get("#check-status").textContent, /^Checked .+ · 0 new · 2 failed$/);
  assert.equal(elements.get("#check-button").disabled, false);
  assert.equal(elements.get("#dry-run-button").disabled, false);
});

test("cards rendered after a refresh keep the NES dark classes", async () => {
  const elements = await loadDashboard({ storedTheme: "nes", storedMode: "dark" });
  elements.get("#nes-stylesheet").listeners.load();
  const button = elements.get("#check-button");
  button.listeners.click({ currentTarget: button });
  await new Promise((resolve) => setImmediate(resolve));

  assert.match(elements.get("#feeds-list").innerHTML, /class="item nes-container is-dark"/);
});

test("NES.css rules only apply while the NES theme is active", async () => {
  const elements = await loadDashboard();
  const link = elements.get("#nes-stylesheet");
  assert.equal(link.appended, true);
  assert.equal(link.media, "not all");

  link.listeners.load();
  const nesOption = elements.get("#theme-nes");
  nesOption.checked = true;
  nesOption.listeners.change();
  assert.equal(link.media, "all");

  const picoOption = elements.get("#theme-pico");
  picoOption.checked = true;
  picoOption.listeners.change();
  assert.equal(link.media, "not all");
});

test("NES stylesheet is loaded with subresource integrity", async () => {
  const elements = await loadDashboard();
  const link = elements.get("#nes-stylesheet");
  assert.match(link.integrity, /^sha256-[A-Za-z0-9+/]{43}=$/);
  assert.equal(link.crossOrigin, "anonymous");
});

test("dashboard defaults to Pico in light mode", async () => {
  const elements = await loadDashboard();
  assert.equal(elements.get("#theme-pico").checked, true);
  assert.equal(elements.get("#theme-dos").checked, false);
  assert.equal(elements.get("#theme-nes").checked, false);
  assert.equal(elements.get("documentElement").dataset.appTheme, "pico");
  assert.equal(elements.get("documentElement").dataset.colorMode, "light");
  assert.equal(elements.get("documentElement").dataset.theme, "light");
  assert.equal(elements.get("storage").get("keyword-watcher-theme"), "pico");
});

test("NES theme appears and restores its saved choice when its stylesheet loads", async () => {
  const elements = await loadDashboard({ storedTheme: "nes" });
  const nesCard = elements.get("#theme-card-nes");
  assert.equal(nesCard.hidden, true);

  elements.get("#nes-stylesheet").listeners.load();
  assert.equal(nesCard.hidden, false);
  assert.equal(elements.get("documentElement").dataset.appTheme, "nes");
  assert.equal(elements.get("#theme-nes").checked, true);
});

test("NES theme stays hidden and falls back when its stylesheet fails", async () => {
  const elements = await loadDashboard({ storedTheme: "nes" });
  elements.get("#nes-stylesheet").listeners.error();

  assert.equal(elements.get("#theme-card-nes").hidden, true);
  assert.equal(elements.get("documentElement").dataset.appTheme, "pico");
  assert.equal(elements.get("storage").get("keyword-watcher-theme"), "pico");
});

test("theme selection switches to NES and persists the choice", async () => {
  const elements = await loadDashboard();
  elements.get("#nes-stylesheet").listeners.load();
  const nesOption = elements.get("#theme-nes");
  nesOption.checked = true;
  nesOption.listeners.change();

  assert.equal(elements.get("documentElement").dataset.appTheme, "nes");
  assert.equal(elements.get("#theme-pico").checked, false);
  assert.equal(nesOption.checked, true);
  assert.equal(elements.get("storage").get("keyword-watcher-theme"), "nes");
});

test("light mode applies across themes and persists independently", async () => {
  const elements = await loadDashboard();
  const lightOption = elements.get("#mode-light");
  lightOption.checked = true;
  lightOption.listeners.change();

  assert.equal(elements.get("documentElement").dataset.appTheme, "pico");
  assert.equal(elements.get("documentElement").dataset.colorMode, "light");
  assert.equal(elements.get("documentElement").dataset.theme, "light");
  assert.equal(elements.get("storage").get("keyword-watcher-color-mode"), "light");
});

test("UI size slider applies and persists its scale", async () => {
  const elements = await loadDashboard();
  const slider = elements.get("#ui-scale");
  slider.value = "115";
  slider.listeners.input();

  assert.equal(elements.get("documentElement").style.properties["--app-ui-scale"], "1.15");
  assert.equal(elements.get("#ui-scale-value").textContent, "115%");
  assert.equal(elements.get("storage").get("keyword-watcher-ui-size"), "115");
});

test("add actions reveal inline editors without dialogs", async () => {
  const elements = await loadDashboard();
  const html = readFileSync(path.join(__dirname, "..", "index.html"), "utf8");

  elements.get("#add-feed-button").listeners.click();
  assert.equal(elements.get("#feed-form").hidden, false);
  assert.equal(elements.get("#feed-name").focused, true);

  elements.get("#add-topic-button").listeners.click();
  assert.equal(elements.get("#topic-form").hidden, false);
  assert.equal(elements.get("#topic-name").focused, true);
  assert.doesNotMatch(html, /<dialog\b/i);
});

function historyItem(index, overrides = {}) {
  return {
    topic: "AI tooling",
    link: `https://example.com/story-${index}`,
    first_seen: `2026-04-01T10:${String(index).padStart(2, "0")}:00+00:00`,
    source: "Example feed",
    title: `Story ${index}`,
    ...overrides,
  };
}

function search(elements, name, query) {
  const input = elements.get(`#${name}-search`);
  input.value = query;
  input.listeners.input();
  return elements.get(`#${name}-list`).innerHTML;
}

test("fuzzy search tolerates typos, needs every term, and ignores accents", async () => {
  const { searchScore, searchMatchers, indexSearchFields } = (await loadDashboard()).get("context");
  const fields = [
    { weight: 3, value: (item) => item.title },
    { weight: 1, value: (item) => item.summary },
  ];
  const indexed = indexSearchFields(
    { title: "Agentic coding tools for Kubernetes", summary: "A café review" },
    fields,
  );
  const score = (query) => searchScore(searchMatchers(query), indexed);

  assert.ok(score("agnet") > 0, "adjacent swap in a word prefix");
  assert.ok(score("kubernets") > 0, "missing letter");
  assert.ok(score("cafe") > 0, "accents are ignored");
  assert.ok(score("agent kube") > 0, "multiple terms");
  assert.equal(score("agent blockchain"), 0, "every term must match");
  assert.equal(score("xyz"), 0, "short terms need an exact substring");
  assert.ok(score("agent") > score("review"), "title outweighs summary");
});

test("history search ranks matches and reports no results", async () => {
  const elements = await loadDashboard({
    historyItems: [
      historyItem(1, { title: "Weather update", summary: "Mentions agents in passing." }),
      historyItem(2, { title: "Agent frameworks compared" }),
    ],
  });

  const rendered = search(elements, "history", "agent");
  assert.ok(rendered.indexOf("Agent frameworks compared") < rendered.indexOf("Weather update"));
  assert.equal(elements.get("#history-page-status").textContent, "2 results");

  assert.match(search(elements, "history", "quantum"), /No results for "quantum"\./);
  assert.equal(elements.get("#history-pager").hidden, true);
});

const articleCount = (html) => (html.match(/<article/g) ?? []).length;

test("history paginates 12 per page and search returns to the first page", async () => {
  const elements = await loadDashboard({
    historyItems: Array.from({ length: 32 }, (_, index) => historyItem(index)),
  });
  const list = elements.get("#history-list");
  const status = elements.get("#history-page-status");

  assert.equal(elements.get("#history-page-size").value, "12");
  assert.equal(articleCount(list.innerHTML), 12);
  assert.equal(status.textContent, "Page 1 of 3 · 32 items");
  assert.equal(elements.get("#history-prev").disabled, true);

  elements.get("#history-next").listeners.click();
  elements.get("#history-next").listeners.click();
  assert.equal(articleCount(list.innerHTML), 8);
  assert.equal(status.textContent, "Page 3 of 3 · 32 items");
  assert.equal(elements.get("#history-next").disabled, true);
  assert.equal(list.scrolled, true);

  search(elements, "history", "story");
  assert.equal(status.textContent, "Page 1 of 3 · 32 results");
});

test("page size can be changed, set to All, and is remembered", async () => {
  const elements = await loadDashboard({
    historyItems: Array.from({ length: 32 }, (_, index) => historyItem(index)),
  });
  const select = elements.get("#history-page-size");
  const list = elements.get("#history-list");
  const status = elements.get("#history-page-status");
  assert.match(select.innerHTML, /<option value="all">All \(can be slow\)<\/option>/);

  elements.get("#history-next").listeners.click();
  select.value = "24";
  select.listeners.change();
  assert.equal(articleCount(list.innerHTML), 24);
  assert.equal(status.textContent, "Page 1 of 2 · 32 items");
  assert.equal(elements.get("storage").get("keyword-watcher-page-size-history"), "24");

  select.value = "all";
  select.listeners.change();
  assert.equal(articleCount(list.innerHTML), 32);
  assert.equal(status.textContent, "32 items");
  assert.equal(elements.get("#history-next").disabled, true);
});

test("a saved page size is restored and invalid values fall back to 12", async () => {
  const restored = await loadDashboard({
    storedPageSizes: { history: "48", matches: "15" },
    historyItems: Array.from({ length: 32 }, (_, index) => historyItem(index)),
  });
  assert.equal(restored.get("#history-page-size").value, "48");
  assert.equal(articleCount(restored.get("#history-list").innerHTML), 32);
  assert.equal(restored.get("#matches-page-size").value, "12");
});

test("matches from a check are searchable", async () => {
  const match = (title) => ({
    topic: "AI tooling",
    keywords: ["agent*"],
    item: { source: "Example feed", title, link: "https://example.com/" },
  });
  const elements = await loadDashboard({
    checkResult: { matches: [match("Agent release notes"), match("Policy roundup")] },
  });
  const button = elements.get("#check-button");
  button.listeners.click({ currentTarget: button });
  await new Promise((resolve) => setImmediate(resolve));

  const rendered = search(elements, "matches", "policy");
  assert.match(rendered, /Policy roundup/);
  assert.doesNotMatch(rendered, /Agent release notes/);
});

test("the Seen tab is presented as History", () => {
  const html = readFileSync(path.join(__dirname, "..", "index.html"), "utf8");
  assert.match(html, /data-panel="history">History</);
  assert.doesNotMatch(html, />Seen</);
});

const visiblePanels = (elements) =>
  ["inbox", "matches", "history", "feeds"].filter((panel) => !elements.get(`#${panel}-panel`).hidden);

test("the active tab is remembered and restored", async () => {
  const elements = await loadDashboard();
  assert.deepEqual(visiblePanels(elements), ["inbox"], "the Inbox opens first");

  elements.get("#tab-history").listeners.click();
  assert.deepEqual(visiblePanels(elements), ["history"]);
  assert.equal(elements.get("storage").get("keyword-watcher-tab"), "history");

  const restored = await loadDashboard({ storedTab: "feeds" });
  assert.deepEqual(visiblePanels(restored), ["feeds"]);

  const formerSettingsTab = await loadDashboard({ storedTab: "settings" });
  assert.deepEqual(visiblePanels(formerSettingsTab), ["inbox"]);
});

test("the tab bar is Inbox, Matches, History, Setup", () => {
  const html = readFileSync(path.join(__dirname, "..", "index.html"), "utf8");
  const order = [...html.matchAll(/class="tab[^"]*" type="button" data-panel="(\w+)"/g)].map((match) => match[1]);
  assert.deepEqual(order, ["inbox", "matches", "history", "feeds"]);
});

test("broken feed images are removed to reveal the placeholder", async () => {
  const elements = await loadDashboard();
  let removed = false;
  elements.get("#history-list").listeners.error({ target: { tagName: "IMG", remove: () => { removed = true; } } });
  assert.equal(removed, true);

  const rendered = elements.get("#history-list").innerHTML;
  assert.match(rendered, /<span class="article-media-label" aria-hidden="true">Example feed<\/span>/);
});

test("match cards show matched keywords, images, and authors", async () => {
  const elements = await loadDashboard({
    storedPreferences: { "show-images": "true" },
    checkResult: {
      matches: [{
        topic: "AI tooling",
        keywords: ["agent*", "LLM"],
        item: {
          source: "Example feed",
          title: "Agent news",
          link: "https://example.com/a",
          author: "Editor",
          image_url: "https://example.com/a.jpg",
        },
      }],
    },
  });
  const button = elements.get("#dry-run-button");
  button.listeners.click({ currentTarget: button });
  await new Promise((resolve) => setImmediate(resolve));

  const rendered = elements.get("#matches-list").innerHTML;
  assert.match(rendered, /Matched: agent\*, LLM/);
  assert.match(rendered, /Example feed · Editor/);
  assert.match(rendered, /src="https:\/\/example\.com\/a\.jpg"/);
  assert.match(elements.get("#check-status").textContent, /^Previewed .+ · 1 new$/);
});

test("toolbar tools open a flyout and close by toggle, button, or Escape", async () => {
  const elements = await loadDashboard();
  const tool = elements.get("#tool-button-check");

  tool.listeners.click();
  const flyout = elements.get("#tool-check");
  assert.equal(flyout.hidden, false);
  assert.equal(tool.attributes["aria-expanded"], "true");

  tool.listeners.click();
  assert.equal(flyout.hidden, true);
  assert.equal(tool.attributes["aria-expanded"], "false");

  tool.listeners.click();
  elements.get("#tool-close-check").listeners.click();
  assert.equal(flyout.hidden, true);

  tool.listeners.click();
  elements.get("document").listeners.keydown({ key: "Escape" });
  assert.equal(flyout.hidden, true);
});

test("check actions live in the toolbar flyout, not the page header", () => {
  const html = readFileSync(path.join(__dirname, "..", "index.html"), "utf8");
  const flyout = html.slice(html.indexOf('<section id="tool-check"'), html.indexOf("</section>", html.indexOf('<section id="tool-check"')));
  assert.match(flyout, /id="check-button"/);
  assert.match(flyout, /id="dry-run-button"/);
  assert.match(flyout, /id="check-status"/);
  assert.doesNotMatch(html, /class="dock"/);
});

test("Settings and Shut down close the toolbar, pinned to the bottom, and Settings has its own sections", () => {
  const html = readFileSync(path.join(__dirname, "..", "index.html"), "utf8");
  const tools = [...html.matchAll(/class="(tool-button[^"]*)" type="button" data-tool="(\w+)"/g)];
  assert.deepEqual(tools.map((match) => match[2]), ["check", "tester", "health", "log", "settings", "shutdown"]);
  // The first pinned tool takes the free space above it, so both sit at the bottom.
  assert.deepEqual(tools.filter((match) => /tool-button-bottom/.test(match[1])).map((match) => match[2]), ["settings"]);

  const flyout = html.slice(html.indexOf('<section id="tool-settings"'), html.indexOf("<main"));
  assert.match(flyout, /id="settings-appearance"[\s\S]*name="app-theme"/);
  assert.match(flyout, /id="settings-appearance"[\s\S]*name="color-mode"/);
  assert.match(flyout, /id="settings-display"[\s\S]*id="ui-scale"/);
  assert.doesNotMatch(html, /id="settings-panel"/);
});

test("settings sections switch and the last one is remembered", async () => {
  const elements = await loadDashboard();
  elements.get("#tool-button-settings").listeners.click();
  assert.equal(elements.get("#tool-settings").hidden, false);
  assert.equal(elements.get("#settings-appearance").hidden, false);
  assert.equal(elements.get("#settings-display").hidden, true);

  elements.get("#settings-nav-display").listeners.click();
  assert.equal(elements.get("#settings-appearance").hidden, true);
  assert.equal(elements.get("#settings-display").hidden, false);
  assert.equal(elements.get("storage").get("keyword-watcher-settings-section"), "display");

  elements.get("#tool-button-check").listeners.click();
  assert.equal(elements.get("#tool-settings").hidden, true, "opening another tool closes Settings");

  const restored = await loadDashboard({ storedSettingsSection: "display" });
  assert.equal(restored.get("#settings-display").hidden, false);
});

const settle = () => new Promise((resolve) => setImmediate(resolve));

test("turning feed images on redraws every list, the Inbox included", async () => {
  const elements = await loadDashboard({
    historyItems: [{ topic: "T", link: "https://example.com/1", first_seen: "2026-11-21T10:00:00+00:00",
      image_url: "https://example.com/1.jpg" }],
  });
  assert.doesNotMatch(elements.get("#inbox-list").innerHTML, /<img/);
  const toggle = elements.get("#show-images");
  toggle.checked = true;
  toggle.listeners.change();
  assert.match(elements.get("#inbox-list").innerHTML, /<img class="article-image" src="https:\/\/example\.com\/1\.jpg"/);
  assert.match(elements.get("#history-list").innerHTML, /<img class="article-image"/);
});

test("feed images are off by default and can be turned on", async () => {
  const elements = await loadDashboard();
  assert.equal(elements.get("#show-images").checked, false);
  assert.doesNotMatch(elements.get("#history-list").innerHTML, /<img/);
  assert.match(elements.get("#history-list").innerHTML, /article-media-label/);

  const toggle = elements.get("#show-images");
  toggle.checked = true;
  toggle.listeners.change();
  assert.match(elements.get("#history-list").innerHTML, /<img class="article-image" src="https:\/\/example\.com\/article\.jpg"/);
  assert.equal(elements.get("storage").get("keyword-watcher-show-images"), "true");
});

test("automatic checks are off by default and the dashboard tab can run them", async () => {
  const elements = await loadDashboard({ checkResult: { matches: [], failed_sources: [] } });
  const interval = elements.get("#check-interval");
  assert.match(interval.innerHTML, /<option value="15">15 minutes<\/option>/);
  assert.match(interval.innerHTML, /<option value="1440">1 day<\/option>/);
  assert.equal(interval.value, "15");
  assert.equal(elements.get("#check-mode-off").checked, true);
  assert.equal(elements.get("#auto-check-status").textContent, "Automatic checks are off");
  assert.equal(elements.get("#dashboard-check-action").hidden, true);

  const dashboard = elements.get("#check-mode-dashboard");
  dashboard.checked = true;
  await dashboard.listeners.change();
  const timers = elements.get("timers").filter((timer) => timer.delay === 15 * 60_000 && !timer.cleared);
  assert.equal(timers.length, 1);
  assert.match(elements.get("#auto-check-status").textContent, /^Auto-check every 15 minutes \(Preview only\) · next /);
  assert.equal(elements.get("storage").get("keyword-watcher-check-mode"), "dashboard");
  assert.equal(elements.get("#dashboard-check-action").hidden, false);

  timers[0].callback();
  await settle();
  const check = elements.get("requests").find((request) => request.path === "/api/check");
  assert.deepEqual(JSON.parse(check.body), { dry_run: true, trigger: "auto" });
  assert.match(elements.get("#notice").textContent, /^Auto-check: /);
  const rescheduled = elements.get("timers").filter((timer) => timer.delay === 15 * 60_000 && !timer.cleared);
  assert.equal(rescheduled.length, 1, "exactly one pending auto-check after a run");

  interval.value = "30";
  await interval.listeners.change();
  assert.equal(elements.get("storage").get("keyword-watcher-auto-check-interval"), "30");
  assert.equal(elements.get("timers").filter((timer) => timer.delay === 30 * 60_000 && !timer.cleared).length, 1);

  const off = elements.get("#check-mode-off");
  off.checked = true;
  await off.listeners.change();
  assert.equal(elements.get("timers").filter((timer) => timer.delay >= 60_000 && !timer.cleared).length, 0);
});

test("the old auto-check setting carries over to the new mode", async () => {
  const on = await loadDashboard({ storedPreferences: { "auto-check-interval": "5" } });
  assert.equal(on.get("#check-mode-dashboard").checked, true);
  assert.equal(on.get("#check-interval").value, "5");
  assert.equal(on.get("storage").get("keyword-watcher-check-mode"), "dashboard");

  const off = await loadDashboard({ storedPreferences: { "auto-check-interval": "0" } });
  assert.equal(off.get("#check-mode-off").checked, true);
  assert.equal(off.get("#check-interval").value, "15");
});

test("auto-check with Check & save saves, and notifies each article only once", async () => {
  const shown = [];
  class FakeNotification {
    static permission = "granted";
    constructor(title, options) {
      shown.push({ title, ...options });
    }
  }
  const item = { source: "Feed", title: "Agent news", link: "https://example.com/a" };
  const elements = await loadDashboard({
    notification: FakeNotification,
    storedPreferences: { "auto-check-interval": "5", "auto-check-action": "save", notifications: "true" },
    checkResult: {
      matches: [
        { topic: "AI tooling", keywords: ["agent*"], item },
        { topic: "Breaking", keywords: ["news"], item },
      ],
      failed_sources: [],
    },
  });
  assert.equal(elements.get("#notify-new-matches").checked, true);

  const fire = async () => {
    const timer = elements.get("timers").find((pending) => pending.delay === 5 * 60_000 && !pending.cleared);
    timer.cleared = true;
    timer.callback();
    await settle();
  };
  await fire();
  await fire();
  const checks = elements.get("requests").filter((request) => request.path === "/api/check");
  assert.equal(checks.length, 2);
  assert.deepEqual(JSON.parse(checks[0].body), { dry_run: false, trigger: "auto" });
  assert.deepEqual(shown, [{ title: "HoundDog", body: "Agent news", tag: "hounddog-new-matches" }]);
});

test("notifications stay off when the browser refuses permission", async () => {
  class DeniedNotification {
    static permission = "default";
    static async requestPermission() {
      return "denied";
    }
  }
  const elements = await loadDashboard({ notification: DeniedNotification });
  const toggle = elements.get("#notify-new-matches");
  toggle.checked = true;
  await toggle.listeners.change();
  assert.equal(toggle.checked, false);
  assert.match(elements.get("#notice").textContent, /blocked/);
  assert.equal(elements.get("storage").get("keyword-watcher-notifications"), "false");
});

test("shared settings forms load from the server and save only their own fields", async () => {
  const elements = await loadDashboard();
  assert.equal(elements.get("#setting-fetch-timeout").value, "20");
  assert.equal(elements.get("#setting-user-agent").value, "HoundDog/1.0");
  assert.equal(elements.get("#setting-fetch-timeout").placeholder, "15", "default shown when the field is cleared");
  assert.equal(elements.get("#setting-user-agent").placeholder, "keyword-watcher/0.1");
  assert.equal(
    elements.get("#feed-settings-defaults").textContent,
    'Defaults: 15 seconds, 5 MB, user agent "keyword-watcher/0.1".',
  );
  assert.equal(elements.get("#setting-history-retention").value, "0");

  const retention = elements.get("#setting-history-retention");
  retention.value = "90";
  retention.type = "number";
  const form = elements.get("#retention-form");
  form.listeners.input();
  await form.listeners.submit({ preventDefault() {} });
  const save = elements.get("requests").find((request) => request.path === "/api/settings");
  assert.equal(save.method, "PUT");
  assert.deepEqual(JSON.parse(save.body), { history_retention_days: 90 });
});

test("the event export toggle shows the setting and saves it as a boolean", async () => {
  const elements = await loadDashboard();
  const toggle = elements.get("#setting-event-export");
  assert.equal(toggle.checked, true);

  toggle.checked = false;
  const form = elements.get("#event-export-form");
  form.listeners.input();
  await form.listeners.submit({ preventDefault() {} });
  const save = elements.get("requests").find((request) => request.path === "/api/settings");
  assert.deepEqual(JSON.parse(save.body), { event_export: false });
});

test("a check whose event export could not be written says so", async () => {
  const elements = await loadDashboard({
    checkResult: { matches: [], failed_sources: [], export_error: "file in use (3 record(s) waiting)" },
  });
  const button = elements.get("#check-button");
  button.listeners.click({ currentTarget: button });
  await new Promise((resolve) => setImmediate(resolve));

  assert.match(elements.get("#notice").textContent, /Event export not written yet: file in use \(3 record\(s\) waiting\)\./);
});

test("Settings has Appearance, Display, Checking, Feeds, and Data sections", () => {
  const html = readFileSync(path.join(__dirname, "..", "index.html"), "utf8");
  const sections = [...html.matchAll(/class="settings-nav-button" type="button" data-panel="(\w+)"/g)].map((match) => match[1]);
  assert.deepEqual(sections, ["appearance", "display", "checking", "feeds", "data"]);
  for (const section of sections) assert.match(html, new RegExp(`id="settings-${section}"`));
  assert.match(html, /href="\/api\/export\?format=json" download/);
  assert.match(html, /href="\/api\/export\?format=csv" download/);
});

test("an outdated server gets an actionable message instead of a crash", async () => {
  const elements = await loadDashboard({ omitSettings: true });
  assert.match(elements.get("#notice").textContent, /server is out of date\. Restart watcher_server\.py/);
  assert.match(elements.get("#history-list").innerHTML, /Useful article/, "the rest of the dashboard still loads");
});

test("articles already seen in a manual check are not announced by auto-check", async () => {
  const shown = [];
  class FakeNotification {
    static permission = "granted";
    constructor(title, options) {
      shown.push(options.body);
    }
  }
  const item = { source: "Feed", title: "Seen by hand", link: "https://example.com/manual" };
  const elements = await loadDashboard({
    notification: FakeNotification,
    storedPreferences: { "auto-check-interval": "5", notifications: "true" },
    checkResult: { matches: [{ topic: "AI tooling", keywords: ["agent*"], item }], failed_sources: [] },
  });
  const button = elements.get("#dry-run-button");
  button.listeners.click({ currentTarget: button });
  await settle();

  const timer = elements.get("timers").find((pending) => pending.delay === 5 * 60_000 && !pending.cleared);
  timer.callback();
  await settle();
  assert.deepEqual(shown, []);
});

test("feed health lists each feed's status and flags failures on the toolbar", async () => {
  const toggles = [];
  const elements = await loadDashboard({
    apiResponses: {
      "/api/health": {
        sources: [
          { name: "Good", url: "https://good.example/feed", status: "ok", last_checked: "2026-11-21T10:00:00+00:00",
            last_success: "2026-11-21T10:00:00+00:00", last_new_match: null, item_count: 30, duration_ms: 120, error: "", failure_streak: 0 },
          { name: "Broken <b>", url: "https://broken.example/feed", status: "failing", last_checked: "2026-11-21T10:00:00+00:00",
            last_success: null, last_new_match: null, item_count: 0, duration_ms: 40, error: "HTTP Error 404", failure_streak: 3 },
        ],
      },
    },
  });
  const button = elements.get('.tool-button[data-tool="health"]');
  button.classList.toggle = (name, on) => toggles.push([name, on]);
  elements.get("#tool-button-health").listeners.click();
  await settle();

  const rendered = elements.get("#health-list").innerHTML;
  assert.match(rendered, /health-ok[\s\S]*30 items · 120 ms[\s\S]*No new matches yet/);
  assert.match(rendered, /health-failing[\s\S]*Broken &lt;b&gt;[\s\S]*HTTP Error 404<\/p>\s*<p class="tool-row-error">Failed 3 checks in a row; no successful check in the log\./);
  assert.deepEqual(toggles.at(-1), ["has-alert", true]);
});

test("activity log shows each check with its trigger and failures", async () => {
  const elements = await loadDashboard({
    apiResponses: {
      "/api/activity": {
        checks: [
          { id: 2, started_at: "2026-11-21T10:05:00+00:00", duration_ms: 2300, trigger: "auto", saved: false,
            new_matches: 3, pruned: 0, source_count: 3, failed: [{ name: "BBC News", error: "timed out" }] },
          { id: 1, started_at: "2026-11-21T10:00:00+00:00", duration_ms: 900, trigger: "cli", saved: true,
            new_matches: 0, pruned: 4, source_count: 3, failed: [] },
        ],
      },
    },
  });
  elements.get("#tool-button-log").listeners.click();
  await settle();
  const rendered = elements.get("#activity-list").innerHTML;
  assert.match(rendered, /Auto-check · Preview[\s\S]*3 new · 3 feeds · 2\.3 s[\s\S]*Failed: <span title="timed out">BBC News<\/span>/);
  assert.match(rendered, /Command line · Saved[\s\S]*0 new · 4 removed by retention · 3 feeds · 900 ms/);
});

test("topic tester loads a topic, reports keyword hits, and saves back", async () => {
  const testResult = {
    corpus: "latest", fetched_at: "2026-11-21T10:00:00+00:00", failed_sources: [],
    total_items: 40, matched_count: 12, excluded_count: 2,
    keyword_hits: [{ keyword: "agent*", items: 14 }, { keyword: "LLM", items: 0 }],
    matches: [{ title: "Agents ship", link: "https://example.com/a", source: "HN", keywords: ["agent*"] }],
  };
  const elements = await loadDashboard({ apiResponses: { "/api/topic-test": testResult } });
  elements.get("#tool-button-tester").listeners.click();
  await settle();
  assert.match(elements.get("#tester-topic").innerHTML, /<option value="AI tooling">AI tooling<\/option>/);

  const select = elements.get("#tester-topic");
  select.value = "AI tooling";
  select.listeners.change();
  await settle();
  assert.equal(elements.get("#tester-keywords").value, "agent*, LLM");
  assert.equal(elements.get("#tester-exclude").value, "spam");
  const testRequest = elements.get("requests").filter((request) => request.path === "/api/topic-test").at(-1);
  assert.deepEqual(JSON.parse(testRequest.body), { keywords: ["agent*", "LLM"], exclude: ["spam"], corpus: "", refresh: false });

  assert.match(elements.get("#tester-summary").textContent, /^12 of 40 latest feed items match · 2 excluded \(fetched /);
  const report = elements.get("#tester-keyword-report").innerHTML;
  assert.match(report, /agent\*<\/code>[\s\S]*14 items \(35%\)[\s\S]*Very broad/);
  assert.match(report, /LLM<\/code>[\s\S]*0 items \(0%\)[\s\S]*No hits/);
  assert.match(elements.get("#tester-results").innerHTML, /href="https:\/\/example\.com\/a"[^>]*>Agents ship<\/a>/);

  elements.get("#tester-keywords").value = "agent*, model*";
  await elements.get("#tester-form").listeners.submit({ preventDefault() {} });
  const save = elements.get("requests").find((request) => request.path === "/api/topics/0");
  assert.equal(save.method, "PUT");
  assert.deepEqual(JSON.parse(save.body), {
    name: "AI tooling",
    keywords: ["agent*", "model*"],
    exclude: ["spam"],
    expected: { name: "AI tooling", keywords: ["agent*", "LLM"], exclude: ["spam"] },
  });
});

function listClick(attribute, index) {
  return { target: { closest: (selector) => (selector === `[${attribute}]` ? { dataset: { [datasetKey(attribute)]: String(index) } } : null) } };
}

function datasetKey(attribute) {
  return attribute.replace(/^data-/, "").replace(/-(\w)/g, (_, letter) => letter.toUpperCase());
}

async function refreshViaCheck(elements) {
  const button = elements.get("#check-button");
  button.listeners.click({ currentTarget: button });
  await settle();
}

test("a topic being edited is saved to its new position after the list shifts", async () => {
  const elements = await loadDashboard();
  elements.get("#topics-list").listeners.click(listClick("data-edit-topic", 1));
  assert.equal(elements.get("#topic-name").value, "Policy");

  // Another tab deletes "AI tooling", so "Policy" moves from position 1 to 0.
  elements.get("dashboard").topics = [{ name: "Policy", keywords: ["privacy"] }];
  await refreshViaCheck(elements);

  elements.get("#topic-keywords").value = "privacy, GDPR";
  await elements.get("#topic-form").listeners.submit({ preventDefault() {} });
  const saves = elements.get("requests").filter((request) => request.method === "PUT");
  assert.deepEqual(saves.map((request) => request.path), ["/api/topics/0"]);
  assert.deepEqual(JSON.parse(saves[0].body).expected, { name: "Policy", keywords: ["privacy"] });
});

test("editing a feed that was removed elsewhere sends nothing and says so", async () => {
  const elements = await loadDashboard();
  elements.get("#feeds-list").listeners.click(listClick("data-edit-feed", 0));
  elements.get("dashboard").sources = [{ name: "Other feed", url: "https://example.org/feed.xml" }];
  await refreshViaCheck(elements);

  await elements.get("#feed-form").listeners.submit({ preventDefault() {} });
  assert.equal(elements.get("requests").some((request) => request.method === "PUT"), false);
  assert.match(elements.get("#notice").textContent, /"Example feed" was changed or removed elsewhere/);
});

test("a delete refused as stale reloads the list", async () => {
  const elements = await loadDashboard({
    apiResponses: { "/api/topics/0": { status: 409, error: "That topic was changed elsewhere; check the list and try again." } },
  });
  elements.get("context").window.confirm = () => true;
  const before = elements.get("requests").filter((request) => request.path === "/api/dashboard").length;

  await elements.get("#topics-list").listeners.click(listClick("data-delete-topic", 0));
  const remove = elements.get("requests").find((request) => request.path === "/api/topics/0");
  assert.equal(remove.method, "DELETE");
  assert.deepEqual(JSON.parse(remove.body), { expected: { name: "AI tooling", keywords: ["agent*", "LLM"], exclude: ["spam"] } });
  assert.match(elements.get("#notice").textContent, /changed elsewhere/);
  assert.equal(elements.get("requests").filter((request) => request.path === "/api/dashboard").length, before + 1);
});

test("an older dashboard response does not overwrite a newer one", async () => {
  const elements = await loadDashboard();
  const context = elements.get("context");
  const realFetch = context.fetch;
  const pending = [];
  const dashboard = elements.get("dashboard");
  // Each dashboard request answers with the data as it was when the request was made.
  context.fetch = (requestPath, options) => {
    if (requestPath !== "/api/dashboard") return realFetch(requestPath, options);
    const snapshot = structuredClone(dashboard);
    return new Promise((resolve) => pending.push(() => resolve({ ok: true, status: 200, json: async () => snapshot })));
  };

  dashboard.topics = [{ name: "Stale", keywords: ["old"] }];
  const older = context.refresh();
  await settle();
  const staleResponse = pending.shift();
  dashboard.topics = [{ name: "Fresh", keywords: ["new"] }];
  const newer = context.refresh();
  await settle();
  pending.shift()();
  await newer;
  staleResponse();
  await older;

  const rendered = elements.get("#topics-list").innerHTML;
  assert.match(rendered, /Fresh/);
  assert.doesNotMatch(rendered, /Stale/);
});

test("topic tester asks for a keyword before testing", async () => {
  const elements = await loadDashboard();
  elements.get("#tool-button-tester").listeners.click();
  await settle();
  assert.equal(elements.get("#tester-summary").textContent, "Enter at least one include keyword to test.");
  assert.equal(elements.get("requests").some((request) => request.path === "/api/topic-test"), false);
});

test("clearing the tester keywords invalidates a pending response", async () => {
  const elements = await loadDashboard();
  const context = elements.get("context");
  let respond;
  context.fetch = () => new Promise(resolve => { respond = resolve; });
  const keywords = elements.get("#tester-keywords");
  keywords.value = "old";
  const pending = context.runTopicTest();
  keywords.value = "";
  await context.runTopicTest();
  respond({ ok: false, status: 400, json: async () => ({ error: "An out-of-date error" }) });
  await pending;
  assert.equal(elements.get("#tester-summary").textContent, "Enter at least one include keyword to test.");
});

function savedRow(topic, link, overrides = {}) {
  return { topic, link, first_seen: "2026-11-21T10:00:00+00:00", source: "Example feed", title: `Story ${link.at(-1)}`, ...overrides };
}

function cardClick(card, target) {
  const dataset = { link: card.link, read: String(Boolean(card.read)), starred: String(Boolean(card.starred)) };
  return {
    target: {
      closest: (selector) => {
        if (selector === "[data-link]") return { dataset };
        if (selector === "[data-item-action]") return target === "link" ? null : { dataset: { itemAction: target } };
        if (selector === "a.article-link, a.article-media") return target === "link" ? {} : null;
        return null;
      },
    },
  };
}

const stateRequests = (elements) => elements.get("requests")
  .filter((request) => request.path === "/api/items/state")
  .map((request) => JSON.parse(request.body));

test("the inbox shows each unread article once, with every topic, and counts them", async () => {
  const elements = await loadDashboard({
    historyItems: [
      savedRow("AI tooling", "https://example.com/1"),
      savedRow("Breaking", "https://example.com/1"),
      savedRow("AI tooling", "https://example.com/2", { read_at: "2026-11-21T11:00:00+00:00" }),
      savedRow("Breaking", "https://example.com/3", { starred_at: "2026-11-21T11:00:00+00:00" }),
    ],
  });
  const inbox = elements.get("#inbox-list").innerHTML;
  assert.equal((inbox.match(/data-link=/g) ?? []).length, 2);
  assert.match(inbox, /AI tooling · Breaking/);
  assert.doesNotMatch(inbox, /example\.com\/2/);
  assert.match(inbox, /is-starred/);
  assert.match(inbox, /aria-pressed="true" aria-label="Remove from favorites" title="Remove from favorites">\u2605</);
  assert.match(inbox, /aria-pressed="false" aria-label="Add to favorites" title="Add to favorites">\u2606</);
  assert.equal(elements.get("#inbox-count").textContent, "2");
  assert.equal(elements.get("#inbox-mark-read").disabled, false);
});

test("mark all read sends exactly the links shown in the inbox", async () => {
  const elements = await loadDashboard({
    historyItems: [savedRow("AI tooling", "https://example.com/1"), savedRow("Policy", "https://example.com/2")],
  });
  await elements.get("#inbox-mark-read").listeners.click();
  assert.deepEqual(stateRequests(elements), [{ links: ["https://example.com/1", "https://example.com/2"], read: true }]);
  assert.match(elements.get("#notice").textContent, /Marked 2 articles read/);
});

test("card actions toggle read and star, and opening an unread link marks it read", async () => {
  const elements = await loadDashboard({ historyItems: [savedRow("AI tooling", "https://example.com/1")] });
  const list = elements.get("#inbox-list");
  await list.listeners.click(cardClick({ link: "https://example.com/1" }, "star"));
  await list.listeners.click(cardClick({ link: "https://example.com/1", starred: true }, "star"));
  await list.listeners.click(cardClick({ link: "https://example.com/1" }, "read"));
  await list.listeners.auxclick({ type: "auxclick", button: 2, ...cardClick({ link: "https://example.com/1" }, "link") });
  await list.listeners.auxclick({ type: "auxclick", button: 1, ...cardClick({ link: "https://example.com/1" }, "link") });
  await list.listeners.click(cardClick({ link: "https://example.com/1", read: true }, "link"));
  assert.deepEqual(stateRequests(elements), [
    { links: ["https://example.com/1"], starred: true },
    { links: ["https://example.com/1"], starred: false },
    { links: ["https://example.com/1"], read: true },
    { links: ["https://example.com/1"], read: true },
  ], "a right-click or an already read link sends nothing");
});

test("history can be filtered to unread or starred, and the choice is remembered", async () => {
  const historyItems = [
    savedRow("AI tooling", "https://example.com/1"),
    savedRow("AI tooling", "https://example.com/2", { read_at: "2026-11-21T11:00:00+00:00", starred_at: "2026-11-21T11:00:00+00:00" }),
  ];
  const elements = await loadDashboard({ historyItems });
  const filter = elements.get("#history-filter");
  assert.equal(filter.value, "all");
  assert.equal((elements.get("#history-list").innerHTML.match(/data-link=/g) ?? []).length, 2);

  filter.value = "starred";
  filter.listeners.change();
  assert.match(elements.get("#history-list").innerHTML, /example\.com\/2/);
  assert.doesNotMatch(elements.get("#history-list").innerHTML, /example\.com\/1"/);
  assert.equal(elements.get("storage").get("keyword-watcher-history-filter"), "starred");

  const restored = await loadDashboard({ historyItems: [], storedPreferences: { "history-filter": "starred" } });
  assert.equal(restored.get("#history-filter").value, "starred");
  assert.match(restored.get("#history-list").innerHTML, /No favorites yet/);

  const tampered = await loadDashboard({ storedPreferences: { "history-filter": "constructor" } });
  assert.equal(tampered.get("#history-filter").value, "all");
});

test("a feed's check interval is edited and saved with the feed", async () => {
  const elements = await loadDashboard();
  elements.get("#feeds-list").listeners.click(listClick("data-edit-feed", 0));
  assert.equal(elements.get("#feed-interval").value, "");
  elements.get("#feed-interval").value = "1440";
  await elements.get("#feed-form").listeners.submit({ preventDefault() {} });
  const save = elements.get("requests").find((request) => request.method === "PUT" && request.path === "/api/feeds/0");
  assert.equal(JSON.parse(save.body).check_every_minutes, 1440);
});

test("health shows unchanged feeds and checks report skipped feeds", async () => {
  const elements = await loadDashboard({
    checkResult: { matches: [], failed_sources: [], skipped_sources: [{ name: "arXiv", reason: "not due" }] },
    apiResponses: {
      "/api/health": {
        sources: [{ name: "HN", url: "https://hn.example/rss", status: "ok", last_checked: "2026-11-22T10:00:00+00:00",
          last_success: "2026-11-22T10:00:00+00:00", last_new_match: null, item_count: 0, duration_ms: 50,
          error: "", failure_streak: 0, not_modified: true, conditional: false }],
      },
    },
  });
  await refreshViaCheck(elements);
  assert.match(elements.get("#notice").textContent, /Skipped: arXiv\./);
  assert.match(elements.get("#health-list").innerHTML, /Unchanged since the last download/);
  assert.match(elements.get("#health-list").innerHTML, /Sends no ETag or Last-Modified, so every check downloads it in full/);
});

test("the card banner opens the article, except when the link is unsafe", async () => {
  const elements = await loadDashboard({
    historyItems: [
      savedRow("AI tooling", "https://example.com/1"),
      savedRow("AI tooling", "javascript:alert(1)"),
    ],
  });
  const rendered = elements.get("#history-list").innerHTML;
  assert.match(rendered, /<a class="article-media" href="https:\/\/example\.com\/1" target="_blank" rel="noreferrer" tabindex="-1" aria-hidden="true">/);
  assert.equal((rendered.match(/<a class="article-media"/g) ?? []).length, 1);
  assert.match(rendered, /<div class="article-media">/);
});

test("the History filter calls starred articles Favorites", () => {
  const html = readFileSync(path.join(__dirname, "..", "index.html"), "utf8");
  assert.match(html, /<option value="starred">Favorites<\/option>/);
  assert.doesNotMatch(html, />Starred</);
});

const INSTALLED_JOB = {
  supported: true, installed: true, state: "Ready",
  options: { interval_minutes: 60, run_on_battery: true, catch_up: true, require_network: true },
  next_run: "2026-11-22T16:00:00Z", last_run: "2026-11-22T15:00:00Z", last_result: 0,
  runs_this_folder: true, command_found: true, command: '"C:\\Py\\pythonw.exe" "C:\\HoundDog\\watcher.py" --scheduled',
  log: [],
};
const NO_JOB = { supported: true, installed: false, log: [] };

// /api/schedule answers like the server: with the job as it is after the request.
function fakeSchedule(initial) {
  let job = initial;
  return (options = {}) => {
    if (options.method === "PUT") {
      job = { ...INSTALLED_JOB, options: { ...INSTALLED_JOB.options, ...JSON.parse(options.body) } };
    } else if (options.method === "DELETE") {
      job = NO_JOB;
    }
    return job;
  };
}

const scheduleRequests = (elements) => elements.get("requests")
  .filter((request) => request.path === "/api/schedule" && request.method)
  .map((request) => [request.method, request.body && JSON.parse(request.body)]);

async function choose(elements, mode) {
  const radio = elements.get(`#check-mode-${mode}`);
  radio.checked = true;
  await radio.listeners.change();
  await settle();
}

test("choosing the background job installs it and pauses this tab's auto-check", async () => {
  const elements = await loadDashboard({
    storedPreferences: { "check-mode": "dashboard", "auto-check-interval": "30" },
    apiResponses: { "/api/schedule": fakeSchedule(NO_JOB) },
  });
  await settle();
  assert.equal(elements.get("timers").filter((timer) => timer.delay === 30 * 60_000 && !timer.cleared).length, 1);

  elements.get("#job-battery").checked = false;
  await choose(elements, "background");
  assert.deepEqual(scheduleRequests(elements), [
    ["PUT", { interval_minutes: 30, run_on_battery: false, catch_up: true, require_network: true }],
  ]);
  assert.equal(elements.get("#check-mode-background").checked, true);
  assert.equal(elements.get("storage").get("keyword-watcher-check-mode"), "off");
  assert.equal(elements.get("timers").filter((timer) => timer.delay >= 60_000 && !timer.cleared).length, 0);
  assert.equal(elements.get("#background-check-options").hidden, false);
  assert.match(elements.get("#auto-check-status").textContent, /^Background job every 30 minutes · next /);

  elements.get("#check-interval").value = "120";
  await elements.get("#check-interval").listeners.change();
  assert.deepEqual(scheduleRequests(elements).at(-1)[1].interval_minutes, 120);

  await choose(elements, "dashboard");
  assert.deepEqual(scheduleRequests(elements).at(-1), ["DELETE", undefined]);
  assert.equal(elements.get("#check-mode-dashboard").checked, true);
  assert.equal(elements.get("timers").filter((timer) => timer.delay === 30 * 60_000 && !timer.cleared).length, 1);
});

test("an installed job wins over this browser's own choice", async () => {
  const elements = await loadDashboard({
    storedPreferences: { "check-mode": "dashboard", "auto-check-interval": "5" },
    apiResponses: { "/api/schedule": INSTALLED_JOB },
  });
  await settle();
  assert.equal(elements.get("#check-mode-background").checked, true);
  assert.equal(elements.get("#check-interval").value, "60");
  assert.equal(elements.get("timers").filter((timer) => timer.delay >= 60_000 && !timer.cleared).length, 0);
  assert.match(elements.get("#check-mode-status").textContent, /^Every 1 hour · next .+ · last run .+ \(OK\)\.$/);
  assert.equal(elements.get("#job-repair").hidden, true);
});

test("a pending tab timer yields to a job enabled elsewhere", async () => {
  let job = NO_JOB;
  const elements = await loadDashboard({
    storedPreferences: { "check-mode": "dashboard", "auto-check-interval": "5" },
    apiResponses: { "/api/schedule": () => job },
  });
  await settle();
  const timer = elements.get("timers").find((timer) => timer.delay === 5 * 60_000 && !timer.cleared);
  assert.ok(timer);
  job = INSTALLED_JOB;
  timer.callback();
  await settle();
  assert.equal(elements.get("#check-mode-background").checked, true);
  assert.ok(!elements.get("requests").some((request) => request.path === "/api/check"));
});

test("a tab keeps auto-checking when the background job cannot be read", async () => {
  let failing = false;
  const elements = await loadDashboard({
    storedPreferences: { "check-mode": "dashboard", "auto-check-interval": "5" },
    apiResponses: {
      "/api/schedule": () => (failing ? { status: 500, error: "PowerShell is unavailable" } : NO_JOB),
    },
  });
  await settle();
  failing = true;
  const timer = elements.get("timers").find((pending) => pending.delay === 5 * 60_000 && !pending.cleared);
  timer.cleared = true;
  timer.callback();
  await settle();

  assert.equal(elements.get("requests").filter((request) => request.path === "/api/check").length, 1);
  assert.match(elements.get("#check-mode-status").textContent, /PowerShell is unavailable/);
});

test("the background job panel explains problems and offers a repair", async () => {
  const broken = {
    ...INSTALLED_JOB, state: "Disabled", command_found: false, runs_this_folder: false, options: null,
    last_result: 0x80070002, log: ["2026-11-22T15:00:00+00:00 exit 3", "RuntimeError: boom"],
  };
  const elements = await loadDashboard({ apiResponses: { "/api/schedule": fakeSchedule(broken) } });
  await settle();
  const status = elements.get("#check-mode-status").textContent;
  assert.match(status, /^On · next .+ \(Python or watcher\.py was not found\)\./);
  assert.match(status, /disabled in Task Scheduler/);
  assert.match(status, /program no longer exists/);
  assert.match(status, /different HoundDog folder or Python/);
  assert.match(status, /changed in Task Scheduler/);
  assert.equal(elements.get("#job-repair").hidden, false);
  assert.equal(elements.get("#job-log-details").hidden, false);
  assert.equal(elements.get("#job-log").textContent, "2026-11-22T15:00:00+00:00 exit 3\nRuntimeError: boom");

  await elements.get("#job-repair").listeners.click();
  assert.deepEqual(scheduleRequests(elements).at(-1)[0], "PUT");
  assert.equal(elements.get("#job-repair").hidden, true);
});

test("unknown result codes show in hex, and the job is Windows-only", async () => {
  const odd = await loadDashboard({ apiResponses: { "/api/schedule": { ...INSTALLED_JOB, last_result: 0x8007ffff } } });
  await settle();
  assert.match(odd.get("#check-mode-status").textContent, /\(result 0x8007FFFF\)/);

  const elsewhere = await loadDashboard({ apiResponses: { "/api/schedule": { supported: false, installed: false } } });
  await settle();
  assert.equal(elsewhere.get("#check-mode-background").disabled, true);
  assert.match(elsewhere.get("#check-mode-hint").textContent, /only available on Windows/);
});

test("a failed change keeps showing what Task Scheduler really has", async () => {
  let answer = NO_JOB;
  const elements = await loadDashboard({
    apiResponses: {
      "/api/schedule": (options = {}) => (options.method === "PUT"
        ? { status: 502, error: "Access is denied." }
        : answer),
    },
  });
  await settle();
  await choose(elements, "background");
  assert.equal(elements.get("#check-mode-off").checked, true, "the radio goes back");
  assert.match(elements.get("#check-mode-status").textContent, /^Access is denied\./);
  assert.match(elements.get("#notice").textContent, /Access is denied/);
  assert.equal(elements.get("#check-mode-background").disabled, false, "trying again stays possible");
  answer = INSTALLED_JOB;
});

test("run now and clearing messages use their endpoints", async () => {
  const elements = await loadDashboard({
    apiResponses: {
      "/api/schedule": { ...INSTALLED_JOB, log: ["old problem"] },
      "/api/schedule/run": INSTALLED_JOB,
      "/api/schedule/log": { log: [] },
    },
  });
  await settle();
  await elements.get("#job-run").listeners.click();
  await elements.get("#job-log-clear").listeners.click();
  const sent = elements.get("requests").filter((request) => request.method).map((request) => [request.method, request.path]);
  assert.deepEqual(sent.slice(-2), [["POST", "/api/schedule/run"], ["DELETE", "/api/schedule/log"]]);
  assert.equal(elements.get("#job-log-details").hidden, true);
});

test("shut down opens a confirmation from the toolbar; only confirming stops the server", async () => {
  const elements = await loadDashboard();
  const shutdowns = () => elements.get("requests").filter((request) => request.path === "/api/shutdown");
  const confirm = elements.get("#shutdown-confirm");

  elements.get("#tool-button-shutdown").listeners.click();
  assert.equal(elements.get("#tool-shutdown").hidden, false);
  assert.equal(elements.get("#tool-settings").hidden, true);
  elements.get("#tool-close-shutdown").listeners.click();
  assert.equal(elements.get("#tool-shutdown").hidden, true);
  assert.equal(shutdowns().length, 0);

  elements.get("#tool-button-shutdown").listeners.click();
  await confirm.listeners.click({ currentTarget: confirm });
  assert.equal(shutdowns().length, 1);
  assert.equal(shutdowns()[0].method, "POST");
  assert.equal(elements.get("#tool-shutdown").hidden, true);
  assert.equal(elements.get("document").querySelector("#stopped").hidden, false);
});

test("a refused shut down leaves the page working and says why", async () => {
  const elements = await loadDashboard({
    apiResponses: { "/api/shutdown": { status: 403, error: "Cross-origin request refused" } },
  });
  const confirm = elements.get("#shutdown-confirm");

  elements.get("#tool-button-shutdown").listeners.click();
  await confirm.listeners.click({ currentTarget: confirm });
  assert.notEqual(elements.get("document").querySelector("#stopped").hidden, false);
  assert.equal(elements.get("#tool-shutdown").hidden, false);
  assert.equal(confirm.disabled, false);
  assert.match(elements.get("#notice").textContent, /Could not shut down: Cross-origin request refused/);
});
