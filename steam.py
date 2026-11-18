"""Steam detection, Steam account enumeration, and local profile reading."""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import winreg  # type: ignore
except Exception:  # pragma: no cover - non-Windows fallback
    winreg = None  # type: ignore

from settings import get_avatar_cache_dir

LOGGER = logging.getLogger(__name__)

DEFAULT_STEAM_PATH = r"C:\Program Files (x86)\Steam"
STEAMID64_OFFSET = 76561197960265728
DOTA_APP_ID = "570"


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


@dataclass
class SteamAccount:
    account_id: int            # из имени папки userdata
    steam_id64: int            # account_id + 76561197960265728
    persona_name: str          # из loginusers.vdf, fallback localconfig.vdf
    account_name: Optional[str]  # из loginusers.vdf
    avatar_path: Optional[Path]  # путь к локальному файлу аватарки или None
    has_dota: bool             # есть ли userdata\<id>\570


def _strip_bom(text: str) -> str:
    if text.startswith("\ufeff"):
        return text.lstrip("\ufeff")
    return text


def parse_vdf_text(text: str) -> Dict[str, Any]:
    """Parse Valve Data Format (VDF) text into nested dicts.

    Supports quoted keys/values, nested blocks in {}, // comments, BOM and CRLF.
    Returns {} on parse errors.
    """
    try:
        text = _strip_bom(text or "")
        i = 0
        n = len(text)

        def skip_ws_and_comments() -> None:
            nonlocal i
            while i < n:
                ch = text[i]
                if ch in " \t\r\n":
                    i += 1
                    continue
                if ch == "/" and i + 1 < n and text[i + 1] == "/":
                    # comment until end of line
                    i += 2
                    while i < n and text[i] not in "\r\n":
                        i += 1
                    continue
                break

        def parse_string_token() -> str:
            nonlocal i
            if i >= n:
                raise ValueError("Unexpected end of VDF while reading token")
            ch = text[i]
            if ch == '"':
                i += 1
                out = []
                while i < n:
                    c = text[i]
                    if c == "\\" and i + 1 < n:
                        # basic escape handling
                        nxt = text[i + 1]
                        if nxt in ['"', "\\"]:
                            out.append(nxt)
                            i += 2
                            continue
                        # keep escaped char as-is (e.g. \n)
                        out.append(nxt)
                        i += 2
                        continue
                    if c == '"':
                        i += 1
                        return "".join(out)
                    out.append(c)
                    i += 1
                raise ValueError("Unterminated quoted string in VDF")
            else:
                # unquoted token until whitespace, brace, or comment
                start = i
                while i < n:
                    c = text[i]
                    if c in " \t\r\n{}":
                        break
                    if c == "/" and i + 1 < n and text[i + 1] == "/":
                        break
                    i += 1
                if start == i:
                    raise ValueError("Expected token in VDF")
                return text[start:i]

        def parse_object() -> Dict[str, Any]:
            nonlocal i
            obj: Dict[str, Any] = {}
            while True:
                skip_ws_and_comments()
                if i >= n:
                    break
                if text[i] == "}":
                    i += 1
                    break
                key = parse_string_token()
                skip_ws_and_comments()
                if i >= n:
                    raise ValueError("Unexpected end of VDF after key")
                if text[i] == "{":
                    i += 1
                    value = parse_object()
                else:
                    value = parse_string_token()
                obj[key] = value
            return obj

        # Parse top-level key/value pairs (common VDF files have one root object)
        root: Dict[str, Any] = {}
        while True:
            skip_ws_and_comments()
            if i >= n:
                break
            # tolerate stray closing brace
            if text[i] == "}":
                i += 1
                continue
            key = parse_string_token()
            skip_ws_and_comments()
            if i >= n:
                raise ValueError("Unexpected end of VDF after top-level key")
            if text[i] == "{":
                i += 1
                value = parse_object()
            else:
                value = parse_string_token()
            root[key] = value
        return root
    except Exception as e:
        LOGGER.warning("Failed to parse VDF: %s", e)
        return {}


def load_vdf(path: str | Path) -> Dict[str, Any]:
    p = Path(path)
    try:
        # utf-8-sig handles BOM; errors ignored for robustness
        text = p.read_text(encoding="utf-8-sig", errors="ignore")
    except Exception as e:
        LOGGER.warning("Failed to read VDF file %s: %s", p, e)
        return {}
    return parse_vdf_text(text)


