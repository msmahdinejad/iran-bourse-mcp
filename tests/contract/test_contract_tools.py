"""Contract tests: every tool, end to end, on recorded real upstream responses (no network).

Each scenario calls the tool through the MCP server object, on top of the real service, api and client code, with
the exchange's answers served from tests/fixtures/recorded by respx and the clock frozen at the recording time.
A request without a recording fails the test and names its URL. See tests/README.md.
"""

from __future__ import annotations

import pytest
from contract_replay import load_scenarios, replay_scenario

SCENARIOS = load_scenarios()


@pytest.mark.parametrize("sc", SCENARIOS.values(), ids=list(SCENARIOS))
async def test_tool_contract(sc):
    run = await replay_scenario(sc)
    assert not run.replay.unmatched, f"{sc.id}: requests with no recording: {run.replay.unmatched}"
    assert not run.replay.unused(), (
        f"{sc.id}: recordings the tool no longer requests (stale, re-record with "
        f"scripts/record_contract.py --record --only {sc.id}): {run.replay.unused()}"
    )
    sc.check(run)
