"""Small helpers shared by the contract scenarios' checks (plain asserts, no pytest: the recorder runs them too)."""

from __future__ import annotations

import datetime as dt
import re

from iran_bourse_mcp.text import clean

__all__ = [
    "assert_keys",
    "by_symbol",
    "clean",
    "descending",
    "hms",
    "in_session",
    "is_jdate",
    "iso",
    "one",
    "pct",
    "pick",
]


def assert_keys(obj: dict, names: str, where: str = "result") -> None:
    """The mapping has exactly these keys: a renamed, dropped or added field is a change of the tool's contract."""
    want = set(names.split())
    assert set(obj) == want, (
        f"{where}: unexpected keys {sorted(set(obj) - want)}, missing keys {sorted(want - set(obj))}"
    )


def pct(new: float, base: float) -> float:
    return round((new - base) / base * 100, 2)


def hms(heven: int) -> str:
    """The exchange's HHMMSS integer as HH:MM:SS."""
    text = f"{int(heven):06d}"
    return f"{text[:2]}:{text[2:4]}:{text[4:]}"


def iso(deven: int | str) -> str:
    """The exchange's YYYYMMDD as YYYY-MM-DD."""
    text = str(int(deven))
    return f"{text[:4]}-{text[4:6]}-{text[6:]}"


def in_session(now: dt.datetime) -> bool:
    """Tehran trading hours: Saturday to Wednesday, 09:00 to 12:30 (public holidays are not modelled)."""
    return now.weekday() in (5, 6, 0, 1, 2) and dt.time(9, 0) <= now.time() <= dt.time(12, 30)


def is_jdate(text: str) -> bool:
    return re.fullmatch(r"14\d\d/(0[1-9]|1[0-2])/(0[1-9]|[12]\d|3[01])", text) is not None


def one(rows: list, test, what: str = "row"):
    """The only element that passes ``test`` (more or fewer is a failure)."""
    found = [row for row in rows if test(row)]
    assert len(found) == 1, f"expected one {what}, found {len(found)}"
    return found[0]


def pick(rows: list, key, value, what: str = "row"):
    """The only element whose ``key(element)`` equals ``value`` (``value`` is bound here, so it is safe to pass from a loop)."""
    return one(rows, lambda row: key(row) == value, what)


def descending(values) -> bool:
    values = list(values)
    return values == sorted(values, reverse=True)


def by_symbol(rows: list[dict], symbol: str, field: str = "lva") -> dict:
    """The raw row whose symbol, normalised the way the server does, is ``symbol``."""
    return one(rows, lambda row: clean(row[field]) == symbol, f"row for {symbol}")
