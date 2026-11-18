"""Config listing and copy operations."""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Tuple

LOGGER = logging.getLogger(__name__)

FORBIDDEN_NAME_CHARS = set('\\/:*?"<>|')
DOTA_APP_ID = "570"


@dataclass
class ConfigInfo:
    name: str
    path: str
    modified_ts: float
    size_bytes: int

    @property
    def modified_str(self) -> str:
        try:
            return datetime.fromtimestamp(self.modified_ts).strftime("%d.%m.%Y %H:%M")
        except Exception:
            return "—"

    @property
    def size_str(self) -> str:
        return format_size(self.size_bytes)


def format_size(num_bytes: int) -> str:
    size = float(max(0, int(num_bytes)))
    units = ["Б", "КБ", "МБ", "ГБ", "ТБ"]
    for unit in units:
        if size < 1024.0 or unit == units[-1]:
            if unit == "Б":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{int(num_bytes)} Б"


def validate_config_name_format(name: str) -> Tuple[bool, str]:
    name = (name or "").strip()
    if not name:
        return False, "Имя конфига не может быть пустым."
    if name in {".", ".."}:
        return False, "Недопустимое имя конфига."
    if any(ch in FORBIDDEN_NAME_CHARS for ch in name):
        return False, 'Имя содержит недопустимые символы: \\ / : * ? " < > |'
    if any(ord(ch) < 32 for ch in name):
        return False, "Имя содержит недопустимые управляющие символы."
    # Prevent path separators / traversal via weird names
    if "/" in name or "\\" in name:
        return False, "Имя конфига не должно содержать разделители пути."
    return True, ""


def validate_config_name(name: str, configs_dir: str | Path) -> Tuple[bool, str]:
    name = (name or "").strip()
    ok, msg = validate_config_name_format(name)
    if not ok:
        return False, msg
    target = Path(configs_dir) / name
    if target.exists():
        return False, "Конфиг с таким именем уже существует."
    return True, ""


def is_valid_config_dir(path: Path) -> bool:
    return path.is_dir() and (path / DOTA_APP_ID).is_dir()


def _iter_files(root: Path) -> Iterable[Path]:
    for dirpath, _, filenames in os.walk(root):
        base = Path(dirpath)
        for fn in filenames:
            yield base / fn


def get_directory_stats(path: str | Path) -> Tuple[int, float]:
    """Return (total_size_bytes, latest_mtime)."""
    p = Path(path)
    total = 0
    latest = 0.0
    if not p.exists():
        return 0, 0.0
    for dirpath, _, filenames in os.walk(p):
        dp = Path(dirpath)
        try:
            latest = max(latest, dp.stat().st_mtime)
        except OSError:
            pass
        for fn in filenames:
            fp = dp / fn
            try:
                st = fp.stat()
                total += st.st_size
                latest = max(latest, st.st_mtime)
            except OSError:
                continue
    try:
        latest = max(latest, p.stat().st_mtime)
    except OSError:
        pass
    return total, latest


def list_configs(configs_dir: str | Path) -> List[ConfigInfo]:
    root = Path(configs_dir)
    result: List[ConfigInfo] = []
    if not root.exists() or not root.is_dir():
        return result
    try:
        for entry in root.iterdir():
            try:
                if not is_valid_config_dir(entry):
                    continue
                size, mtime = get_directory_stats(entry)
                result.append(ConfigInfo(name=entry.name, path=str(entry), modified_ts=mtime, size_bytes=size))
            except Exception as e:
                LOGGER.warning("Failed to read config %s: %s", entry, e)
    except Exception as e:
        LOGGER.exception("Failed to list configs in %s: %s", root, e)
        raise
    result.sort(key=lambda c: c.name.lower())
    return result


def _count_files(root: Path) -> int:
    count = 0
    for _, _, filenames in os.walk(root):
        count += len(filenames)
    return count


def _copy_tree_with_progress(
    src: Path,
    dst: Path,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> None:
    """Copy src directory tree to dst (dst may exist) with file-level progress."""
    total_files = _count_files(src)
    copied = 0
    if progress_callback:
        progress_callback(0, total_files, "Подготовка копирования...")

    for dirpath, dirnames, filenames in os.walk(src):
        rel = Path(dirpath).relative_to(src)
        target_dir = dst / rel
        target_dir.mkdir(parents=True, exist_ok=True)
        # Preserve directory metadata best-effort
        try:
            shutil.copystat(dirpath, target_dir, follow_symlinks=True)
        except Exception:
            pass
        for fn in filenames:
            src_file = Path(dirpath) / fn
            dst_file = target_dir / fn
            # Ensure parent exists (in case)
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, dst_file)
            copied += 1
            if progress_callback:
                progress_callback(copied, total_files, str(src_file))


