from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any


DEFAULT_PROFILE = {
    "preferred_theme_id": "",
    "brand_note": "",
    "assets": [],
}

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


class UserProfileStore:
    def __init__(self, root: Path):
        self.root = root
        self.path = root / "user_profiles.json"
        self.asset_root = root / "assets"
        self.root.mkdir(parents=True, exist_ok=True)
        self.asset_root.mkdir(parents=True, exist_ok=True)

    def _read_all(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write_all(self, data: dict[str, Any]) -> None:
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.chmod(temporary, 0o600)
        temporary.replace(self.path)
        os.chmod(self.path, 0o600)

    def get(self, user_id: int | str | None) -> dict[str, Any]:
        if user_id is None:
            return dict(DEFAULT_PROFILE)
        stored = self._read_all().get(str(user_id), {})
        return {**DEFAULT_PROFILE, **stored}

    def save(self, user_id: int | str | None, profile: dict[str, Any]) -> dict[str, Any]:
        if user_id is None:
            return profile
        data = self._read_all()
        current = self.get(user_id)
        current.update({key: value for key, value in profile.items() if key in DEFAULT_PROFILE})
        data[str(user_id)] = current
        self._write_all(data)
        return current

    def clear(self, user_id: int | str | None) -> None:
        if user_id is None:
            return
        data = self._read_all()
        data.pop(str(user_id), None)
        self._write_all(data)
        folder = self.asset_root / str(user_id)
        if folder.exists():
            shutil.rmtree(folder)

    def add_asset(
        self,
        user_id: int | str | None,
        source: Path,
        file_name: str,
        role: str,
    ) -> dict[str, Any]:
        if user_id is None:
            raise ValueError("لا يمكن حفظ الهوية دون معرف مستخدم")
        suffix = source.suffix.lower()
        if suffix not in IMAGE_SUFFIXES:
            raise ValueError("نوع الصورة غير مدعوم")
        folder = self.asset_root / str(user_id)
        folder.mkdir(parents=True, exist_ok=True)
        safe_role = role if role in {"logo", "stamp", "cover", "background"} else "logo"
        existing = self.get(user_id).get("assets", [])
        target = folder / f"{safe_role}-{len(existing) + 1}{suffix}"
        shutil.copyfile(source, target)
        asset = {"path": str(target), "file_name": file_name, "role": safe_role}
        assets = [
            item
            for item in existing
            if item.get("role") != safe_role or safe_role == "background"
        ]
        assets.append(asset)
        self.save(user_id, {"assets": assets[-8:]})
        return asset


def infer_asset_role(text: str = "") -> str:
    lowered = text.lower()
    if any(word in lowered for word in ("ختم", "stamp")):
        return "stamp"
    if any(word in lowered for word in ("غلاف", "cover")):
        return "cover"
    if any(word in lowered for word in ("خلفية", "background")):
        return "background"
    return "logo"
