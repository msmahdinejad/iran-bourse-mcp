# Architecture

```
MCP client (Claude, Cursor, ...)
        │  stdio / streamable-http
┌───────▼────────┐
│ server.py      │  FastMCP/MCPServer: 38 read-only tools, 4 prompts, 1 resource.
│                │  Expected errors become readable ToolErrors.
├────────────────┤
│ service.py     │  `Bourse`: one coroutine per tool. Orchestrates calls, joins sources,
│                │  validates input, decides defaults (latest trading day, session window).
├────────────────┤
│ shape.py and   │  PURE functions: raw payload -> clean dict. All maths lives here.
│ the pure       │  shape.py: quotes, queues, book reconstruction, ticks, adjustment, flows.
│ modules        │  market.py: market-watch rows and instrument classes. screener.py: the safe
│                │  filter language of `screen_stocks`. derivatives.py, indices.py, funds.py,
│                │  toplists.py, calendar_events.py, status.py: options and futures, indices,
│                │  funds, the exchange's best-of lists, capital-increase calendar, trading status.
├────────────────┤
│ clients.py     │  Install recipes for 17 agents (snippets, deep links, safe config merge).
│ cli.py         │  serve | doctor | tools | call | config | install.
│ resolver.py    │  symbol / name / insCode -> Instrument (normalised matching).
│ api.py         │  One method per upstream endpoint; returns raw payloads, sets cache TTLs.
│ client.py      │  httpx wrapper: browser UA, retries (403/429/5xx), 429 cooldown per host, TTL+LRU cache, 6-way limit.
│ dates.py text.py glossary.py   (dates.py also holds the public-holiday calendar)
└────────────────┘
```

Design rules:

1. **Pure core.** The shaping modules have no I/O, so every number can be tested offline against recorded fixtures (`tests/fixtures`, captured by `scripts/capture_fixtures.py`). On top of that, **contract tests** (`tests/contract`) call every tool through the MCP server on recorded real responses replayed with `respx`; see [tests/README.md](../tests/README.md).
2. **Facts vs inference.** Exchange-published values are returned as-is (after unit/field fixes). Anything derived is named `*estimate*`/`*estimated*` or documented in the field's note.
3. **Token-aware.** Large series are summarised by default (`trade_summary`, `order_book_history` samples). Raw access exists but is capped and filterable.
4. **Fail loudly and helpfully.** Unknown symbol? The error lists close matches. Foreign IP? The error says so and names `IRAN_BOURSE_PROXY`. Rate-limited? The error says so and for how long. Endpoint not applicable (HTTP 500 for a stock on a fund endpoint)? A clear "not available for this instrument" instead of a stack trace.
5. **Read-only forever.** No tool places, changes or cancels anything and none handles credentials.
6. **Both MCP SDK generations.** `server.py` imports `MCPServer` (SDK 2.x) or `FastMCP` (1.x); CI tests both.
7. **Never `eval`.** The screener parses a filter with Python's `ast`, checks it against a whitelist and compiles it to closures; it cannot import or call anything else, and its size and depth are limited.

Adding a tool: add the endpoint to `api.py`, the transformation to a pure module with a test, the orchestration to `service.py`, the registration (with a rich docstring, it is the prompt the model sees) to `server.py`, a contract scenario in `tests/contract` with its recording, then run `scripts/gen_tools_doc.py`.
