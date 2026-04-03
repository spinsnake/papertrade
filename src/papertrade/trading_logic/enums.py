from enum import Enum


class RunStatus(str, Enum):
    RUNNING = "running"
    BLOCKED = "blocked"
    FINISHED = "finished"
    FAILED = "failed"


class PositionState(str, Enum):
    OPEN = "open"
    CLOSED = "closed"
    SETTLEMENT_ERROR = "settlement_error"
