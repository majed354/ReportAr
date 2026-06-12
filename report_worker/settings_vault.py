from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


DEFAULTS = {
    "telegram_bot_token": "",
    "gemini_api_key": "",
    "provider": "local",
    "fallback_provider": "",
    "ollama_base_url": "http://127.0.0.1:11434",
    "ollama_model": "gemma4:31b",
    "gemini_model": "gemini-3.5-flash",
    "allowed_telegram_users": "",
    "enable_web_research": False,
}
SECRET_FIELDS = {"telegram_bot_token", "gemini_api_key"}


class SettingsVault:
    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return dict(DEFAULTS)
        stored = json.loads(self.path.read_text(encoding="utf-8"))
        return {**DEFAULTS, **stored}

    def save(self, updates: dict[str, Any]) -> dict[str, Any]:
        current = self.load()
        for key, value in updates.items():
            if key not in DEFAULTS:
                continue
            if key in SECRET_FIELDS and not value:
                continue
            current[key] = value
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.chmod(temporary, 0o600)
        temporary.replace(self.path)
        os.chmod(self.path, 0o600)
        return current

    def public(self) -> dict[str, Any]:
        settings = self.load()
        return {
            key: ("محفوظ" if settings.get(key) else "غير محفوظ")
            if key in SECRET_FIELDS
            else settings.get(key)
            for key in DEFAULTS
        }

    def allowed_users(self) -> set[int]:
        raw = str(self.load().get("allowed_telegram_users", ""))
        return {
            int(item.strip())
            for item in raw.split(",")
            if item.strip().lstrip("-").isdigit()
        }
