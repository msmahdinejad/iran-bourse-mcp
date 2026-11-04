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
│ shape.py       │  PURE functions: raw payload -> clean dict. All maths lives here
│                │  (queues, book reconstruction, tick aggregation, adjustment, flows).
├────────────────┤
│ clients.py     │  Install recipes for 17 agents (snippets, deep links, safe config merge).
│ cli.py         │  serve | doctor | tools | call | config | install.
│ resolver.py    │  symbol / name / insCode -> Instrument (normalised matching).
│ api.py         │  One method per upstream endpoint; returns raw payloads, sets cache TTLs.
│ client.py      │  httpx wrapper: browser UA, retries (403/429/5xx), TTL+LRU cache, 6-way limit.
│ dates.py text.py glossary.py
└────────────────┘
```

Design rules:

1. **Pure core.** `shape.py` has no I/O, so every number can be tested offline against recorded fixtures (`tests/fixtures`, captured by `scripts/capture_fixtures.py`).
2. **Facts vs inference.** Exchange-published values are returned as-is (after unit/field fixes). Anything derived is named `*estimate*`/`*estimated*` or documented in the field's note.
3. **Token-aware.** Large series are summarised by default (`trade_summary`, `order_book_history` samples). Raw access exists but is capped and filterable.
4. **Fail loudly and helpfully.** Unknown symbol? The error lists close matches. Foreign IP? The error says so and names `IRAN_BOURSE_PROXY`. Endpoint not applicable (HTTP 500 for a stock on a fund endpoint)? A clear "not available for this instrument" instead of a stack trace.
5. **Read-only forever.** No tool places, changes or cancels anything and none handles credentials.
6. **Both MCP SDK generations.** `server.py` imports `MCPServer` (SDK 2.x) or `FastMCP` (1.x); CI tests both.

Adding a tool: add the endpoint to `api.py`, the transformation to `shape.py` with a test, the orchestration to `service.py`, the registration (with a rich docstring, it is the prompt the model sees) to `server.py`, then run `scripts/gen_tools_doc.py`.
