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
    fee_bps: Decimal | None = Decimal("4")
    bybit_taker_fee_bps: Decimal | None = None
    bitget_taker_fee_bps: Decimal | None = None
    slippage_bps: Decimal = Decimal("4")
    slippage_model: str = "top_of_book"
    decision_buffer_seconds: int = 30
    market_state_staleness_seconds: int = 120
    orderbook_staleness_seconds: int = 15
    strict_liquidation: bool = True
    open_interest_mode: str = "raw"
    risky_artifact_path: Path | None = None
    safe_artifact_path: Path | None = None
    platform_postgres_dsn: str | None = None
    state_db_path: Path | None = None
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

    def __post_init__(self) -> None:
        self.resolve_fee_config()

    @classmethod
    def from_env(cls) -> "Settings":
        legacy_fee_bps_raw = os.environ.get("PAPERTRADE_FEE_BPS", "").strip()
        bybit_taker_fee_bps_raw = os.environ.get("PAPERTRADE_BYBIT_TAKER_FEE_BPS", "").strip()
        bitget_taker_fee_bps_raw = os.environ.get("PAPERTRADE_BITGET_TAKER_FEE_BPS", "").strip()
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
            fee_bps=Decimal(legacy_fee_bps_raw) if legacy_fee_bps_raw else None,
            bybit_taker_fee_bps=Decimal(bybit_taker_fee_bps_raw) if bybit_taker_fee_bps_raw else None,
            bitget_taker_fee_bps=Decimal(bitget_taker_fee_bps_raw) if bitget_taker_fee_bps_raw else None,
            slippage_bps=Decimal(_env("PAPERTRADE_SLIPPAGE_BPS", "4")),
            slippage_model=_env("PAPERTRADE_SLIPPAGE_MODEL", "top_of_book"),
            decision_buffer_seconds=int(_env("PAPERTRADE_DECISION_BUFFER_SECONDS", "30")),
            market_state_staleness_seconds=int(_env("PAPERTRADE_MARKET_STATE_STALENESS_SECONDS", "120")),
            orderbook_staleness_seconds=int(_env("PAPERTRADE_ORDERBOOK_STALENESS_SECONDS", "15")),
            strict_liquidation=_env("PAPERTRADE_STRICT_LIQUIDATION", "true").lower() in {"1", "true", "yes"},
            open_interest_mode=_env("PAPERTRADE_OPEN_INTEREST_MODE", "raw"),
            risky_artifact_path=_path_or_none(_env("PAPERTRADE_RISKY_ARTIFACT_PATH", "")),
            safe_artifact_path=_path_or_none(_env("PAPERTRADE_SAFE_ARTIFACT_PATH", "")),
            platform_postgres_dsn=_env("PAPERTRADE_PLATFORM_POSTGRES_DSN", "") or None,
            state_db_path=_path_or_none(_env("PAPERTRADE_STATE_DB_PATH", "")),
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
        if settings.bybit_taker_fee_bps is None and settings.bitget_taker_fee_bps is None and settings.fee_bps is None:
            settings.bybit_taker_fee_bps = Decimal("6")
            settings.bitget_taker_fee_bps = Decimal("6")
            settings.resolve_fee_config()
        if settings.state_db_path is None and settings.platform_db_path is not None:
            settings.state_db_path = settings.platform_db_path
        settings.validate()
        return settings

    def resolve_fee_config(self) -> None:
        if self.bybit_taker_fee_bps is None and self.bitget_taker_fee_bps is None:
            if self.fee_bps is None:
                return
            per_exchange_taker_fee_bps = self.fee_bps / Decimal("4")
            self.bybit_taker_fee_bps = per_exchange_taker_fee_bps
            self.bitget_taker_fee_bps = per_exchange_taker_fee_bps
            self.fee_bps = (self.bybit_taker_fee_bps + self.bitget_taker_fee_bps) * Decimal("2")
            return
        if self.bybit_taker_fee_bps is None or self.bitget_taker_fee_bps is None:
            raise ValueError("bybit_taker_fee_bps and bitget_taker_fee_bps must be configured together")
        self.fee_bps = (self.bybit_taker_fee_bps + self.bitget_taker_fee_bps) * Decimal("2")

    def validate(self) -> None:
        self.resolve_fee_config()
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
        if self.bybit_taker_fee_bps is None or self.bybit_taker_fee_bps < 0:
            raise ValueError("bybit_taker_fee_bps must be non-negative")
        if self.bitget_taker_fee_bps is None or self.bitget_taker_fee_bps < 0:
            raise ValueError("bitget_taker_fee_bps must be non-negative")
        if self.slippage_model not in {"fixed_bps", "top_of_book"}:
            raise ValueError("slippage_model must be one of fixed_bps, top_of_book")
        if self.open_interest_mode not in {"raw", "mark_notional"}:
            raise ValueError("open_interest_mode must be one of raw, mark_notional")
