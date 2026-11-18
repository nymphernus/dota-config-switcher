"""Dialog for selecting legacy configs to import."""

from __future__ import annotations

from typing import List

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from configs import ImportCandidate


class ImportConfigsDialog(QDialog):
    def __init__(self, candidates: List[ImportCandidate], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Импорт конфигов")
        self.resize(560, 420)
        self._candidates = list(candidates)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        info = QLabel("Найдены конфиги (папки с подпапкой 570). Выберите, какие импортировать:")
        info.setWordWrap(True)
        layout.addWidget(info)

        self.list_widget = QListWidget()
        self.list_widget.setAlternatingRowColors(False)
        for cand in self._candidates:
            text = f"{cand.name}  —  изменён: {cand.modified_str}, размер: {cand.size_str}"
            item = QListWidgetItem(text)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            item.setData(Qt.UserRole, cand.path)
            item.setData(Qt.UserRole + 1, cand.name)
            self.list_widget.addItem(item)
        layout.addWidget(self.list_widget, 1)

        sel_row = QHBoxLayout()
        sel_all = QPushButton("Выбрать все")
        sel_none = QPushButton("Снять выбор")
        sel_all.clicked.connect(lambda: self._set_all(Qt.Checked))
        sel_none.clicked.connect(lambda: self._set_all(Qt.Unchecked))
        sel_row.addWidget(sel_all)
        sel_row.addWidget(sel_none)
        sel_row.addStretch(1)
        layout.addLayout(sel_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Импортировать")
        buttons.button(QDialogButtonBox.Cancel).setText("Отмена")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _set_all(self, state: Qt.CheckState) -> None:
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item:
                item.setCheckState(state)

    def selected_candidates(self) -> List[ImportCandidate]:
        selected: List[ImportCandidate] = []
        by_path = {c.path: c for c in self._candidates}
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if not item or item.checkState() != Qt.Checked:
                continue
            path = item.data(Qt.UserRole)
            cand = by_path.get(path)
            if cand:
                selected.append(cand)
        return selected
