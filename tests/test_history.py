from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import unittest

from papertrade.trading_logic.contracts import Funding, Pair
from papertrade.trading_logic.history import FundingSpreadHistoryLoader
from papertrade.data_streaming.sources.platform_db import InMemoryPlatformDBSource


def make_funding(*, exchange: str, pair: Pair, time: datetime, rate: str) -> Funding:
    return Funding(
        time=time,
        exchange=exchange,
        base=pair.base,
        quote=pair.quote,
        funding_rate=Decimal(rate),
    )


class FundingSpreadHistoryLoaderTests(unittest.TestCase):
    def test_load_computes_lag1_and_rolling3_from_latest_matched_rounds(self) -> None:
        pair = Pair("BTC", "USDT")
        source = InMemoryPlatformDBSource()
        source.put_funding(
            make_funding(
                exchange="bybit",
                pair=pair,
                time=datetime(2025, 1, 11, 0, 0, tzinfo=timezone.utc),
                rate="0.0005",
            )
        )
        source.put_funding(
            make_funding(
                exchange="bitget",
                pair=pair,
                time=datetime(2025, 1, 11, 0, 0, tzinfo=timezone.utc),
                rate="0.0002",
            )
        )
        source.put_funding(
            make_funding(
                exchange="bybit",
                pair=pair,
                time=datetime(2025, 1, 10, 16, 0, tzinfo=timezone.utc),
                rate="0.0004",
            )
        )
        source.put_funding(
            make_funding(
                exchange="bitget",
                pair=pair,
                time=datetime(2025, 1, 10, 16, 0, tzinfo=timezone.utc),
                rate="0.0001",
            )
        )
        source.put_funding(
            make_funding(
                exchange="bybit",
                pair=pair,
                time=datetime(2025, 1, 10, 8, 0, tzinfo=timezone.utc),
                rate="0.0003",
            )
        )
        source.put_funding(
            make_funding(
                exchange="bitget",
                pair=pair,
                time=datetime(2025, 1, 10, 8, 0, tzinfo=timezone.utc),
                rate="0.0001",
            )
        )

        history = FundingSpreadHistoryLoader(source).load(
            pair=pair,
            funding_round=datetime(2025, 1, 11, 8, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(history.lag1_abs_spread_bps, Decimal("3"))
        self.assertEqual(history.rolling3_mean_abs_spread_bps, Decimal("8") / Decimal("3"))
        self.assertEqual(history.matched_spreads_bps, (Decimal("3"), Decimal("3"), Decimal("2")))

    def test_load_ignores_unmatched_and_future_rounds(self) -> None:
        pair = Pair("BTC", "USDT")
        source = InMemoryPlatformDBSource()
        source.put_funding(
            make_funding(
                exchange="bybit",
                pair=pair,
                time=datetime(2025, 1, 11, 8, 0, tzinfo=timezone.utc),
                rate="0.0009",
            )
        )
        source.put_funding(
            make_funding(
                exchange="bybit",
                pair=pair,
                time=datetime(2025, 1, 11, 0, 0, tzinfo=timezone.utc),
                rate="0.0005",
            )
        )
        source.put_funding(
            make_funding(
                exchange="bitget",
                pair=pair,
                time=datetime(2025, 1, 11, 0, 0, tzinfo=timezone.utc),
                rate="0.0003",
            )
        )
        source.put_funding(
            make_funding(
                exchange="bitget",
                pair=pair,
                time=datetime(2025, 1, 10, 16, 0, tzinfo=timezone.utc),
                rate="0.0002",
            )
        )

        history = FundingSpreadHistoryLoader(source).load(
            pair=pair,
            funding_round=datetime(2025, 1, 11, 8, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(history.matched_spreads_bps, (Decimal("2"),))
        self.assertEqual(history.lag1_abs_spread_bps, Decimal("2"))
        self.assertIsNone(history.rolling3_mean_abs_spread_bps)

