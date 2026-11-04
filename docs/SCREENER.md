# Stock screener

`screen_stocks` is the filter box of tsetmc.com, driven by an AI agent. You describe what you want in plain
language, the agent writes a short condition, and the server returns only the stocks that satisfy it right
now, in one call, with the evidence for each hit.

```text
You:    stocks whose volume today is over twice their 20-day average, that rose more than 1% yesterday,
        are positive today, and trade over 5 billion rial
Agent:  screen_stocks(filter="volume > 2 * avg(volume, 20) and close_pct[1] > 1 and close_pct > 0 and value > 5B")
```

The condition is parsed with Python's `ast` module, checked against a whitelist and compiled to closures. It is
never passed to `eval` or `exec`, cannot import anything, and is limited in size and depth.

## How it works

* **Universe:** every instrument of the exchange's market watch (about 580 ordinary shares on Bourse and Fara
  Bourse by default); narrow it with `market`, `security_type`, `industry`.
* **Today:** live values from the market watch, plus real/legal flow from the exchange's client-type table.
* **Past days:** up to 60 trading days read from the exchange's end-of-day tables (one request per day for the
  whole market, cached). Prices are adjusted for capital increases and dividends by default, so `close[5]` is
  comparable with `close`.
* **Evidence:** besides `symbol`, `last`, `close_pct`, `volume` and `value`, every result shows the fields the
  filter uses and its window terms (for example `avg(volume, 20)`), so a hit explains itself.
* **Missing data is unknown, not false:** a comparison against a missing value is unknown and never matches. A past
  day on which a symbol did not trade counts as zero volume; days before it was listed are unknown.
* **Time:** about 3 seconds the first time a history depth is needed, well under a second afterwards.

## Syntax

* Conditions: comparisons (< <= > >= == !=), combine with and / or / not (also && || !), parentheses.
* Arithmetic: + - * / %  (no powers). Numbers accept suffixes k, m, b, t: 5B = 5 billion rial. Persian digits work.
* Text: quote it, 'بانکها'. Letter variants (ی/ي, ک/ك) are equal. has(industry, 'خودرو'), industry in ('بانکها', 'بیمه').
* History: close[1] is yesterday's close; avg(volume, 20) averages the 20 trading days before today; count(close_pct > 0, 5) counts rising days.
* Inside aggregates every field means 'that day': count(close > open, 3) counts days whose close was above their own open.
* Missing data makes a comparison unknown (not true), so a row with no history never matches a history condition.
* A past day on which the symbol did not trade counts as zero volume/value/trades (prices unknown); days before its listing are unknown.
* Prices are rial. History is adjusted for capital increases/dividends so close[5] is comparable with close.

## Examples

| Goal | Filter |
|---|---|
| Volume surge on a rising day | `volume > 2 * avg(volume, 20) and close_pct > 1` |
| Yesterday rose, today opens with a gap up | `close_pct[1] > 0 and gap_pct > 1.5` |
| Three red days then a green one | `close_pct > 0 and all(close_pct < 0, 3)` |
| Real-person buyers dominating | `real_buyer_power > 2 and real_net_value > 5B and value > 10B` |
| Breakout above the 20-day high on volume | `close > highest(high, 20) and volume > avg(volume, 20)` |
| Cheap banks with liquidity | `has(industry, 'بانک') and pe > 0 and pe < 6 and value > 3B` |
| Up 10% in 5 sessions | `pct(close, close[5]) > 10` |

## Fields

Fields marked **history** also work as `name[k]` and inside the window functions.

