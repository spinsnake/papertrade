from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


UTC = timezone.utc


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(UTC)


@dataclass(frozen=True)
class FundingDecision:
    funding_round: datetime
    decision_cutoff: datetime


@dataclass(frozen=True)
class RoundScheduler:
    cadence_hours: int = 8
    decision_buffer_seconds: int = 30

    def __post_init__(self) -> None:
        if self.cadence_hours <= 0:
            raise ValueError("cadence_hours must be positive")
        if self.decision_buffer_seconds <= 0:
            raise ValueError("decision_buffer_seconds must be positive")

    @property
    def cadence(self) -> timedelta:
        return timedelta(hours=self.cadence_hours)

    @property
    def decision_buffer(self) -> timedelta:
        return timedelta(seconds=self.decision_buffer_seconds)

    def floor_round(self, value: datetime) -> datetime:
        value = ensure_utc(value)
        floored_hour = (value.hour // self.cadence_hours) * self.cadence_hours
        return value.replace(hour=floored_hour, minute=0, second=0, microsecond=0)

    def ceil_round(self, value: datetime) -> datetime:
        value = ensure_utc(value)
        floored = self.floor_round(value)
        if value == floored:
            return floored
        return floored + self.cadence

    def next_decision(self, now_utc: datetime) -> FundingDecision:
        now_utc = ensure_utc(now_utc)
        candidate = self.ceil_round(now_utc)
        cutoff = candidate - self.decision_buffer
        if now_utc > cutoff:
            candidate = candidate + self.cadence
            cutoff = candidate - self.decision_buffer
        return FundingDecision(funding_round=candidate, decision_cutoff=cutoff)

    def exit_round(self, entry_round: datetime) -> datetime:
        return ensure_utc(entry_round) + (self.cadence * 2)
