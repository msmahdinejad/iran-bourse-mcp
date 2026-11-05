# Changelog

## Unreleased

- Install commands, snippets and one-click links now use PyPI (`uvx iran-bourse-mcp`) instead of the GitHub URL. `IRAN_BOURSE_SOURCE=git+https://github.com/msmahdinejad/iran-bourse-mcp` still selects the repository.

## 0.4.0 (2026-11-05)

Two exchange tools (40 in total), public holidays in `market_status`, contract tests for every tool, Persian technical notes and a package ready for PyPI.

### Added
- **Launch film** (2 minutes, Persian narration): on the website (`#film`) with a player, a 16:9 / 9:16 switch, English and Persian subtitles, downloads (web and social files on the site, Full HD and 4K as release assets of `launch-film`), share links, a ready-made post and an embeddable player (`embed.html`). Every number in it is real tool output.
- **Public holidays in `market_status`** (#7): `holiday`, `is_trading_day`, `day_status`, `next_session` (skips weekends and holidays and lists what it skipped), `upcoming_holidays` and a `holiday_calendar` block. The table is the official calendar of Jalali year 1405 (time.ir) plus the fixed Solar Hijri holidays for any other year, and says so when religious holidays of a year are unknown. `within_session_hours` and the screener's `session_open` now respect holidays. When the exchange's newest data disagrees with the calendar (an unannounced closure), `calendar_check` says so. Both tables are tested against the exchange's own history of non-trading days since 2019.
- **Contract tests** (#10): recorded real upstream responses (`tests/fixtures/recorded/`) replayed through `respx` exercise every tool (40 now) end to end without network, through the MCP server layer, with the clock frozen. A meta-test fails for any registered tool without a scenario. Re-record with `scripts/record_contract.py --record` (see `tests/README.md`).
- **`commodity_market` and `energy_market`**: the commodity and energy exchanges, read-only and without an account, from the exchanges' own public sites. `commodity_market` reads the Iran Mercantile Exchange (IME, بورس کالای ایران) physical market: a session's offers and contracts (product, producer, hall, contract type, delivery date, offered, demand and traded tons, weighted-average price in rial per kilogram, value in rial) with totals by hall and contract type and the top products, or IME's own roll-ups by ring and market, one row per session and its dollar rate. `energy_market` reads the Iran Energy Exchange (بورس انرژی ایران): auction results of oil, gas and petrochemical products and of electricity, announced offers, one auction's terms with its buy and sell order levels and trades, and whether the market is open. Units are explicit everywhere: the keys say them (`volume_tons`, `price_rial_per_kg`, `value_rial`) and every energy row carries its `volume_unit` and `price_basis` (rial per kilogram, US dollars per tonne, a premium on a reference price, rial per kWh); volumes of different units are never added, and the exchange's own totals are reproduced to the rial. Glossary: the commodity and energy terms (سلف, مچینگ, عرضه, تحویل, گواهی سپرده کالایی ...).
- The contract-test recorder and replay match a request's JSON body, so the POSTed IME services are recorded and replayed like any other request; recordings made before are unchanged.
- **Persian technical notes** (#11): `docs/DATA_SOURCES.fa.md` and `docs/ARCHITECTURE.fa.md`, linked from both READMEs. The English notes were brought up to date with 0.3.0 (the exchange's market-watch feed, the new endpoints, quirks 18 to 28, the holiday calendar).
- **Packaging** (#8, repository side): a slim sdist, project URLs, a PyPI README whose images and links are absolute, a manually runnable publish workflow and `docs/RELEASING.md` with the one-time PyPI steps.

### Fixed
- `market_snapshot` through MCP listed every instrument type (bonds topped the table) because the tool's default for `security_type` overrode the service default of stocks.
- Sector codes `01`-`09` of the market feed matched no industry name (40 of 3,680 rows); both spellings of a code are now registered.

## 0.3.0 (2026-11-04)

Ten new tools (38 in total), the whole-market tools moved to the exchange's own feed, and every finding of two independent client reviews fixed.

### Added
- **Stock screener**: `screen_stocks` and `screener_reference`. A safe expression language (parsed with `ast`, never `eval`) evaluated over every instrument: today's live values, up to 60 past trading days adjusted for capital increases (`close[1]`, `avg(volume, 20)`, `count(close_pct > 0, 5)`, `highest(high, 10)` ...), real/legal flow, a five-level order book, base volume, fund NAV and open interest. Accepts the field names and JavaScript spellings of the filter box on tsetmc.com, ships 15 presets, explains mistakes with suggestions and shows the evidence for each hit. New prompt `find_stocks`. Guide: `docs/SCREENER.md`.
- `option_chain` (calls and puts by strike and expiry with moneyness, intrinsic and time value, break-even, spread, put/call ratios, open-interest strikes and an estimated max pain) and `futures_market` (with basis).
- `index_history` (daily since 2008, weekly to yearly bars, or today's 5-minute path), `index_constituents` (members with their effect in index points) and `fund_ranking` (579 funds: NAV, returns, size, portfolio mix).
- `top_lists` (the exchange's 69 official best-of lists), `capital_calendar` (upcoming capital increases and price adjustments) and `trading_status` (suspended and supervised symbols, state changes, one symbol's history).
- `price_history(granularity=weekly|monthly|yearly)`, `shareholder_history(holder=...)` (one major holder's position over time), industry-level real money flow in `industry_summary`.
- Glossary: base volume, P/E, NAV, premium (حباب), TAL.

### Changed
- `market_watch`, `top_movers`, `industry_summary` and the screener run on `ClosingPrice/GetMarketWatch`, the feed tsetmc.com itself uses: about 3,700 instruments (shares, base market, funds, bonds, rights, options, futures, commodities) with a five-level book, instead of the 582 shares of the TSE gateway (kept as a fallback). `market_watch` and `market_snapshot` default to stocks; `security_type` takes `stock`, `fund`, `bond`, `option`, `future`, `rights`, `commodity`, `base`, `all`.
- `real_legal_flow` reads the whole history in one request, with exact rial values.
- Buy and sell queues ignore orders priced beyond the day's limits (an ask above the ceiling cannot trade): queues are no longer missed, and order-book levels outside the limits are flagged.
- One P/E definition (the exchange's, on the closing price). The server reports its version.
- The Codex install recipe waits for the server in scripted runs (`required = true`).

### Fixed
- Codal title filters read further pages instead of filtering one page of 20.
- `market_snapshot` no longer lists options as stocks; Persian digits in symbols; a ticker listed twice resolves to the record that traded most recently (about 5% of symbols failed with HTTP 500); `real_legal_flow(days=N)` returns N days; supervisor messages are no longer crowded out by pinned notices; loss-makers have no P/E; gainers rank by closing change.
- HTTP 429 is reported as rate limiting (with a per-host cooldown) instead of as an Iranian-IP problem; a slow optional section no longer stalls `symbol_overview`.

### Verified
- Independent QA through a real Codex client (58 questions) and a Claude agent (59 questions, 130 tool calls), every number recomputed from raw exchange data: no fabricated figure; the issues found are the fixes above.
- Screener results checked against an independent re-implementation from raw data: identical on three screens (29/29, 14/14, 32/32).
- 584 offline tests, 92% line coverage.

## 0.2.0 (2026-11-04)

- **Fix:** `top_movers` queue and real-money rankings returned nothing during the session (today's end-of-day table is empty until the close). The instrument index now falls back to the newest published day.
- **Fix:** gateway failures (HTTP 502/503) are retried more patiently and reported as an overloaded exchange, not as an IP problem.
- New CLI: `tools`, `call` (every tool from the shell, for agents without MCP), `config <client>` and `install <client>` (safe merge into the client's JSON config, with backup).
- Install recipes, one-click deep links (Cursor, VS Code, Goose) and framework snippets for 17 agents and IDEs, generated from one table.
- Website (GitHub Pages) with a promo video, animated README artwork, benchmark harness (`benchmarks/`) with independent ground truth, real example outputs (`docs/EXAMPLES.md`).
- Container image, AGENTS.md, llms.txt and an install guide written for AI agents, code of conduct, citation file, dependabot.
- Tests: 142 offline tests, 89% line coverage (service layer 96%).

## 0.1.0 (2026-11-04)

First public release.

- 28 read-only tools covering market state, indices, whole-market screens, quotes, order book (live and rebuilt history with queue episodes), tick-by-tick trades with aggregation and a coverage check, real/legal flow, shareholders, corporate actions, adjusted price history, fund NAV, Codal filings and supervisor notices.
- 3 prompts and a glossary resource.
- Persian/Arabic text normalisation, Jalali/Gregorian date handling.
- Works with MCP Python SDK 1.x and 2.x.
- `iran-bourse-mcp doctor` connectivity check; `serve` for stdio / streamable-http / sse.
