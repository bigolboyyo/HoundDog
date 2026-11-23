# Bridge

Joins HoundDog's news export with ThetaDesk's market export and runs the first
daily study: do a ticker's sessions move more, or trade more, on days HoundDog
found news about it? Use it from the command line or its dashboard.

The study reads the two apps' export folders, so neither app needs to be
running to view results. Adding a ticker uses HoundDog's local API. Loading
prices and working with shared pins use ThetaDesk's local API.

## Setup

Use Python 3.11 or newer. Install the dashboard and time-zone dependencies
from the repository root.

```powershell
python -m pip install -r bridge\requirements.txt
```

## Dashboard

```powershell
python bridge\server.py
```

The dashboard opens at [127.0.0.1:8090](http://127.0.0.1:8090). Use `--port`
to change its port or `--no-browser` to start it without opening a tab.
Stop Bridge with **Shut down** or Ctrl+C.

- the selected ticker's closing-price chart and weekly news at the top,
  with the last price shown and the latest recorded check in HoundDog's
  exports;
- a watchlist with the latest exported close, news and quiet session
  counts, and actions to load prices or open a ticker's study;
- the full study table for each ticker and group below the watchlist;
- coverage, session counts, and article placement under **Study details**,
  and export summaries under **Sources and connections**.

**Producer connections.** The ThetaHound launcher passes custom producer
ports when you start the apps together. To choose the ports for one
standalone Bridge run, use `--hounddog-port` and `--thetadesk-port` on
`server.py`. Each overrides the corresponding enabled connection for that
run. For persistent settings, edit [`bridge.toml`](#settings-bridgetoml).

**Watch tickers.** Choose tickers (those with prices in ThetaDesk are listed;
add any other) and give each the words its news uses, such as `Apple, AAPL`.
Optionally name a group, such as `Tech Bros`. For each ticker the bridge:

1. creates a HoundDog topic named after the ticker, through HoundDog's own
   API (HoundDog must be running; it still owns `watch.toml`). A topic that
   already exists is left as it is.
2. adds the ticker, and the group, to `bridge.toml`.

A group pools its member tickers' sessions. Each ticker still uses its own
topic mapping. Load prices for each ticker you want to compare.

Choose **Watch and load price history** to request daily bars for each
successfully watched ticker. Bridge shows the topic outcome in the watch
form and the price outcome on the ticker card. Failed topic entries stay
selected for retry. If only prices failed, use the watchlist's price action.

**Price loading.** A first load requests about a year through the latest
closed NYSE session. An update starts after the last saved close, within
that rolling year. ThetaDesk fills gaps in its cached lookup dates. Use
**Retry missing bars** to recheck the range with the provider after a
successful lookup left a bar missing. ThetaDesk can save today's bar
starting at 6 p.m. ET. If the daily bar is still pending, the normal update
will retry only the recent dates. Bridge refreshes its study from
the exports after a price request, including when the request reports an
error after saving partial progress.

**News on the chart.** Select a news marker to see the price move, volume,
and articles for that day. Select it again to close the details. The
optional **Study details** panel shows HoundDog's activity by New York
calendar date, including weekends and today. The bar starts with the first
recorded check for the ticker's topics. Each day with feed attempts shows
the successful and failed proportions. Successful attempts include downloads
and unchanged responses. Pick a day for the counts, including skipped
feeds, which are counted separately from attempts. The date range controls
filter the chart and ticker detail. The main study summary uses the full
available sample.

**Weekly news.** The list sits beside the chart on wide screens. **Weekdays**
shows live articles assigned to trading sessions and counts how many have
yet to be matched to a price move. **Full week** also displays a separate
**Weekend news** list for Friday at or after the NYSE close through Sunday
in New York time. If Friday was closed, the weekend starts at 4 p.m. ET.
Weekend articles have a detection time and stay outside the daily price
study. Monday through Thursday after-close articles still go to the next
trading session. Use the arrows to browse earlier weeks by detection date.
The chart's date range controls operate independently of this view.

**Pinned ranges.** Use **Pin this range** beside the date controls to save
the active ticker and dates in ThetaDesk. Opening a shared pin restores its
range, reads stored closes through ThetaDesk, and shows matching news from
Bridge's exports. A pin outside the Bridge watchlist uses the topic named
after its ticker. Refresh either dashboard to see pins added in the other.

### HTTP API

| Method and path | Behavior |
| --- | --- |
| `GET /api/overview` | Export status, the study report, HoundDog connection status, and Bridge settings. The `report` is the same as the CLI's JSON report. |
| `POST /api/watch` | Accepts `tickers`, each with a `symbol` and `keywords`, and an optional `group`. Successful tickers are recorded even if another ticker fails. A topic created before a config write fails may already exist when you retry. |
| `POST /api/prices/{symbol}/fetch` | Requests bars for a watched ticker through ThetaDesk. Send `{}` for normal caching, `after` to update after a saved date, or `{"refresh": true}` to recheck with the provider. |
| `GET /api/pins`, `POST /api/pins` | Lists shared pins or saves a range by `symbol`, `start_date`, and `end_date` in ThetaDesk. |
| `GET /api/tickers/{symbol}` | Returns stored prices for the requested `start_date` and `end_date` alongside Bridge's export-based study for that ticker. |
| `POST /api/shutdown` | Requests shutdown on a server started by `server.py`. |

## Demo

A real comparison needs live detections, watched quiet sessions, and
overlapping prices. Use the demo to explore the dashboard with generated news.

```powershell
python bridge\make_demo.py
python bridge\server.py --config bridge\demo\demo.toml --port 8091
```

`make_demo.py` regenerates the news files in `bridge\demo\exports\` and
writes `bridge\demo\demo.toml`. It uses the saved daily prices for AAPL,
MSFT, and TSLA by default. Load at least two bars for each ticker first.
Use `--symbols` for others and `--thetadesk` for a different export folder.
Use a dedicated directory for any custom `--out` path.

The demo config disables both API connections and shows a banner. Every
demo headline starts with `[DEMO]`. The generator includes examples of
news and quiet sessions, a period without checks, weekend news, backfill,
and repeat detections. It places news more often near large price moves
to illustrate a populated comparison. Use `--seed` for a different
repeatable sample.

Bridge reads the original price exports for the demo. The generated
news and configuration stay in the demo output folder.

## Command line

From the repository root.

```powershell
python bridge\bridge.py status    # what each export folder holds
python bridge\bridge.py report    # the study, per symbol
```

Add `--json` to either command for machine-readable output. Use
`--config PATH` with another settings file. The status command also
reports malformed, incomplete, and duplicate export records.

## Settings: `bridge.toml`

- `[inputs]`:
  - `hounddog_exports` defaults to `../HoundDog/exports`;
  - `thetadesk_exports`, left empty, means ThetaDesk's own store,
    `%LOCALAPPDATA%\ThetaDesk\exports` on Windows or
    `~/.thetadesk/exports` if `LOCALAPPDATA` is absent.

  Relative paths are relative to `bridge.toml`.
- `[hounddog] url`: where HoundDog's dashboard runs, `http://127.0.0.1:8080`
  by default. An empty value (`url = ""`) turns the connection off: the
  dashboard only reads exports and cannot watch tickers.
- `[thetadesk] url`: the local ThetaDesk API. Defaults to
  `http://127.0.0.1:8000` when using the default export directory. With a
  custom ThetaDesk export directory, price loading and pins are off unless
  a loopback URL is set explicitly. Set `url = ""` to disable them.
- `[display] banner`: optional text shown across the top of the dashboard.
- `[[symbols]]`: one entry per ticker to study, with the HoundDog topics that
  count as news about it. `topics` defaults to the ticker itself:

  ```toml
  [[symbols]]
  symbol = "NVDA"
  topics = ["NVDA"]
  ```

  The topic must exist in HoundDog (for example a topic named `NVDA` with the
  keyword `Nvidia`), and the ticker's history must be loaded in ThetaDesk.
- `[[groups]]`: a name and its tickers, studied together.

The dashboard rewrites `bridge.toml` when it adds tickers and regenerates the
comments. Keep custom settings to flat tables with scalar or list values.
Listing a ticker twice in `[[symbols]]` is an error. Listing it twice in one
group counts once.

## What the report means

The dashboard's **Study details** shows HoundDog's daily check activity,
session statuses, and article placement. The session table hides unwatched
sessions before the ticker's first relevant weekday check.
The table still shows missing bars across ThetaDesk's recorded lookup dates.
**Article placement** lists only articles assigned to a trading session,
including sessions with prices pending. Backfill and repeat detections are
available in the JSON report from `python bridge\bridge.py report --json`.

- **Session move** compares the session's close with the previous session's
  close. Bridge assigns non-weekend detections from the previous close
  through the moment before this close to the session. Sessions follow the
  NYSE calendar, including holidays and 13:00 early closes.
- **Group:** its members' sessions pooled; each member's volume is compared
  with that member's own median.
- **News session** has a return and an eligible live article. Bridge uses an
  article's earliest detection for any mapped topic. A live match takes
  priority if that same detection also contains backfill matches. An
  article first seen only as backfill is excluded for that ticker.
- **Quiet session:** no such article, while HoundDog was watching. That means
  at least one check that read a feed and listed one of the symbol's topics
  started outside the weekend window, after the previous close and at or
  before this close. Weekend checks still appear in HoundDog activity.
  Sessions without a qualifying check are left out of the quiet sample.
- **Average move** is the average size of the close-to-close move, up or down.
- **Volume ratio** compares session volume with the ticker's median volume.
- **Missing bars** are trading days inside ThetaDesk's recorded lookup dates
  with no daily bar.

## Limits

- The study describes daily returns and volume for the observed sample.
  Intraday timing and causal analysis need different data and methods.
- One qualifying check establishes session coverage.
- Backfill-only checks can count as coverage. A session with a qualifying
  check, a return, and only backfill events can be labeled quiet.
- The report flags one to nine news sessions as a small sample. The dashboard
  verdict also flags fewer than ten quiet sessions when a comparison exists.
- One-off market closures (such as days of mourning) are listed by hand in
  `market_calendar.py`.

## Tests

```powershell
cd bridge
python -m unittest discover -s tests
```
