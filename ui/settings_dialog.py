"""Settings dialog."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class SettingsDialog(QDialog):
    def __init__(self, settings: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Настройки")
        self.setModal(True)
        self.resize(500, 260)
        self._settings = dict(settings)

        self._build_ui()
        self._load_values()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignLeft)
        form.setFormAlignment(Qt.AlignTop)
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(12)

        # Steam path
        self.steam_path_edit = QLineEdit()
        self.steam_path_edit.setPlaceholderText("C:\\Program Files (x86)\\Steam")
        steam_browse = QPushButton("Обзор...")
        steam_browse.clicked.connect(self.browse_steam_path)
        steam_row = QHBoxLayout()
        steam_row.setContentsMargins(0, 0, 0, 0)
        steam_row.setSpacing(8)
        steam_row.addWidget(self.steam_path_edit, 1)
        steam_row.addWidget(steam_browse)
        steam_wrap = QWidget()
        steam_wrap.setLayout(steam_row)
        form.addRow("Путь к Steam:", steam_wrap)

        # Configs dir
        self.configs_dir_edit = QLineEdit()
        configs_browse = QPushButton("Обзор...")
        configs_browse.clicked.connect(self.browse_configs_dir)
        configs_row = QHBoxLayout()
        configs_row.setContentsMargins(0, 0, 0, 0)
        configs_row.setSpacing(8)
        configs_row.addWidget(self.configs_dir_edit, 1)
        configs_row.addWidget(configs_browse)
        configs_wrap = QWidget()
        configs_wrap.setLayout(configs_row)
        form.addRow("Папка конфигов:", configs_wrap)

        layout.addLayout(form)
        layout.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("Сохранить")
        buttons.button(QDialogButtonBox.Cancel).setText("Отмена")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _load_values(self) -> None:
        self.steam_path_edit.setText(str(self._settings.get("steam_path") or ""))
        self.configs_dir_edit.setText(str(self._settings.get("configs_dir") or ""))

    def browse_steam_path(self) -> None:
        current = self.steam_path_edit.text().strip() or str(Path.home())
        path = QFileDialog.getExistingDirectory(self, "Выберите папку Steam", current)
        if path:
            self.steam_path_edit.setText(path)

    def browse_configs_dir(self) -> None:
        current = self.configs_dir_edit.text().strip() or str(Path.home())
        path = QFileDialog.getExistingDirectory(self, "Выберите папку конфигов", current)
        if path:
            self.configs_dir_edit.setText(path)

    def get_settings(self) -> Dict[str, Any]:
        data = dict(self._settings)
        data["steam_path"] = self.steam_path_edit.text().strip()
        data["configs_dir"] = self.configs_dir_edit.text().strip()
        # Drop legacy keys if present in old settings dict
        data.pop("api_key", None)
        data.pop("check_avatar_updates", None)
        return data

