"""Application settings management."""

from __future__ import annotations

import json
import logging
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, Tuple

APP_NAME = "DotaConfigSwitcher"
SETTINGS_FILENAME = "settings.json"
CONFIGS_DIRNAME = "configs"
CACHE_DIRNAME = "cache"
AVATAR_CACHE_DIRNAME = "avatars"
LOG_FILENAME = "app.log"

LOGGER = logging.getLogger(__name__)
_LAST_MIGRATION_MESSAGE = ""


def get_last_migration_message() -> str:
    return _LAST_MIGRATION_MESSAGE


def get_legacy_base_dir() -> Path:
    """Return old storage directory (next to EXE or project root)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def get_app_data_dir() -> Path:
    """Return application data directory in %APPDATA%/DotaConfigSwitcher."""
    appdata = os.getenv("APPDATA")
    if appdata:
        base = Path(appdata)
    else:
        base = Path.home() / "AppData" / "Roaming"
    path = base / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_base_dir() -> Path:
    """Return directory where app data is stored (AppData)."""
    return get_app_data_dir()


def get_settings_path() -> Path:
    return get_base_dir() / SETTINGS_FILENAME


def get_default_configs_dir() -> Path:
    path = get_base_dir() / CONFIGS_DIRNAME
    path.mkdir(parents=True, exist_ok=True)
    return path


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


def get_resource_path(*parts: str) -> Path:
    """Return path to a bundled/read-only resource (works in dev and PyInstaller onefile)."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        base = Path(getattr(sys, "_MEIPASS"))
    else:
        base = Path(__file__).resolve().parent
    return base.joinpath(*parts)


def default_settings() -> Dict[str, Any]:
    return {
        "steam_path": "",
        "selected_account_id": "",
        "favorite_account_id": "",
        "configs_dir": str(get_default_configs_dir()),
        "last_applied_config": "",
        "migrated_from_legacy": False,
    }


def _is_valid_config_dir(path: Path) -> bool:
    return path.is_dir() and (path / "570").is_dir()


def _unique_destination_path(dst: Path) -> Path:
    if not dst.exists():
        return dst
    stem = dst.name
    parent = dst.parent
    for i in range(1, 1000):
        candidate = parent / f"{stem} (migrated {i})"
        if not candidate.exists():
            return candidate
    return parent / f"{stem} (migrated)"


