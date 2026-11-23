# Bridge

Joins HoundDog's news export with ThetaDesk's market export and runs the first
daily study: do a ticker's sessions move more, or trade more, on days HoundDog
found news about it? Use it from the command line or its dashboard.

The study reads the two apps' export folders, so neither app needs to be
running to view results. Adding a ticker uses HoundDog's local API. Loading
prices and working with shared pins use ThetaDesk's local API.

## Setup

Python 3.11 or newer, plus time zone data (which Windows Python does not
include) and the dashboard's server:

```powershell
python -m pip install -r bridge\requirements.txt
```

## Dashboard

```powershell
python bridge\server.py
```

It opens http://127.0.0.1:8090 (`--port` to change it, `--no-browser` to stay
in the console). Stop it with **Shut down** at the top of the page, or Ctrl+C. It shows:

- a watchlist with the latest exported close, the last qualifying HoundDog
  check, the news and quiet session counts, and actions to load prices or
  open the ticker's study;
- what each app's export holds, under **Sources and connections**;
- the study table for each ticker and group, with a one-line comparison per
  ticker;
- closing prices, session counts, reasons for each session label, and article
  placement and exclusions for the selected ticker.

**Watch tickers.** Choose tickers (those with prices in ThetaDesk are listed;
add any other) and give each the words its news uses, such as `Apple, AAPL`.
Optionally name a group, such as `Tech Bros`. For each ticker the bridge:

1. creates a HoundDog topic named after the ticker, through HoundDog's own
   API (HoundDog must be running; it still owns `watch.toml`). A topic that
   already exists is left as it is.
2. adds the ticker, and the group, to `bridge.toml`.

A group is a bridge idea only. Each ticker keeps its own HoundDog topic, so an
article about Nvidia never counts as news for Apple; the group's row pools its
members' sessions. Load each new ticker's prices in ThetaDesk too.

Choose **Watch and load price history** to request daily bars for each
successfully watched ticker. Bridge shows the topic outcome in the watch
form and the price outcome on the ticker card. Failed topic entries stay
selected for retry. If only prices failed, use the watchlist's price action.

**Price loading.** A first load requests about a year through the latest
closed NYSE session. An update starts after the last saved close, within
that rolling year. ThetaDesk fills gaps in its cached lookup dates. Use
**Retry missing bars** to recheck the range with the provider after a
successful lookup left a bar missing. Wait for an end-of-day bar to be
available if the market has just closed. Bridge refreshes its study from
the exports after a price request, including when the request reports an
error after saving partial progress.

**Inspect a session.** Pick a news marker, a segment of the coverage strip, or
a date in **Inspect a session** to see the close, return, volume, and assigned
articles. The date range controls filter the chart and ticker detail. The
main study summary still shows the full available sample.

**Pinned ranges.** Use **Pin this range** to save the active ticker and
dates in ThetaDesk. Opening a shared pin restores its range, reads the
stored closes through ThetaDesk, and shows matching news from Bridge's
exports. It also works for pins outside the Bridge watchlist. In that case
Bridge uses the topic named after the ticker if it has exported matches.
Refresh either dashboard to see pins added in the other.

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

Real data takes weeks to build up: a session only counts once HoundDog has
watched its ticker's topic. To see the dashboard working now:

```powershell
python bridge\make_demo.py
python bridge\server.py --config bridge\demo\demo.toml --port 8091
```

`make_demo.py` writes `bridge\demo\` (rewritten each run, not kept in git):

- a year of made-up news and HoundDog checks around your real ThetaDesk prices
  for AAPL, MSFT and TSLA (`--symbols` for others; their prices must be
  loaded in ThetaDesk);
- `demo.toml`, which disables the HoundDog and ThetaDesk API connections and
  shows a "demo data" banner.

Every demo headline starts with `[DEMO]`. The demo includes each case the study
handles:

- news and quiet sessions;
- two weeks with HoundDog "off" (not watched);
- weekend and after-close articles moving to the next session;
- backfill that is left out;
- one article detected twice that counts once.

The demo news is planted: the bigger a session's real move, the likelier it
gets an article. So the demo shows what an effect looks like on the dashboard;
it says nothing about the market. `--seed` picks a different (repeatable) demo.

## Command line

From the `theta_hound` folder:

```powershell
python bridge\bridge.py status    # what each export folder holds
python bridge\bridge.py report    # the study, per symbol
```

Add `--json` to either command for machine-readable output (for a dashboard or
another program), and `--config PATH` to use another settings file.

## Settings: `bridge.toml`

- `[inputs]`:
  - `hounddog_exports` defaults to `../HoundDog/exports`;
  - `thetadesk_exports`, left empty, means ThetaDesk's own store,
    `%LOCALAPPDATA%\ThetaDesk\exports`.

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

The dashboard's **Ticker detail** shows the session counts, the label and
reason for each session in ThetaDesk's recorded lookup ranges, and each
article detection for the ticker's topics. It shows where eligible news lands
and why backfill, repeat detections, and articles without a usable return
are excluded. Detection times in this table use New York time. The same
details are available from `python bridge.py report --json`.

- **Session move** compares the session's close with the previous session's
  close. Detections from the previous close through the moment before this
  close belong to this session. Sessions follow the NYSE calendar, including
  holidays and 13:00 early closes.
- **Group:** its members' sessions pooled; each member's volume is compared
  with that member's own median.
- **News session:** at least one live article matched one of the symbol's
  topics. An article counts once, at its first detection. Backfill (articles
  found when a feed or topic was first read) is left out, because those
  articles may be old.
- **Quiet session:** no such article, while HoundDog was watching. That means
  at least one check that read a feed and listed one of the symbol's topics
  started after the previous close and at or before this close. Sessions HoundDog did not
  watch (PC off, topic not created yet) are left out and counted as "not
  watched", because finding no news there means nothing.
- **avg |move|:** the average size of the move, up or down.
- **volume:** session volume as a multiple of the symbol's median volume.
- **Missing bars:** trading days inside ThetaDesk's looked-up ranges that have
  no bar. They are gaps, not moves.

## Limits

- Daily bars only (ThetaData's free tier), so the study cannot show how fast,
  or in which direction within a day, a ticker reacted.
- A session counts as watched after a single check in its window; with an
  hourly background job, that is nearly always true while the PC is on.
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
