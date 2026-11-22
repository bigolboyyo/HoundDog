import argparse
import json
import sqlite3
import sys
from datetime import date
from pathlib import Path
from typing import Sequence

from dotenv import load_dotenv

from market_store import INTERVAL, fetch_daily_bars
from theta_data import get_dotenv_path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Store and export ThetaData daily stock bars.")
    parser.add_argument("--symbols", required=True, help="Comma-separated stock tickers.")
    parser.add_argument("--from", dest="start_date", type=date.fromisoformat, required=True)
    parser.add_argument("--to", dest="end_date", type=date.fromisoformat, required=True)
    parser.add_argument("--interval", choices=[INTERVAL], default=INTERVAL)
    parser.add_argument("--data-dir", type=Path, help="Folder for market.db and exports.")
    parser.add_argument("--refresh", action="store_true", help="Fetch the full range again to fill missing bars.")
    args = parser.parse_args(argv)
    symbols = [symbol.strip().upper() for symbol in args.symbols.split(",")]
    if not all(symbols):
        parser.error("--symbols must contain only nonempty tickers")

    load_dotenv(get_dotenv_path())
    failed = False
    for symbol in dict.fromkeys(symbols):
        try:
            result = fetch_daily_bars(
                symbol, args.start_date, args.end_date, data_dir=args.data_dir, refresh=args.refresh
            )
        except (OSError, RuntimeError, ValueError, sqlite3.Error) as error:
            # Keep going: one bad ticker should not skip the rest of a watchlist.
            print(f"{symbol}: {error}", file=sys.stderr)
            failed = True
            continue
        print(json.dumps({
            "symbol": result.symbol,
            "interval": result.interval,
            "start_date": result.start_date.isoformat(),
            "end_date": result.end_date.isoformat(),
            "covered_through": result.covered_through.isoformat() if result.covered_through else None,
            "bar_count": len(result.data),
            "added": result.added,
        }), flush=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
