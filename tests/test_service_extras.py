"""Service wiring of the lists, calendar, status, index and fund tools against recorded exchange payloads."""

from __future__ import annotations

import pytest
from conftest import load

from iran_bourse_mcp.client import NotAvailable
from iran_bourse_mcp.service import Bourse, InputError


class ExtrasApi:
    """Answers each endpoint with the payload recorded live on 2026-11-04 (ordered like the TseApi methods)."""

    def __init__(self):
        self.calls: list[tuple] = []

    # lists -------------------------------------------------------------------------------
    async def trade_top(self, kind, flow, top):
        self.calls.append(("trade_top", kind, flow, top))
        if kind == "BlockOTC" and flow == 2:
            raise NotAvailable("HTTP 500")
        return load("toplists_trade_block" if kind.startswith("Block") else "toplists_trade_gainers")["tradeTop"]

    async def best_limits_top(self, kind, flow, top):
        self.calls.append(("best_limits_top", kind, flow, top))
        return load("toplists_limits_buy")["bestLimitsTop"]

    async def market_cap_top(self, kind, flow, top):
        self.calls.append(("market_cap_top", kind, flow, top))
        return load("toplists_cap_top")["marketCap"]

    async def sector_top(self, top=0):
        self.calls.append(("sector_top", top))
        return load("toplists_sectors")["sectorTop"]

    # calendar -------------------------------------------------------------------------------
    async def share_changes_by_flow(self, flow):
        self.calls.append(("share_changes_by_flow", flow))
        return load({1: "calendar_share_changes", 2: "calendar_share_changes_fara", 4: "calendar_share_changes_base"}[flow])["instrumentShareChange"]

    async def price_adjust_by_flow(self, flow, top):
        self.calls.append(("price_adjust_by_flow", flow, top))
        return load("calendar_price_adjust" if flow == 1 else "calendar_price_adjust_fara")["priceAdjust"]

    # status -------------------------------------------------------------------------------
    async def supervision_list(self, source, list_type):
        self.calls.append(("supervision_list", source, list_type))
        return load(f"status_supervision_{source}_{list_type}")["supervision"]

    async def supervision_for(self, ins):
        return load("status_supervision_record")["supervision"] if isinstance(load("status_supervision_record")["supervision"], dict) else {}

    async def state_log(self, n):
        self.calls.append(("state_log", n))
        return load("status_state_top")["instrumentState"]

    async def state_history(self, ins):
        return load("status_state_all")["instrumentState"]

    # indices -------------------------------------------------------------------------------
    async def indices(self, flow):
        return load(f"indices_list_flow{flow}")["indexB1"]

    async def index_history(self, ins):
        self.calls.append(("index_history", ins))
        return load("indices_history_total")["indexB2"]

    async def index_intraday(self, ins):
        return load("indices_intraday_total")["indexB1"]

    async def index_members(self, ins):
        return load("indices_constituents_total")["indexCompany"]

    async def index_effects(self, deven, flow, top=9999):
        return load("indices_effects_total")["instEffect"]

    # funds -------------------------------------------------------------------------------
    async def funds(self, fund_type):
        self.calls.append(("funds", fund_type))
        return load("funds_registry_sample").get(str(fund_type), {}).get("funds", [])

    # shared -------------------------------------------------------------------------------
    async def market_watch_all(self):
        raise NotAvailable("not needed here")

    async def market_watch(self):
        return []

    async def search(self, query):
        return load("search_folad")

    async def instrument_info(self, ins):
        return load("info")


@pytest.fixture()
def bourse():
    b = Bourse()
    b.api = ExtrasApi()
    b.resolver._api = b.api
    return b


# ------------------------------------------------------------------------------- top_lists


async def test_top_lists_catalogue_and_each_family_hit_the_right_endpoint(bourse):
    assert (await bourse.top_lists())["count"] >= 60
    assert (await bourse.top_lists("catalogue", 2))["count"] > 0
    gainers = await bourse.top_lists("price_gainers", 1, 3)
    assert gainers["rows"][0]["rank"] == 1 and bourse.api.calls[-1][0] == "trade_top"
    await bourse.top_lists("largest_bids", 1, 3)
    assert bourse.api.calls[-1][0] == "best_limits_top"
    await bourse.top_lists("market_cap_gainers", 1, 3)
    assert bourse.api.calls[-1][0] == "market_cap_top"
    sectors = await bourse.top_lists("sectors_by_value", None, 3)
    assert bourse.api.calls[-1][0] == "sector_top" and sectors["rows"][0]["rank"] == 1