def apply_config(
    config_path: str | Path,
    steam_path: str | Path,
    account_id: str | int,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> None:
    """Apply config by mirroring <config>/570 into userdata/<account>/570."""
    config_path = Path(config_path)
    src = config_path / DOTA_APP_ID
    if not src.exists() or not src.is_dir():
        raise FileNotFoundError(f"В конфиге не найдена папка {DOTA_APP_ID}: {src}")

    userdata_target = Path(steam_path) / "userdata" / str(account_id) / DOTA_APP_ID
    userdata_parent = userdata_target.parent
    if not userdata_parent.exists():
        raise FileNotFoundError(
            f"Папка аккаунта Steam не найдена: {userdata_parent}. Запустите Steam/Dota 2 хотя бы раз."
        )

    # Mirror by clearing target dir then copying
    try:
        if progress_callback:
            progress_callback(0, 0, "Очистка текущего конфига...")
        if userdata_target.exists():
            # Remove contents/files/dirs inside 570 (mirror target folder)
            shutil.rmtree(userdata_target)
        userdata_target.mkdir(parents=True, exist_ok=True)
        _copy_tree_with_progress(src, userdata_target, progress_callback)
        if progress_callback:
            progress_callback(1, 1, "Готово")
    except PermissionError as e:
        LOGGER.exception("Permission error while applying config: %s", e)
        raise PermissionError(
            "Нет доступа к файлам. Закройте Steam и Dota 2 и попробуйте снова."
        ) from e
    except OSError as e:
        LOGGER.exception("OS error while applying config: %s", e)
        # Common case: files locked by game/steam
        raise OSError(
            f"Ошибка копирования файлов: {e}. Закройте Steam и Dota 2 и попробуйте снова."
        ) from e


def save_current_config(
    steam_path: str | Path,
    account_id: str | int,
    configs_dir: str | Path,
    name: str,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
) -> Path:
    """Save current userdata/<account>/570 to configs_dir/<name>/570."""
    ok, msg = validate_config_name(name, configs_dir)
    if not ok:
        raise ValueError(msg)

    src = Path(steam_path) / "userdata" / str(account_id) / DOTA_APP_ID
    if not src.exists() or not src.is_dir():
        raise FileNotFoundError(
            f"Текущий конфиг Dota 2 не найден: {src}. Убедитесь, что Dota 2 запускалась для этого аккаунта."
        )

    configs_dir = Path(configs_dir)
    configs_dir.mkdir(parents=True, exist_ok=True)
    dest_config = configs_dir / name.strip()
    dest_570 = dest_config / DOTA_APP_ID
    try:
        dest_config.mkdir(parents=True, exist_ok=False)
        if progress_callback:
            progress_callback(0, 0, "Сохранение текущего конфига...")
        _copy_tree_with_progress(src, dest_570, progress_callback)
        if progress_callback:
            progress_callback(1, 1, "Готово")
        return dest_config
    except FileExistsError:
        raise ValueError("Конфиг с таким именем уже существует.")
    except PermissionError as e:
        LOGGER.exception("Permission error while saving config: %s", e)
        # Cleanup partial folder on failure if empty-ish
        try:
            if dest_config.exists() and not any(dest_config.iterdir()):
                dest_config.rmdir()
        except Exception:
            pass
        raise PermissionError(
            "Нет доступа к файлам. Закройте Steam и Dota 2 и попробуйте снова."
        ) from e
    except OSError as e:
        LOGGER.exception("OS error while saving config: %s", e)
        try:
            if dest_config.exists() and is_valid_config_dir(dest_config) is False:
                # best-effort cleanup partial copy
                shutil.rmtree(dest_config, ignore_errors=True)
        except Exception:
            pass
        raise OSError(
            f"Ошибка сохранения конфига: {e}. Закройте Steam и Dota 2 и попробуйте снова."
        ) from e


def delete_config(config_path: str | Path) -> None:
    p = Path(config_path)
    if not p.exists():
        return
    if not is_valid_config_dir(p):
        # safety: only delete folders that look like configs
        raise ValueError("Выбранная папка не похожа на конфиг Dota 2.")
    shutil.rmtree(p)


def open_in_explorer(path: str | Path) -> None:
    p = str(Path(path))
    if not os.path.exists(p):
        raise FileNotFoundError(f"Папка не найдена: {p}")
    if sys.platform.startswith("win"):
        os.startfile(p)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", p])
    else:
        subprocess.Popen(["xdg-open", p])


@dataclass
class ImportCandidate:
    name: str
    path: str
    modified_ts: float
    size_bytes: int

    @property
    def modified_str(self) -> str:
        try:
            return datetime.fromtimestamp(self.modified_ts).strftime("%d.%m.%Y %H:%M")
        except Exception:
            return "—"

    @property
    def size_str(self) -> str:
        return format_size(self.size_bytes)


def scan_importable_configs(source_dir: str | Path) -> List[ImportCandidate]:
    """Scan a directory for legacy/config folders containing a '570' subfolder."""
    root = Path(source_dir)
    result: List[ImportCandidate] = []
    if not root.exists() or not root.is_dir():
        return result
    try:
        for entry in root.iterdir():
            try:
                if not is_valid_config_dir(entry):
                    continue
                size, mtime = get_directory_stats(entry)
                result.append(ImportCandidate(name=entry.name, path=str(entry), modified_ts=mtime, size_bytes=size))
            except Exception as e:
                LOGGER.warning("Failed to inspect import candidate %s: %s", entry, e)
    except Exception as e:
        LOGGER.exception("Failed to scan import folder %s: %s", root, e)
        raise
    result.sort(key=lambda c: c.name.lower())
    return result


def import_config_folder(src_path: str | Path, configs_dir: str | Path, target_name: str, replace: bool = False) -> Path:
    """Copy a config folder (containing 570) into configs_dir as target_name."""
    src = Path(src_path)
    if not is_valid_config_dir(src):
        raise ValueError(f"Папка '{src}' не является конфигом (нет подпапки 570).")

    target_name = (target_name or "").strip()
    ok, msg = validate_config_name_format(target_name)
    if not ok:
        raise ValueError(msg)

    configs_dir = Path(configs_dir)
    configs_dir.mkdir(parents=True, exist_ok=True)
    dest = configs_dir / target_name

    if dest.exists():
        if not replace:
            raise FileExistsError("Конфиг с таким именем уже существует.")
        # Safety: only replace folders that look like config dirs
        if not is_valid_config_dir(dest):
            raise ValueError("Существующая папка с таким именем не является конфигом Dota 2 и не будет заменена.")
        shutil.rmtree(dest)

    shutil.copytree(src, dest)
    return dest

