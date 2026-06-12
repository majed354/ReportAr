from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


class SafeHttpError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(f"HTTP {status}: {message}")
        self.status = status


def request_json(
    method: str,
    url: str,
    *,
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 120,
) -> dict[str, Any]:
    body = None
    safe_headers = {"Accept": "application/json", **(headers or {})}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        safe_headers["Content-Type"] = "application/json"

    request = urllib.request.Request(url, data=body, headers=safe_headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content = response.read().decode("utf-8")
            return json.loads(content) if content else {}
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw)
            message = (
                parsed.get("error", {}).get("message")
                if isinstance(parsed.get("error"), dict)
                else parsed.get("error") or parsed.get("message")
            )
        except json.JSONDecodeError:
            message = raw
        raise SafeHttpError(error.code, str(message or "request failed")[:500]) from None
    except urllib.error.URLError as error:
        raise SafeHttpError(0, str(error.reason)[:500]) from None
