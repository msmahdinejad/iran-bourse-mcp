# Install guide for AI agents

You are an AI agent asked to connect the user to Tehran Stock Exchange data with `iran-bourse-mcp`. Follow these steps in order. All commands are safe and read-only.

## 1. Check prerequisites

- `uv` must be installed (`uv --version`). If not: Windows `powershell -c "irm https://astral.sh/uv/install.ps1 | iex"`, macOS/Linux `curl -LsSf https://astral.sh/uv/install.sh | sh`.
- The machine should be in Iran and not behind a foreign VPN: TSETMC and Codal often refuse foreign addresses.

## 2. Verify access

```bash
uvx iran-bourse-mcp doctor
```

Expect four `OK` lines. If you see `FAIL` or HTTP 403, tell the user it is the IP restriction and offer `IRAN_BOURSE_PROXY=http://host:port` (an in-Iran proxy) before continuing.

## 3. Register the server with the user's client

List the supported clients, then use the printed instructions:

```bash
uvx iran-bourse-mcp config            # list client ids
uvx iran-bourse-mcp config <client>   # exact steps for one client
```

Clients with an automatic installer (it backs up the config file and refuses to touch files it cannot parse):

```bash
uvx iran-bourse-mcp install <client>   # claude-desktop, cursor, gemini-cli, windsurf, kiro, qwen-code
```

For Claude Code run `claude mcp add iran-bourse -- uvx iran-bourse-mcp`. For Codex run `codex mcp add iran-bourse -- uvx iran-bourse-mcp`.

The server entry is always: command `uvx`, args `["iran-bourse-mcp"]`, transport stdio.

## 4. Tell the user to restart the client, then test

Ask the client something like: "Call market_status, then quote for the symbol فولاد." The answer should include Tehran time, the market state and a price in Rial.

## If the client has no MCP support

Use the shell interface instead. Every tool is available:

```bash
uvx iran-bourse-mcp tools
uvx iran-bourse-mcp call quote symbol=فولاد --compact
uvx iran-bourse-mcp call top_movers kind=buy_queue limit=5 --compact
```

## Usage notes for the agent

- Symbols are Persian (فولاد، خودرو، وبملت). Dates may be Gregorian or Jalali (`1405/08/12`).
- Prices and values are in Rial (1 Toman = 10 Rial).
- Start with `symbol_overview` for a stock, `market_watch` / `top_movers` for the whole market.
- Values under keys named `estimate`/`estimated` are derived, not published by the exchange. Say so when you report them.
- This is information, not investment advice. There is no tool to place orders.