| Field (aliases) | Persian label | Unit | History | Meaning |
|---|---|---|---|---|
| `symbol` | نماد | text |  | Ticker, e.g. فولاد. |
| `name` | نام شرکت | text |  | Company name. |
| `industry` | گروه صنعت | text |  | Industry group, e.g. 'فلزات اساسی'. Use has(industry, 'فلزات') or industry in ('بانکها', 'خودرو'). |
| `sub_industry` | زیرگروه صنعت | text |  | Industry sub-group. |
| `market` | بازار | text |  | 'بورس' or 'فرابورس'. |
| `board` | تابلو | text |  | Board, e.g. 'بازار اول - اصلی', 'تابلو فرعی', 'نوآفرین'. |
| `security_type` | نوع اوراق | text |  | e.g. 'سهام عادی', 'حق تقدم'. |
| `status` | وضعیت نماد | text |  | Trading status: 'مجاز', 'مجاز-محفوظ', 'ممنوع' ... |
| `last`, `pl`, `last_price` | آخرین معامله | rial | yes | Last trade price. |
| `close`, `pc`, `closing_price` | قیمت پایانی | rial | yes | Closing (volume-weighted) price. |
| `open`, `pf`, `first`, `first_price` | اولین قیمت | rial | yes | First trade price of the day. |
| `high`, `pmax`, `max_price` | بیشترین قیمت | rial | yes | Day high. |
| `low`, `pmin`, `min_price` | کمترین قیمت | rial | yes | Day low. |
| `yesterday`, `py`, `yesterday_price` | قیمت دیروز | rial | yes | Reference price: previous day's adjusted close. |
| `last_pct`, `pl_pct` | درصد آخرین معامله | % | yes | Last trade vs reference price, in percent. |
| `close_pct`, `pc_pct` | درصد قیمت پایانی | % | yes | Close vs reference price, in percent. |
| `vwap` | میانگین قیمت معاملات | rial | yes | value / volume. |
| `volume`, `tvol`, `vol` | حجم معاملات | shares | yes | Traded volume in shares. |
| `value`, `tval` | ارزش معاملات | rial | yes | Traded value in rial (1B = one billion rial = 100M toman). |
| `trades`, `tno` | تعداد معاملات | count | yes | Number of trades. |
| `upper_limit`, `pmaxlim`, `max_limit` | حد مجاز بالا | rial |  | Upper price limit (سقف قیمت). |
| `lower_limit`, `pminlim`, `min_limit` | حد مجاز پایین | rial |  | Lower price limit (کف قیمت). |
| `bid_price`, `pd1` | بهترین قیمت خرید | rial |  | Best bid price. |
| `bid_volume`, `qd1` | حجم بهترین خرید | shares |  | Volume at the best bid. |
| `bid_orders`, `zd1` | تعداد سفارش خرید | count |  | Orders at the best bid. |
| `ask_price`, `po1` | بهترین قیمت فروش | rial |  | Best ask price. |
| `ask_volume`, `qo1` | حجم بهترین فروش | shares |  | Volume at the best ask. |
| `ask_orders`, `zo1` | تعداد سفارش فروش | count |  | Orders at the best ask. |
| `bid_value` | ارزش صف خرید (تخمین) | rial |  | bid_volume x bid_price (queue size when locked at the upper limit). |
| `ask_value` | ارزش صف فروش (تخمین) | rial |  | ask_volume x ask_price. |
| `at_upper_limit` | در سقف قیمت | flag |  | Last price is at the upper limit. |
| `at_lower_limit` | در کف قیمت | flag |  | Last price is at the lower limit. |
| `buy_queue` | صف خرید | flag |  | At the upper limit with nothing offered: a probable buy queue (top_movers confirms against the order book). |
| `sell_queue` | صف فروش | flag |  | At the lower limit with nothing bid: a probable sell queue. |
| `pe`, `p_e` | P/E | ratio |  | Price / earnings (null when loss-making). |
| `eps` | EPS | rial |  | Earnings per share, rial. |
| `market_cap` | ارزش بازار | rial |  | Market capitalisation, rial. |
| `index_effect`, `effect_on_index` | تاثیر در شاخص | points |  | Contribution to the total index, in index points. |
| `gap_pct` | گپ بازگشایی | % |  | (open / yesterday - 1) x 100. |
| `range_pct` | دامنه نوسان روز | % |  | (high - low) / yesterday x 100. |
| `from_high_pct` | فاصله از سقف روز | % |  | (last / high - 1) x 100; 0 when trading at the day high. |
| `from_low_pct` | فاصله از کف روز | % |  | (last / low - 1) x 100. |
| `to_upper_limit_pct` | فاصله تا سقف مجاز | % |  | (upper_limit / last - 1) x 100. |
| `real_buy_volume`, `buy_i_volume` | حجم خرید حقیقی | shares |  | Real-person buy volume. |
| `real_sell_volume`, `sell_i_volume` | حجم فروش حقیقی | shares |  | Real-person sell volume. |
| `real_buy_count`, `buy_count_i` | تعداد خریدار حقیقی | count |  | Number of real-person buyers. |
| `real_sell_count`, `sell_count_i` | تعداد فروشنده حقیقی | count |  | Number of real-person sellers. |
| `legal_buy_volume`, `buy_n_volume` | حجم خرید حقوقی | shares |  | Legal-entity buy volume. |
| `legal_sell_volume`, `sell_n_volume` | حجم فروش حقوقی | shares |  | Legal-entity sell volume. |
| `legal_buy_count`, `buy_count_n` | تعداد خریدار حقوقی | count |  | Number of legal-entity buyers. |
| `legal_sell_count`, `sell_count_n` | تعداد فروشنده حقوقی | count |  | Number of legal-entity sellers. |
| `real_net_volume` | خالص حجم خرید حقیقی | shares |  | Real buy volume - real sell volume (>0 = real-person inflow). |
| `real_net_value` | خالص ورود پول حقیقی (تخمین) | rial |  | Estimate: real_net_volume x vwap. |
| `legal_net_volume` | خالص حجم خرید حقوقی | shares |  | Legal buy volume - legal sell volume. |
| `real_buyer_power`, `buyer_power` | قدرت خریدار حقیقی | ratio |  | Average real buy size / average real sell size (>1: buyers are bigger). |
| `real_buy_share` | سهم خرید حقیقی | % |  | Real-person share of all buy volume, percent. |
| `real_sell_share` | سهم فروش حقیقی | % |  | Real-person share of all sell volume, percent. |

## Functions

