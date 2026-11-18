"""Main application window."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QEvent, QSize, Qt, QThreadPool, QTimer
from PySide6.QtGui import QAction, QCloseEvent, QFontMetrics, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStatusBar,
    QStyle,
    QSystemTrayIcon,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from configs import (
    ConfigInfo,
    apply_config,
    delete_config,
    import_config_folder,
    list_configs,
    open_in_explorer,
    save_current_config,
    scan_importable_configs,
    validate_config_name_format,
)
from settings import (
    get_base_dir,
    get_default_configs_dir,
    get_last_migration_message,
    get_legacy_base_dir,
    get_resource_path,
    load_settings,
    save_settings,
)
from steam import detect_steam_path, enumerate_accounts, get_local_profiles
from ui.import_dialog import ImportConfigsDialog
from ui.settings_dialog import SettingsDialog
from ui.widgets import (
    AccountComboDelegate,
    ConfigCard,
    RenameDialog,
    ask_yes_no,
    make_avatar_pixmap,
    show_error,
    show_info,
    show_warning,
)
from ui.workers import CopyWorker, FunctionRunnable

LOGGER = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DotaConfigSwitcher")
        self.resize(800, 600)
        self.setMinimumSize(720, 520)

        self._app_icon = QIcon()
        icon_path = get_resource_path("icon.ico")
        if icon_path.exists():
            self._app_icon = QIcon(str(icon_path))
            self.setWindowIcon(self._app_icon)

        self.settings_data: Dict[str, Any] = load_settings()
        self.accounts: List[Dict[str, Any]] = []
        self.profiles: Dict[str, Dict[str, Any]] = {}
        self.configs_cache: List[ConfigInfo] = []
        self.current_copy_worker: Optional[CopyWorker] = None
        self.thread_pool = QThreadPool.globalInstance()
        self._is_quitting: bool = False
        self.tray_icon: Optional[QSystemTrayIcon] = None
        self.tray_menu: Optional[QMenu] = None

        self._build_ui()
        self._apply_styles()
        self._init_tray_icon()

        QTimer.singleShot(0, self.initialize_state)

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # Top bar
        top_bar = QFrame()
        top_bar.setObjectName("TopBar")
        top_bar.setFixedHeight(64)
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(16, 10, 16, 10)
        top_layout.setSpacing(12)

        self.account_combo = QComboBox()
        self.account_combo.setObjectName("AccountCombo")
        self.account_combo.setMinimumWidth(280)
        self.account_combo.setMaximumWidth(420)
        self.account_combo.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.account_combo.setIconSize(QSize(32, 32))
        self.account_combo.setItemDelegate(AccountComboDelegate(self.account_combo))
        self.account_combo.currentIndexChanged.connect(self.on_account_changed)
        top_layout.addWidget(self.account_combo, 0, Qt.AlignVCenter)

        self.favorite_btn = QToolButton()
        self.favorite_btn.setObjectName("IconButton")
        self.favorite_btn.setToolTip("Сделать профиль избранным")
        self.favorite_btn.setText("☆")
        self.favorite_btn.setFixedSize(32, 32)
        self.favorite_btn.clicked.connect(self.toggle_favorite_account)
        top_layout.addWidget(self.favorite_btn, 0, Qt.AlignVCenter)

        top_layout.addStretch(1)

        self.settings_btn = QToolButton()
        self.settings_btn.setObjectName("IconButton")
        self.settings_btn.setToolTip("\u041d\u0430\u0441\u0442\u0440\u043e\u0439\u043a\u0438")
        self.settings_btn.setText("\u2699")
        self.settings_btn.setFixedSize(32, 32)
        self.settings_btn.clicked.connect(self.open_settings_dialog)
        top_layout.addWidget(self.settings_btn, 0, Qt.AlignVCenter)
        root.addWidget(top_bar)

        # Center area (scrollable config cards)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.cards_container = QWidget()
        self.cards_layout = QVBoxLayout(self.cards_container)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        self.cards_layout.setSpacing(12)
        self.cards_layout.addStretch(1)
        self.scroll.setWidget(self.cards_container)
        root.addWidget(self.scroll, 1)

        # Empty state
        self.empty_state = QFrame()
        self.empty_state.setObjectName("EmptyState")
        empty_layout = QVBoxLayout(self.empty_state)
        empty_layout.setContentsMargins(16, 16, 16, 16)
        empty_layout.setSpacing(12)
        empty_layout.addStretch(1)

        empty_icon = QLabel()
        empty_icon.setAlignment(Qt.AlignCenter)
        empty_icon.setPixmap(self.style().standardIcon(QStyle.SP_DirIcon).pixmap(56, 56))
        empty_layout.addWidget(empty_icon, 0, Qt.AlignHCenter)

        self.empty_label = QLabel("Нет сохранённых конфигов")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setObjectName("EmptyLabel")
        empty_layout.addWidget(self.empty_label, 0, Qt.AlignHCenter)

        self.empty_hint_label = QLabel("Сохраните текущий конфиг Dota 2 или импортируйте существующие папки.")
        self.empty_hint_label.setAlignment(Qt.AlignCenter)
        self.empty_hint_label.setWordWrap(True)
        self.empty_hint_label.setObjectName("EmptyHintLabel")
        empty_layout.addWidget(self.empty_hint_label, 0, Qt.AlignHCenter)

        empty_buttons = QHBoxLayout()
        empty_buttons.setSpacing(12)
        empty_buttons.addStretch(1)
        self.empty_save_btn = QPushButton("Создать первый конфиг")
        self.empty_save_btn.setObjectName("PrimaryButton")
        self.empty_save_btn.clicked.connect(self.save_current_config_dialog)
        empty_buttons.addWidget(self.empty_save_btn)
        self.empty_import_btn = QPushButton("Импортировать конфиги")
        self.empty_import_btn.setObjectName("SecondaryButton")
        self.empty_import_btn.clicked.connect(self.open_import_dialog)
        empty_buttons.addWidget(self.empty_import_btn)
        empty_buttons.addStretch(1)
        empty_layout.addLayout(empty_buttons)

        empty_layout.addStretch(1)
        self.empty_state.setVisible(False)
        root.addWidget(self.empty_state, 1)

        # Bottom panel
        bottom = QFrame()
        bottom.setObjectName("BottomBar")
        bottom_layout = QVBoxLayout(bottom)
        bottom_layout.setContentsMargins(16, 12, 16, 12)
        bottom_layout.setSpacing(8)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(6)
        bottom_layout.addWidget(self.progress_bar)

        actions_row = QHBoxLayout()
        actions_row.setSpacing(12)

        self.save_btn = QPushButton("Сохранить текущий конфиг")
        self.save_btn.setObjectName("PrimaryButton")
        self.save_btn.clicked.connect(self.save_current_config_dialog)
        actions_row.addWidget(self.save_btn, 0, Qt.AlignVCenter)

        self.import_btn = QPushButton("Импортировать конфиги")
        self.import_btn.setObjectName("SecondaryButton")
        self.import_btn.clicked.connect(self.open_import_dialog)
        actions_row.addWidget(self.import_btn, 0, Qt.AlignVCenter)

        self.refresh_profiles_btn = QPushButton("Обновить профили")
        self.refresh_profiles_btn.setObjectName("SecondaryButton")
        self.refresh_profiles_btn.setIcon(self.style().standardIcon(QStyle.SP_BrowserReload))
        self.refresh_profiles_btn.setToolTip("Обновить профили, аккаунты и список конфигов")
        self.refresh_profiles_btn.clicked.connect(self.refresh_all)
        actions_row.addWidget(self.refresh_profiles_btn, 0, Qt.AlignVCenter)

        actions_row.addStretch(1)

        bottom_layout.addLayout(actions_row)

        self.status_label = QLabel("Готово")
        self.status_label.setObjectName("StatusLabel")
        self.status_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.status_label.setWordWrap(False)
        bottom_layout.addWidget(self.status_label)

        root.addWidget(bottom)

        self.setStatusBar(QStatusBar())
        self.statusBar().hide()

    def _apply_styles(self) -> None:
        self.setStyleSheet(
            """
            QWidget { background-color: #1e1e2e; color: #e6e6f0; font-family: 'Segoe UI'; font-size: 13px; }
            QFrame#TopBar, QFrame#BottomBar { background-color: #232334; border: 1px solid #2f3042; border-radius: 10px; }
            QFrame#ConfigCard { background-color: #2a2a3a; border: 1px solid #343446; border-radius: 10px; }
            QFrame#EmptyState { background-color: #232334; border: 1px dashed #3a3a4d; border-radius: 10px; }
            QLabel#ConfigName { font-size: 14px; font-weight: 600; color: #f0f2ff; }
            QLabel#ConfigMeta { font-size: 12px; color: #9aa3b2; }
            QLabel#SteamPathLabel { font-size: 12px; color: #8f97a8; }
            QLabel#StatusLabel { font-size: 12px; color: #8bc34a; }
            QLabel#EmptyLabel { font-size: 17px; font-weight: 600; color: #d8deef; }
            QLabel#EmptyHintLabel { font-size: 12px; color: #9aa3b2; }
            QComboBox#AccountCombo { background-color: #2a2a3a; border: 1px solid #3a3a4d; border-radius: 8px; padding: 4px 10px; min-height: 36px; }
            QComboBox#AccountCombo::drop-down { border: none; width: 24px; }
            QComboBox QAbstractItemView { background-color: #252536; border: 1px solid #3a3a4d; selection-background-color: #3a4a6a; outline: 0; }
            QPushButton { background-color: #343447; border: 1px solid #404055; border-radius: 8px; padding: 7px 14px; }
            QPushButton:hover { background-color: #3b3b52; }
            QPushButton:disabled { color: #7f8796; background-color: #2d2d3b; border-color: #353545; }
            QPushButton#PrimaryButton, QPushButton#ApplyButton { background-color: #7c9ef5; color: #111522; border: none; font-weight: 600; }
            QPushButton#PrimaryButton:hover, QPushButton#ApplyButton:hover { background-color: #8cabf7; }
            QPushButton#PrimaryButton:disabled, QPushButton#ApplyButton:disabled { background-color: #4a5e86; color: #d0d6e4; }
            QToolButton#IconButton, QToolButton#MoreButton { background-color: #343447; border: 1px solid #404055; border-radius: 8px; padding: 4px; }
            QToolButton#IconButton:hover, QToolButton#MoreButton:hover { background-color: #3b3b52; }
            QToolButton#MoreButton { font-size: 16px; font-weight: 700; min-width: 32px; }
            QProgressBar { background-color: #2a2a3a; border: 1px solid #343446; border-radius: 3px; }
            QProgressBar::chunk { background-color: #7c9ef5; border-radius: 3px; }
            QScrollArea { background: transparent; }
            QMenu { background-color: #252536; color: #e6e6f0; border: 1px solid #3a3a4d; }
            QMenu::item:selected { background-color: #3a4a6a; }
            QMenu::separator { height: 1px; background: #3a3a4d; margin: 4px 6px; }
            QLineEdit { background-color: #2a2a3a; border: 1px solid #3a3a4d; border-radius: 6px; padding: 6px; }
            """
        )
        self.set_status("Готово", "ok")

    # --- Initialization & state ---
    def initialize_state(self) -> None:
        self.ensure_steam_path()
        self.refresh_accounts(select_saved=True, prefer_favorite=True)
        self.refresh_configs()
        self.refresh_profiles_async(force=True)

        migration_msg = get_last_migration_message()
        if migration_msg:
            show_info(self, "\u041c\u0438\u0433\u0440\u0430\u0446\u0438\u044f \u0434\u0430\u043d\u043d\u044b\u0445", migration_msg)
            self.set_status("\u0414\u0430\u043d\u043d\u044b\u0435 \u043f\u0435\u0440\u0435\u043d\u0435\u0441\u0435\u043d\u044b \u0432 AppData", "ok")

        self._update_tray_menu()
        self._update_tray_tooltip()

    def ensure_steam_path(self) -> None:
        steam_path = (self.settings_data.get("steam_path") or "").strip()
        if steam_path and Path(steam_path).exists():
            return
        detected = detect_steam_path()
        if detected:
            self.settings_data["steam_path"] = detected
            save_settings(self.settings_data)
            self.set_status(f"Найден Steam: {detected}", "ok")
            return
        self.set_status("Steam \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d", "error")
        show_info(
            self,
            "Steam \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d",
            "\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u0430\u0432\u0442\u043e\u043c\u0430\u0442\u0438\u0447\u0435\u0441\u043a\u0438 \u043e\u043f\u0440\u0435\u0434\u0435\u043b\u0438\u0442\u044c \u043f\u0443\u0442\u044c \u043a Steam. \u0423\u043a\u0430\u0436\u0438\u0442\u0435 \u043f\u0430\u043f\u043a\u0443 Steam \u0432\u0440\u0443\u0447\u043d\u0443\u044e.",
        )
        self.choose_steam_path()


    @staticmethod
    def _sanitize_account_id(value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        if text.isdigit():
            return text
        import re
        m = re.findall(r"\d+", text)
        if m:
            return max(m, key=len)
        return None

    def get_selected_account_id(self) -> Optional[str]:
        idx = self.account_combo.currentIndex()
        if idx < 0:
            return None
        val = self.account_combo.itemData(idx, Qt.UserRole + 1)
        if not val:
            val = self.account_combo.itemData(idx)
        return self._sanitize_account_id(val)

    def refresh_all(self) -> None:
        self.refresh_accounts(select_saved=False)
        self.refresh_configs()
        self.refresh_profiles_async(force=True)
        self.set_status("Обновлено", "ok")

    def refresh_profiles_only(self) -> None:
        self.refresh_profiles_async(force=True)
        self.set_status("Профили обновлены", "ok")

    # --- Accounts ---
    def refresh_accounts(self, select_saved: bool = True, prefer_favorite: bool = False) -> None:
        steam_path = self.settings_data.get("steam_path") or ""
        self.account_combo.blockSignals(True)
        self.account_combo.clear()
        self.accounts = []
        if not steam_path or not Path(steam_path).exists():
            self.account_combo.addItem("Steam не найден")
            self.account_combo.setEnabled(False)
            self.favorite_btn.setEnabled(False)
            self.account_combo.blockSignals(False)
            self.profiles = {}
            self._update_favorite_button()
            return
        self.account_combo.setEnabled(True)
        self.favorite_btn.setEnabled(True)
        try:
            self.accounts = enumerate_accounts(steam_path)
        except Exception as e:
            LOGGER.exception("Failed to enumerate accounts: %s", e)
            self.set_status("Ошибка сканирования аккаунтов", "error")
            self.accounts = []

        if not self.accounts:
            self.account_combo.addItem("\u0410\u043a\u043a\u0430\u0443\u043d\u0442\u044b Steam \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d\u044b")
            self.account_combo.setEnabled(False)
            self.favorite_btn.setEnabled(False)
            self.account_combo.blockSignals(False)
            show_info(
                self,
                "\u0410\u043a\u043a\u0430\u0443\u043d\u0442\u044b \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d\u044b",
                "\u0412 \u043f\u0430\u043f\u043a\u0435 userdata \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d\u043e \u043d\u0438 \u043e\u0434\u043d\u043e\u0433\u043e \u0430\u043a\u043a\u0430\u0443\u043d\u0442\u0430. \u0417\u0430\u043f\u0443\u0441\u0442\u0438\u0442\u0435 Steam \u0445\u043e\u0442\u044f \u0431\u044b \u0440\u0430\u0437.",
            )
            self.profiles = {}
            self._update_favorite_button()
            return

        favorite_id = self._sanitize_account_id(self.settings_data.get("favorite_account_id")) or ""
        account_ids_set = {str(a["account_id"]) for a in self.accounts}
        if favorite_id and favorite_id not in account_ids_set:
            favorite_id = ""
            self.settings_data["favorite_account_id"] = ""
            save_settings(self.settings_data)

        # Favorite account first, preserve relative order for others
        ordered_accounts = list(self.accounts)
        if favorite_id:
            ordered_accounts.sort(key=lambda a: 0 if str(a.get("account_id")) == favorite_id else 1)

        selected_id = self._sanitize_account_id(self.settings_data.get("selected_account_id")) or ""
        desired_id = ""
        if prefer_favorite and favorite_id:
            desired_id = favorite_id
        elif select_saved and selected_id:
            desired_id = selected_id
        elif favorite_id:
            desired_id = favorite_id

        selected_index = 0
        for i, acc in enumerate(ordered_accounts):
            aid = str(acc["account_id"])
            is_fav = (aid == favorite_id and bool(favorite_id))
            base_name = aid
            if not acc.get("has_dota", False):
                base_name += " (нет Dota 2)"
            display_name = f"★ {base_name}" if is_fav else base_name
            self.account_combo.addItem(make_avatar_pixmap(None, name=base_name, account_id=aid), display_name)
            self.account_combo.setItemData(i, display_name, Qt.UserRole)
            self.account_combo.setItemData(i, aid, Qt.UserRole + 1)
            self.account_combo.setItemData(i, None, Qt.UserRole + 2)
            self.account_combo.setItemData(i, is_fav, Qt.UserRole + 3)
            if desired_id and aid == desired_id:
                selected_index = i

        if desired_id and all(str(a["account_id"]) != desired_id for a in ordered_accounts):
            desired_id = favorite_id or str(ordered_accounts[0]["account_id"])
            selected_index = 0
            for i, acc in enumerate(ordered_accounts):
                if str(acc["account_id"]) == desired_id:
                    selected_index = i
                    break

        if not desired_id and ordered_accounts:
            desired_id = str(ordered_accounts[0]["account_id"])
            selected_index = 0

        self.settings_data["selected_account_id"] = desired_id or ""
        save_settings(self.settings_data)

        self.account_combo.setCurrentIndex(selected_index)
        self.account_combo.blockSignals(False)
        self.update_account_combo_display()
        self._update_favorite_button()

    def update_account_combo_display(self) -> None:
        favorite_id = self._sanitize_account_id(self.settings_data.get("favorite_account_id")) or ""
        for i in range(self.account_combo.count()):
            aid_raw = self.account_combo.itemData(i, Qt.UserRole + 1)
            if not aid_raw:
                aid_raw = self.account_combo.itemData(i)
            aid = self._sanitize_account_id(aid_raw)
            if not aid:
                continue
            is_fav = (aid == favorite_id and bool(favorite_id))
            prof = self.profiles.get(aid, {})
            persona = prof.get("personaname") or aid
            acc = next((a for a in self.accounts if str(a["account_id"]) == aid), None)
            display_name = persona
            if acc and not acc.get("has_dota", False):
                display_name = f"{display_name} (нет Dota 2)"
            if is_fav:
                display_name = f"★ {display_name}"
            avatar_path = prof.get("avatar_path")
            source = prof.get("source")
            if source == "loginusers.vdf":
                tooltip = f"Никнейм: из loginusers.vdf\nAccountID: {aid}"
            elif source == "localconfig.vdf":
                tooltip = f"Никнейм: из localconfig.vdf\nAccountID: {aid}"
            else:
                tooltip = f"Никнейм: не найдено (используется AccountID)\nAccountID: {aid}"
            if is_fav:
                tooltip = "Избранный профиль\n" + tooltip
            self.account_combo.setItemIcon(i, QIcon(make_avatar_pixmap(avatar_path, 32, 8, name=persona, account_id=aid)))
            self.account_combo.setItemData(i, display_name, Qt.UserRole)
            self.account_combo.setItemData(i, aid, Qt.UserRole + 1)
            self.account_combo.setItemData(i, avatar_path, Qt.UserRole + 2)
            self.account_combo.setItemData(i, is_fav, Qt.UserRole + 3)
            self.account_combo.setItemData(i, tooltip, Qt.ToolTipRole)
            self.account_combo.setItemText(i, display_name)
        self._update_favorite_button()
        self._update_tray_menu()
        self._update_tray_tooltip()

    def refresh_profiles_async(self, force: bool = False) -> None:
        if not self.accounts:
            self.profiles = {}
            self.update_account_combo_display()
            return
        steam_path = self.settings_data.get("steam_path") or ""
        if not steam_path or not Path(steam_path).exists():
            self.profiles = {}
            self.update_account_combo_display()
            return
        account_ids = [str(a["account_id"]) for a in self.accounts]
        task = FunctionRunnable(get_local_profiles, steam_path, account_ids)
        task.signals.finished.connect(self.on_profiles_loaded)
        task.signals.error.connect(self.on_profiles_error)
        self.thread_pool.start(task)

    def on_profiles_loaded(self, result: object) -> None:
        if isinstance(result, dict):
            self.profiles = result
            self.update_account_combo_display()

    def on_profiles_error(self, message: str, details: str) -> None:
        LOGGER.warning("Local profile load error: %s\n%s", message, details)
        self.set_status("Ошибка чтения профилей Steam", "error")

    def on_account_changed(self, index: int) -> None:
        aid = self.get_selected_account_id()
        if aid:
            self.settings_data["selected_account_id"] = aid
            save_settings(self.settings_data)
        self._update_favorite_button()
        self.refresh_configs()

    def _update_favorite_button(self) -> None:
        selected = self.get_selected_account_id()
        favorite = self._sanitize_account_id(self.settings_data.get("favorite_account_id")) or ""
        has_accounts = self.account_combo.isEnabled() and self.account_combo.count() > 0 and bool(selected)
        self.favorite_btn.setEnabled(has_accounts)
        if selected and favorite and selected == favorite:
            self.favorite_btn.setText("★")
            self.favorite_btn.setToolTip("Убрать профиль из избранного")
        else:
            self.favorite_btn.setText("☆")
            self.favorite_btn.setToolTip("Сделать профиль избранным")

    def toggle_favorite_account(self) -> None:
        aid = self.get_selected_account_id()
        if not aid:
            return
        current_fav = self._sanitize_account_id(self.settings_data.get("favorite_account_id")) or ""
        if current_fav == aid:
            self.settings_data["favorite_account_id"] = ""
            self.set_status("Профиль убран из избранного", "info")
        else:
            self.settings_data["favorite_account_id"] = aid
            self.set_status("Профиль добавлен в избранное", "ok")
        save_settings(self.settings_data)
        # Rebuild list so favorite is first; keep current selection
        self.settings_data["selected_account_id"] = aid
        self.refresh_accounts(select_saved=True, prefer_favorite=False)
        self._update_tray_menu()
        self._update_tray_tooltip()

    # --- Configs ---
    def get_configs_dir(self) -> str:
        return str(self.settings_data.get("configs_dir") or get_default_configs_dir())

    def clear_config_cards(self) -> None:
        while self.cards_layout.count() > 1:
            item = self.cards_layout.takeAt(0)
            w = item.widget() if item else None
            if w:
                w.deleteLater()

    def _get_last_applied_config_name(self) -> str:
        value = self.settings_data.get("last_applied_config_name")
        if value is None or str(value).strip() == "":
            value = self.settings_data.get("last_applied_config")
        return str(value or "").strip()

    def refresh_configs(self) -> None:
        self.clear_config_cards()
        configs_dir = self.get_configs_dir()
        configs: List[ConfigInfo] = []
        try:
            if configs_dir and Path(configs_dir).exists():
                configs = list_configs(configs_dir)
        except Exception as e:
            LOGGER.exception("Failed to list configs: %s", e)
            self.set_status("\u041e\u0448\u0438\u0431\u043a\u0430 \u0447\u0442\u0435\u043d\u0438\u044f \u043a\u043e\u043d\u0444\u0438\u0433\u043e\u0432", "error")
            show_warning(self, "\u041e\u0448\u0438\u0431\u043a\u0430", f"\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u043f\u0440\u043e\u0447\u0438\u0442\u0430\u0442\u044c \u0441\u043f\u0438\u0441\u043e\u043a \u043a\u043e\u043d\u0444\u0438\u0433\u043e\u0432: {e}")
            configs = []

        self.configs_cache = configs
        self._update_tray_menu()

        if not configs:
            self.scroll.setVisible(False)
            self.empty_state.setVisible(True)
            return

        self.empty_state.setVisible(False)
        self.scroll.setVisible(True)
        last_applied = self._get_last_applied_config_name()
        for cfg in configs:
            is_last_applied = (cfg.name == last_applied)
            card = ConfigCard(cfg.name, cfg.path, cfg.modified_date_str, cfg.size_str, is_last_applied=is_last_applied)
            card.apply_clicked.connect(self.start_apply_config)
            card.delete_clicked.connect(self.confirm_delete_config)
            card.open_clicked.connect(self.open_config_folder)
            card.rename_clicked.connect(self.rename_config)
            self.cards_layout.insertWidget(self.cards_layout.count() - 1, card)

    # --- Actions ---
    def choose_steam_path(self) -> None:
        current = self.settings_data.get("steam_path") or str(get_legacy_base_dir())
        path = QFileDialog.getExistingDirectory(self, "Выберите папку Steam", current)
        if not path:
            return
        self.settings_data["steam_path"] = path
        save_settings(self.settings_data)
        self.refresh_accounts(select_saved=True)
        self.refresh_configs()
        self.refresh_profiles_async(force=True)
        self.set_status("Путь к Steam обновлён", "ok")

    def open_settings_dialog(self) -> None:
        dlg = SettingsDialog(self.settings_data, self)
        if dlg.exec():
            new_settings = dlg.get_settings()
            self.settings_data.update(new_settings)
            save_settings(self.settings_data)
            self.refresh_accounts(select_saved=True)
            self.refresh_configs()
            self.refresh_profiles_async(force=True)
            self.set_status("Настройки сохранены", "ok")

    def validate_ready_for_ops(self) -> Optional[tuple[str, str]]:
        steam_path = self.settings_data.get("steam_path") or ""
        if not steam_path or not Path(steam_path).exists():
            show_warning(self, "\u041e\u0448\u0438\u0431\u043a\u0430", "\u041f\u0443\u0442\u044c \u043a Steam \u043d\u0435 \u0437\u0430\u0434\u0430\u043d \u0438\u043b\u0438 \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d.")
            self.set_status("\u041f\u0443\u0442\u044c \u043a Steam \u043d\u0435 \u0437\u0430\u0434\u0430\u043d", "error")
            return None
        account_id = self.get_selected_account_id()
        if not account_id:
            show_warning(self, "\u041e\u0448\u0438\u0431\u043a\u0430", "\u041d\u0435 \u0432\u044b\u0431\u0440\u0430\u043d \u0430\u043a\u043a\u0430\u0443\u043d\u0442 Steam.")
            self.set_status("\u041d\u0435 \u0432\u044b\u0431\u0440\u0430\u043d \u0430\u043a\u043a\u0430\u0443\u043d\u0442 Steam", "error")
            return None
        return steam_path, account_id

    def save_current_config_dialog(self) -> None:
        ready = self.validate_ready_for_ops()
        if not ready:
            return
        steam_path, account_id = ready
        configs_dir = self.get_configs_dir()
        name, ok = RenameDialog.get_text(
            self,
            "\u0421\u043e\u0445\u0440\u0430\u043d\u0438\u0442\u044c \u0442\u0435\u043a\u0443\u0449\u0438\u0439 \u043a\u043e\u043d\u0444\u0438\u0433",
            "\u0412\u0432\u0435\u0434\u0438\u0442\u0435 \u0438\u043c\u044f \u043a\u043e\u043d\u0444\u0438\u0433\u0430:",
        )
        if not ok:
            return
        name = (name or "").strip()
        from configs import validate_config_name
        valid, msg = validate_config_name(name, configs_dir)
        if not valid:
            show_warning(self, "\u041d\u0435\u043a\u043e\u0440\u0440\u0435\u043a\u0442\u043d\u043e\u0435 \u0438\u043c\u044f", msg)
            return

        self.start_worker(
            save_current_config,
            steam_path,
            account_id,
            configs_dir,
            name,
            busy_text="\u0421\u043e\u0445\u0440\u0430\u043d\u0435\u043d\u0438\u0435 \u043a\u043e\u043d\u0444\u0438\u0433\u0430...",
            success_message=f"\u041a\u043e\u043d\u0444\u0438\u0433 '{name}' \u0441\u043e\u0445\u0440\u0430\u043d\u0451\u043d",
            on_success=lambda _p: self.refresh_configs(),
        )

    def start_apply_config(self, config_path: str) -> None:
        ready = self.validate_ready_for_ops()
        if not ready:
            return
        steam_path, account_id = ready
        cfg_name = Path(config_path).name
        confirmed = ask_yes_no(
            self,
            "\u041f\u0440\u0438\u043c\u0435\u043d\u0438\u0442\u044c \u043a\u043e\u043d\u0444\u0438\u0433",
            f"\u041f\u0440\u0438\u043c\u0435\u043d\u0438\u0442\u044c \u043a\u043e\u043d\u0444\u0438\u0433 '{cfg_name}' \u0434\u043b\u044f \u0432\u044b\u0431\u0440\u0430\u043d\u043d\u043e\u0433\u043e \u0430\u043a\u043a\u0430\u0443\u043d\u0442\u0430?\n\n"
            f"\u0422\u0435\u043a\u0443\u0449\u0438\u0435 \u0444\u0430\u0439\u043b\u044b \u0432 userdata\\{account_id}\\570 \u0431\u0443\u0434\u0443\u0442 \u0437\u0430\u043c\u0435\u043d\u0435\u043d\u044b.",
        )
        if not confirmed:
            return
        self.start_worker(
            apply_config,
            config_path,
            steam_path,
            account_id,
            busy_text=f"\u041f\u0440\u0438\u043c\u0435\u043d\u0435\u043d\u0438\u0435 '{cfg_name}'...",
            success_message=f"\u041a\u043e\u043d\u0444\u0438\u0433 '{cfg_name}' \u043f\u0440\u0438\u043c\u0435\u043d\u0451\u043d",
            on_success=lambda _p, n=cfg_name: self._record_last_applied_config(n),
        )

    def confirm_delete_config(self, config_path: str) -> None:
        name = Path(config_path).name
        confirmed = ask_yes_no(
            self,
            "\u0423\u0434\u0430\u043b\u0438\u0442\u044c \u043a\u043e\u043d\u0444\u0438\u0433",
            f"\u0423\u0434\u0430\u043b\u0438\u0442\u044c \u043a\u043e\u043d\u0444\u0438\u0433 '{name}'?\n\u042d\u0442\u043e \u0434\u0435\u0439\u0441\u0442\u0432\u0438\u0435 \u043d\u0435\u043b\u044c\u0437\u044f \u043e\u0442\u043c\u0435\u043d\u0438\u0442\u044c.",
        )
        if not confirmed:
            return
        try:
            delete_config(config_path)
            self.set_status(f"\u041a\u043e\u043d\u0444\u0438\u0433 '{name}' \u0443\u0434\u0430\u043b\u0451\u043d", "ok")
            self.refresh_configs()
        except Exception as e:
            LOGGER.exception("Failed to delete config %s: %s", config_path, e)
            self.set_status("\u041e\u0448\u0438\u0431\u043a\u0430 \u0443\u0434\u0430\u043b\u0435\u043d\u0438\u044f \u043a\u043e\u043d\u0444\u0438\u0433\u0430", "error")
            show_error(self, "\u041e\u0448\u0438\u0431\u043a\u0430", f"\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u0443\u0434\u0430\u043b\u0438\u0442\u044c \u043a\u043e\u043d\u0444\u0438\u0433: {e}")

    def open_config_folder(self, config_path: str) -> None:
        try:
            open_in_explorer(config_path)
        except Exception as e:
            show_warning(self, "\u041e\u0448\u0438\u0431\u043a\u0430", f"\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u043e\u0442\u043a\u0440\u044b\u0442\u044c \u043f\u0430\u043f\u043a\u0443: {e}")
            self.set_status("\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u043e\u0442\u043a\u0440\u044b\u0442\u044c \u043f\u0430\u043f\u043a\u0443", "error")


    def _record_last_applied_config(self, config_name: str) -> None:
        name = str(config_name or "")
        self.settings_data["last_applied_config"] = name
        self.settings_data["last_applied_config_name"] = name
        save_settings(self.settings_data)
        self._update_tray_tooltip()
        self._update_tray_menu()
        self.refresh_configs()

    def _init_tray_icon(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            LOGGER.warning("System tray is not available")
            return
        icon = self._app_icon if not self._app_icon.isNull() else self.style().standardIcon(QStyle.SP_ComputerIcon)
        self.tray_icon = QSystemTrayIcon(icon, self)
        self.tray_icon.setToolTip("DotaConfigSwitcher")
        self.tray_menu = QMenu(self)
        self.tray_menu.aboutToShow.connect(self._update_tray_menu)
        self.tray_icon.setContextMenu(self.tray_menu)
        self.tray_icon.show()
        self._update_tray_menu()
        self._update_tray_tooltip()

    def _get_favorite_profile_display_name(self) -> str:
        fav = self._sanitize_account_id(self.settings_data.get("favorite_account_id")) or ""
        if not fav:
            return "не выбран"
        prof = self.profiles.get(fav, {}) if isinstance(self.profiles, dict) else {}
        name = prof.get("personaname") or fav
        return str(name)

    def _update_tray_menu(self) -> None:
        if not self.tray_menu:
            return
        self.tray_menu.clear()

        profile_name = self._get_favorite_profile_display_name()
        profile_action = QAction(f"\u041f\u0440\u043e\u0444\u0438\u043b\u044c: {profile_name}", self.tray_menu)
        self.tray_menu.addAction(profile_action)
        profile_action.triggered.connect(self.show_from_tray)
        self.tray_menu.addSeparator()

        configs = list(self.configs_cache) if hasattr(self, "configs_cache") else []
        if configs:
            for cfg in configs:
                act = QAction(cfg.name, self.tray_menu)
                self.tray_menu.addAction(act)
                act.triggered.connect(
                    lambda _checked=False, p=cfg.path, n=cfg.name: self.quick_apply_config_from_tray(p, n)
                )
        else:
            empty_act = QAction("\u041d\u0435\u0442 \u0441\u043e\u0445\u0440\u0430\u043d\u0451\u043d\u043d\u044b\u0445 \u043a\u043e\u043d\u0444\u0438\u0433\u043e\u0432", self.tray_menu)
            self.tray_menu.addAction(empty_act)
            empty_act.setEnabled(False)

        self.tray_menu.addSeparator()
        quit_action = QAction("\u0412\u044b\u0445\u043e\u0434", self.tray_menu)
        self.tray_menu.addAction(quit_action)
        quit_action.triggered.connect(self.quit_from_tray)


    def _update_tray_tooltip(self) -> None:
        if not self.tray_icon:
            return
        last = self._get_last_applied_config_name()
        if last:
            self.tray_icon.setToolTip(f"DotaConfigSwitcher\n\u0422\u0435\u043a\u0443\u0449\u0438\u0439 \u0430\u043a\u0442\u0438\u0432\u043d\u044b\u0439 \u043a\u043e\u043d\u0444\u0438\u0433: {last}")
        else:
            self.tray_icon.setToolTip("DotaConfigSwitcher")


    def show_from_tray(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def quit_from_tray(self) -> None:
        self._is_quitting = True
        if self.tray_icon:
            self.tray_icon.hide()
        app = QApplication.instance()
        if app:
            app.quit()

    def changeEvent(self, event):  # type: ignore[override]
        if event.type() == QEvent.WindowStateChange and self.isMinimized():
            self.hide()
            event.accept()
            return
        super().changeEvent(event)

    def closeEvent(self, event: QCloseEvent) -> None:  # type: ignore[override]
        self._is_quitting = True
        if self.tray_icon:
            self.tray_icon.hide()
        app = QApplication.instance()
        if app:
            app.quit()
        event.accept()

    def rename_config(self, config_path: str) -> None:
        configs_dir = self.get_configs_dir()
        old_path = Path(config_path)
        old_name = old_path.name
        if not configs_dir:
            show_warning(
                self,
                "\u041f\u0435\u0440\u0435\u0438\u043c\u0435\u043d\u043e\u0432\u0430\u043d\u0438\u0435",
                "\u041f\u0430\u043f\u043a\u0430 \u043a\u043e\u043d\u0444\u0438\u0433\u043e\u0432 \u043d\u0435 \u0437\u0430\u0434\u0430\u043d\u0430.",
            )
            return

        new_name, ok = RenameDialog.get_text(
            self,
            "\u041f\u0435\u0440\u0435\u0438\u043c\u0435\u043d\u043e\u0432\u0430\u0442\u044c \u043a\u043e\u043d\u0444\u0438\u0433",
            "\u041d\u043e\u0432\u043e\u0435 \u0438\u043c\u044f:",
            text=old_name,
        )
        if not ok:
            return
        new_name = (new_name or "").strip()
        if not new_name or new_name == old_name:
            return

        fmt_ok, fmt_msg = validate_config_name_format(new_name)
        if not fmt_ok:
            show_warning(self, "\u041d\u0435\u043a\u043e\u0440\u0440\u0435\u043a\u0442\u043d\u043e\u0435 \u0438\u043c\u044f", fmt_msg)
            return

        target_path = Path(configs_dir) / new_name
        if target_path.exists():
            try:
                same = target_path.resolve() == old_path.resolve()
            except Exception:
                same = str(target_path).lower() == str(old_path).lower()
            if not same:
                show_warning(
                    self,
                    "\u041f\u0435\u0440\u0435\u0438\u043c\u0435\u043d\u043e\u0432\u0430\u043d\u0438\u0435",
                    "\u041a\u043e\u043d\u0444\u0438\u0433 \u0441 \u0442\u0430\u043a\u0438\u043c \u0438\u043c\u0435\u043d\u0435\u043c \u0443\u0436\u0435 \u0441\u0443\u0449\u0435\u0441\u0442\u0432\u0443\u0435\u0442.",
                )
                return

        try:
            old_path.rename(target_path)
        except Exception as e:
            LOGGER.exception("Failed to rename config %s -> %s: %s", old_path, target_path, e)
            show_error(self, "\u041e\u0448\u0438\u0431\u043a\u0430", f"\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u043f\u0435\u0440\u0435\u0438\u043c\u0435\u043d\u043e\u0432\u0430\u0442\u044c \u043a\u043e\u043d\u0444\u0438\u0433: {e}")
            self.set_status("\u041e\u0448\u0438\u0431\u043a\u0430 \u043f\u0435\u0440\u0435\u0438\u043c\u0435\u043d\u043e\u0432\u0430\u043d\u0438\u044f", "error")
            return

        last_applied = self._get_last_applied_config_name()
        if last_applied == old_name:
            self.settings_data["last_applied_config"] = new_name
            self.settings_data["last_applied_config_name"] = new_name
            save_settings(self.settings_data)
            self._update_tray_tooltip()

        self.refresh_configs()
        self.set_status(f"\u041a\u043e\u043d\u0444\u0438\u0433 \u043f\u0435\u0440\u0435\u0438\u043c\u0435\u043d\u043e\u0432\u0430\u043d: {new_name}", "ok")


    def quick_apply_config_from_tray(self, config_path: str, config_name: str) -> None:
        steam_path = str(self.settings_data.get("steam_path") or "").strip()
        favorite_id = self._sanitize_account_id(self.settings_data.get("favorite_account_id")) or ""
        if not steam_path or not Path(steam_path).exists():
            if self.tray_icon:
                self.tray_icon.showMessage("DotaConfigSwitcher", "Путь к Steam не задан или не найден.", QSystemTrayIcon.Warning, 4000)
            return
        if not favorite_id:
            if self.tray_icon:
                self.tray_icon.showMessage("DotaConfigSwitcher", "Избранный профиль Steam не выбран.", QSystemTrayIcon.Warning, 4000)
            return
        try:
            apply_config(config_path, steam_path, favorite_id)
            self._record_last_applied_config(config_name)
            self.set_status(f"Конфиг '{config_name}' применён (трей)", "ok")
            if self.tray_icon:
                self.tray_icon.showMessage(
                    "DotaConfigSwitcher",
                    f"Конфиг '{config_name}' применён для избранного профиля.",
                    QSystemTrayIcon.Information,
                    3000,
                )
        except Exception as e:
            LOGGER.exception("Tray quick-apply failed: %s", e)
            if self.tray_icon:
                self.tray_icon.showMessage("DotaConfigSwitcher", f"Ошибка применения: {e}", QSystemTrayIcon.Critical, 5000)

    def open_import_dialog(self) -> None:
        configs_dir = self.get_configs_dir()
        if not configs_dir:
            show_warning(self, "\u041e\u0448\u0438\u0431\u043a\u0430", "\u041d\u0435 \u0437\u0430\u0434\u0430\u043d\u0430 \u043f\u0430\u043f\u043a\u0430 \u043a\u043e\u043d\u0444\u0438\u0433\u043e\u0432 \u043f\u0440\u0438\u043b\u043e\u0436\u0435\u043d\u0438\u044f.")
            self.set_status("\u041d\u0435 \u0437\u0430\u0434\u0430\u043d\u0430 \u043f\u0430\u043f\u043a\u0430 \u043a\u043e\u043d\u0444\u0438\u0433\u043e\u0432", "error")
            return
        source_dir = QFileDialog.getExistingDirectory(self, "\u0412\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u043f\u0430\u043f\u043a\u0443 \u0441 \u043a\u043e\u043d\u0444\u0438\u0433\u0430\u043c\u0438 \u0434\u043b\u044f \u0438\u043c\u043f\u043e\u0440\u0442\u0430", str(get_legacy_base_dir()))
        if not source_dir:
            return
        try:
            candidates = scan_importable_configs(source_dir)
        except Exception as e:
            LOGGER.exception("Failed to scan import folder %s: %s", source_dir, e)
            self.set_status("\u041e\u0448\u0438\u0431\u043a\u0430 \u0441\u043a\u0430\u043d\u0438\u0440\u043e\u0432\u0430\u043d\u0438\u044f \u043f\u0430\u043f\u043a\u0438 \u0438\u043c\u043f\u043e\u0440\u0442\u0430", "error")
            show_error(self, "\u041e\u0448\u0438\u0431\u043a\u0430", f"\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u043f\u0440\u043e\u0441\u043a\u0430\u043d\u0438\u0440\u043e\u0432\u0430\u0442\u044c \u043f\u0430\u043f\u043a\u0443: {e}")
            return

        if not candidates:
            show_info(
                self,
                "\u0418\u043c\u043f\u043e\u0440\u0442 \u043a\u043e\u043d\u0444\u0438\u0433\u043e\u0432",
                "\u0412 \u0432\u044b\u0431\u0440\u0430\u043d\u043d\u043e\u0439 \u043f\u0430\u043f\u043a\u0435 \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d\u043e \u043a\u043e\u043d\u0444\u0438\u0433\u043e\u0432 (\u043e\u0436\u0438\u0434\u0430\u044e\u0442\u0441\u044f \u043f\u043e\u0434\u043f\u0430\u043f\u043a\u0438, \u0441\u043e\u0434\u0435\u0440\u0436\u0430\u0449\u0438\u0435 \u043f\u0430\u043f\u043a\u0443 570).",
            )
            self.set_status("\u041a\u043e\u043d\u0444\u0438\u0433\u0438 \u0434\u043b\u044f \u0438\u043c\u043f\u043e\u0440\u0442\u0430 \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d\u044b", "info")
            return

        dlg = ImportConfigsDialog(candidates, self)
        if not dlg.exec():
            return
        selected = dlg.selected_candidates()
        if not selected:
            self.set_status("Импорт отменён", "info")
            return

        imported = 0
        replaced = 0
        skipped = 0
        errors = 0

        for cand in selected:
            target_name = cand.name
            while True:
                dest_path = Path(configs_dir) / target_name
                if not dest_path.exists():
                    try:
                        import_config_folder(cand.path, configs_dir, target_name, replace=False)
                        imported += 1
                    except Exception as e:
                        errors += 1
                        LOGGER.exception("Failed to import config %s: %s", cand.path, e)
                        show_warning(self, "\u041e\u0448\u0438\u0431\u043a\u0430 \u0438\u043c\u043f\u043e\u0440\u0442\u0430", f"\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u0438\u043c\u043f\u043e\u0440\u0442\u0438\u0440\u043e\u0432\u0430\u0442\u044c '{cand.name}': {e}")
                    break

                conflict_dlg = QDialog(self)
                conflict_dlg.setWindowTitle("\u041a\u043e\u043d\u0444\u0438\u0433 \u0443\u0436\u0435 \u0441\u0443\u0449\u0435\u0441\u0442\u0432\u0443\u0435\u0442")
                conflict_dlg.setModal(True)
                if hasattr(self, "styleSheet") and self.styleSheet():
                    conflict_dlg.setStyleSheet(self.styleSheet())
                conflict_layout = QVBoxLayout(conflict_dlg)
                conflict_layout.setContentsMargins(16, 16, 16, 16)
                conflict_layout.setSpacing(12)
                conflict_label = QLabel(
                    f"\u041a\u043e\u043d\u0444\u0438\u0433 '{target_name}' \u0443\u0436\u0435 \u0441\u0443\u0449\u0435\u0441\u0442\u0432\u0443\u0435\u0442 \u0432 \u043f\u0430\u043f\u043a\u0435 \u043a\u043e\u043d\u0444\u0438\u0433\u043e\u0432.\n\u0427\u0442\u043e \u0441\u0434\u0435\u043b\u0430\u0442\u044c?"
                )
                conflict_label.setWordWrap(True)
                conflict_layout.addWidget(conflict_label)
                conflict_buttons = QHBoxLayout()
                conflict_buttons.setSpacing(8)
                conflict_buttons.addStretch(1)
                btn_rename = QPushButton("\u041f\u0435\u0440\u0435\u0438\u043c\u0435\u043d\u043e\u0432\u0430\u0442\u044c")
                btn_replace = QPushButton("\u0417\u0430\u043c\u0435\u043d\u0438\u0442\u044c")
                btn_skip = QPushButton("\u041f\u0440\u043e\u043f\u0443\u0441\u0442\u0438\u0442\u044c")
                btn_cancel = QPushButton("\u041e\u0442\u043c\u0435\u043d\u0430 \u0438\u043c\u043f\u043e\u0440\u0442\u0430")
                for b in (btn_rename, btn_replace, btn_skip, btn_cancel):
                    conflict_buttons.addWidget(b)
                conflict_layout.addLayout(conflict_buttons)
                choice = {"value": "skip"}

                def _set_choice(val: str):
                    choice["value"] = val
                    conflict_dlg.accept()

                btn_rename.clicked.connect(lambda: _set_choice("rename"))
                btn_replace.clicked.connect(lambda: _set_choice("replace"))
                btn_skip.clicked.connect(lambda: _set_choice("skip"))
                btn_cancel.clicked.connect(lambda: _set_choice("cancel"))
                conflict_dlg.exec()
                clicked = choice["value"]

                if clicked == "cancel":
                    self.refresh_configs()
                    summary = f"\u0418\u043c\u043f\u043e\u0440\u0442 \u043f\u0440\u0435\u0440\u0432\u0430\u043d: \u0434\u043e\u0431\u0430\u0432\u043b\u0435\u043d\u043e {imported}, \u0437\u0430\u043c\u0435\u043d\u0435\u043d\u043e {replaced}, \u043f\u0440\u043e\u043f\u0443\u0449\u0435\u043d\u043e {skipped}, \u043e\u0448\u0438\u0431\u043e\u043a {errors}"
                    self.set_status(summary, "info")
                    show_info(self, "\u0418\u043c\u043f\u043e\u0440\u0442 \u043a\u043e\u043d\u0444\u0438\u0433\u043e\u0432", "\u0418\u043c\u043f\u043e\u0440\u0442 \u043f\u0440\u0435\u0440\u0432\u0430\u043d \u043f\u043e\u043b\u044c\u0437\u043e\u0432\u0430\u0442\u0435\u043b\u0435\u043c.")
                    return
                if clicked == "skip":
                    skipped += 1
                    break
                if clicked == "replace":
                    try:
                        import_config_folder(cand.path, configs_dir, target_name, replace=True)
                        replaced += 1
                    except Exception as e:
                        errors += 1
                        LOGGER.exception("Failed to replace imported config %s: %s", cand.path, e)
                        show_warning(self, "\u041e\u0448\u0438\u0431\u043a\u0430 \u0438\u043c\u043f\u043e\u0440\u0442\u0430", f"\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u0437\u0430\u043c\u0435\u043d\u0438\u0442\u044c '{target_name}': {e}")
                    break
                if clicked == "rename":
                    new_name, ok = RenameDialog.get_text(
                        self,
                        "\u041f\u0435\u0440\u0435\u0438\u043c\u0435\u043d\u043e\u0432\u0430\u0442\u044c \u043a\u043e\u043d\u0444\u0438\u0433",
                        f"\u0412\u0432\u0435\u0434\u0438\u0442\u0435 \u043d\u043e\u0432\u043e\u0435 \u0438\u043c\u044f \u0434\u043b\u044f '{cand.name}':",
                        text=target_name,
                    )
                    if not ok:
                        continue
                    new_name = (new_name or "").strip()
                    fmt_ok, fmt_msg = validate_config_name_format(new_name)
                    if not fmt_ok:
                        show_warning(self, "\u041d\u0435\u043a\u043e\u0440\u0440\u0435\u043a\u0442\u043d\u043e\u0435 \u0438\u043c\u044f", fmt_msg)
                        continue
                    target_name = new_name
                    continue

                skipped += 1
                break

        self.refresh_configs()
        summary = f"\u0418\u043c\u043f\u043e\u0440\u0442 \u0437\u0430\u0432\u0435\u0440\u0448\u0451\u043d: \u0434\u043e\u0431\u0430\u0432\u043b\u0435\u043d\u043e {imported}, \u0437\u0430\u043c\u0435\u043d\u0435\u043d\u043e {replaced}, \u043f\u0440\u043e\u043f\u0443\u0449\u0435\u043d\u043e {skipped}"
        if errors:
            summary += f", \u043e\u0448\u0438\u0431\u043e\u043a {errors}"
        self.set_status(summary, "ok" if errors == 0 else "error")
        show_info(self, "\u0418\u043c\u043f\u043e\u0440\u0442 \u043a\u043e\u043d\u0444\u0438\u0433\u043e\u0432", summary + ".")

    # --- Worker/progress handling ---
    def set_busy(self, busy: bool, text: str = "") -> None:
        controls = [
            self.import_btn,
            self.save_btn,
            self.refresh_profiles_btn,
            self.empty_save_btn,
            self.empty_import_btn,
            self.settings_btn,
            self.favorite_btn,
            self.account_combo,
        ]
        for w in controls:
            w.setDisabled(busy)

        for i in range(self.cards_layout.count() - 1):
            item = self.cards_layout.itemAt(i)
            if not item:
                continue
            card = item.widget()
            if isinstance(card, ConfigCard):
                card.apply_btn.setDisabled(busy)
                if hasattr(card, "rename_btn"):
                    card.rename_btn.setDisabled(busy)
                if hasattr(card, "delete_btn"):
                    card.delete_btn.setDisabled(busy)
                if hasattr(card, "more_btn"):
                    card.more_btn.setDisabled(busy)

        self.progress_bar.setVisible(busy)
        if busy:
            self.progress_bar.setRange(0, 0)
            self.progress_bar.setValue(0)
            if text:
                self.set_status(text, "info")
        else:
            self.progress_bar.setRange(0, 1)
            self.progress_bar.setValue(0)

    def start_worker(self, fn, *args, busy_text: str, success_message: str, on_success=None) -> None:
        if self.current_copy_worker and self.current_copy_worker.isRunning():
            show_info(
                self,
                "\u041e\u043f\u0435\u0440\u0430\u0446\u0438\u044f \u0432\u044b\u043f\u043e\u043b\u043d\u044f\u0435\u0442\u0441\u044f",
                "\u0414\u043e\u0436\u0434\u0438\u0442\u0435\u0441\u044c \u0437\u0430\u0432\u0435\u0440\u0448\u0435\u043d\u0438\u044f \u0442\u0435\u043a\u0443\u0449\u0435\u0439 \u043e\u043f\u0435\u0440\u0430\u0446\u0438\u0438.",
            )
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
                self.set_status(message, "info")

        def on_finished(result: object) -> None:
            self.set_busy(False)
            self.current_copy_worker = None
            self.set_status(success_message, "ok")
            show_info(self, "\u0413\u043e\u0442\u043e\u0432\u043e", success_message)
            if on_success:
                try:
                    on_success(result)
                except Exception:
                    LOGGER.exception("on_success callback failed")

        def on_error(message: str, details: str) -> None:
            self.set_busy(False)
            self.current_copy_worker = None
            LOGGER.error("Operation failed: %s\n%s", message, details)
            self.set_status("\u041e\u0448\u0438\u0431\u043a\u0430", "error")
            show_error(self, "\u041e\u0448\u0438\u0431\u043a\u0430", str(message))

        worker.progress.connect(on_progress)
        worker.finished.connect(on_finished)
        worker.error.connect(on_error)
        worker.start()

    def set_status(self, text: str, kind: str = "info") -> None:
        self.status_label.setText(text)
        self.status_label.setToolTip(text)
        if kind == "error":
            color = "#e57373"
        elif kind == "ok":
            color = "#8bc34a"
        else:
            color = "#aab2c0"
        self.status_label.setStyleSheet(f"color: {color}; font-size: 12px;")
