"""The contract suite covers every registered tool, and the recordings on disk are complete, lean and clean."""

from __future__ import annotations

import json
import re
from pathlib import Path

from contract_replay import (
    HOSTS,
    MANIFESTS,
    RECORDED,
    REQUEST_KEYS,
    REQUESTS,
    RESPONSE_KEYS,
    Recorded,
    load_scenarios,
)

from iran_bourse_mcp.server import mcp

BUDGET_BYTES = 6 * 1024 * 1024  # all recordings together
FILE_LIMIT_BYTES = 900 * 1024  # the pre-commit large-file hook
SOURCE = Path(__file__).resolve().parents[2] / "src" / "iran_bourse_mcp"


async def test_every_registered_tool_has_a_contract_scenario():
    registered = {tool.name for tool in await mcp.list_tools()}
    covered = {sc.tool for sc in load_scenarios().values()}
    missing = sorted(registered - covered)
    assert not missing, (
        f"tools without a contract scenario: {missing}. Add one with @scenario(...) in "
        "tests/contract/contract_scenarios_*.py, then record it: "
        "python scripts/record_contract.py --record --only <scenario id>  (see tests/README.md)"
    )
    stale = sorted(covered - registered)
    assert not stale, f"scenarios for tools that no longer exist: {stale}"


def test_every_scenario_is_recorded_and_nothing_else_is():
    scenarios = set(load_scenarios())
    on_disk = {path.stem for path in MANIFESTS.glob("*.json")}
    unrecorded = sorted(scenarios - on_disk)
    assert not unrecorded, (
        f"scenarios without a recording: {unrecorded} (python scripts/record_contract.py --record)"
    )
    leftovers = sorted(on_disk - scenarios)
    assert not leftovers, f"recordings of scenarios that no longer exist: {leftovers}"

    wanted = {
        rid
        for sid in scenarios
        for rid in json.loads((MANIFESTS / f"{sid}.json").read_text(encoding="utf-8"))["requests"]
    }
    present = {path.stem for path in REQUESTS.glob("*.json")}
    assert wanted <= present, f"manifests name missing request files: {sorted(wanted - present)}"
    assert present <= wanted, (
        f"request files no scenario uses (scripts/record_contract.py --record prunes them): "
        f"{sorted(present - wanted)}"
    )


def test_recordings_keep_only_status_content_type_and_body():
    for path in REQUESTS.glob("*.json"):
        doc = json.loads(path.read_text(encoding="utf-8"))
        assert set(doc) == {"request", "response", "trimmed"}, path.name
        request = doc["request"]
        assert {"method", "url"} <= set(request) <= REQUEST_KEYS, path.name  # no request headers
        assert "body" not in request or request["method"] == "POST", f"{path.name}: body on a GET"
        # no cookies, tokens or other response headers
        assert set(doc["response"]) <= RESPONSE_KEYS, path.name
        assert request["url"].split("/")[2] in HOSTS, f"{path.name}: unexpected host"


def test_every_recording_is_stored_under_the_name_of_its_request():
    """The file name is a hash of method, URL and request body: a changed identity rule would orphan old recordings."""
    for path in REQUESTS.glob("*.json"):
        assert Recorded.from_file(path.read_text(encoding="utf-8")).id == path.stem, path.name


def test_recordings_stay_within_the_size_budget():
    sizes = {path.name: path.stat().st_size for path in RECORDED.rglob("*.json")}
    too_big = {name: size for name, size in sizes.items() if size > FILE_LIMIT_BYTES}
    assert not too_big, f"recordings over {FILE_LIMIT_BYTES // 1024} KB: {too_big}"
    total = sum(sizes.values())
    assert total <= BUDGET_BYTES, (
        f"recordings take {total / 1024 / 1024:.1f} MB, the budget is {BUDGET_BYTES // 1024 // 1024} MB"
    )


def test_the_real_clock_is_read_in_the_known_places_only():
    """Replays freeze tehran_now(). A new direct read of the clock would make results depend on when the test runs."""
    reads_the_clock = re.compile(r"datetime\.now\(|date\.today\(|utcnow\(|time\.time\(")
    found = sorted(
        path.name
        for path in SOURCE.glob("*.py")
        if reads_the_clock.search(path.read_text(encoding="utf-8"))
    )
    # dates.py is tehran_now() itself; clients.py stamps config backups; service.utc_now() is an unused helper
    assert found == ["clients.py", "dates.py", "service.py"], (
        f"files that read the real clock: {found}. Use dates.tehran_now() so the contract tests can freeze it."
    )