def migrate_legacy_data_if_needed() -> Tuple[bool, str]:
    """Migrate legacy settings/configs/cache from old base dir to AppData.

    Returns (migrated, message).
    """
    app_dir = get_app_data_dir()
    legacy_dir = get_legacy_base_dir()
    try:
        if legacy_dir.resolve() == app_dir.resolve():
            return False, ""
    except Exception:
        if str(legacy_dir) == str(app_dir):
            return False, ""

    new_settings_path = app_dir / SETTINGS_FILENAME
    legacy_settings_path = legacy_dir / SETTINGS_FILENAME
    legacy_configs_dir_setting: str = ""

    # Read legacy settings if present (best-effort)
    legacy_data: Dict[str, Any] = {}
    if legacy_settings_path.exists():
        try:
            with legacy_settings_path.open("r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                legacy_data = loaded
                legacy_configs_dir_setting = str(loaded.get("configs_dir") or "")
        except Exception:
            legacy_data = {}

    # If AppData settings already exist, consider migration already handled unless explicitly needed.
    if new_settings_path.exists():
        # Still try to migrate stray legacy configs into AppData configs dir if empty-ish? keep simple.
        return False, ""

    migrated_any = False
    notes = []

    # Ensure target dirs
    new_configs_dir = get_default_configs_dir()
    new_cache_dir = get_cache_dir()
    new_avatar_cache_dir = get_avatar_cache_dir()

    # Migrate settings.json
    if legacy_settings_path.exists():
        try:
            data = dict(legacy_data) if isinstance(legacy_data, dict) else {}
            # Force configs_dir to AppData configs dir (old may point to legacy location)
            data["configs_dir"] = str(new_configs_dir)
            data["migrated_from_legacy"] = True
            # Keep known legacy values if present
            for k in ("steam_path", "selected_account_id", "favorite_account_id", "last_applied_config"):
                if k not in data:
                    data[k] = default_settings().get(k, "")
            tmp_path = new_settings_path.with_suffix(".tmp")
            with tmp_path.open("w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, new_settings_path)
            migrated_any = True
            notes.append("настройки")
        except Exception as e:
            LOGGER.warning("Failed to migrate legacy settings: %s", e)

    # Migrate cache/avatars
    legacy_cache_dir = legacy_dir / CACHE_DIRNAME
    if legacy_cache_dir.exists() and legacy_cache_dir.is_dir():
        try:
            for src in legacy_cache_dir.rglob("*"):
                if not src.is_file():
                    continue
                rel = src.relative_to(legacy_cache_dir)
                dst = new_cache_dir / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                if not dst.exists():
                    shutil.copy2(src, dst)
            migrated_any = True
            notes.append("кэш")
        except Exception as e:
            LOGGER.warning("Failed to migrate legacy cache: %s", e)

    # Migrate config folders into AppData configs/
    config_sources = set()
    if legacy_configs_dir_setting:
        try:
            config_sources.add(Path(legacy_configs_dir_setting))
        except Exception:
            pass
    config_sources.add(legacy_dir)

    moved_configs = 0
    for src_root in list(config_sources):
        try:
            if not src_root.exists() or not src_root.is_dir():
                continue
            # Avoid migrating from inside target
            try:
                if src_root.resolve() == new_configs_dir.resolve():
                    continue
            except Exception:
                pass
            for entry in src_root.iterdir():
                try:
                    if not _is_valid_config_dir(entry):
                        continue
                    dst = new_configs_dir / entry.name
                    if dst.exists():
                        # If destination exists, keep both (copy to unique name)
                        dst = _unique_destination_path(dst)
                    shutil.copytree(entry, dst)
                    moved_configs += 1
                except Exception as e:
                    LOGGER.warning("Failed to migrate config folder %s: %s", entry, e)
        except Exception as e:
            LOGGER.warning("Failed scanning legacy configs in %s: %s", src_root, e)

    if moved_configs:
        migrated_any = True
        notes.append(f"конфиги ({moved_configs})")

    # If no legacy settings existed but we migrated configs/cache, create settings in AppData
    if migrated_any and not new_settings_path.exists():
        try:
            data = default_settings()
            data["migrated_from_legacy"] = True
            with new_settings_path.open("w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            LOGGER.warning("Failed to create settings after migration: %s", e)

    if migrated_any:
        msg = "Данные перенесены в AppData: " + ", ".join(notes) + "."
        return True, msg
    return False, ""


def load_settings() -> Dict[str, Any]:
    # Best-effort migration before loading
    global _LAST_MIGRATION_MESSAGE
    try:
        migrated, msg = migrate_legacy_data_if_needed()
        if migrated:
            _LAST_MIGRATION_MESSAGE = msg
    except Exception as e:
        LOGGER.warning("Legacy migration failed: %s", e)

    settings = default_settings()
    path = get_settings_path()
    if not path.exists():
        # Ensure configs dir exists for fresh installs
        get_default_configs_dir()
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
    settings["favorite_account_id"] = str(settings.get("favorite_account_id") or "")
    settings["configs_dir"] = str(settings.get("configs_dir") or get_default_configs_dir())
    settings["last_applied_config"] = str(settings.get("last_applied_config") or "")
    settings["migrated_from_legacy"] = bool(settings.get("migrated_from_legacy", False))

    # Ensure configs dir exists
    try:
        Path(settings["configs_dir"]).mkdir(parents=True, exist_ok=True)
    except Exception:
        settings["configs_dir"] = str(get_default_configs_dir())
    return settings


def save_settings(settings: Dict[str, Any]) -> None:
    path = get_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = default_settings()
    if settings:
        for k in data.keys():
            if k in settings:
                data[k] = settings[k]
    # Normalize known string fields
    data["steam_path"] = str(data.get("steam_path") or "")
    data["selected_account_id"] = str(data.get("selected_account_id") or "")
    data["favorite_account_id"] = str(data.get("favorite_account_id") or "")
    data["configs_dir"] = str(data.get("configs_dir") or get_default_configs_dir())
    data["last_applied_config"] = str(data.get("last_applied_config") or "")
    # Only persist known settings (drops legacy keys like api_key)
    tmp_path = path.with_suffix(".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


