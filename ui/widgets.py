"""Custom widgets for the UI."""

from __future__ import annotations

import os
from typing import Optional

from PySide6.QtCore import QModelIndex, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSizePolicy,
    QStyledItemDelegate,
    QStyle,
    QStyleOptionViewItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


def _fallback_avatar_color(account_id: Optional[int | str]) -> QColor:
    try:
        aid = int(account_id) if account_id is not None and str(account_id).strip() != "" else 0
    except Exception:
        aid = 0
    h = (aid * 2654435761) & 0xFFFFFFFF
    r = 60 + (h & 0x7F)
    g = 60 + ((h >> 8) & 0x7F)
    b = 60 + ((h >> 16) & 0x7F)
    return QColor(r, g, b)


def make_avatar_pixmap(
    path: Optional[str],
    size: int = 32,
    radius: int = 8,
    name: Optional[str] = None,
    account_id: Optional[int | str] = None,
) -> QPixmap:
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    painter.setRenderHint(QPainter.Antialiasing, True)
    rect = QRect(0, 0, size, size)

    loaded = False
    if path and os.path.exists(path):
        src = QPixmap(path)
        if not src.isNull():
            path_clip = QPainterPath()
            path_clip.addRoundedRect(rect, radius, radius)
            painter.setClipPath(path_clip)
            scaled = src.scaled(size, size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            x = (scaled.width() - size) // 2
            y = (scaled.height() - size) // 2
            painter.drawPixmap(-x, -y, scaled)
            loaded = True

    if not loaded:
        # Fallback: circle with first letter and deterministic color
        painter.setClipping(False)
        painter.setPen(Qt.NoPen)
        painter.setBrush(_fallback_avatar_color(account_id))
        painter.drawEllipse(rect.adjusted(1, 1, -1, -1))

        letter = "?"
        text_source = (name or "").strip()
        if text_source:
            for ch in text_source:
                if ch.strip():
                    letter = ch.upper()
                    break
        elif account_id is not None and str(account_id).strip():
            letter = str(account_id).strip()[0]

        painter.setPen(QColor("#f5f7ff"))
        font = QFont()
        font.setBold(True)
        font.setPointSize(max(8, int(size * 0.45)))
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignCenter, letter)

    painter.end()
    return pix


class AccountComboDelegate(QStyledItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.avatar_size = 32
        self.padding = 8

    def sizeHint(self, option: QStyleOptionViewItem, index: QModelIndex) -> QSize:
        base = super().sizeHint(option, index)
        return QSize(base.width(), max(base.height(), 44))

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)

        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        style = opt.widget.style() if opt.widget else None

        # Draw base selection/hover background
        if style:
            opt.text = ""
            style.drawControl(QStyle.CE_ItemViewItem, opt, painter, opt.widget)
        else:
            if opt.state & QStyle.State_Selected:
                painter.fillRect(opt.rect, opt.palette.highlight())

        rect = opt.rect.adjusted(self.padding, 4, -self.padding, -4)
        avatar_path = index.data(Qt.UserRole + 2)
        name = index.data(Qt.UserRole) or index.data(Qt.DisplayRole) or ""
        account_id = index.data(Qt.UserRole + 1) or ""
        avatar = make_avatar_pixmap(avatar_path, self.avatar_size, 8, name=str(name), account_id=account_id)
        avatar_y = rect.y() + (rect.height() - self.avatar_size) // 2
        painter.drawPixmap(rect.x(), avatar_y, avatar)

        text_x = rect.x() + self.avatar_size + 10
        text_rect = QRect(text_x, rect.y(), rect.width() - self.avatar_size - 10, rect.height())
        name_font = QFont(opt.font)
        name_font.setPointSize(10)
        name_font.setBold(True)
        id_font = QFont(opt.font)
        id_font.setPointSize(8)

        name_color = QColor("#e6e6f0")
        id_color = QColor("#9aa3b2")
        if opt.state & QStyle.State_Selected:
            # Keep readable on highlight
            name_color = QColor("#ffffff")
            id_color = QColor("#d7dce8")

        painter.setPen(name_color)
        painter.setFont(name_font)
        name_rect = QRect(text_rect.x(), text_rect.y() + 2, text_rect.width(), text_rect.height() // 2)
        painter.drawText(name_rect, Qt.AlignLeft | Qt.AlignVCenter, str(name))

        painter.setPen(id_color)
        painter.setFont(id_font)
        id_rect = QRect(text_rect.x(), text_rect.y() + text_rect.height() // 2 - 1, text_rect.width(), text_rect.height() // 2)
        painter.drawText(id_rect, Qt.AlignLeft | Qt.AlignVCenter, f"AccountID: {account_id}")

        painter.restore()


class ConfigCard(QFrame):
    apply_clicked = Signal(str)  # config path
    delete_clicked = Signal(str)
    open_clicked = Signal(str)

    def __init__(self, name: str, path: str, modified: str, size: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.config_name = name
        self.config_path = path
        self.setObjectName("ConfigCard")
        self.setFrameShape(QFrame.StyledPanel)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(12)

        # Folder icon
        icon_label = QLabel()
        icon = self.style().standardIcon(QStyle.SP_DirIcon)
        icon_label.setPixmap(icon.pixmap(28, 28))
        icon_label.setFixedSize(32, 32)
        icon_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(icon_label, 0, Qt.AlignTop)

        # Texts
        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        self.name_label = QLabel(name)
        self.name_label.setObjectName("ConfigName")
        self.meta_label = QLabel(f"Изменён: {modified}   •   Размер: {size}")
        self.meta_label.setObjectName("ConfigMeta")
        text_col.addWidget(self.name_label)
        text_col.addWidget(self.meta_label)
        layout.addLayout(text_col, 1)

        # Buttons
        btn_col = QHBoxLayout()
        btn_col.setSpacing(6)
        self.apply_btn = QPushButton("Применить")
        self.apply_btn.setObjectName("ApplyButton")
        self.apply_btn.setCursor(Qt.PointingHandCursor)
        self.apply_btn.clicked.connect(lambda: self.apply_clicked.emit(self.config_path))

        self.more_btn = QToolButton()
        self.more_btn.setText("⋯")
        self.more_btn.setObjectName("MoreButton")
        self.more_btn.setCursor(Qt.PointingHandCursor)
        self.more_btn.setPopupMode(QToolButton.InstantPopup)
        self.more_btn.setStyleSheet("QToolButton::menu-indicator { image: none; width: 0px; }")
        menu = QMenu(self)
        act_open = menu.addAction("Открыть папку")
        act_delete = menu.addAction("Удалить")
        act_open.triggered.connect(lambda: self.open_clicked.emit(self.config_path))
        act_delete.triggered.connect(lambda: self.delete_clicked.emit(self.config_path))
        self.more_btn.setMenu(menu)

        btn_col.addWidget(self.apply_btn)
        btn_col.addWidget(self.more_btn)
        layout.addLayout(btn_col)
