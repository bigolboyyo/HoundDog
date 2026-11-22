import argparse
import logging
import sys
from datetime import date
from typing import Sequence

from dotenv import load_dotenv

from theta_data import get_eod_stock_history

DEFAULT_SYMBOL = "AAPL"
DEFAULT_START_DATE = date(2024, 1, 1)
DEFAULT_END_DATE = date(2024, 1, 31)


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            f"invalid date {value!r}; expected YYYY-MM-DD"
        ) from error


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fetch ThetaData stock history.")
    parser.add_argument("--symbol", default=DEFAULT_SYMBOL, help="Stock ticker.")
    parser.add_argument(
        "--start-date",
        type=_parse_date,
        default=DEFAULT_START_DATE,
        metavar="YYYY-MM-DD",
    )
    parser.add_argument(
        "--end-date",
        type=_parse_date,
        default=DEFAULT_END_DATE,
        metavar="YYYY-MM-DD",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    args = _build_parser().parse_args(argv)

    try:
        history = get_eod_stock_history(
            args.symbol,
            args.start_date,
            args.end_date,
        )
    except (RuntimeError, ValueError) as error:
        logging.error("%s", error)
        return 1

    print(history)
    return 0


if __name__ == "__main__":
    sys.exit(main())
