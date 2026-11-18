"""Main application window."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QSize, Qt, QThreadPool, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStatusBar,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from configs import ConfigInfo, apply_config, delete_config, format_size, list_configs, open_in_explorer, save_current_config
from settings import get_base_dir, load_settings, save_settings
from steam import detect_steam_path, enumerate_accounts, get_account_profiles
from ui.settings_dialog import SettingsDialog
from ui.widgets import AccountComboDelegate, ConfigCard, make_avatar_pixmap
from ui.workers import CopyWorker, FunctionRunnable

LOGGER = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Dota 2 Config Switcher")
        self.resize(800, 600)
        self.setMinimumSize(720, 520)

        self.settings_data: Dict[str, Any] = load_settings()
        self.accounts: List[Dict[str, Any]] = []
        self.profiles: Dict[str, Dict[str, Any]] = {}
        self.current_copy_worker: Optional[CopyWorker] = None
        self.thread_pool = QThreadPool.globalInstance()

        self._build_ui()
        self._apply_styles()

        QTimer.singleShot(0, self.initialize_state)

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)

        # Top bar
        top_bar = QFrame()
        top_bar.setObjectName("TopBar")
        top_bar.setFixedHeight(60)
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(12, 8, 12, 8)
        top_layout.setSpacing(10)

        self.account_combo = QComboBox()
        self.account_combo.setObjectName("AccountCombo")
        self.account_combo.setMinimumWidth(280)
        self.account_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.account_combo.setIconSize(QSize(32, 32))
        self.account_combo.setItemDelegate(AccountComboDelegate(self.account_combo))
        self.account_combo.currentIndexChanged.connect(self.on_account_changed)
        top_layout.addWidget(self.account_combo, 2)

        path_container = QWidget()
        path_layout = QHBoxLayout(path_container)
        path_layout.setContentsMargins(0, 0, 0, 0)
        path_layout.setSpacing(6)
        self.steam_path_label = QLabel()
        self.steam_path_label.setObjectName("SteamPathLabel")
        self.steam_path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.steam_path_label.setMinimumWidth(180)
        self.steam_path_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        path_layout.addWidget(self.steam_path_label, 1)

        self.change_path_btn = QToolButton()
        self.change_path_btn.setObjectName("IconButton")
        self.change_path_btn.setToolTip("Выбрать папку Steam")
        self.change_path_btn.setIcon(self.style().standardIcon(QStyle.SP_DirOpenIcon))
        self.change_path_btn.clicked.connect(self.choose_steam_path)
        path_layout.addWidget(self.change_path_btn)
        top_layout.addWidget(path_container, 3)

        self.settings_btn = QToolButton()
        self.settings_btn.setObjectName("IconButton")
        self.settings_btn.setToolTip("Настройки")
        self.settings_btn.setIcon(self.style().standardIcon(QStyle.SP_FileDialogDetailedView))
        self.settings_btn.setText("⚙")
        self.settings_btn.clicked.connect(self.open_settings_dialog)
        top_layout.addWidget(self.settings_btn, 0, Qt.AlignRight)
        root.addWidget(top_bar)

        # Center area (scrollable config cards)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.cards_container = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_container)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        self.cards_layout.setSpacing(10)
        self.cards_layout.addStretch(1)
        self.scroll.setWidget(self.cards_container)
        root.addWidget(self.scroll, 1)

        # Empty state (overlay-like in central area by swapping visibility)
        self.empty_state = QFrame()
        self.empty_state.setObjectName("EmptyState")
        empty_layout = QVBoxLayout(self.empty_state)
        empty_layout.setAlignment(Qt.AlignCenter)
        empty_layout.setSpacing(12)
        self.empty_label = QLabel("Нет сохранённых конфигов")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setObjectName("EmptyLabel")
        self.empty_save_btn = QPushButton("Сохранить текущий")
        self.empty_save_btn.setObjectName("PrimaryButton")
        self.empty_save_btn.clicked.connect(self.save_current_config_dialog)
        empty_layout.addWidget(self.empty_label)
        empty_layout.addWidget(self.empty_save_btn, 0, Qt.AlignCenter)
        self.empty_state.setVisible(False)
        root.addWidget(self.empty_state)

        # Bottom panel
        bottom = QFrame()
        bottom.setObjectName("BottomBar")
        bottom_layout = QVBoxLayout(bottom)
        bottom_layout.setContentsMargins(8, 8, 8, 8)
        bottom_layout.setSpacing(6)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFixedHeight(8)
        bottom_layout.addWidget(self.progress_bar)

        row = QHBoxLayout()
        row.setSpacing(8)

        self.save_btn = QPushButton("Сохранить текущий конфиг")
        self.save_btn.setObjectName("PrimaryButton")
        self.save_btn.clicked.connect(self.save_current_config_dialog)
        row.addWidget(self.save_btn, 2)

        self.refresh_btn = QToolButton()
        self.refresh_btn.setToolTip("Обновить")
        self.refresh_btn.setText("↻")
        self.refresh_btn.setObjectName("IconButton")
        self.refresh_btn.clicked.connect(self.refresh_all)
        row.addWidget(self.refresh_btn, 0, Qt.AlignCenter)

        self.status_label = QLabel("Готово")
        self.status_label.setObjectName("StatusLabel")
        self.status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row.addWidget(self.status_label, 2)

        bottom_layout.addLayout(row)
        root.addWidget(bottom)

        self.setStatusBar(QStatusBar())  # hidden-ish, but keeps layout consistent if needed
        self.statusBar().hide()

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QWidget { background-color: #1e1e2e; color: #e6e6f0; font-family: 'Segoe UI'; font-size: 13px; }
            QFrame#TopBar, QFrame#BottomBar { background-color: #232334; border-radius: 8px; }
            QFrame#ConfigCard { background-color: #2a2a3a; border: 1px solid #343446; border-radius: 8px; }
            QLabel#ConfigName { font-size: 14px; font-weight: 600; color: #f0f2ff; }
            QLabel#ConfigMeta { font-size: 12px; color: #9aa3b2; }
            QLabel#SteamPathLabel, QLabel#StatusLabel { font-size: 12px; color: #aab2c0; }
            QLabel#EmptyLabel { font-size: 16px; color: #b8bfd0; }
            QComboBox#AccountCombo { background-color: #2a2a3a; border: 1px solid #3a3a4d; border-radius: 6px; padding: 4px 8px; min-height: 36px; }
            QComboBox#AccountCombo::drop-down { border: none; width: 24px; }
            QComboBox QAbstractItemView { background-color: #252536; border: 1px solid #3a3a4d; selection-background-color: #3a4a6a; outline: 0; }
            QPushButton { background-color: #343447; border: 1px solid #404055; border-radius: 6px; padding: 6px 12px; }
            QPushButton:hover { background-color: #3b3b52; }
            QPushButton:disabled { color: #7f8796; background-color: #2d2d3b; }
            QPushButton#PrimaryButton, QPushButton#ApplyButton { background-color: #7c9ef5; color: #111522; border: none; font-weight: 600; }
            QPushButton#PrimaryButton:hover, QPushButton#ApplyButton:hover { background-color: #8cabf7; }
            QPushButton#PrimaryButton:disabled, QPushButton#ApplyButton:disabled { background-color: #4a5e86; color: #d0d6e4; }
            QToolButton#IconButton, QToolButton#MoreButton { background-color: #343447; border: 1px solid #404055; border-radius: 6px; padding: 6px; min-width: 28px; }
            QToolButton#IconButton:hover, QToolButton#MoreButton:hover { background-color: #3b3b52; }
            QToolButton#MoreButton { font-size: 16px; font-weight: 700; }
            QProgressBar { background-color: #2a2a3a; border: 1px solid #343446; border-radius: 4px; }
            QProgressBar::chunk { background-color: #7c9ef5; border-radius: 4px; }
            QScrollArea { background: transparent; }
            QMenu { background-color: #252536; color: #e6e6f0; border: 1px solid #3a3a4d; }
            QMenu::item:selected { background-color: #3a4a6a; }
            QMessageBox QLabel { color: #e6e6f0; }
            QLineEdit { background-color: #2a2a3a; border: 1px solid #3a3a4d; border-radius: 6px; padding: 6px; }
            """
        )

    # --- Initialization & state ---
    def initialize_state(self) -> None:
        self.ensure_steam_path()
        self.update_steam_path_label()
        self.refresh_accounts(select_saved=True)
        self.refresh_configs()
        self.refresh_profiles_async(force=bool(self.settings_data.get("check_avatar_updates", True)))

    def ensure_steam_path(self) -> None:
        steam_path = (self.settings_data.get("steam_path") or "").strip()
        if steam_path and Path(steam_path).exists():
            return
        detected = detect_steam_path()
        if detected:
            self.settings_data["steam_path"] = detected
            save_settings(self.settings_data)
            self.set_status(f"Найден Steam: {detected}")
            return
        self.set_status("Steam не найден")
        QMessageBox.information(
            self,
            "Steam не найден",
            "Не удалось автоматически определить путь к Steam. Укажите папку Steam вручную.",
        )
        self.choose_steam_path()

    def update_steam_path_label(self) -> None:
        path = self.settings_data.get("steam_path") or "Не задан"
        self.steam_path_label.setText(self._elide_middle(str(path), 60))
        self.steam_path_label.setToolTip(str(path))

    @staticmethod
    def _elide_middle(text: str, max_len: int) -> str:
        if len(text) <= max_len:
            return text
        keep = max_len - 3
        left = keep // 2
        right = keep - left
        return text[:left] + "..." + text[-right:]

    def get_selected_account_id(self) -> Optional[str]:
        idx = self.account_combo.currentIndex()
        if idx < 0:
            return None
        val = self.account_combo.itemData(idx)
        return str(val) if val else None

    def refresh_all(self) -> None:
        self.refresh_accounts(select_saved=False)
        self.refresh_configs()
        self.refresh_profiles_async(force=False)
        self.set_status("Обновлено")

    # --- Accounts ---
    def refresh_accounts(self, select_saved: bool = True) -> None:
        steam_path = self.settings_data.get("steam_path") or ""
        self.account_combo.blockSignals(True)
        self.account_combo.clear()
        self.accounts = []
        if not steam_path or not Path(steam_path).exists():
            self.account_combo.addItem("Steam не найден")
            self.account_combo.setEnabled(False)
            self.account_combo.blockSignals(False)
            return
        self.account_combo.setEnabled(True)
        try:
            self.accounts = enumerate_accounts(steam_path)
        except Exception as e:
            LOGGER.exception("Failed to enumerate accounts: %s", e)
            self.set_status("Ошибка сканирования аккаунтов")
            self.accounts = []

        if not self.accounts:
            self.account_combo.addItem("Аккаунты Steam не найдены")
            self.account_combo.setEnabled(False)
            self.account_combo.blockSignals(False)
            QMessageBox.information(
                self,
                "Аккаунты не найдены",
                "В папке userdata не найдено ни одного аккаунта. Запустите Steam хотя бы раз.",
            )
            return

        selected_id = str(self.settings_data.get("selected_account_id") or "")
        selected_index = 0
        for i, acc in enumerate(self.accounts):
            aid = str(acc["account_id"])
            label = f"SteamID: {aid}" if not self.settings_data.get("api_key") else aid
            # Show has_dota hint subtly in tooltip/label maybe not necessary; add marker in name later if no profile
            display_name = f"{aid}" if self.settings_data.get("api_key") else f"SteamID: {aid}"
            if not acc.get("has_dota", False):
                display_name += " (нет Dota 2)"
            self.account_combo.addItem(make_avatar_pixmap(None), display_name, aid)
            self.account_combo.setItemData(i, display_name, Qt.UserRole)
            self.account_combo.setItemData(i, aid, Qt.UserRole + 1)
            self.account_combo.setItemData(i, None, Qt.UserRole + 2)
            if select_saved and selected_id and aid == selected_id:
                selected_index = i

        # If saved not found, keep previous selection if possible
        if not selected_id and self.accounts:
            selected_index = 0
            self.settings_data["selected_account_id"] = str(self.accounts[0]["account_id"])
            save_settings(self.settings_data)
        elif selected_id and all(str(a["account_id"]) != selected_id for a in self.accounts):
            self.settings_data["selected_account_id"] = str(self.accounts[0]["account_id"])
            save_settings(self.settings_data)
            selected_index = 0

        self.account_combo.setCurrentIndex(selected_index)
        self.account_combo.blockSignals(False)
        self.update_account_combo_display()

    def update_account_combo_display(self) -> None:
        for i in range(self.account_combo.count()):
            aid = self.account_combo.itemData(i)
            if not aid:
                continue
            aid = str(aid)
            prof = self.profiles.get(aid, {})
            name = prof.get("personaname") or f"SteamID: {aid}"
            acc = next((a for a in self.accounts if str(a["account_id"]) == aid), None)
            if acc and not acc.get("has_dota", False):
                name = f"{name} (нет Dota 2)"
            avatar_path = prof.get("avatar_path")
            self.account_combo.setItemIcon(i, QIcon(make_avatar_pixmap(avatar_path, 32, 8)))
            self.account_combo.setItemData(i, name, Qt.UserRole)
            self.account_combo.setItemData(i, aid, Qt.UserRole + 1)
            self.account_combo.setItemData(i, avatar_path, Qt.UserRole + 2)
            # Also set display text for accessibility/fallback
            self.account_combo.setItemText(i, name)

    def refresh_profiles_async(self, force: bool = False) -> None:
        if not self.accounts:
            return
        account_ids = [str(a["account_id"]) for a in self.accounts]
        api_key = (self.settings_data.get("api_key") or "").strip()
        if not api_key:
            # no API key -> ensure fallback display
            self.profiles = {}
            self.update_account_combo_display()
            return

        task = FunctionRunnable(get_account_profiles, account_ids, api_key, force)
        task.signals.finished.connect(self.on_profiles_loaded)
        task.signals.error.connect(self.on_profiles_error)
        self.thread_pool.start(task)

    def on_profiles_loaded(self, result: object) -> None:
        if isinstance(result, dict):
            self.profiles = result
            self.update_account_combo_display()

    def on_profiles_error(self, message: str, details: str) -> None:
        LOGGER.warning("Profile load error: %s\n%s", message, details)
        # Don't block app; show status once
        if "Steam API" in message or "ключ" in message.lower():
            self.set_status("Ошибка Steam API")
            QMessageBox.warning(self, "Steam API", f"Не удалось получить профили Steam: {message}")

    def on_account_changed(self, index: int) -> None:
        aid = self.get_selected_account_id()
        if aid:
            self.settings_data["selected_account_id"] = aid
            save_settings(self.settings_data)
        self.refresh_configs()

    # --- Configs ---
    def get_configs_dir(self) -> str:
        return str(self.settings_data.get("configs_dir") or get_base_dir())

    def clear_config_cards(self) -> None:
        # remove all widgets except final stretch
        while self.cards_layout.count() > 1:
            item = self.cards_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def refresh_configs(self) -> None:
        self.clear_config_cards()
        configs_dir = self.get_configs_dir()
        configs: List[ConfigInfo] = []
        try:
            if configs_dir and Path(configs_dir).exists():
                configs = list_configs(configs_dir)
        except Exception as e:
            LOGGER.exception("Failed to list configs: %s", e)
            self.set_status("Ошибка чтения конфигов")
            QMessageBox.warning(self, "Ошибка", f"Не удалось прочитать список конфигов: {e}")
            configs = []

        if not configs:
            self.scroll.setVisible(False)
            self.empty_state.setVisible(True)
            return

        self.empty_state.setVisible(False)
        self.scroll.setVisible(True)
        for cfg in configs:
            card = ConfigCard(cfg.name, cfg.path, cfg.modified_str, cfg.size_str)
            card.apply_clicked.connect(self.start_apply_config)
            card.delete_clicked.connect(self.confirm_delete_config)
            card.open_clicked.connect(self.open_config_folder)
            self.cards_layout.insertWidget(self.cards_layout.count() - 1, card)

    # --- Actions ---
    def choose_steam_path(self) -> None:
        current = self.settings_data.get("steam_path") or str(get_base_dir())
        path = QFileDialog.getExistingDirectory(self, "Выберите папку Steam", current)
        if not path:
            return
        self.settings_data["steam_path"] = path
        save_settings(self.settings_data)
        self.update_steam_path_label()
        self.refresh_accounts(select_saved=True)
        self.refresh_configs()
        self.refresh_profiles_async(force=False)
        self.set_status("Путь к Steam обновлён")

    def open_settings_dialog(self) -> None:
        dlg = SettingsDialog(self.settings_data, self)
        if dlg.exec():
            new_settings = dlg.get_settings()
            self.settings_data.update(new_settings)
            save_settings(self.settings_data)
            self.update_steam_path_label()
            self.refresh_accounts(select_saved=True)
            self.refresh_configs()
            self.refresh_profiles_async(force=False)
            self.set_status("Настройки сохранены")

    def validate_ready_for_ops(self) -> Optional[tuple[str, str]]:
        steam_path = self.settings_data.get("steam_path") or ""
        if not steam_path or not Path(steam_path).exists():
            QMessageBox.warning(self, "Ошибка", "Путь к Steam не задан или не найден.")
            return None
        account_id = self.get_selected_account_id()
        if not account_id:
            QMessageBox.warning(self, "Ошибка", "Не выбран аккаунт Steam.")
            return None
        return steam_path, account_id

    def save_current_config_dialog(self) -> None:
        ready = self.validate_ready_for_ops()
        if not ready:
            return
        steam_path, account_id = ready
        configs_dir = self.get_configs_dir()
        name, ok = QInputDialog.getText(self, "Сохранить текущий конфиг", "Введите имя конфига:")
        if not ok:
            return
        name = (name or "").strip()
        # quick validation feedback early
        from configs import validate_config_name
        valid, msg = validate_config_name(name, configs_dir)
        if not valid:
            QMessageBox.warning(self, "Некорректное имя", msg)
            return

        self.start_worker(
            save_current_config,
            steam_path,
            account_id,
            configs_dir,
            name,
            busy_text="Сохранение конфига...",
            success_message=f"Конфиг '{name}' сохранён",
            on_success=lambda _p: self.refresh_configs(),
        )

    def start_apply_config(self, config_path: str) -> None:
        ready = self.validate_ready_for_ops()
        if not ready:
            return
        steam_path, account_id = ready
        cfg_name = Path(config_path).name
        reply = QMessageBox.question(
            self,
            "Применить конфиг",
            f"Применить конфиг '{cfg_name}' для выбранного аккаунта?\n\n"
            f"Текущие файлы в userdata\\{account_id}\\570 будут заменены.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        self.start_worker(
            apply_config,
            config_path,
            steam_path,
            account_id,
            busy_text=f"Применение '{cfg_name}'...",
            success_message=f"Конфиг '{cfg_name}' применён",
        )

    def confirm_delete_config(self, config_path: str) -> None:
        name = Path(config_path).name
        reply = QMessageBox.question(
            self,
            "Удалить конфиг",
            f"Удалить конфиг '{name}'?\nЭто действие нельзя отменить.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        try:
            delete_config(config_path)
            self.set_status(f"Конфиг '{name}' удалён")
            self.refresh_configs()
        except Exception as e:
            LOGGER.exception("Failed to delete config %s: %s", config_path, e)
            QMessageBox.critical(self, "Ошибка", f"Не удалось удалить конфиг: {e}")

    def open_config_folder(self, config_path: str) -> None:
        try:
            open_in_explorer(config_path)
        except Exception as e:
            QMessageBox.warning(self, "Ошибка", f"Не удалось открыть папку: {e}")

    # --- Worker/progress handling ---
    def set_busy(self, busy: bool, text: str = "") -> None:
        for w in [self.save_btn, self.refresh_btn, self.empty_save_btn, self.change_path_btn, self.settings_btn, self.account_combo]:
            w.setDisabled(busy)
        # Disable apply/more buttons on cards
        for i in range(self.cards_layout.count() - 1):
            item = self.cards_layout.itemAt(i)
            if not item:
                continue
            card = item.widget()
            if isinstance(card, ConfigCard):
                card.apply_btn.setDisabled(busy)
                card.more_btn.setDisabled(busy)

        self.progress_bar.setVisible(busy)
        if busy:
            self.progress_bar.setRange(0, 0)  # indeterminate until first progress
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat("")
            if text:
                self.set_status(text)
        else:
            self.progress_bar.setRange(0, 1)
            self.progress_bar.setValue(0)

    def start_worker(self, fn, *args, busy_text: str, success_message: str, on_success=None) -> None:
        if self.current_copy_worker and self.current_copy_worker.isRunning():
            QMessageBox.information(self, "Операция выполняется", "Дождитесь завершения текущей операции.")
            return
        worker = CopyWorker(fn, *args)
        self.current_copy_worker = worker
        self.set_busy(True, busy_text)

        def on_progress(current: int, total: int, message: str) -> None:
            if total > 0:
                self.progress_bar.setRange(0, total)
                self.progress_bar.setValue(max(0, min(current, total)))
            else:
                self.progress_bar.setRange(0, 0)
            if message:
                self.set_status(message)

        def on_finished(result: object) -> None:
            self.set_busy(False)
            self.current_copy_worker = None
            self.set_status(success_message)
            QMessageBox.information(self, "Готово", success_message)
            if on_success:
                try:
                    on_success(result)
                except Exception:
                    LOGGER.exception("on_success callback failed")

        def on_error(message: str, details: str) -> None:
            self.set_busy(False)
            self.current_copy_worker = None
            LOGGER.error("Operation failed: %s\n%s", message, details)
            self.set_status("Ошибка")
            QMessageBox.critical(self, "Ошибка", str(message))

        worker.progress.connect(on_progress)
        worker.finished.connect(on_finished)
        worker.error.connect(on_error)
        worker.start()

    def set_status(self, text: str) -> None:
        self.status_label.setText(text)
        self.status_label.setToolTip(text)
