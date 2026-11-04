"""Resolve user input (symbol, company name, insCode) into an :class:`Instrument`."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .api import TseApi
from .text import ascii_digits, clean, match_key

_INS_CODE = re.compile(r"^\d{12,20}$")

FLOW_NAMES = {
    0: "unknown",
    1: "bourse",
    2: "fara-bourse",
    3: "derivatives / options",
    4: "bonds / sukuk",
    5: "energy bourse",
    6: "commodity (IME)",
    7: "mixed",
}


class SymbolError(ValueError):
    """The symbol could not be resolved to exactly one instrument."""


@dataclass(frozen=True)
class Instrument:
    ins_code: str
    symbol: str
    name: str
    flow: int
    board: str | None = None
    isin: str | None = None

    def brief(self) -> dict:
        out = {
            "symbol": self.symbol,
            "name": self.name,
            "ins_code": self.ins_code,
            "market": FLOW_NAMES.get(self.flow, str(self.flow)),
        }
        if self.board:
            out["board"] = self.board
        return out


def _from_search_row(row: dict) -> Instrument:
    return Instrument(
        ins_code=str(row["insCode"]),
        symbol=clean(row.get("lVal18AFC")) or "",
        name=clean(row.get("lVal30")) or "",
        flow=int(row.get("flow") or 0),
        board=clean(row.get("cgrValCotTitle")) or None,
    )


class Resolver:
    def __init__(self, api: TseApi) -> None:
        self._api = api
        self._cache: dict[str, Instrument] = {}

    async def resolve(self, ref: str) -> Instrument:
        ref = (ref or "").strip()
        if not ref:
            raise SymbolError("Empty symbol. Pass a Persian symbol like 'فولاد' or an insCode.")
        key = match_key(ref)
        if key in self._cache:
            return self._cache[key]

        if _INS_CODE.match(key):
            inst = await self._by_ins_code(key)
        else:
            inst = await self._by_symbol(ref)
        self._cache[key] = inst
        self._cache[match_key(inst.symbol)] = inst
        return inst

    async def _by_ins_code(self, ins: str) -> Instrument:
        info = await self._api.instrument_info(ins)
        if not info or not info.get("lVal18AFC"):
            raise SymbolError(f"No instrument found for insCode {ins}.")
        return Instrument(
            ins_code=ins,
            symbol=clean(info.get("lVal18AFC")) or "",
            name=clean(info.get("lVal30")) or "",
            flow=int(info.get("flow") or 0),
            board=clean(info.get("cgrValCotTitle")) or None,
            isin=info.get("cIsin"),
        )

    async def _by_symbol(self, ref: str) -> Instrument:
        rows = await self._api.search(ascii_digits(clean(ref) or ref))
        if not rows:
            raise SymbolError(f"No instrument matches {ref!r}.")
        key = match_key(ref)
        exact = [r for r in rows if match_key(r.get("lVal18AFC")) == key]
        if not exact:
            exact = [r for r in rows if match_key(r.get("lVal30")) == key]
        if len(exact) == 1:
            return _from_search_row(exact[0])
        if len(exact) > 1:
            # Same symbol on several boards: prefer the main equity markets (lowest flow id).
            exact.sort(key=lambda r: (int(r.get("flow") or 99), str(r.get("cgrValCot") or "")))
            return _from_search_row(exact[0])
        suggestions = ", ".join(
            f"{clean(r.get('lVal18AFC'))} ({clean(r.get('lVal30'))})" for r in rows[:8]
        )
        raise SymbolError(
            f"No exact symbol match for {ref!r}. Closest: {suggestions}. "
            "Retry with the exact symbol or use search_symbol."
        )
