"""Service layer for the option chain and futures tools: flow selection and ValueError -> InputError."""

from __future__ import annotations

import pytest

from iran_bourse_mcp.service import Bourse, InputError


class DerivativesApi:
    def __init__(self, fx):
        self.options, self.futures, self.flows = fx("derivatives_option_watch"), fx("derivatives_future_watch"), []

    async def option_market_watch(self, flow=0):
        self.flows.append(flow)
        return self.options

    async def future_market_watch(self):
        return self.futures


@pytest.fixture()
def bourse(fx):
    b = Bourse()
    b.api = DerivativesApi(fx)
    return b


async def test_option_chain_reads_the_requested_market_and_shapes_the_chain(bourse):
    result = await bourse.option_chain("اهرم", market="bourse")
    assert bourse.api.flows == [1] and result["market"] == "bourse"
    assert result["groups"][0]["expiry"] == "2026-11-18"
    await bourse.option_chain()
    await bourse.option_chain(market="fara")
    assert bourse.api.flows == [1, 0, 2]


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"option_type": "straddle"}, "option_type"),
        ({"market": "mars"}, "market must be"),
        ({"underlying": "فولاد"}, "No underlying with listed options"),
        ({"underlying": "اهرم", "expiry": "2026-11-19"}, "has no option expiring"),
    ],
)
async def test_option_chain_input_errors(bourse, kwargs, message):
    with pytest.raises(InputError, match=message):
        await bourse.option_chain(**kwargs)


async def test_futures_market(bourse):
    result = await bourse.futures_market("اهرم", sort_by="open_interest", limit=2)
    assert [c["symbol"] for c in result["contracts"]] == ["جهرم0508", "جهرم0509"]
    with pytest.raises(InputError, match="No futures contract matches"):
        await bourse.futures_market("فولاد")
