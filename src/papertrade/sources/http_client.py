from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Mapping
from urllib.parse import urlencode
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class HttpJsonClient:
    timeout_seconds: float = 10.0
    user_agent: str = "papertrade/0.1"

    def get_json(
        self,
        base_url: str,
        path: str,
        params: Mapping[str, str] | None = None,
    ) -> Any:
        query = ""
        if params:
            query = f"?{urlencode(params)}"
        request = Request(
            f"{base_url.rstrip('/')}{path}{query}",
            headers={
                "Accept": "application/json",
                "User-Agent": self.user_agent,
            },
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
