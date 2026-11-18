"""Dialog showing detailed information about a config."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from configs import ConfigDetails, format_size


def _fmt_dt(ts: float) -> str:
    try:
        return datetime.fromtimestamp(ts).strftime("%d.%m.%Y %H:%M")
    except Exception:
        return "—"


def _get_video_summary(settings: dict) -> list[tuple[str, str]]:
    # Try common Dota 2 video.txt keys
    mapping = [
        ("Разрешение", ("setting.defaultres", "setting.defaultresheight")),
        ("Режим отображения", ("setting.fullscreen",)),
        ("Рендеринг (API)", ("setting.dx11", "setting.vulkan", "setting.dx9")),
        ("VSync", ("setting.nowindowborder", "setting.vsync")),  # vsync key varies; best-effort
        ("Частота обновления", ("setting.refreshrate_numerator",)),
        ("Аспект", ("setting.aspectratiomode",)),
    ]
    rows: list[tuple[str, str]] = []

    w = settings.get("setting.defaultres")
    h = settings.get("setting.defaultresheight")
    if w or h:
        rows.append(("Разрешение", f"{w or '?'} x {h or '?'}"))

    fullscreen = settings.get("setting.fullscreen")
    borderless = settings.get("setting.nowindowborder")
    if fullscreen is not None or borderless is not None:
        if fullscreen == "1" and borderless == "1":
            mode = "Оконный без рамки"
        elif fullscreen == "1":
            mode = "Полноэкранный"
        elif fullscreen == "0":
            mode = "Оконный"
        else:
            mode = f"fullscreen={fullscreen}, nowindowborder={borderless}"
        rows.append(("Режим отображения", mode))

    # Rendering hints
    if settings.get("setting.dx11") == "1":
        rows.append(("Рендеринг", "DirectX 11"))
    elif settings.get("setting.vulkan") == "1":
        rows.append(("Рендеринг", "Vulkan"))
    elif settings.get("setting.dx9") == "1":
        rows.append(("Рендеринг", "DirectX 9"))

    # A few other useful values
    extra_keys = [
        ("setting.mat_vsync", "VSync"),
        ("setting.msaa_samples", "MSAA"),
        ("setting.cpu_level", "Качество CPU"),
        ("setting.gpu_level", "Качество GPU"),
        ("setting.gpu_mem_level", "Память GPU"),
    ]
    for key, label in extra_keys:
        val = settings.get(key)
        if val is not None and val != "":
            rows.append((label, str(val)))

    # If we couldn't extract much, show a few raw entries
    if not rows and settings:
        for k in sorted(settings.keys())[:8]:
            rows.append((k, settings[k]))
    return rows


class ConfigDetailsDialog(QDialog):
    def __init__(self, config_name: str, details: ConfigDetails, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Детали конфига: {config_name}")
        self.resize(760, 560)
        self._details = details
        self._build_ui(config_name)

    def _build_ui(self, config_name: str) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel(config_name)
        title.setStyleSheet("font-size: 16px; font-weight: 600;")
        layout.addWidget(title)

        path_label = QLabel(self._details.path)
        path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        path_label.setWordWrap(True)
        path_label.setStyleSheet("color: #9aa3b2; font-size: 12px;")
        layout.addWidget(path_label)

        # Summary
        summary_group = QGroupBox("Сводка")
        summary_form = QFormLayout(summary_group)
        summary_form.setLabelAlignment(Qt.AlignLeft)
        summary_form.setFormAlignment(Qt.AlignTop)
        summary_form.setHorizontalSpacing(12)
        summary_form.setVerticalSpacing(6)

        if self._details.autoexec_exists:
            autoexec_text = f"Найден ({format_size(self._details.autoexec_size)}) — {self._details.autoexec_path}"
        else:
            autoexec_text = "Не найден"
        summary_form.addRow("autoexec.cfg:", self._make_value_label(autoexec_text))

        if self._details.video_exists:
            video_text = f"Найден — {self._details.video_path}"
        else:
            video_text = "Не найден"
        summary_form.addRow("video.txt:", self._make_value_label(video_text))

        # Video settings summary
        video_rows = _get_video_summary(self._details.video_settings) if self._details.video_exists else []
        if self._details.video_exists and video_rows:
            for label, value in video_rows[:10]:
                summary_form.addRow(f"{label}:", self._make_value_label(value))
        elif self._details.video_exists and not self._details.video_settings:
            summary_form.addRow("Настройки video.txt:", self._make_value_label("Не удалось разобрать параметры (файл есть)"))

        layout.addWidget(summary_group)

        # Files list
        files_group = QGroupBox("Файлы в конфиге")
        files_layout = QVBoxLayout(files_group)
        files_layout.setContentsMargins(8, 8, 8, 8)

        table = QTableWidget()
        table.setColumnCount(3)
        table.setHorizontalHeaderLabels(["Файл", "Размер", "Изменён"])
        table.setRowCount(len(self._details.files))
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.SingleSelection)
        table.verticalHeader().setVisible(False)
        table.horizontalHeader().setStretchLastSection(True)
        table.setAlternatingRowColors(False)

        for row, (rel, size, mtime) in enumerate(self._details.files):
            item_name = QTableWidgetItem(rel)
            item_size = QTableWidgetItem(format_size(size))
            item_mtime = QTableWidgetItem(_fmt_dt(mtime))
            item_size.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            item_mtime.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            table.setItem(row, 0, item_name)
            table.setItem(row, 1, item_size)
            table.setItem(row, 2, item_mtime)

        table.resizeColumnsToContents()
        if table.columnWidth(0) < 320:
            table.setColumnWidth(0, 320)
        files_layout.addWidget(table)
        layout.addWidget(files_group, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        close_btn = buttons.button(QDialogButtonBox.Close)
        if close_btn:
            close_btn.setText("Закрыть")
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

    def _make_value_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        lbl.setWordWrap(True)
        return lbl