def read_loginusers_vdf(steam_path: str | Path) -> Dict[int, Dict[str, Any]]:
    """Read <steam>/config/loginusers.vdf.

    Returns mapping account_id (int) -> {steam_id64, persona_name, account_name, ...}.
    """
    path = Path(_normalize_path(str(steam_path))) / "config" / "loginusers.vdf"
    data = load_vdf(path)
    users = data.get("users") if isinstance(data, dict) else None
    if not isinstance(users, dict):
        # sometimes file structure differs; try root if it looks like users map
        users = data if isinstance(data, dict) else {}
    result: Dict[int, Dict[str, Any]] = {}
    for key, value in users.items():
        if not isinstance(value, dict):
            continue
        sid64_str = str(key).strip()
        if not sid64_str.isdigit():
            # sometimes nested differently; skip
            continue
        try:
            sid64 = int(sid64_str)
            account_id = sid64 - STEAMID64_OFFSET
            if account_id < 0:
                continue
        except Exception:
            continue
        persona = str(value.get("PersonaName") or "").strip()
        account_name = str(value.get("AccountName") or "").strip() or None
        if not persona and account_name:
            persona = account_name
        result[int(account_id)] = {
            "account_id": int(account_id),
            "steam_id64": int(sid64),
            "persona_name": persona,
            "account_name": account_name,
            "timestamp": value.get("Timestamp"),
            "most_recent": value.get("MostRecent"),
        }
    return result


def _find_persona_name_in_vdf(obj: Any) -> Optional[str]:
    """Recursively find first PersonaName string in a parsed VDF structure."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if str(k).lower() == "personaname" and isinstance(v, str) and v.strip():
                return v.strip()
        for v in obj.values():
            found = _find_persona_name_in_vdf(v)
            if found:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = _find_persona_name_in_vdf(v)
            if found:
                return found
    return None


def read_localconfig_persona_name(steam_path: str | Path, account_id: str | int) -> Optional[str]:
    """Fallback: read PersonaName from userdata/<account_id>/config/localconfig.vdf."""
    path = Path(_normalize_path(str(steam_path))) / "userdata" / str(account_id) / "config" / "localconfig.vdf"
    if not path.exists():
        return None
    data = load_vdf(path)
    if not data:
        return None
    # Prefer friends section if present
    try:
        root = data.get("UserLocalConfigStore") if isinstance(data, dict) else None
        if isinstance(root, dict):
            friends = root.get("friends")
            if isinstance(friends, dict):
                name = _find_persona_name_in_vdf(friends)
                if name:
                    return name
    except Exception:
        pass
    # Fallback: first PersonaName anywhere
    name = _find_persona_name_in_vdf(data)
    return name or None


def get_local_profile_info(steam_path: str | Path, account_id: str | int) -> Dict[str, Optional[str]]:
    """Resolve persona/account name from local Steam files.

    Returns {"persona_name": str|None, "account_name": str|None, "source": str}
    source in {"loginusers.vdf", "localconfig.vdf", "none"}.
    """
    aid_int = int(account_id)
    loginusers = read_loginusers_vdf(steam_path)
    lu = loginusers.get(aid_int)
    if lu:
        persona = (lu.get("persona_name") or "").strip() or None
        account_name = (lu.get("account_name") or None)
        if not persona and account_name:
            persona = account_name
        if persona:
            return {"persona_name": persona, "account_name": account_name, "source": "loginusers.vdf"}
        # loginusers entry exists but no name -> try localconfig before giving up account_name
    persona_local = read_localconfig_persona_name(steam_path, aid_int)
    if persona_local:
        account_name = lu.get("account_name") if lu else None
        return {"persona_name": persona_local, "account_name": account_name, "source": "localconfig.vdf"}
    if lu and (lu.get("account_name") or "").strip():
        return {
            "persona_name": str(lu.get("account_name")).strip(),
            "account_name": lu.get("account_name"),
            "source": "loginusers.vdf",
        }
    return {"persona_name": None, "account_name": lu.get("account_name") if lu else None, "source": "none"}


def _is_image_file(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            head = f.read(16)
        if head.startswith(b"\x89PNG\r\n\x1a\n"):
            return True
        if head.startswith(b"\xff\xd8\xff"):
            return True
        if head.startswith(b"RIFF") and b"WEBP" in head:
            return True
        if head.startswith(b"BM"):
            return True
        return False
    except Exception:
        return False


def find_avatarcache_image(steam_path: str | Path, account_id: int, steam_id64: int) -> Optional[Path]:
    """Best-effort search for an avatar image in Steam's avatarcache."""
    cache_dir = Path(_normalize_path(str(steam_path))) / "config" / "avatarcache"
    if not cache_dir.exists() or not cache_dir.is_dir():
        return None

    sid_str = str(steam_id64)
    aid_str = str(account_id)
    candidates: List[Path] = []
    try:
        # Prefer filename matches
        for p in cache_dir.iterdir():
            if not p.is_file():
                continue
            name = p.name.lower()
            if sid_str in name or aid_str in name:
                if _is_image_file(p):
                    return p
                candidates.append(p)
        # Fallback: if exactly one image file exists, can't reliably map to account -> skip
        # (best-effort without false association). Also try files that are images anyway? no mapping.
    except Exception as e:
        LOGGER.warning("Failed to scan avatarcache: %s", e)
        return None

    # If filename matched but signature check failed above (e.g. extensionless), try PIL open lazily later
    for p in candidates:
        try:
            from PIL import Image  # type: ignore
            with Image.open(p) as im:
                im.verify()
            return p
        except Exception:
            continue
    return None


