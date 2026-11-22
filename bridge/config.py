"""bridge.toml: where the exports are, where HoundDog runs, and what to study.

The dashboard rewrites the file in a fixed layout when it adds tickers, the
way HoundDog's dashboard rewrites watch.toml; hand edits keep working.
"""

from __future__ import annotations

import json
import os
import re
import threading
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from study import StudySymbol, SymbolGroup

DEFAULT_CONFIG = Path(__file__).resolve().with_name("bridge.toml")
DEFAULT_HOUNDDOG_URL = "http://127.0.0.1:8080"
SYMBOL_PATTERN = re.compile(r"^[A-Z0-9.^_-]{1,16}$")
HEADER = """# theta_hound bridge settings. Paths are relative to this file.
# The bridge dashboard rewrites this file when it adds tickers or groups.
#
# [inputs] thetadesk_exports empty: ThetaDesk's store, %LOCALAPPDATA%\\ThetaDesk\\exports
# [[symbols]]: a ticker and the HoundDog topics that count as news about it.
# [[groups]]: a named set of tickers, studied together.
# [hounddog] url = "" turns off the HoundDog connection (watching tickers).
# [display] banner: a line shown across the top of the dashboard.
"""
CONFIG_LOCK = threading.Lock()


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class BridgeConfig:
    hounddog_exports: Path
    thetadesk_exports: Path
    hounddog_url: str  # "" when this config has no HoundDog connection
    symbols: tuple[StudySymbol, ...]
    groups: tuple[SymbolGroup, ...]
    banner: str

    @classmethod
    def load(cls, path: Path) -> BridgeConfig:
        return cls.from_raw(path, read_raw(path))

    @classmethod
    def from_raw(cls, path: Path, raw: dict[str, Any]) -> BridgeConfig:
        inputs = raw.get("inputs", {})
        symbols = []
        for entry in raw.get("symbols", []):
            symbol = normalize_symbol(entry.get("symbol", ""), path)
            topics = tuple(str(topic) for topic in entry.get("topics", [symbol]))
            if not topics:
                raise ConfigError(f"{path}: {symbol} needs at least one HoundDog topic")
            if any(known.symbol == symbol for known in symbols):
                raise ConfigError(f"{path}: {symbol} is listed twice in [[symbols]]; keep one entry")
            symbols.append(StudySymbol(symbol, topics))
        groups = []
        for entry in raw.get("groups", []):
            name = str(entry.get("name", "")).strip()
            if not name:
                raise ConfigError(f"{path}: every [[groups]] entry needs a name")
            members = (normalize_symbol(symbol, path) for symbol in entry.get("symbols", []))
            groups.append(SymbolGroup(name, tuple(dict.fromkeys(members))))
        thetadesk = inputs.get("thetadesk_exports", "")
        return cls(
            hounddog_exports=folder(path, inputs.get("hounddog_exports", "../HoundDog/exports")),
            thetadesk_exports=folder(path, thetadesk) if thetadesk else default_thetadesk_exports(),
            hounddog_url=str(raw.get("hounddog", {}).get("url", DEFAULT_HOUNDDOG_URL)).rstrip("/"),
            symbols=tuple(symbols),
            groups=tuple(groups),
            banner=str(raw.get("display", {}).get("banner", "")).strip(),
        )


def normalize_symbol(value: Any, path: Path | None = None) -> str:
    symbol = str(value).strip().upper()
    if not SYMBOL_PATTERN.match(symbol):
        where = f"{path}: " if path else ""
        raise ConfigError(f"{where}{value!r} is not a ticker symbol")
    return symbol


def folder(config_path: Path, value: str) -> Path:
    path = Path(os.path.expandvars(value))
    return path if path.is_absolute() else (config_path.parent / path).resolve()


def default_thetadesk_exports() -> Path:
    """Where both ThetaDesk entry points keep their store (market_store.default_data_directory)."""
    local_app_data = os.getenv("LOCALAPPDATA")
    home = Path(local_app_data) / "ThetaDesk" if local_app_data else Path.home() / ".thetadesk"
    return home / "exports"


def read_raw(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except FileNotFoundError as error:
        raise ConfigError(f"config not found: {path}") from error
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"{path}: {error}") from error


TABLE_ORDER = ("inputs", "hounddog", "display", "symbols", "groups")


def toml_value(value: Any) -> str:
    # A JSON string is a valid TOML basic string: same quotes and escapes.
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, list):
        return "[" + ", ".join(toml_value(item) for item in value) + "]"
    raise ConfigError(f"cannot write {type(value).__name__} to bridge.toml")


def table_lines(header: str, table: dict[str, Any]) -> list[str]:
    return [header, *(f"{key} = {toml_value(value)}" for key, value in table.items()), ""]


def render_raw(raw: dict[str, Any]) -> str:
    """Known tables first, in a fixed order, then any others the user added.
    Values are strings, booleans, numbers, or lists of them; nested tables are
    not part of this file's layout and are refused rather than dropped."""
    lines = [HEADER]
    for name in [*TABLE_ORDER, *sorted(set(raw) - set(TABLE_ORDER))]:
        value = raw.get(name)
        if isinstance(value, dict):
            lines.extend(table_lines(f"[{name}]", value))
        elif isinstance(value, list) and all(isinstance(entry, dict) for entry in value):
            for entry in value:
                lines.extend(table_lines(f"[[{name}]]", entry))
        elif value is not None:
            raise ConfigError(f"bridge.toml: top-level {name!r} must be a table")
    return "\n".join(lines)


def write_raw(path: Path, raw: dict[str, Any]) -> None:
    """Replace bridge.toml whole, so a crash never leaves half a file."""
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(render_raw(raw), encoding="utf-8")
    os.replace(temporary, path)


def add_watched(path: Path, symbols: list[str], group: str | None) -> BridgeConfig:
    """Add tickers (studied against the HoundDog topic of the same name) and,
    optionally, a group of them, keeping everything already configured."""
    with CONFIG_LOCK:
        raw = read_raw(path)
        entries = raw.setdefault("symbols", [])
        known = {normalize_symbol(entry.get("symbol", "")) for entry in entries}
        for symbol in symbols:
            if symbol not in known:
                entries.append({"symbol": symbol, "topics": [symbol]})
                known.add(symbol)
        if group:
            groups = raw.setdefault("groups", [])
            existing = next((entry for entry in groups if str(entry.get("name", "")).strip() == group), None)
            if existing is None:
                groups.append({"name": group, "symbols": list(symbols)})
            else:
                members = [normalize_symbol(symbol) for symbol in existing.get("symbols", [])]
                existing["symbols"] = members + [symbol for symbol in symbols if symbol not in members]
        config = BridgeConfig.from_raw(path, raw)
        write_raw(path, raw)
        return config
