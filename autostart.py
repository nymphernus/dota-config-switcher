"""Windows autostart (registry) helpers."""

from __future__ import annotations

import logging
import os
import sys
import winreg
from pathlib import Path

LOGGER = logging.getLogger(__name__)

RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_RUN_NAME = "DotaConfigSwitcher"


def _get_autostart_command() -> str:
    """Return command used for Windows autostart with minimized flag."""
    if getattr(sys, "frozen", False):
        exe_path = str(Path(sys.executable).resolve())
        return f'"{exe_path}" --minimized'

    python_exe = Path(sys.executable).resolve()
    pythonw_exe = python_exe.with_name("pythonw.exe")
    if pythonw_exe.exists():
        python_path = pythonw_exe
    else:
        # Fallback: try case-insensitive replacement, else keep current interpreter
        name_lower = python_exe.name.lower()
        if name_lower == "python.exe":
            python_path = python_exe.with_name("pythonw.exe")
        else:
            python_path = python_exe

    try:
        main_path = Path(__file__).resolve().parent / "main.py"
    except Exception:
        main_path = Path.cwd() / "main.py"

    return f'"{str(python_path)}" "{str(main_path.resolve())}" --minimized'


def set_autostart(enable: bool) -> None:
    """Enable or disable app autostart in HKCU Run registry key."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE) as key:
            if enable:
                command = _get_autostart_command()
                winreg.SetValueEx(key, APP_RUN_NAME, 0, winreg.REG_SZ, command)
            else:
                try:
                    winreg.DeleteValue(key, APP_RUN_NAME)
                except FileNotFoundError:
                    pass
    except FileNotFoundError:
        # Run key should exist on Windows, but handle gracefully
        if enable:
            try:
                with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE) as key:
                    command = _get_autostart_command()
                    winreg.SetValueEx(key, APP_RUN_NAME, 0, winreg.REG_SZ, command)
            except Exception as e:
                LOGGER.warning("Failed to enable autostart: %s", e)
        # disable when key missing -> nothing to do
    except OSError as e:
        LOGGER.warning("Failed to update autostart registry value: %s", e)
    except Exception as e:
        LOGGER.warning("Unexpected autostart error: %s", e)


def is_autostart_enabled() -> bool:
    """Return True if autostart registry value exists."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY_PATH, 0, winreg.KEY_READ) as key:
            winreg.QueryValueEx(key, APP_RUN_NAME)
            return True
    except FileNotFoundError:
        return False
    except OSError:
        return False
    except Exception:
        return False
