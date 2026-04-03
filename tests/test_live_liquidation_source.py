from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest

from papertrade.trading_logic.contracts import Pair
from papertrade.data_streaming.sources.liquidation import BybitLiveLiquidationSource, LiquidationEvent


class LiveLiquidationSourceTests(unittest.TestCase):
    def test_live_source_persists_and_recovers_coverage_and_events(self) -> None:
        pair = Pair("BTC", "USDT")
        window_end = datetime.now(timezone.utc).replace(microsecond=0)
        coverage_start = window_end - timedelta(hours=4)
        event_time = window_end - timedelta(seconds=30)

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "liquidation-cache.json"
            source = BybitLiveLiquidationSource(
                pairs=(pair,),
                cache_path=cache_path,
            )
            source.start = lambda: None
            source.set_coverage_start(pair, coverage_start)
            source.put_event(
                LiquidationEvent(
                    time=event_time,
                    pair=pair,
                    usd_size=Decimal("125.5"),
                )
            )

            self.assertTrue(
                source.covers_bybit_liquidation_window(
                    pair,
                    coverage_start,
                    window_end,
                )
            )
            self.assertEqual(
                source.sum_bybit_liquidation_usd(
                    pair,
                    coverage_start,
                    window_end,
                ),
                Decimal("125.5"),
            )

            source.stop()

            cache_payload = json.loads(cache_path.read_text(encoding="utf-8"))
            self.assertEqual(cache_payload["coverage_start"][pair.symbol], coverage_start.isoformat())
            self.assertEqual(len(cache_payload["events"]), 1)

            reloaded = BybitLiveLiquidationSource(
                pairs=(pair,),
                cache_path=cache_path,
            )
            reloaded.start = lambda: None

            self.assertTrue(
                reloaded.covers_bybit_liquidation_window(
                    pair,
                    coverage_start,
                    window_end,
                )
            )
            self.assertEqual(
                reloaded.sum_bybit_liquidation_usd(
                    pair,
                    coverage_start,
                    window_end,
                ),
                Decimal("125.5"),
            )

            reloaded.stop()

    def test_stale_cache_drops_coverage(self) -> None:
        pair = Pair("BTC", "USDT")

        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = Path(tmpdir) / "liquidation-cache.json"
            cache_path.write_text(
                json.dumps(
                    {
                        "last_update": "2000-01-01T00:00:00+00:00",
                        "coverage_start": {
                            pair.symbol: "1999-12-31T16:00:00+00:00",
                        },
                        "events": [],
                    }
                ),
                encoding="utf-8",
            )

            source = BybitLiveLiquidationSource(
                pairs=(pair,),
                cache_path=cache_path,
            )
            source.start = lambda: None

            self.assertFalse(
                source.covers_bybit_liquidation_window(
                    pair,
                    datetime(2025, 1, 11, 0, 0, tzinfo=timezone.utc),
                    datetime(2025, 1, 11, 8, 0, tzinfo=timezone.utc),
                )
            )

            source.stop()

