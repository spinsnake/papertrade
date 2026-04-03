from __future__ import annotations

import csv
from dataclasses import dataclass, fields, is_dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
import json
from pathlib import Path
from typing import Any

from ..trading_logic.contracts import Pair, PaperRun, PaperTrade
from .report import MarkdownReportWriter


def _to_serializable(value: Any) -> Any:
    if is_dataclass(value):
        return {
            field.name: _to_serializable(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _to_serializable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_serializable(item) for item in value]
    return value


def _to_csv_value(value: Any) -> str:
    if isinstance(value, Pair):
        return value.symbol
    if isinstance(value, Enum):
        return str(value.value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if is_dataclass(value):
        return json.dumps(_to_serializable(value), sort_keys=True)
    if value is None:
        return ""
    return str(value)


class JsonArtifactStore:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir

    def write_json(self, relative_path: str, payload: Any) -> Path:
        path = self.base_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        content = _to_serializable(payload)
        path.write_text(json.dumps(content, indent=2), encoding="utf-8")
        return path


class CsvTradeLogWriter:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir

    def write_trades(self, relative_path: str, trades: list[PaperTrade]) -> Path:
        path = self.base_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        field_names = [field.name for field in fields(PaperTrade)]
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=field_names)
            writer.writeheader()
            for trade in trades:
                writer.writerow(
                    {
                        name: _to_csv_value(getattr(trade, name))
                        for name in field_names
                    }
                )
        return path


@dataclass(frozen=True)
class RunArtifactPaths:
    summary_path: Path
    run_metadata_path: Path
    trade_log_path: Path


@dataclass(frozen=True)
class RunArtifactWriter:
    report_writer: MarkdownReportWriter
    json_store: JsonArtifactStore
    trade_log_writer: CsvTradeLogWriter

    def write_outputs(
        self,
        *,
        run: PaperRun,
        as_of_round: datetime,
        open_positions: int,
        closed_trades: list[PaperTrade],
    ) -> RunArtifactPaths:
        summary_path = self.report_writer.write_summary(
            run=run,
            as_of_round=as_of_round,
            open_positions=open_positions,
            closed_trades=closed_trades,
        )
        run_metadata_path = self.json_store.write_json(
            f"runs/{run.run_id}.json",
            run,
        )
        trade_log_path = self.trade_log_writer.write_trades(
            f"trades/{run.run_id}.csv",
            closed_trades,
        )
        return RunArtifactPaths(
            summary_path=summary_path,
            run_metadata_path=run_metadata_path,
            trade_log_path=trade_log_path,
        )
