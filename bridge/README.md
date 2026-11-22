# Bridge

Joins HoundDog's news export with ThetaDesk's market export and runs the first
daily study: do a ticker's sessions move more, or trade more, on days HoundDog
found news about it? Use it from the command line or its dashboard.

The bridge only reads the two apps' export folders. It never opens their
databases, and neither app needs to be running.

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

- what each app's export holds, and whether HoundDog is running;
- the study table, for each ticker and each group;
- a ticker's closing prices with its news sessions marked, and its live
  articles.

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

## Demo

Real data takes weeks to build up: a session only counts once HoundDog has
watched its ticker's topic. To see the dashboard working now:

```powershell
python bridge\make_demo.py
python bridge\server.py --config bridge\demo\demo.toml
```

`make_demo.py` writes `bridge\demo\` (rewritten each run, not kept in git):

- a year of made-up news and HoundDog checks around your real ThetaDesk prices
  for AAPL, MSFT and TSLA (`--symbols` for others; their prices must be
  loaded in ThetaDesk);
- `demo.toml`, which has no HoundDog connection, so the demo can never add
  topics to your real HoundDog, and shows a "demo data" banner.

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

The dashboard rewrites `bridge.toml` in this layout when it adds tickers. It
keeps every setting, including tables it does not use, but not comments you
add by hand. A ticker listed twice in `[[symbols]]` is an error; a ticker listed
twice in one group counts once.

## What the report means

- **Session move:** the session's close against the previous session's
  close. News from the previous close up to this close (overnight,
  pre-market, or during the session) belongs to this session. Sessions follow
  the NYSE calendar, including holidays and 13:00 early closes.
- **Group:** its members' sessions pooled; each member's volume is compared
  with that member's own median.
- **News session:** at least one live article matched one of the symbol's
  topics. An article counts once, at its first detection. Backfill (articles
  found when a feed or topic was first read) is left out, because those
  articles may be old.
- **Quiet session:** no such article, while HoundDog was watching. That means
  at least one check that read a feed and listed one of the symbol's topics
  ran between the previous close and this close. Sessions HoundDog did not
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
- Small samples: with fewer than 10 news sessions, the report says the
  difference cannot be told apart from chance. Expect weeks before it means
  anything.
- One-off market closures (such as days of mourning) are listed by hand in
  `market_calendar.py`.

## Tests

```powershell
cd bridge
python -m unittest discover -s tests
```
