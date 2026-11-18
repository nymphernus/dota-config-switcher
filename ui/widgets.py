"""Custom widgets for the UI."""

from __future__ import annotations

import os
from typing import Optional

from PySide6.QtCore import QModelIndex, QRect, QSize, Qt, Signal
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
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
    rename_clicked = Signal(str)

    def __init__(
        self,
        name: str,
        path: str,
        modified: str,
        size: str,
        is_last_applied: bool = False,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.config_name = name
        self.config_path = path
        self.setObjectName("ConfigCard")
        self.setFrameShape(QFrame.StyledPanel)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(12)

        # Folder icon (clickable)
        self.folder_btn = QToolButton()
        self.folder_btn.setObjectName("IconButton")
        icon = self.style().standardIcon(QStyle.SP_DirIcon)
        self.folder_btn.setIcon(icon)
        self.folder_btn.setIconSize(QSize(28, 28))
        self.folder_btn.setFixedSize(32, 32)
        self.folder_btn.setCursor(Qt.PointingHandCursor)
        self.folder_btn.setToolTip("\u041e\u0442\u043a\u0440\u044b\u0442\u044c \u043f\u0430\u043f\u043a\u0443 \u043a\u043e\u043d\u0444\u0438\u0433\u0430")
        self.folder_btn.clicked.connect(lambda: self.open_clicked.emit(self.config_path))
        layout.addWidget(self.folder_btn, 0, Qt.AlignTop)

        # Texts
        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        self.name_label = QLabel(name)
        self.name_label.setObjectName("ConfigName")
        self.meta_label = QLabel(f"\u0418\u0437\u043c\u0435\u043d\u0451\u043d: {modified}   \u2022   \u0420\u0430\u0437\u043c\u0435\u0440: {size}")
        self.meta_label.setObjectName("ConfigMeta")
        text_col.addWidget(self.name_label)
        text_col.addWidget(self.meta_label)
        layout.addLayout(text_col, 1)

        # Buttons
        btn_col = QHBoxLayout()
        btn_col.setSpacing(6)

        self.apply_btn = QToolButton()
        self.apply_btn.setObjectName("ConfigActionButton")
        self.apply_btn.setIcon(self.style().standardIcon(QStyle.SP_DialogApplyButton))
        self.apply_btn.setIconSize(QSize(18, 18))
        self.apply_btn.setFixedSize(32, 32)
        self.apply_btn.setCursor(Qt.PointingHandCursor)
        self.apply_btn.setToolTip("\u041f\u0440\u0438\u043c\u0435\u043d\u0438\u0442\u044c")
        self.apply_btn.clicked.connect(lambda: self.apply_clicked.emit(self.config_path))

        self.rename_btn = QToolButton()
        self.rename_btn.setObjectName("ConfigActionButton")
        self.rename_btn.setText("\u270e")
        self.rename_btn.setFixedSize(32, 32)
        self.rename_btn.setCursor(Qt.PointingHandCursor)
        self.rename_btn.setToolTip("\u041f\u0435\u0440\u0435\u0438\u043c\u0435\u043d\u043e\u0432\u0430\u0442\u044c")
        self.rename_btn.clicked.connect(lambda: self.rename_clicked.emit(self.config_path))

        self.delete_btn = QToolButton()
        self.delete_btn.setObjectName("ConfigDeleteButton")
        self.delete_btn.setIcon(self.style().standardIcon(QStyle.SP_TrashIcon))
        self.delete_btn.setIconSize(QSize(18, 18))
        self.delete_btn.setFixedSize(32, 32)
        self.delete_btn.setCursor(Qt.PointingHandCursor)
        self.delete_btn.setToolTip("\u0423\u0434\u0430\u043b\u0438\u0442\u044c")
        self.delete_btn.clicked.connect(lambda: self.delete_clicked.emit(self.config_path))

        self._apply_button_styles(is_last_applied)

        btn_col.addWidget(self.apply_btn)
        btn_col.addWidget(self.rename_btn)
        btn_col.addWidget(self.delete_btn)
        layout.addLayout(btn_col)

    def set_last_applied(self, is_last_applied: bool) -> None:
        self._apply_button_styles(is_last_applied)

    def _apply_button_styles(self, is_last_applied: bool) -> None:
        base_btn_style = (
            "QToolButton { background-color: #343447; border: 1px solid #404055; border-radius: 8px; padding: 4px; }"
            "QToolButton:hover { background-color: #3b3b52; }"
            "QToolButton:disabled { background-color: #2d2d3b; border-color: #353545; color: #7f8796; }"
        )
        apply_bg = "#2e4a2e" if is_last_applied else "#343447"
        apply_hover = "#355735" if is_last_applied else "#3b3b52"
        self.apply_btn.setStyleSheet(
            f"QToolButton {{ background-color: {apply_bg}; border: 1px solid #404055; border-radius: 8px; padding: 4px; }}"
            f"QToolButton:hover {{ background-color: {apply_hover}; }}"
            "QToolButton:disabled { background-color: #2d2d3b; border-color: #353545; }"
        )
        self.rename_btn.setStyleSheet(base_btn_style)
        self.delete_btn.setStyleSheet(
            "QToolButton { background-color: #5a2a2a; border: 1px solid #6a3535; border-radius: 8px; padding: 4px; color: #ffffff; }"
            "QToolButton:hover { background-color: #6a3232; }"
            "QToolButton:disabled { background-color: #3a2424; border-color: #4a3030; color: #8a6a6a; }"
        )


def _inherit_parent_style(dialog: QDialog, parent: Optional[QWidget]) -> None:
    if parent is not None and hasattr(parent, "styleSheet"):
        ss = parent.styleSheet()
        if ss:
            dialog.setStyleSheet(ss)
    dialog.setMinimumWidth(360)


class RenameDialog(QDialog):
    def __init__(self, parent: Optional[QWidget], title: str, label: str, text: str = ""):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        _inherit_parent_style(self, parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self.label = QLabel(label)
        self.label.setWordWrap(True)
        layout.addWidget(self.label)

        self.line_edit = QLineEdit(text)
        self.line_edit.selectAll()
        layout.addWidget(self.line_edit)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        ok_btn = buttons.button(QDialogButtonBox.Ok)
        cancel_btn = buttons.button(QDialogButtonBox.Cancel)
        if ok_btn:
            ok_btn.setText("OK")
        if cancel_btn:
            cancel_btn.setText("\u041e\u0442\u043c\u0435\u043d\u0430")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.line_edit.returnPressed.connect(self.accept)

    def text_value(self) -> str:
        return self.line_edit.text()

    @staticmethod
    def get_text(parent: Optional[QWidget], title: str, label: str, text: str = "") -> tuple[str, bool]:
        dlg = RenameDialog(parent, title, label, text)
        ok = dlg.exec() == QDialog.Accepted
        return dlg.text_value(), ok


class MessageDialog(QDialog):
    def __init__(
        self,
        parent: Optional[QWidget],
        title: str,
        text: str,
        icon: QStyle.StandardPixmap = QStyle.SP_MessageBoxInformation,
        buttons: QDialogButtonBox.StandardButtons = QDialogButtonBox.Ok,
    ):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        _inherit_parent_style(self, parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        row = QHBoxLayout()
        row.setSpacing(12)
        icon_label = QLabel()
        icon_pix = self.style().standardIcon(icon).pixmap(32, 32)
        icon_label.setPixmap(icon_pix)
        icon_label.setFixedSize(36, 36)
        icon_label.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        row.addWidget(icon_label, 0, Qt.AlignTop)

        text_label = QLabel(text)
        text_label.setWordWrap(True)
        text_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        row.addWidget(text_label, 1)
        layout.addLayout(row)

        self.button_box = QDialogButtonBox(buttons)
        self._localize_buttons()
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

    def _localize_buttons(self) -> None:
        mapping = {
            QDialogButtonBox.Ok: "OK",
            QDialogButtonBox.Cancel: "\u041e\u0442\u043c\u0435\u043d\u0430",
            QDialogButtonBox.Yes: "\u0414\u0430",
            QDialogButtonBox.No: "\u041d\u0435\u0442",
        }
        for std, label in mapping.items():
            btn = self.button_box.button(std)
            if btn:
                btn.setText(label)


def show_info(parent: Optional[QWidget], title: str, text: str) -> None:
    dlg = MessageDialog(parent, title, text, QStyle.SP_MessageBoxInformation, QDialogButtonBox.Ok)
    dlg.exec()


def show_warning(parent: Optional[QWidget], title: str, text: str) -> None:
    dlg = MessageDialog(parent, title, text, QStyle.SP_MessageBoxWarning, QDialogButtonBox.Ok)
    dlg.exec()


def show_error(parent: Optional[QWidget], title: str, text: str) -> None:
    dlg = MessageDialog(parent, title, text, QStyle.SP_MessageBoxCritical, QDialogButtonBox.Ok)
    dlg.exec()


def ask_yes_no(parent: Optional[QWidget], title: str, text: str) -> bool:
    dlg = MessageDialog(
        parent,
        title,
        text,
        QStyle.SP_MessageBoxQuestion,
        QDialogButtonBox.Yes | QDialogButtonBox.No,
    )
    no_btn = dlg.button_box.button(QDialogButtonBox.No)
    if no_btn:
        no_btn.setDefault(True)
        no_btn.setFocus()
    return dlg.exec() == QDialog.Accepted
