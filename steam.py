"""Steam detection, Steam account enumeration, and Steam Web API helpers."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import winreg  # type: ignore
except Exception:  # pragma: no cover - non-Windows fallback
    winreg = None  # type: ignore

import requests

from settings import get_avatar_cache_dir, get_profile_cache_path

LOGGER = logging.getLogger(__name__)

DEFAULT_STEAM_PATH = r"C:\Program Files (x86)\Steam"
STEAMID64_OFFSET = 76561197960265728
DOTA_APP_ID = "570"
PROFILE_CACHE_TTL = timedelta(days=1)


def _normalize_path(path: Optional[str]) -> str:
    if not path:
        return ""
    p = os.path.expandvars(os.path.expanduser(str(path).strip().strip('"')))
    # SteamPath in registry may use forward slashes
    p = p.replace("/", "\\")
    try:
        return str(Path(p).resolve())
    except Exception:
        return os.path.normpath(p)


def _is_valid_steam_root(path: str) -> bool:
    if not path:
        return False
    p = Path(path)
    if not p.exists() or not p.is_dir():
        return False
    # Heuristics: userdata folder or steam.exe/steamapps/libraryfolders.vdf
    if (p / "userdata").exists():
        return True
    if (p / "steam.exe").exists():
        return True
    if (p / "steamapps" / "libraryfolders.vdf").exists():
        return True
    return False


def _read_registry_value(root, subkey: str, value_name: str) -> Optional[str]:
    if winreg is None:
        return None
    try:
        with winreg.OpenKey(root, subkey) as key:
            value, _ = winreg.QueryValueEx(key, value_name)
            if isinstance(value, str) and value.strip():
                return value
    except OSError:
        return None
    except Exception:
        return None
    return None


def detect_steam_path() -> Optional[str]:
    """Try to detect Steam installation path.

    Checks (in order): default path, HKCU SteamPath, HKLM WOW6432Node InstallPath,
    HKLM InstallPath. Returns normalized path if valid, else None.
    """
    candidates: List[str] = []

    candidates.append(DEFAULT_STEAM_PATH)

    if winreg is not None:
        reg_lookups = [
            (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath"),
        ]
        for root, subkey, name in reg_lookups:
            val = _read_registry_value(root, subkey, name)
            if val:
                candidates.append(val)

    seen = set()
    for cand in candidates:
        norm = _normalize_path(cand)
        if not norm or norm.lower() in seen:
            continue
        seen.add(norm.lower())
        if _is_valid_steam_root(norm):
            return norm
    return None


def get_userdata_path(steam_path: str) -> Path:
    return Path(_normalize_path(steam_path)) / "userdata"


def is_numeric_steam_account_dir(name: str) -> bool:
    return bool(re.fullmatch(r"\d+", name))


def parse_libraryfolders_vdf(steam_path: str) -> List[str]:
    """Best-effort parse of libraryfolders.vdf to discover library roots.

    Not required for userdata (userdata lives in Steam root), but useful for diagnostics.
    """
    vdf_path = Path(_normalize_path(steam_path)) / "steamapps" / "libraryfolders.vdf"
    if not vdf_path.exists():
        return []
    try:
        text = vdf_path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return []
    # Simple regex-based extraction of "path" values
    paths = re.findall(r'"path"\s*"([^"]+)"', text, flags=re.IGNORECASE)
    result = []
    for p in paths:
        norm = _normalize_path(p.replace("\\\\", "\\"))
        if norm and norm not in result:
            result.append(norm)
    return result

