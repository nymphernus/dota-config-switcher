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


def enumerate_accounts(steam_path: str) -> List[Dict[str, Any]]:
    """Enumerate Steam accounts from userdata folder.

    Returns list of dicts: {"account_id": str, "has_dota": bool, "path": str}
    sorted by account_id.
    """
    userdata = get_userdata_path(steam_path)
    accounts: List[Dict[str, Any]] = []
    if not userdata.exists() or not userdata.is_dir():
        return accounts
    try:
        for entry in userdata.iterdir():
            if not entry.is_dir():
                continue
            if not is_numeric_steam_account_dir(entry.name):
                continue
            has_dota = (entry / DOTA_APP_ID).exists()
            accounts.append(
                {
                    "account_id": entry.name,
                    "has_dota": has_dota,
                    "path": str(entry),
                }
            )
    except Exception as e:
        LOGGER.exception("Failed to enumerate Steam accounts in %s: %s", userdata, e)
        return []
    accounts.sort(key=lambda x: int(x["account_id"]) if str(x["account_id"]).isdigit() else str(x["account_id"]))
    return accounts


def to_steamid64(account_id: str | int) -> str:
    return str(int(account_id) + STEAMID64_OFFSET)


def _load_profile_cache() -> Dict[str, Any]:
    path = get_profile_cache_path()
    if not path.exists():
        return {"profiles": {}}
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"profiles": {}}
        profiles = data.get("profiles")
        if not isinstance(profiles, dict):
            data["profiles"] = {}
        return data
    except Exception:
        return {"profiles": {}}


def _save_profile_cache(cache: Dict[str, Any]) -> None:
    path = get_profile_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    try:
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception as e:
        LOGGER.warning("Failed to save profile cache: %s", e)


def _parse_ts(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        # ISO format
        return datetime.fromisoformat(str(value))
    except Exception:
        return None


def _is_profile_fresh(entry: Dict[str, Any], force_refresh: bool = False) -> bool:
    if force_refresh:
        return False
    ts = _parse_ts(entry.get("updated_at"))
    if not ts:
        return False
    return datetime.now() - ts < PROFILE_CACHE_TTL


def _download_avatar(url: str, dest: Path, timeout: float = 10.0) -> bool:
    if not url:
        return False
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        with tmp.open("wb") as f:
            f.write(resp.content)
        os.replace(tmp, dest)
        return True
    except Exception as e:
        LOGGER.warning("Failed to download avatar %s: %s", url, e)
        return False


def fetch_profiles_from_api(account_ids: List[str], api_key: str) -> Dict[str, Dict[str, Any]]:
    """Fetch Steam profiles for account IDs. Returns mapping account_id -> profile info."""
    result: Dict[str, Dict[str, Any]] = {}
    if not api_key or not account_ids:
        return result
    steamid64s = [to_steamid64(aid) for aid in account_ids]
    # API supports up to 100 steamids per request; our use case is small
    url = "https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/"
    try:
        resp = requests.get(
            url,
            params={"key": api_key, "steamids": ",".join(steamid64s)},
            timeout=10,
        )
        if resp.status_code == 401 or resp.status_code == 403:
            raise PermissionError("Неверный или недействительный Steam API-ключ.")
        resp.raise_for_status()
        data = resp.json()
        players = (((data or {}).get("response") or {}).get("players") or [])
        by_sid64 = {str(p.get("steamid")): p for p in players if p.get("steamid")}
        for aid in account_ids:
            sid64 = to_steamid64(aid)
            p = by_sid64.get(sid64)
            if not p:
                continue
            result[aid] = {
                "personaname": p.get("personaname") or "",
                "avatarfull": p.get("avatarfull") or p.get("avatarmedium") or p.get("avatar") or "",
                "profileurl": p.get("profileurl") or "",
            }
    except PermissionError:
        raise
    except Exception as e:
        LOGGER.warning("Steam API request failed: %s", e)
        return {}
    return result


def get_account_profiles(
    account_ids: List[str],
    api_key: str = "",
    force_refresh: bool = False,
) -> Dict[str, Dict[str, Any]]:
    """Return profiles for accounts using cache and Steam API when available.

    Result per account_id: {
        "personaname": str,
        "avatar_path": str|None,  # local cached file path
        "avatar_url": str,
        "updated_at": str|None,
        "source": "cache"|"api"|"none"
    }
    """
    cache = _load_profile_cache()
    profiles_cache: Dict[str, Any] = cache.setdefault("profiles", {})
    avatar_dir = get_avatar_cache_dir()

    # Normalize account ids as strings
    account_ids = [str(a) for a in account_ids]
    result: Dict[str, Dict[str, Any]] = {}

    # Seed from cache
    stale_ids: List[str] = []
    for aid in account_ids:
        entry = profiles_cache.get(aid) if isinstance(profiles_cache.get(aid), dict) else {}
        avatar_path = entry.get("avatar_path")
        if avatar_path and not Path(avatar_path).exists():
            avatar_path = None
        result[aid] = {
            "personaname": entry.get("personaname") or "",
            "avatar_path": avatar_path,
            "avatar_url": entry.get("avatar_url") or "",
            "updated_at": entry.get("updated_at"),
            "source": "cache" if entry else "none",
        }
        if not _is_profile_fresh(entry, force_refresh=force_refresh):
            stale_ids.append(aid)

    # Fetch stale from API if key provided
    api_profiles: Dict[str, Dict[str, Any]] = {}
    api_error: Optional[Exception] = None
    if api_key and stale_ids:
        try:
            api_profiles = fetch_profiles_from_api(stale_ids, api_key)
        except Exception as e:
            api_error = e
            LOGGER.warning("Failed to refresh profiles from API: %s", e)

    now_iso = datetime.now().isoformat(timespec="seconds")
    for aid in stale_ids:
        api_p = api_profiles.get(aid)
        if not api_p:
            # keep cached data if present; if force refresh and nothing cached, leave as-is
            continue
        avatar_url = api_p.get("avatarfull") or ""
        # choose extension from url if possible
        ext = ".jpg"
        m = re.search(r"\.(jpg|jpeg|png|webp)(?:\?|$)", avatar_url, re.IGNORECASE)
        if m:
            ext = "." + m.group(1).lower().replace("jpeg", "jpg")
        avatar_path = str(avatar_dir / f"{aid}{ext}")
        if avatar_url:
            downloaded = _download_avatar(avatar_url, Path(avatar_path))
            if not downloaded and result[aid].get("avatar_path"):
                avatar_path = result[aid]["avatar_path"]
            elif not downloaded:
                avatar_path = None
        else:
            avatar_path = result[aid].get("avatar_path")

        entry = {
            "personaname": api_p.get("personaname") or "",
            "avatar_url": avatar_url,
            "avatar_path": avatar_path,
            "updated_at": now_iso,
        }
        profiles_cache[aid] = entry
        result[aid] = {**entry, "source": "api"}

    # Persist cache updates if we attempted refreshes or modified structure
    if stale_ids:
        cache["profiles"] = profiles_cache
        cache["saved_at"] = now_iso
        _save_profile_cache(cache)

    # Propagate permission errors to caller? no, caller can decide; but useful to know.
    # We'll attach a special marker on result via exception in caller flow when needed.
    if api_error and isinstance(api_error, PermissionError):
        raise api_error

    return result


