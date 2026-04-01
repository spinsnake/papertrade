from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import unittest

from papertrade.config import Settings
from papertrade.contracts import Pair
from papertrade.runtime import resolve_runtime_availability
from papertrade.single_cycle_runtime import load_configured_single_cycle_sources
from papertrade.sources.platform_bridge import LiveHttpPlatformBridge
from papertrade.sources.platform_db import LivePlatformDBSource


class FakeHttpClient:
    def __init__(self, responses: dict[tuple[str, str, tuple[tuple[str, str], ...]], object]) -> None:
        self.responses = responses

    def get_json(self, base_url: str, path: str, params: dict[str, str] | None = None) -> object:
        key = (
            base_url,
            path,
            tuple(sorted((params or {}).items())),
        )
        try:
            return self.responses[key]
        except KeyError as exc:
            raise AssertionError(f"unexpected request: {key}") from exc


class LiveSourceAdapterTests(unittest.TestCase):
    def test_live_http_platform_bridge_builds_market_state_and_orderbook(self) -> None:
        pair = Pair("BTC", "USDT")
        http_client = FakeHttpClient(
            {
                (
                    "https://api.bybit.com",
                    "/v5/market/tickers",
                    (("category", "linear"), ("symbol", "BTCUSDT")),
                ): {
                    "retCode": 0,
                    "time": "1736582365000",
                    "result": {
                        "list": [
                            {
                                "indexPrice": "100",
                                "markPrice": "101",
                                "fundingRate": "0.0005",
                                "openInterest": "100",
                                "volume24h": "250",
                                "turnover24h": "25500",
                                "bid1Price": "100",
                                "bid1Size": "3",
                                "ask1Price": "101",
                                "ask1Size": "1",
                            }
                        ]
                    },
                },
                (
                    "https://api.bitget.com",
                    "/api/v2/mix/market/ticker",
                    (("productType", "USDT-FUTURES"), ("symbol", "BTCUSDT")),
                ): {
                    "code": "00000",
                    "data": [
                        {
                            "indexPrice": "100",
                            "markPrice": "100.5",
                            "fundingRate": "0.0002",
                            "holdingAmount": "90",
                            "baseVolume": "220",
                            "quoteVolume": "22100",
                            "bidPr": "100",
                            "bidSz": "2",
                            "askPr": "101",
                            "askSz": "1.5",
                            "ts": "1736582366000",
                        }
                    ],
                },
            }
        )
        bridge = LiveHttpPlatformBridge(http_client=http_client)

        bybit_state = bridge.get_market_state("bybit", pair)
        bybit_orderbook = bridge.get_orderbook("bybit", pair)
        bitget_state = bridge.get_market_state("bitget", pair)
        bitget_orderbook = bridge.get_orderbook("bitget", pair)

        assert bybit_state is not None
        assert bybit_orderbook is not None
        assert bitget_state is not None
        assert bitget_orderbook is not None
        self.assertEqual(bybit_state.mark_price, Decimal("101"))
        self.assertEqual(bybit_orderbook.best_bid().size, Decimal("3"))
        self.assertEqual(bitget_state.mark_price, Decimal("100.5"))
        self.assertEqual(bitget_orderbook.best_ask().size, Decimal("1.5"))

    def test_live_platform_db_source_lists_intersection_pairs_and_loads_history(self) -> None:
        pair = Pair("BTC", "USDT")
        http_client = FakeHttpClient(
            {
                (
                    "https://api.bybit.com",
                    "/v5/market/instruments-info",
                    (("category", "linear"), ("limit", "1000")),
                ): {
                    "retCode": 0,
                    "result": {
                        "nextPageCursor": "",
                        "list": [
                            {
                                "symbol": "BTCUSDT",
                                "contractType": "LinearPerpetual",
                                "status": "Trading",
                                "baseCoin": "BTC",
                                "quoteCoin": "USDT",
                                "launchTime": "1585526400000",
                                "priceFilter": {"tickSize": "0.1"},
                                "lotSizeFilter": {
                                    "qtyStep": "0.001",
                                    "minOrderQty": "0.001",
                                    "maxOrderQty": "100",
                                },
                                "leverageFilter": {"maxLeverage": "50"},
                            },
                            {
                                "symbol": "XRPUSDT",
                                "contractType": "LinearPerpetual",
                                "status": "Trading",
                                "baseCoin": "XRP",
                                "quoteCoin": "USDT",
                                "launchTime": "1585526400000",
                                "priceFilter": {"tickSize": "0.0001"},
                                "lotSizeFilter": {
                                    "qtyStep": "1",
                                    "minOrderQty": "1",
                                    "maxOrderQty": "100000",
                                },
                                "leverageFilter": {"maxLeverage": "25"},
                            },
                        ],
                    },
                },
                (
                    "https://api.bitget.com",
                    "/api/v2/mix/market/contracts",
                    (("productType", "USDT-FUTURES"),),
                ): {
                    "code": "00000",
                    "data": [
                        {
                            "baseCoin": "BTC",
                            "quoteCoin": "USDT",
                            "symbolStatus": "normal",
                            "sizeMultiplier": "0.001",
                            "minTradeNum": "0.001",
                            "priceEndStep": "1",
                            "pricePlace": "1",
                        },
                        {
                            "baseCoin": "ETH",
                            "quoteCoin": "USDT",
                            "symbolStatus": "normal",
                            "sizeMultiplier": "0.001",
                            "minTradeNum": "0.001",
                            "priceEndStep": "1",
                            "pricePlace": "1",
                        },
                    ],
                },
                (
                    "https://api.bybit.com",
                    "/v5/market/funding/history",
                    (("category", "linear"), ("limit", "2"), ("symbol", "BTCUSDT")),
                ): {
                    "retCode": 0,
                    "result": {
                        "list": [
                            {"fundingRateTimestamp": "1736553600000", "fundingRate": "0.0005"},
                            {"fundingRateTimestamp": "1736524800000", "fundingRate": "0.0004"},
                        ]
                    },
                },
                (
                    "https://api.bitget.com",
                    "/api/v2/mix/market/history-fund-rate",
                    (("pageNo", "1"), ("pageSize", "2"), ("productType", "USDT-FUTURES"), ("symbol", "BTCUSDT")),
                ): {
                    "code": "00000",
                    "data": [
                        {"fundingTime": "1736553600000", "fundingRate": "0.0002"},
                        {"fundingTime": "1736524800000", "fundingRate": "0.0001"},
                    ],
                },
                (
                    "https://api.bybit.com",
                    "/v5/market/open-interest",
                    (("category", "linear"), ("intervalTime", "5min"), ("limit", "2"), ("symbol", "BTCUSDT")),
                ): {
                    "retCode": 0,
                    "result": {
                        "list": [
                            {"timestamp": "1736553600000", "openInterest": "100"},
                            {"timestamp": "1736553300000", "openInterest": "99"},
                        ]
                    },
                },
                (
                    "https://api.bitget.com",
                    "/api/v2/mix/market/open-interest",
                    (("productType", "USDT-FUTURES"), ("symbol", "BTCUSDT")),
                ): {
                    "code": "00000",
                    "data": {
                        "openInterestList": [
                            {"symbol": "BTCUSDT", "size": "90"}
                        ],
                        "ts": "1736553600000",
                    },
                },
            }
        )
        source = LivePlatformDBSource(http_client=http_client)

        pairs = source.list_pairs()
        bybit_funding = source.load_funding_history(pair, "bybit", 2)
        bitget_funding = source.load_funding_history(pair, "bitget", 2)
        bybit_open_interest = source.load_open_interest_history(pair, "bybit", 2)
        bitget_open_interest = source.load_open_interest_history(pair, "bitget", 1)

        self.assertEqual(pairs, (pair,))
        self.assertEqual(len(bybit_funding), 2)
        self.assertEqual(bybit_funding[0].funding_rate, Decimal("0.0005"))
        self.assertEqual(bitget_funding[1].funding_rate, Decimal("0.0001"))
        self.assertEqual(bybit_open_interest[0].open_interest, Decimal("100"))
        self.assertEqual(bitget_open_interest[0].open_interest, Decimal("90"))

    def test_live_settings_enable_runtime_availability_and_source_bundle(self) -> None:
        settings = Settings(
            live_platform_sources=True,
            bybit_rest_base_url="https://api.bybit.com",
            bitget_rest_base_url="https://api.bitget.com",
        )

        availability = resolve_runtime_availability(settings)
        source_bundle = load_configured_single_cycle_sources(
            settings,
            pair=Pair("BTC", "USDT"),
            now_utc=datetime(2025, 1, 11, 7, 59, tzinfo=timezone.utc),
        )

        self.assertTrue(availability.has_platform_db_source)
        self.assertTrue(availability.has_platform_bridge_source)
        self.assertIsInstance(source_bundle.bridge, LiveHttpPlatformBridge)
        self.assertIsInstance(source_bundle.platform_db_source, LivePlatformDBSource)
