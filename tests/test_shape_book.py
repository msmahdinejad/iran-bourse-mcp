from iran_bourse_mcp import shape


def row(number, bid_price, bid_vol, bid_orders, ask_price, ask_vol, ask_orders, ref=1, time=90000):
    return {
        "number": number,
        "pMeDem": bid_price,
        "qTitMeDem": bid_vol,
        "zOrdMeDem": bid_orders,
        "pMeOf": ask_price,
        "qTitMeOf": ask_vol,
        "zOrdMeOf": ask_orders,
        "refID": ref,
        "hEven": time,
    }


def test_book_from_fixture(fx):
    book = shape.shape_order_book(fx("best_limits"), 4210.0, 3970.0)
    assert len(book["bids"]) == 5 and len(book["asks"]) == 5
    assert book["best_bid"] == 4210.0 and book["best_ask"] == 4240.0
    assert book["spread"] == 30.0
    assert book["total_bid_volume"] == sum(b["volume"] for b in book["bids"])
    assert -1 <= book["imbalance"] <= 1
    # the asks start at 4240, above today's ceiling of 4210: nobody can trade against the bid, so it is a queue
    assert book["queue"]["state"] == "buy_queue" and book["queue"]["queue_volume"] == book["bids"][0]["volume"]
    assert all(a.get("outside_price_limits") for a in book["asks"])


def test_buy_queue_detected_when_no_sellers_at_upper_limit():
    rows = [row(1, 4210, 5_000_000, 120, 0, 0, 0), row(2, 4200, 1000, 3, 0, 0, 0)]
    book = shape.shape_order_book(rows, 4210.0, 3970.0)
    assert book["queue"] == {
        "state": "buy_queue",
        "queue_volume": 5_000_000,
        "queue_orders": 120,
        "queue_value": 5_000_000 * 4210,
    }
    assert book["asks"] == []


def test_sell_queue_detected_when_no_buyers_at_lower_limit():
    rows = [row(1, 0, 0, 0, 3970, 9_000_000, 40)]
    assert shape.shape_order_book(rows, 4210.0, 3970.0)["queue"]["state"] == "sell_queue"


def test_no_queue_when_bid_at_limit_but_sellers_present():
    rows = [row(1, 4210, 5000, 2, 4200, 100, 1)]  # a seller at 4200 is within today's limits and trades with the bid
    assert shape.shape_order_book(rows, 4210.0, 3970.0)["queue"]["state"] is None


def test_orders_beyond_the_limits_do_not_break_a_queue():
    """Asks above the ceiling and bids below the floor are next-session orders: they cannot trade today."""
    buy = shape.shape_order_book([row(1, 4210, 5000, 2, 4220, 100, 1), row(2, 4200, 10, 1, 4250, 5, 1)], 4210.0, 3970.0)
    assert buy["queue"]["state"] == "buy_queue" and buy["queue"]["queue_volume"] == 5000
    assert [a["outside_price_limits"] for a in buy["asks"]] == [True, True] and "next session" in buy["note"]
    sell = shape.shape_order_book([row(1, 3900, 50, 1, 3970, 9000, 7)], 4210.0, 3970.0)
    assert sell["queue"]["state"] == "sell_queue" and sell["bids"][0]["outside_price_limits"] is True
    assert shape.shape_order_book([row(1, 4000, 50, 1, 3970, 9000, 7)], 4210.0, 3970.0)["queue"]["state"] is None  # a live bid


def test_empty_book_is_safe():
    book = shape.shape_order_book([], 100.0, 90.0)
    assert book["bids"] == [] and book["asks"] == [] and book["imbalance"] is None


def test_reconstruct_carries_unchanged_levels_forward():
    events = [
        row(1, 100, 10, 1, 101, 20, 1, ref=1, time=90000),
        row(2, 99, 11, 1, 102, 21, 1, ref=1, time=90000),
        row(1, 100, 15, 2, 101, 20, 1, ref=2, time=90100),  # only level 1 changes
    ]
    snaps = shape.reconstruct_book(events)
    assert [s["time"] for s in snaps] == [90000, 90100]
    last = {r["number"]: r for r in snaps[1]["rows"]}
    assert last[1]["qTitMeDem"] == 15  # updated
    assert last[2]["qTitMeDem"] == 11  # carried forward
    assert snaps[0]["rows"][0]["qTitMeDem"] == 10  # earlier snapshot untouched


def test_reconstruct_orders_by_ref_even_if_input_shuffled():
    events = [
        row(1, 100, 15, 2, 101, 20, 1, ref=9, time=90100),
        row(1, 100, 10, 1, 101, 20, 1, ref=3, time=90000),
    ]
    assert [s["ref"] for s in shape.reconstruct_book(events)] == [3, 9]


def test_reconstruct_real_fixture_has_full_depth(fx):
    snaps = shape.reconstruct_book(fx("best_limits_history_head"))
    assert snaps and all(1 <= len(s["rows"]) <= 5 for s in snaps)
    assert len(snaps[-1]["rows"]) == 5


def test_timeline_finds_queue_episodes_and_peak():
    events = []

    def snap(ref, time, bid_vol, ask_vol):
        ask_price = 100 if ask_vol else 0
        events.append(row(1, 100, bid_vol, 1, ask_price, ask_vol, 1 if ask_vol else 0, ref=ref, time=time))

    snap(1, 90000, 1000, 500)  # normal
    snap(2, 90100, 4000, 0)  # queue starts (bid at upper=100, no asks)
    snap(3, 90200, 9000, 0)  # grows
    snap(4, 90300, 2000, 700)  # queue broken
    snap(5, 90400, 8000, 0)  # second queue
    timeline = shape.book_timeline(shape.reconstruct_book(events), 100.0, 90.0, step_seconds=60)
    episodes = timeline["queue_episodes"]
    assert [e["type"] for e in episodes] == ["buy_queue", "buy_queue"]
    first = episodes[0]
    assert (first["start_volume"], first["peak_volume"], first["end_volume"]) == (4000, 9000, 9000)
    assert episodes[1]["start"] == "09:04:00"