async def test_top_lists_errors_are_actionable(bourse):
    with pytest.raises(InputError, match="catalogue"):
        await bourse.top_lists("no_such_list")
    with pytest.raises(InputError, match="does not serve"):
        await bourse.top_lists("block_trades", 2, 5)  # the exchange answers HTTP 500 for this flow


# ---------------------------------------------------------------------------- capital_calendar


async def test_capital_calendar_reads_each_requested_market(bourse):
    out = await bourse.capital_calendar(1, "all", 30, 10, "all", today="2026-11-04")
    assert out["count"] >= 1 and ("share_changes_by_flow", 1) in bourse.api.calls
    await bourse.capital_calendar("all", "recent", 30, 5, "capital_increase", today="2026-11-04")
    assert {c for c in bourse.api.calls if c[0] == "share_changes_by_flow"} >= {("share_changes_by_flow", 1), ("share_changes_by_flow", 2), ("share_changes_by_flow", 4)}
    bourse.api.calls.clear()
    await bourse.capital_calendar(1, "upcoming", 30, 5, "capital_increase", today="2026-11-04")
    assert not any(c[0] == "price_adjust_by_flow" for c in bourse.api.calls)  # the adjustments are not needed for upcoming increases


async def test_capital_calendar_rejects_bad_arguments(bourse):
    for kwargs in ({"direction": "sideways"}, {"kind": "dividends"}, {"flow": "mars"}, {"today": "yesterday-ish"}):
        with pytest.raises(InputError):
            await bourse.capital_calendar(**kwargs)


# ----------------------------------------------------------------------------- trading_status


async def test_trading_status_lists_logs_and_one_symbols_history(bourse):
    suspended = await bourse.trading_status("suspended", None, None, 5)
    assert suspended["kind"] == "suspended" and suspended["total"] > 0
    assert ("supervision_list", 1, 3) in bourse.api.calls and ("supervision_list", 2, 3) in bourse.api.calls
    log = await bourse.trading_status("state_changes", None, None, 5)
    assert log["count"] <= 5 and ("state_log", 200) in bourse.api.calls
    history = await bourse.trading_status("symbol_history", None, "فولاد", 5)
    assert history["instrument"]["symbol"] == "فولاد"
    with pytest.raises(InputError, match="symbol is required"):
        await bourse.trading_status("symbol_history")
    with pytest.raises(InputError, match="kind must be"):
        await bourse.trading_status("halted")


# --------------------------------------------------------------------------------- indices


async def test_index_history_resolves_names_and_reads_the_right_series(bourse):
    out = await bourse.index_history("شاخص کل", "2025-03-01", "2025-03-31", 30)  # the recorded series covers 2025-02-02 .. 2025-05-11
    assert out["index"]["name"] == "شاخص کل" and 0 < out["rows_in_range"] < 62 and bourse.api.calls[-1][0] == "index_history"
    assert out["rows"][0]["date"] >= "2025-03-01" and out["rows"][-1]["date"] <= "2025-03-31"
    today = await bourse.index_history("شاخص کل", intraday=True)
    assert today["rows"] and "time" in today["rows"][0]
    for kwargs in ({"index": "شاخص ناموجود"}, {"index": "شاخص کل", "granularity": "hourly"}, {"index": "شاخص کل", "from_date": "نامعتبر"}):
        with pytest.raises(InputError):
            await bourse.index_history(**kwargs)


async def test_index_constituents_sorts_by_effect_and_validates(bourse):
    out = await bourse.index_constituents("شاخص کل", "value", True, 5)
    assert out["returned"] == 5 and out["totals"]["members"] >= 10
    values = [r["value"] for r in out["rows"] if r["value"] is not None]
    assert values == sorted(values, reverse=True)
    with pytest.raises(InputError):
        await bourse.index_constituents("شاخص کل", "bogus", True, 5)


# ------------------------------------------------------------------------------------ funds


async def test_fund_ranking_reads_only_the_requested_types(bourse):
    out = await bourse.fund_ranking("fixed_income", "net_assets", True, None, 3)
    assert out["returned"] <= 3 and bourse.api.calls == [("funds", 4)]
    bourse.api.calls.clear()
    everything = await bourse.fund_ranking(None, "return_1y", True, 1e9, 5)
    assert {c[1] for c in bourse.api.calls} >= {4, 6, 11} and everything["universe"]["funds"] > 10
    for kwargs in ({"fund_type": "nonsense"}, {"sort_by": "bogus"}):
        with pytest.raises(InputError):
            await bourse.fund_ranking(**kwargs)
