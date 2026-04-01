from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import os
from pathlib import Path


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _path_or_none(value: str) -> Path | None:
    return Path(value) if value else None


@dataclass
class Settings:
    source_mode: str = "platform_forward"
    runtime_mode: str = "forward_market_listener"
    strategy: str = "hybrid_aggressive_safe_valid"
    report_output_dir: Path = Path("reports")
    report_filename_pattern: str = "{strategy}__{run_id}__{as_of_round}__{report_type}.md"
    initial_equity: Decimal = Decimal("100")
    notional_pct: Decimal = Decimal("0.01")
    fee_bps: Decimal = Decimal("4")
    slippage_bps: Decimal = Decimal("4")
    decision_buffer_seconds: int = 30
    market_state_staleness_seconds: int = 120
    orderbook_staleness_seconds: int = 15
    strict_liquidation: bool = True
    risky_artifact_path: Path | None = None
    safe_artifact_path: Path | None = None
    live_platform_sources: bool = False
    live_liquidation_source: bool = False
    bybit_rest_base_url: str = "https://api.bybit.com"
    bitget_rest_base_url: str = "https://api.bitget.com"
    bybit_liquidation_ws_url: str = "wss://stream.bybit.com/v5/public/linear"
    live_liquidation_cache_path: Path | None = None
    platform_db_path: Path | None = None
    market_state_snapshot_path: Path | None = None
    orderbook_snapshot_path: Path | None = None
    liquidation_events_path: Path | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        settings = cls(
            source_mode=_env("PAPERTRADE_SOURCE_MODE", "platform_forward"),
            runtime_mode=_env("PAPERTRADE_RUNTIME_MODE", "forward_market_listener"),
            strategy=_env("PAPERTRADE_STRATEGY", "hybrid_aggressive_safe_valid"),
            report_output_dir=Path(_env("PAPERTRADE_REPORT_OUTPUT_DIR", "reports")),
            report_filename_pattern=_env(
                "PAPERTRADE_REPORT_FILENAME_PATTERN",
                "{strategy}__{run_id}__{as_of_round}__{report_type}.md",
            ),
            initial_equity=Decimal(_env("PAPERTRADE_INITIAL_EQUITY", "100")),
            notional_pct=Decimal(_env("PAPERTRADE_NOTIONAL_PCT", "0.01")),
            fee_bps=Decimal(_env("PAPERTRADE_FEE_BPS", "4")),
            slippage_bps=Decimal(_env("PAPERTRADE_SLIPPAGE_BPS", "4")),
            decision_buffer_seconds=int(_env("PAPERTRADE_DECISION_BUFFER_SECONDS", "30")),
            market_state_staleness_seconds=int(_env("PAPERTRADE_MARKET_STATE_STALENESS_SECONDS", "120")),
            orderbook_staleness_seconds=int(_env("PAPERTRADE_ORDERBOOK_STALENESS_SECONDS", "15")),
            strict_liquidation=_env("PAPERTRADE_STRICT_LIQUIDATION", "true").lower() in {"1", "true", "yes"},
            risky_artifact_path=_path_or_none(_env("PAPERTRADE_RISKY_ARTIFACT_PATH", "")),
            safe_artifact_path=_path_or_none(_env("PAPERTRADE_SAFE_ARTIFACT_PATH", "")),
            live_platform_sources=_env("PAPERTRADE_LIVE_PLATFORM_SOURCES", "false").lower() in {"1", "true", "yes"},
            live_liquidation_source=_env("PAPERTRADE_LIVE_LIQUIDATION_SOURCE", "false").lower() in {"1", "true", "yes"},
            bybit_rest_base_url=_env("PAPERTRADE_BYBIT_REST_BASE_URL", "https://api.bybit.com"),
            bitget_rest_base_url=_env("PAPERTRADE_BITGET_REST_BASE_URL", "https://api.bitget.com"),
            bybit_liquidation_ws_url=_env("PAPERTRADE_BYBIT_LIQUIDATION_WS_URL", "wss://stream.bybit.com/v5/public/linear"),
            live_liquidation_cache_path=_path_or_none(_env("PAPERTRADE_LIVE_LIQUIDATION_CACHE_PATH", "")),
            platform_db_path=_path_or_none(_env("PAPERTRADE_PLATFORM_DB_PATH", "")),
            market_state_snapshot_path=_path_or_none(_env("PAPERTRADE_MARKET_STATE_SNAPSHOT_PATH", "")),
            orderbook_snapshot_path=_path_or_none(_env("PAPERTRADE_ORDERBOOK_SNAPSHOT_PATH", "")),
            liquidation_events_path=_path_or_none(_env("PAPERTRADE_LIQUIDATION_EVENTS_PATH", "")),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.source_mode != "platform_forward":
            raise ValueError("source_mode must be platform_forward")
        if self.decision_buffer_seconds <= 0:
            raise ValueError("decision_buffer_seconds must be positive")
        if self.market_state_staleness_seconds <= 0:
            raise ValueError("market_state_staleness_seconds must be positive")
        if self.orderbook_staleness_seconds <= 0:
            raise ValueError("orderbook_staleness_seconds must be positive")
        if self.notional_pct <= 0 or self.notional_pct > 1:
            raise ValueError("notional_pct must be within (0, 1]")