| Function | Meaning |
|---|---|
| `abs(x)` | absolute value |
| `round(x, digits=0)` | round |
| `sqrt(x), log(x)` | square root, natural log (null if undefined) |
| `min(a, b, ...), max(a, b, ...)` | smallest / largest of several values (null-safe) |
| `pct(a, b)` | (a / b - 1) x 100, the percent change from b to a |
| `between(x, lo, hi)` | lo <= x <= hi |
| `iff(cond, a, b)  or  a if cond else b` | conditional value |
| `coalesce(a, b, ...)` | first non-null value |
| `isnull(x)` | true when the value is missing |
| `has(text, 'sub')` | text contains (Persian/Arabic letter variants are equal), e.g. has(industry, 'خودرو') |
| `startswith(text, 'prefix')` | text starts with |
| `x in ('a', 'b')` | membership for text or numbers |
| `field[k]` | value k trading days ago (close[1] = yesterday); history fields only |
| `ago(expr, k)` | evaluate expr as of k trading days ago |
| `avg(expr, n)  sum  highest  lowest  stdev` | aggregate expr over the n trading days BEFORE today |
| `count(cond, n)` | how many of the last n days cond was true |
| `all(cond, n)  any(cond, n)` | cond true on every / at least one of the last n days (all needs n days of history) |

Windows reach at most 60 trading days back; an expression may be 1500 characters long.

## Ready-made presets

Use `screen_stocks(preset="volume_surge")`, optionally with an extra `filter` that is ANDed.

| Preset | Persian | Filter | Sorted by |
|---|---|---|---|
| `buy_queue` | صف خرید | `buy_queue` | `bid_value` |
| `sell_queue` | صف فروش | `sell_queue` | `ask_value` |
| `near_upper_limit` | نزدیک سقف قیمت | `not at_upper_limit and to_upper_limit_pct <= 1 and volume > 0` | `to_upper_limit_pct` (ascending) |
| `volume_surge` | جهش حجم معاملات | `value > 5B and volume > 2 * avg(volume, 20)` | `volume / avg(volume, 20)` |
| `real_money_inflow` | ورود پول حقیقی | `value > 10B and real_net_value > 0 and real_buyer_power > 1.2` | `real_net_value` |
| `real_money_outflow` | خروج پول حقیقی | `value > 10B and real_net_value < 0 and real_buyer_power < 0.8` | `real_net_value` (ascending) |
| `smart_money` | قدرت خریدار حقیقی همراه با حجم | `value > 10B and real_buyer_power > 1.5 and real_net_value > 0 and volume > avg(volume, 20)` | `real_buyer_power` |
| `breakout_20d` | شکست سقف ۲۰ روزه | `close > highest(high, 20) and volume > avg(volume, 20)` | `pct(close, highest(high, 20))` |
| `breakdown_20d` | شکست کف ۲۰ روزه | `close < lowest(low, 20) and volume > avg(volume, 20)` | `pct(close, lowest(low, 20))` (ascending) |
| `three_green_days` | سه روز صعودی متوالی | `close_pct > 0 and all(close_pct > 0, 2)` | `value` |
| `oversold_bounce` | بازگشت پس از سه روز نزولی | `close_pct > 1 and all(close_pct < 0, 3)` | `close_pct` |
| `gap_up` | گپ صعودی | `gap_pct > 2 and close >= open and value > 2B` | `gap_pct` |
| `strong_close` | بسته‌شدن در سقف روز | `close_pct > 3 and from_high_pct > -0.5 and value > 5B` | `close_pct` |
| `cheap_with_value` | P/E پایین با نقدشوندگی | `pe > 0 and pe < 5 and value > 5B` | `pe` (ascending) |
| `unusual_trade_count` | جهش تعداد معاملات | `trades > 2 * avg(trades, 20) and value > 5B` | `trades / avg(trades, 20)` |

## Reading results

```json
{
  "filter": "(volume > 2 * avg(volume, 20) and close_pct[1] > 1 ...)",
  "as_of": {"date": "2026-11-04", "jdate": "1405/08/13", "session_open": false},
  "history": {"trading_days_loaded": 20, "from": "2026-10-07", "to": "2026-11-03", "adjusted_for_capital_changes": true},
  "matched": 28, "returned": 6,
  "rows": [{"symbol": "...", "yesterday_pct": 2.97, "today_pct": 2.85, "volume_x": 8.42}]
}
```

`matched` is the total number of hits, `returned` how many fit `limit`. While the session is open the response
says so: today's volume, value, trades and real/legal flow are partial then, so ratios against past averages
understate the final ones.

## Limits and honesty

* The expression language is this project's own. It borrows the idea and many field names from the filter box on
  tsetmc.com; filters are not copy-compatible in both directions.
* `buy_queue` / `sell_queue` are inferred from the live snapshot (price at the limit with nothing offered). Use
  `top_movers(kind='buy_queue')` for queue sizes confirmed against each symbol's order book.
* `real_*_value` fields are estimates (net real volume x volume-weighted price); the exchange publishes volumes
  and counts, not values, in its market-wide client-type table.
* History fields exist for prices, volume, value and trade count. P/E, EPS, order-book and flow fields describe
  today only.
* Not investment advice.
