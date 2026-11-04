# Tests

```bash
uv run pytest                  # everything, offline
uv run pytest tests/contract   # only the contract tests
```

Two kinds of test live here:

- **Unit and wiring tests** (`tests/test_*.py`): the pure logic in `shape.py` and friends, and the service orchestration, on small synthetic or hand-trimmed payloads (`tests/fixtures/*.json`, refreshed with `scripts/capture_fixtures.py`).
- **Contract tests** (`tests/contract/`): every MCP tool called the way a client calls it, on **recorded real responses** of the exchange, with no network.

## How the contract tests work

A *scenario* is one tool call (`tests/contract/contract_scenarios_*.py`):

```python
@scenario("quote", "quote", symbol="فولاد")
def _quote(run):
    closing = run.rec.body("GetClosingPriceInfo")["closingPriceInfo"]
    assert run.out["close"]["price"] == closing["pClosing"]
```

For each scenario the test:

1. loads its recordings from `tests/fixtures/recorded/` and serves them through a [respx](https://lundberg.github.io/respx/) router, matched on method + host + path + query (and, for the POSTs of the IME's services, the JSON body, whatever its key order). A request without a recording **fails the test and names its URL**; a recording the tool no longer asks for is reported as stale;
2. freezes `tehran_now()` at the Tehran time the scenario was recorded (every module that imported it is patched), so "today" is the recorded day and results do not depend on when the test runs;
3. calls the tool through the MCP server object in memory (`mcp.call_tool`: argument validation, error mapping, JSON result) on top of the real `service`, `api` and `client` code. It works on MCP SDK 1.x and 2.x;
4. runs the scenario's checks: the **exact set of keys** of the result, units and labels, and values compared with the recorded upstream payload they were computed from (`run.rec.body(...)` gives the raw payload), so a changed shaper, a renamed field or a different unit fails. Checks never hard-code a market value; they read it from the recording, except for fixed past days (history does not change), where exact numbers are pinned.

`test_contract_meta.py` fails when a registered tool has no scenario (and says which), when a scenario has no recording, and when the recordings are not lean and clean (size budget, nothing but status, content type and body stored).

### What is on disk

```
tests/fixtures/recorded/
  requests/<host>__<path>-<hash>.json   one upstream request and its response (compact JSON, shared by scenarios)
                                        (a request that sends a JSON body keeps it under "request"."body" and the hash covers it)
  scenarios/<id>.json                   the requests a scenario needs and the Tehran time it was recorded at
```

Responses are **trimmed** so the whole directory stays around 2.5 MB (budget 6 MB): whole-market feeds keep one fixed set of about 150 instruments (the busiest of each type, limit-locked ones so queues exist, and the symbols the scenarios use), long histories keep their newest rows, huge arrays are cut. Every field of every kept row is kept, and what was cut is written into the file (`"trimmed"`). So a market-wide count in a test (for example `total_instruments`) is the size of the recorded set, not of the market.

## Adding a tool

Register the tool as usual, then add a scenario and record it:

```bash
uv run python scripts/record_contract.py --record --only <scenario id>
uv run python scripts/record_contract.py --show <scenario id>    # print the recorded result while you write the checks
```

Until then `test_every_registered_tool_has_a_contract_scenario` fails and lists the tool.

## Re-recording

Needs a connection that reaches TSETMC (see the README), the IME (`www.ime.co.ir`) and the Iran Energy Exchange (`webapi.iee.ir`) and, for Codal, patience.

```bash
uv run python scripts/record_contract.py                 # list scenarios and when each was recorded (offline)
uv run python scripts/record_contract.py --record        # record all of them, then verify each by replay
```

The recorder is deliberately slow and sequential: one request at a time, 0.5 s between requests (6 s for Codal, which answers HTTP 429 to a shared IP quickly, so it goes last), a wait of 30 to 240 s before retrying a 429, and failed scenarios are retried in up to three rounds 90 s apart (`--delay`, `--codal-delay`, `--rounds`, `--pause`). It stores only status, content type and body (no request headers, cookies or tokens), refuses a response that is still large after trimming (add a rule to `RULES` in the script) and prunes recordings no scenario uses. Use `--proxy` or `IRAN_BOURSE_PROXY` for an in-Iran proxy.

After a re-recording, run `uv run pytest tests/contract`. A failure that says a key is missing or a value is `None` means the **upstream format changed**: that is what the suite is for. Re-record everything (not just `--only`) for a consistent snapshot, because scenarios share their requests. Check `git diff --stat tests/fixtures/recorded` before committing.
