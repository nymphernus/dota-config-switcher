"""Background workers for long-running tasks."""

from __future__ import annotations

import traceback
from dataclasses import dataclass
from typing import Any, Callable, Optional

from PySide6.QtCore import QObject, QRunnable, QThread, Signal, Slot


class WorkerSignals(QObject):
    finished = Signal(object)
    error = Signal(str, str)  # user_message, details
    progress = Signal(int, int, str)  # current, total, message


class FunctionRunnable(QRunnable):
    def __init__(self, fn: Callable[..., Any], *args, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()
        self.setAutoDelete(True)

    @Slot()
    def run(self) -> None:
        try:
            result = self.fn(*self.args, **self.kwargs)
            self.signals.finished.emit(result)
        except Exception as e:
            tb = traceback.format_exc()
            self.signals.error.emit(str(e), tb)


@dataclass
class CopyTask:
    mode: str  # "apply" or "save"
    config_path: Optional[str] = None
    config_name: Optional[str] = None


class CopyWorker(QThread):
    progress = Signal(int, int, str)
    finished = Signal(object)
    error = Signal(str, str)

    def __init__(self, fn: Callable[..., Any], *args, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs

    def _progress_cb(self, current: int, total: int, message: str) -> None:
        self.progress.emit(int(current), int(total), str(message))

    def run(self) -> None:
        try:
            # Inject progress_callback if supported
            result = self.fn(*self.args, progress_callback=self._progress_cb, **self.kwargs)
            self.finished.emit(result)
        except Exception as e:
            tb = traceback.format_exc()
            self.error.emit(str(e), tb)