def test_timeline_respects_window():
    events = [row(1, 100, 10 * (i + 1), 1, 101, 10, 1, ref=i + 1, time=90000 + i * 100) for i in range(6)]
    timeline = shape.book_timeline(shape.reconstruct_book(events), 110.0, 90.0, start=90200, end=90400, step_seconds=60)
    assert timeline["snapshots_in_range"] == 3


# ------------------------------------------------------------------ queues at the close of a past day


def day_row(symbol, last, high, low, yesterday, value, trades=10):
    return {"lVal18AFC": symbol, "pDrCotVal": last, "priceMax": high, "priceMin": low, "priceYesterday": yesterday,
            "qTotCap": value, "zTotTran": trades}


def test_limit_close_candidates_pick_the_day_extreme_in_the_queue_direction():
    rows = [
        day_row("up_small", 103, 103, 100, 100, 1e9),
        day_row("up_big", 206, 206, 200, 200, 5e9),
        day_row("faded", 101, 103, 100, 100, 9e9),  # touched the high but closed below it
        day_row("flat", 100, 100, 100, 100, 9e9),  # high but not above yesterday
        day_row("down", 97, 100, 97, 100, 2e9),
        day_row("silent", 103, 103, 103, 100, 9e9, trades=0),
        day_row("unpriced", 2, 2, 1, 1, 9e9),  # a reference price of 1 is an unpriced contract
    ]
    assert [r["lVal18AFC"] for r in shape.limit_close_candidates(rows, "buy")] == ["up_big", "up_small"]
    assert [r["lVal18AFC"] for r in shape.limit_close_candidates(rows, "sell")] == ["down"]


def test_thresholds_on_takes_the_latest_record_of_that_day():
    rows = [
        {"dEven": 20261103, "hEven": 1, "psGelStaMax": 22610.0, "psGelStaMin": 21310.0},
        {"dEven": 20261104, "hEven": 1, "psGelStaMax": 1.0, "psGelStaMin": 1.0},
        {"dEven": 20261104, "hEven": 60125, "psGelStaMax": 23280.0, "psGelStaMin": 21940.0},
    ]
    assert shape.thresholds_on(rows, 20261104) == (23280.0, 21940.0)
    assert shape.thresholds_on(rows, 20261105) == (None, None)


def test_queue_holds_agrees_with_queue_state():
    import itertools
    import random

    rng = random.Random(7)
    prices = [None, 0, 960, 970, 980, 1000, 1020, 1030, 1040]
    checked = 0
    for _ in range(3000):
        rows = []
        for number in range(1, rng.randint(1, 5) + 1):
            rows.append(row(number, rng.choice(prices), rng.choice([0, 0, 5, 100]), rng.choice([1, 2]),
                            rng.choice(prices), rng.choice([0, 0, 7, 100]), rng.choice([1, 3])))
        rng.shuffle(rows)  # queue_holds does not rely on the order it is given
        for upper, lower in itertools.product([1030.0, None], [970.0, None]):
            state = shape.queue_state(*shape._levels(rows), upper, lower)["state"]
            for wanted in ("buy_queue", "sell_queue"):
                assert shape.queue_holds(rows, wanted, upper, lower) == (state == wanted), (rows, upper, lower, wanted)
                checked += 1
    assert checked == 24000


def test_queue_at_close_reads_the_book_at_1230_and_since_when_it_held():
    events = [
        row(1, 1020, 100, 1, 1030, 50, 2, ref=1, time=84500),  # pre-open: a seller at the ceiling, no queue
        row(1, 1030, 900, 9, 0, 0, 0, ref=2, time=90100),  # the queue forms
        row(2, 1020, 10, 1, 0, 0, 0, ref=3, time=100000),
        row(1, 1030, 0, 0, 1030, 10, 1, ref=4, time=110000),  # broken: a seller at the ceiling
        row(1, 1030, 5000, 40, 0, 0, 0, ref=5, time=113000),  # queue again, for good
        row(1, 1030, 7000, 55, 0, 0, 0, ref=6, time=122959),
        row(1, 1030, 7000, 55, 1040, 300, 3, ref=7, time=123000),  # an ask above the ceiling does not break it
        row(1, 1030, 1, 1, 1000, 999, 9, ref=8, time=140000),  # after the close: ignored
    ]
    snaps = shape.reconstruct_book(events)
    out = shape.queue_at_close(snaps, 1030.0, 970.0)
    assert out == {
        "state": "buy_queue", "queue_volume": 7000, "queue_orders": 55, "queue_value": 7000 * 1030,
        "book_time": "12:30:00", "queue_since": "11:30:00", "held_last_30_minutes": True,
    }
    late = shape.queue_at_close(snaps, 1030.0, 970.0, held_from=113000 - 1)
    assert late["held_last_30_minutes"] is False
    before_break = shape.queue_at_close(snaps, 1030.0, 970.0, close=105959)
    assert before_break["queue_since"] == "09:01:00" and before_break["book_time"] == "10:00:00"
    broken = shape.queue_at_close(snaps, 1030.0, 970.0, close=112959)
    assert broken["state"] is None and broken["queue_since"] is None and broken["held_last_30_minutes"] is False
    empty = shape.queue_at_close([], 1030.0, 970.0)
    assert empty["state"] is None and empty["book_time"] is None
