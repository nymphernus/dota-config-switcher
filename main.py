"""Entry point for Dota 2 Config Switcher."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from settings import APP_NAME, get_log_path
from ui.main_window import MainWindow


def setup_logging() -> None:
    log_path = get_log_path()
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    # Avoid duplicate handlers if reloaded
    if logger.handlers:
        return

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    try:
        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=1_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setFormatter(fmt)
        file_handler.setLevel(logging.INFO)
        logger.addHandler(file_handler)
    except Exception:
        # Fallback to stderr only
        pass

    stream_handler = logging.StreamHandler(sys.stderr)
    stream_handler.setFormatter(fmt)
    stream_handler.setLevel(logging.WARNING)
    logger.addHandler(stream_handler)


def main() -> int:
    setup_logging()
    # High DPI attributes (Qt6 enables most by default, but keep safe)
    try:
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )
    except Exception:
        pass

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

