"""Settings dialog (placeholder, implemented in a later step)."""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout


class SettingsDialog(QDialog):
    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Настройки")
        self._settings = dict(settings)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Диалог настроек будет реализован позже."))
        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

    def get_settings(self) -> dict:
        return dict(self._settings)