def _deterministic_avatar_color(account_id: int) -> Tuple[int, int, int]:
    # Pleasant deterministic palette-ish color from account id
    h = (account_id * 2654435761) & 0xFFFFFFFF
    r = 60 + (h & 0x7F)
    g = 60 + ((h >> 8) & 0x7F)
    b = 60 + ((h >> 16) & 0x7F)
    return (r, g, b)


def generate_fallback_avatar(account_id: int, persona_name: str, out_path: Path, size: int = 128) -> Optional[Path]:
    try:
        from PIL import Image, ImageDraw, ImageFont  # type: ignore
    except Exception as e:
        LOGGER.warning("Pillow is not available for fallback avatar generation: %s", e)
        return None

    try:
        name = (persona_name or "").strip()
        letter = "?"
        if name:
            # Prefer first alphabetic/digit char
            for ch in name:
                if ch.strip():
                    letter = ch.upper()
                    break
        bg = _deterministic_avatar_color(int(account_id))
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse((0, 0, size - 1, size - 1), fill=bg + (255,))

        # Font
        font = None
        font_size = int(size * 0.5)
        for font_name in ("segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"):
            try:
                font = ImageFont.truetype(font_name, font_size)
                break
            except Exception:
                continue
        if font is None:
            font = ImageFont.load_default()

        text = letter
        try:
            bbox = draw.textbbox((0, 0), text, font=font)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
        except Exception:
            tw, th = draw.textsize(text, font=font)  # type: ignore[attr-defined]
        x = (size - tw) / 2
        y = (size - th) / 2 - size * 0.04
        draw.text((x, y), text, fill=(245, 247, 255, 255), font=font)

        out_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = out_path.with_suffix(".tmp.png")
        img.save(tmp, format="PNG")
        os.replace(tmp, out_path)
        return out_path
    except Exception as e:
        LOGGER.warning("Failed to generate fallback avatar for %s: %s", account_id, e)
        return None


def resolve_avatar_path(steam_path: str | Path, account_id: int, steam_id64: int, persona_name: str) -> Optional[str]:
    """Resolve local avatar path (cached). Creates/updates cache from avatarcache or fallback."""
    cache_dir = get_avatar_cache_dir()
    cached_path = cache_dir / f"{account_id}.png"

    src = find_avatarcache_image(steam_path, account_id, steam_id64)
    if src and src.exists():
        try:
            src_mtime = src.stat().st_mtime
            need_update = True
            if cached_path.exists():
                try:
                    need_update = src_mtime > cached_path.stat().st_mtime
                except Exception:
                    need_update = True
            if need_update:
                try:
                    from PIL import Image  # type: ignore
                    with Image.open(src) as im:
                        im = im.convert("RGBA")
                        tmp = cached_path.with_suffix(".tmp.png")
                        im.save(tmp, format="PNG")
                    os.replace(tmp, cached_path)
                except Exception as e:
                    # If PIL can't read, try raw copy only if already png-like? otherwise fallback
                    LOGGER.warning("Failed to convert avatarcache image %s: %s", src, e)
            if cached_path.exists():
                return str(cached_path)
        except Exception as e:
            LOGGER.warning("Avatar cache update failed for %s: %s", account_id, e)

    # Fallback generated avatar (refresh each time in case name initial changes)
    fb = generate_fallback_avatar(account_id, persona_name, cached_path)
    if fb and fb.exists():
        return str(fb)
    return str(cached_path) if cached_path.exists() else None


def get_local_profiles(steam_path: str | Path, account_ids: List[str | int]) -> Dict[str, Dict[str, Any]]:
    """Build local profile data for accounts (no network).

    Result per account_id (str): {
        "personaname": str,
        "account_name": str|None,
        "avatar_path": str|None,
        "source": str,  # loginusers.vdf/localconfig.vdf/none
    }
    """
    result: Dict[str, Dict[str, Any]] = {}
    loginusers = read_loginusers_vdf(steam_path)
    for aid in account_ids:
        aid_str = str(aid)
        try:
            aid_int = int(aid)
        except Exception:
            result[aid_str] = {
                "personaname": f"SteamID: {aid_str}",
                "account_name": None,
                "avatar_path": None,
                "source": "none",
            }
            continue

        lu = loginusers.get(aid_int)
        persona = None
        account_name = lu.get("account_name") if lu else None
        source = "none"
        if lu:
            persona = (lu.get("persona_name") or "").strip() or None
            if not persona and account_name:
                persona = str(account_name).strip() or None
            if persona:
                source = "loginusers.vdf"
        if not persona:
            persona_local = read_localconfig_persona_name(steam_path, aid_int)
            if persona_local:
                persona = persona_local
                source = "localconfig.vdf"
        if not persona and account_name:
            persona = str(account_name).strip() or None
            if persona:
                source = "loginusers.vdf"

        if not persona:
            persona = aid_str  # show AccountID as nickname fallback per requirements

        steam_id64 = aid_int + STEAMID64_OFFSET
        avatar_path = resolve_avatar_path(steam_path, aid_int, steam_id64, persona)

        result[aid_str] = {
            "personaname": persona,
            "account_name": account_name,
            "avatar_path": avatar_path,
            "source": source,
        }
    return result


