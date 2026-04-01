from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import unittest

from papertrade.contracts import Funding, Instrument, OpenInterest, Pair
from papertrade.sources.liquidation import InMemoryLiquidationSource, LiquidationEvent
from papertrade.sources.platform_db import InMemoryPlatformDBSource


def make_instrument(*, exchange: str, pair: Pair, funding_interval: int) -> Instrument:
    return Instrument(
        exchange=exchange,
        base=pair.base,
        quote=pair.quote,
        margin_asset=pair.quote,
        contract_multiplier=Decimal("1"),
        tick_size=Decimal("0.1"),
        lot_size=Decimal("0.001"),
        min_qty=Decimal("0.001"),
        max_qty=Decimal("100"),
        min_notional=Decimal("10"),
        max_leverage=50,
        funding_interval=funding_interval,
        launch_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )


def make_funding(*, exchange: str, pair: Pair, hour: int, rate: str) -> Funding:
    return Funding(
        time=datetime(2025, 1, 1, hour, 0, tzinfo=timezone.utc),
        exchange=exchange,
        base=pair.base,
        quote=pair.quote,
        funding_rate=Decimal(rate),
    )


def make_open_interest(*, exchange: str, pair: Pair, hour: int, value: str) -> OpenInterest:
    return OpenInterest(
        time=datetime(2025, 1, 1, hour, 0, tzinfo=timezone.utc),
        exchange=exchange,
        base=pair.base,
        quote=pair.quote,
        open_interest=Decimal(value),
    )


class InMemoryPlatformDBSourceTests(unittest.TestCase):
    def test_list_pairs_returns_unique_eight_hour_pairs_in_insertion_order(self) -> None:
        btc = Pair("BTC", "USDT")
        eth = Pair("ETH", "USDT")
        source = InMemoryPlatformDBSource()
        source.put_instrument(make_instrument(exchange="bybit", pair=btc, funding_interval=8))
        source.put_instrument(make_instrument(exchange="bitget", pair=btc, funding_interval=8))
        source.put_instrument(make_instrument(exchange="bybit", pair=eth, funding_interval=4))
        source.put_instrument(make_instrument(exchange="bitget", pair=eth, funding_interval=8))

        pairs = source.list_pairs()

        self.assertEqual(pairs, (btc, eth))

    def test_load_funding_history_filters_by_pair_and_exchange_and_sorts_latest_first(self) -> None:
        btc = Pair("BTC", "USDT")
        eth = Pair("ETH", "USDT")
        source = InMemoryPlatformDBSource()
        source.put_funding(make_funding(exchange="bybit", pair=btc, hour=0, rate="0.0001"))
        source.put_funding(make_funding(exchange="bybit", pair=btc, hour=8, rate="0.0002"))
        source.put_funding(make_funding(exchange="bitget", pair=btc, hour=16, rate="0.0003"))
        source.put_funding(make_funding(exchange="bybit", pair=eth, hour=16, rate="0.0004"))

        fundings = source.load_funding_history(btc, "bybit", limit=2)

        self.assertEqual(len(fundings), 2)
        self.assertEqual(fundings[0].time, datetime(2025, 1, 1, 8, 0, tzinfo=timezone.utc))
        self.assertEqual(fundings[1].time, datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc))

    def test_load_open_interest_history_filters_by_pair_and_exchange_and_limit(self) -> None:
        btc = Pair("BTC", "USDT")
        source = InMemoryPlatformDBSource()
        source.put_open_interest(make_open_interest(exchange="bybit", pair=btc, hour=0, value="100"))
        source.put_open_interest(make_open_interest(exchange="bybit", pair=btc, hour=8, value="120"))
        source.put_open_interest(make_open_interest(exchange="bybit", pair=btc, hour=16, value="140"))

        history = source.load_open_interest_history(btc, "bybit", limit=2)

        self.assertEqual([item.open_interest for item in history], [Decimal("140"), Decimal("120")])

    def test_load_history_rejects_negative_limit(self) -> None:
        source = InMemoryPlatformDBSource()

        with self.assertRaisesRegex(ValueError, "limit must not be negative"):
            source.load_funding_history(Pair("BTC", "USDT"), "bybit", limit=-1)

        with self.assertRaisesRegex(ValueError, "limit must not be negative"):
            source.load_open_interest_history(Pair("BTC", "USDT"), "bybit", limit=-1)


class InMemoryLiquidationSourceTests(unittest.TestCase):
    def test_sum_bybit_liquidation_usd_sums_matching_pair_inside_half_open_window(self) -> None:
        btc = Pair("BTC", "USDT")
        eth = Pair("ETH", "USDT")
        source = InMemoryLiquidationSource()
        source.put_event(
            LiquidationEvent(
                time=datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc),
                pair=btc,
                usd_size=Decimal("50"),
            )
        )
        source.put_event(
            LiquidationEvent(
                time=datetime(2025, 1, 1, 4, 0, tzinfo=timezone.utc),
                pair=btc,
                usd_size=Decimal("25"),
            )
        )
        source.put_event(
            LiquidationEvent(
                time=datetime(2025, 1, 1, 8, 0, tzinfo=timezone.utc),
                pair=btc,
                usd_size=Decimal("999"),
            )
        )
        source.put_event(
            LiquidationEvent(
                time=datetime(2025, 1, 1, 4, 0, tzinfo=timezone.utc),
                pair=eth,
                usd_size=Decimal("10"),
            )
        )

        total = source.sum_bybit_liquidation_usd(
            btc,
            datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc),
            datetime(2025, 1, 1, 8, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(total, Decimal("75"))

    def test_sum_bybit_liquidation_usd_rejects_reverse_time_window(self) -> None:
        source = InMemoryLiquidationSource()
        pair = Pair("BTC", "USDT")

        with self.assertRaisesRegex(ValueError, "end must not be earlier than start"):
            source.sum_bybit_liquidation_usd(
                pair,
                datetime(2025, 1, 1, 8, 0, tzinfo=timezone.utc),
                datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc),
            )
