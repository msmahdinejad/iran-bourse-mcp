"""Record small, trimmed real responses into tests/fixtures (run from a machine that reaches TSETMC).

    uv run python scripts/capture_fixtures.py

The contract tests (every tool, end to end, offline) have their own recordings: scripts/record_contract.py.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from iran_bourse_mcp.service import Bourse

OUT = Path(__file__).resolve().parent.parent / "tests" / "fixtures"


def dump(name: str, data: object) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print("wrote", name)


async def main() -> None:
    b = Bourse()
    inst = await b.resolver.resolve("فولاد")
    ins = inst.ins_code
    deven = int((await b.api.closing_info(ins))["dEven"])
    prev = int((await b.api.daily_prices(ins))[1]["dEven"])

    dump("info", await b.api.instrument_info(ins))
    dump("closing_info", await b.api.closing_info(ins))
    dump("best_limits", await b.api.best_limits(ins))
    history = await b.api.best_limits_history(ins, prev)
    refs = sorted({r["refID"] for r in history})[:12]
    dump("best_limits_history_head", [r for r in history if r["refID"] in refs])
    trades = await b.api.trades_history(ins, prev)
    dump("trades_head", trades[:60])
    dump("client_type", await b.api.client_type(ins))
    dump("client_type_history", await b.api.client_type_history(ins, prev))
    daily = await b.api.daily_prices(ins)
    # Window around the 2026-03-30 capital increase (1500bn -> 1935bn shares)
    dump("daily_prices_capital_increase", [r for r in daily if 20260325 <= r["dEven"] <= 20260406])
    dump("shareholders_last", await b.api.shareholders_last(ins))
    watch = await b.api.market_watch()
    dump("market_watch_sample", [r for r in watch if r.get("instrumentName") in ("فولاد", "آباد")] or watch[:2])
    letters = await b.api.codal_search(Symbol="فولاد")
    dump("codal_letters", {"Total": letters.get("Total"), "Letters": letters.get("Letters", [])[:2]})
    dump("search_folad", (await b.api.search("فولاد"))[:6])
    print("quote date", deven, "history date", prev)
    await b.aclose()


if __name__ == "__main__":
    asyncio.run(main())
