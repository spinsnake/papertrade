from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
from typing import Any


class JsonArtifactStore:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir

    def write_json(self, relative_path: str, payload: Any) -> Path:
        path = self.base_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        if hasattr(payload, "__dataclass_fields__"):
            content = asdict(payload)
        else:
            content = payload
        path.write_text(json.dumps(content, indent=2, default=str), encoding="utf-8")
        return path
