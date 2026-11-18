"""Application settings management."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict

APP_NAME = "Dota 2 Config Switcher"
SETTINGS_FILENAME = "settings.json"
CACHE_DIRNAME = "cache"
AVATAR_CACHE_DIRNAME = "avatars"
LOG_FILENAME = "app.log"


def get_base_dir() -> Path:
    """Return directory where settings/configs are stored by default.

    - Frozen (PyInstaller): directory of the executable
    - Source: directory of this file/project root
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def get_settings_path() -> Path:
    return get_base_dir() / SETTINGS_FILENAME


def get_default_configs_dir() -> Path:
    return get_base_dir()


def get_cache_dir() -> Path:
    path = get_base_dir() / CACHE_DIRNAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_avatar_cache_dir() -> Path:
    path = get_cache_dir() / AVATAR_CACHE_DIRNAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_log_path() -> Path:
    return get_base_dir() / LOG_FILENAME


def default_settings() -> Dict[str, Any]:
    return {
        "steam_path": "",
        "selected_account_id": "",
        "configs_dir": str(get_default_configs_dir()),
    }


def load_settings() -> Dict[str, Any]:
    settings = default_settings()
    path = get_settings_path()
    if not path.exists():
        return settings
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            for key in settings:
                if key in data and data[key] is not None:
                    settings[key] = data[key]
    except Exception:
        # Corrupt/unreadable settings -> fall back to defaults
        return default_settings()
    # Normalize types/values lightly
    settings["steam_path"] = str(settings.get("steam_path") or "")
    settings["selected_account_id"] = str(settings.get("selected_account_id") or "")
    settings["configs_dir"] = str(settings.get("configs_dir") or get_default_configs_dir())
    # Ignore legacy keys from older versions (e.g. api_key, check_avatar_updates)
    return settings


def save_settings(settings: Dict[str, Any]) -> None:
    path = get_settings_path()
    data = default_settings()
    if settings:
        for k in data.keys():
            if k in settings:
                data[k] = settings[k]
    # Only persist known settings (drops legacy keys like api_key)
    tmp_path = path.with_suffix(".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)

