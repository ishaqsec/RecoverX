"""Main RecoverX PySide6 Desktop Window with Updated Gradient Ribbon Logo."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Dict, List, Optional, Set

from PySide6.QtCore import QTimer, Qt, QUrl
from PySide6.QtGui import QColor, QCursor, QDesktopServices, QGuiApplication, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from devices.discovery import DeviceInfo, DeviceType, DriveDiscovery
from filesystems.base import (
    IntegrityStatus,
    RecoveredFileEntry,
    format_file_size,
)
from recovery.engine import (
    RecoveryEngine,
    ScanMode,
    is_same_storage_device,
)
from storage.database import RecoverXDatabase, ScanSessionRecord
from .icons import (
    create_recoverx_wordmark_pixmap,
    create_vector_icon,
    icon_kind_for_entry,
)
from .theme import ThemeManager, ThemePalette
from .views import AboutView, ReportsView, ScanDetailView
from .widgets import (
    BottomStatusBar,
    CategoryChipWidget,
    DriveCardWidget,
    HeroBannerWidget,
    OutputSaveBarWidget,
    ScanModeCardWidget,
    SidebarNavButton,
    ThemeToggleSwitch,
)
from .workers import RecoveryWorker, ScanWorker

logger = logging.getLogger("recoverx.ui.main_window")


class RecoverXMainWindow(QMainWindow):
    """
    Senior UI/UX Engineered PySide6 Desktop Interface for RecoverX:
    - Displays the updated RecoverX Gradient Ribbon Logo (`RecoverX Gradient Ribbon Logo.png`)
      at the top of the left sidebar with 'Advanced Data Recovery Tool' below it.
    - Launches in Light Mode by default (`theme_dark_v2` defaults to False).
    - Starts completely clean with zero previous data records when opened.
    - Clean floating Neon Orbit animation without radial blur shadow popping.
    - Horizontal File-Type Selection Strip placed directly below Scan Mode buttons.
    - Includes 'Clear Results' button in Scan Results toolbar and Scan tab.
    """

    def __init__(
        self,
        db: Optional[RecoverXDatabase] = None,
        sample_images_dir: Optional[str] = None,
    ):
        super().__init__()
        self.db = db or RecoverXDatabase()
        # Ensure zero previous scan findings or report records show when opening the tool
        self.db.clear_all_session_and_report_records()

        self.engine = RecoveryEngine(db=self.db)
        self.sample_images_dir = sample_images_dir or str(
            Path(__file__).resolve().parent.parent / "sample_images"
        )
        self.discovery = DriveDiscovery()

        saved_dark = self.db.get_setting("theme_dark_v2", False)
        self._is_dark: bool = bool(saved_dark)
        self._palette: ThemePalette = ThemeManager.get_palette(self._is_dark)

        default_out = str(Path.home() / "RecoverX_Output")
        self._output_dir: str = str(self.db.get_setting("output_directory", default_out))

        self._devices: List[DeviceInfo] = []
        self._selected_device: Optional[DeviceInfo] = None
        self._selected_mode: ScanMode = ScanMode.QUICK_SCAN
        self._current_session: Optional[ScanSessionRecord] = None
        self._all_entries: List[RecoveredFileEntry] = []
        self._filtered_entries: List[RecoveredFileEntry] = []
        self._active_category: str = "All Files"
        self._selected_file_types: Set[str] = set()

        self._scan_worker: Optional[ScanWorker] = None
        self._recovery_worker: Optional[RecoveryWorker] = None
        self._last_drive_signature: str = ""

        self.setWindowTitle("RecoverX — Advanced Data Recovery Tool")
        self.setWindowIcon(QIcon(create_vector_icon("recoverx_logo", 64)))

        self._build_ui()
        self._fit_to_screen_resolution()
        self.apply_theme(self._is_dark)
        self.refresh_drives()

        self._hotplug_timer = QTimer(self)
        self._hotplug_timer.setInterval(2000)
        self._hotplug_timer.timeout.connect(self._check_peripheral_hotplug)
        self._hotplug_timer.start()

    def _fit_to_screen_resolution(self) -> None:
        self.setMinimumSize(980, 640)
        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            target_w = min(1536, max(1024, int(avail.width() * 0.94)))
            target_h = min(1000, max(660, int(avail.height() * 0.92)))
            self.resize(target_w, target_h)
            x = avail.x() + max(0, (avail.width() - target_w) // 2)
            y = avail.y() + max(0, (avail.height() - target_h) // 2)
            self.move(x, y)
        else:
            self.resize(1366, 768)

    def _check_peripheral_hotplug(self) -> None:
        sig = self.discovery.get_connected_drive_signature()
        if sig != self._last_drive_signature:
            self._last_drive_signature = sig
            self.refresh_drives()

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("MainRoot")
        self.setCentralWidget(root)

        root_hbox = QHBoxLayout(root)
        root_hbox.setContentsMargins(0, 0, 0, 0)
        root_hbox.setSpacing(0)

        self.root_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.root_splitter.setHandleWidth(2)
        self.root_splitter.setChildrenCollapsible(False)

        # =====================================================================
        # 1. LEFT SIDEBAR (with Updated RecoverX Gradient Ribbon Wordmark Logo)
        # =====================================================================
        self.sidebar = QFrame()
        self.sidebar.setObjectName("SidebarFrame")
        self.sidebar.setMinimumWidth(242)
        self.sidebar.setMaximumWidth(280)
        sb_vbox = QVBoxLayout(self.sidebar)
        sb_vbox.setContentsMargins(12, 14, 12, 14)
        sb_vbox.setSpacing(7)

        brand_col = QVBoxLayout()
        brand_col.setContentsMargins(4, 2, 4, 10)
        brand_col.setSpacing(4)

        self.brand_logo_lbl = QLabel()
        self.brand_logo_lbl.setFixedHeight(44)
        self.brand_logo_lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.brand_logo_lbl.setPixmap(create_recoverx_wordmark_pixmap(42, is_dark=self._is_dark))
        brand_col.addWidget(self.brand_logo_lbl)

        self.brand_sub = QLabel("Advanced Data Recovery Tool")
        self.brand_sub.setWordWrap(False)
        brand_col.addWidget(self.brand_sub)
        sb_vbox.addLayout(brand_col)

        self.nav_buttons: Dict[str, SidebarNavButton] = {}
        nav_specs = [
            ("Recover", "home"),
            ("Scan", "search"),
            ("Reports", "reports"),
            ("About", "about"),
        ]
        for label, icon_kind in nav_specs:
            btn = SidebarNavButton(label, icon_kind)
            btn.clicked.connect(lambda _=False, name=label: self.switch_section(name))
            sb_vbox.addWidget(btn)
            self.nav_buttons[label] = btn

        sb_vbox.addStretch(1)

        # Theme Switch Row in Left Sidebar Panel
        self.sidebar_theme_card = QFrame()
        self.sidebar_theme_card.setObjectName("SafeReadOnlyCard")
        theme_row = QHBoxLayout(self.sidebar_theme_card)
        theme_row.setContentsMargins(12, 8, 12, 8)
        theme_row.setSpacing(8)
        self.theme_lbl = QLabel("Theme")
        theme_row.addWidget(self.theme_lbl)
        theme_row.addStretch(1)
        self.theme_switch = ThemeToggleSwitch(is_dark=self._is_dark)
        self.theme_switch.toggled.connect(self.apply_theme)
        theme_row.addWidget(self.theme_switch)
        sb_vbox.addWidget(self.sidebar_theme_card)

        # Safe. Read-Only. Card
        self.safe_card = QFrame()
        self.safe_card.setObjectName("SafeReadOnlyCard")
        safe_hbox = QHBoxLayout(self.safe_card)
        safe_hbox.setContentsMargins(10, 10, 10, 10)
        safe_hbox.setSpacing(10)

        shield_lbl = QLabel()
        shield_lbl.setPixmap(create_vector_icon("shield", 34))
        safe_hbox.addWidget(shield_lbl)

        safe_txt_col = QVBoxLayout()
        safe_txt_col.setSpacing(1)
        self.safe_title_lbl = QLabel("Safe. Read-Only.")
        self.safe_desc_lbl = QLabel("Your data is never modified during scanning.")
        self.safe_desc_lbl.setWordWrap(True)
        safe_txt_col.addWidget(self.safe_title_lbl)
        safe_txt_col.addWidget(self.safe_desc_lbl)
        safe_hbox.addLayout(safe_txt_col, stretch=1)
        sb_vbox.addWidget(self.safe_card)

        self.root_splitter.addWidget(self.sidebar)

        # =====================================================================
        # 2. RIGHT MAIN CONTENT AREA
        # =====================================================================
        right_container = QWidget()
        right_vbox = QVBoxLayout(right_container)
        right_vbox.setContentsMargins(14, 10, 14, 8)
        right_vbox.setSpacing(6)

        self.main_stack = QStackedWidget()

        self.recover_page = self._build_recover_dashboard()
        self.main_stack.addWidget(self.recover_page)

        self.scan_view = ScanDetailView(self.db)
        self.scan_view.resume_session_requested.connect(self._load_saved_session)
        self.scan_view.clear_requested.connect(self.clear_scan_results)
        self.main_stack.addWidget(self.scan_view)

        self.reports_view = ReportsView(
            self.db,
            get_current_context=lambda: (self._current_session, self._all_entries),
        )
        self.main_stack.addWidget(self.reports_view)

        self.about_view = AboutView(db=self.db)
        self.main_stack.addWidget(self.about_view)

        right_vbox.addWidget(self.main_stack, stretch=1)

        self.bottom_status = BottomStatusBar()
        self.bottom_status.stop_requested.connect(self.stop_active_scan)
        right_vbox.addWidget(self.bottom_status)

        self.root_splitter.addWidget(right_container)
        self.root_splitter.setStretchFactor(0, 0)
        self.root_splitter.setStretchFactor(1, 1)
        self.root_splitter.setSizes([244, 1015])

        root_hbox.addWidget(self.root_splitter)

    def _build_recover_dashboard(self) -> QWidget:
        page = QWidget()
        vbox = QVBoxLayout(page)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(6)

        # 1. Clean Floating Neon Orbit Hero Banner
        self.hero_banner = HeroBannerWidget()
        vbox.addWidget(self.hero_banner)

        # 2. Select a Drive to Scan Header + Outlined Refresh Drives Button
        drive_hdr_row = QHBoxLayout()
        drive_hdr_row.setContentsMargins(2, 1, 2, 0)
        drive_hdr_row.setSpacing(8)

        self.drive_hdr_icon = QLabel()
        drive_hdr_row.addWidget(self.drive_hdr_icon)

        self.lbl_select_drive = QLabel("Select a Drive to Scan")
        drive_hdr_row.addWidget(self.lbl_select_drive)

        self.lbl_select_drive_sub = QLabel("— Choose a drive or connected peripheral to search for deleted files.")
        drive_hdr_row.addWidget(self.lbl_select_drive_sub)
        drive_hdr_row.addStretch(1)

        self.refresh_drives_btn = QPushButton("  Refresh Drives")
        self.refresh_drives_btn.setObjectName("OutlinedActionBtn")
        self.refresh_drives_btn.setFixedHeight(28)
        self.refresh_drives_btn.setMinimumWidth(128)
        self.refresh_drives_btn.setIcon(QIcon(create_vector_icon("refresh", 15, "#0570FA")))
        self.refresh_drives_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.refresh_drives_btn.clicked.connect(self.refresh_drives)
        drive_hdr_row.addWidget(self.refresh_drives_btn)
        vbox.addLayout(drive_hdr_row)

        # Drive Cards Horizontal Scrollable Strip
        self.drive_scroll = QScrollArea()
        self.drive_scroll.setWidgetResizable(True)
        self.drive_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.drive_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.drive_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.drive_scroll.setFixedHeight(84)
        self.drive_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")

        self.drive_cards_container = QWidget()
        self.drive_cards_container.setStyleSheet("background: transparent;")
        self.drive_cards_layout = QHBoxLayout(self.drive_cards_container)
        self.drive_cards_layout.setContentsMargins(0, 0, 0, 0)
        self.drive_cards_layout.setSpacing(10)
        self._drive_card_widgets: List[DriveCardWidget] = []
        self.drive_scroll.setWidget(self.drive_cards_container)
        vbox.addWidget(self.drive_scroll)

        # 3. Choose Scan Mode Header
        mode_hdr_row = QHBoxLayout()
        mode_hdr_row.setContentsMargins(2, 1, 2, 0)
        mode_hdr_row.setSpacing(8)
        self.mode_hdr_icon = QLabel()
        mode_hdr_row.addWidget(self.mode_hdr_icon)

        self.lbl_choose_mode = QLabel("Choose Scan Mode")
        mode_hdr_row.addWidget(self.lbl_choose_mode)

        self.lbl_choose_mode_sub = QLabel(
            "— Select a scan type (and optionally check specific file types below before scanning)."
        )
        mode_hdr_row.addWidget(self.lbl_choose_mode_sub)
        mode_hdr_row.addStretch(1)
        vbox.addLayout(mode_hdr_row)

        # Scan Mode Cards (Quick Scan & Deep Scan) + Start Scan Button
        modes_row = QHBoxLayout()
        modes_row.setSpacing(10)
        self._mode_cards: Dict[ScanMode, ScanModeCardWidget] = {}
        mode_specs = [
            (ScanMode.QUICK_SCAN, "Find recently deleted files.", "bolt"),
            (ScanMode.DEEP_SCAN, "Thorough scan for more recoverable files.", "search"),
        ]
        for mode_enum, desc, ic_kind in mode_specs:
            card = ScanModeCardWidget(mode_enum, desc, ic_kind, selected=(mode_enum == self._selected_mode))
            card.clicked.connect(self.on_scan_mode_selected)
            modes_row.addWidget(card, stretch=1)
            self._mode_cards[mode_enum] = card

        self.start_scan_btn = QPushButton("▶   Start Scan")
        self.start_scan_btn.setObjectName("PrimaryStartScanBtn")
        self.start_scan_btn.setFixedHeight(60)
        self.start_scan_btn.setMinimumWidth(210)
        self.start_scan_btn.setMaximumWidth(260)
        self.start_scan_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.start_scan_btn.clicked.connect(self.start_scan)
        modes_row.addWidget(self.start_scan_btn)
        vbox.addLayout(modes_row)

        # 4. Horizontal File-Type Selection Strip Directly Below Scan Buttons
        cat_strip_row = QHBoxLayout()
        cat_strip_row.setContentsMargins(0, 2, 0, 2)
        cat_strip_row.setSpacing(6)

        self._category_rows: Dict[str, CategoryChipWidget] = {}
        for cat_name in [
            "All Files",
            "Images",
            "Videos",
            "Documents",
            "Audio",
            "Archives",
            "Other Files",
        ]:
            chip = CategoryChipWidget(cat_name, active=(cat_name == "All Files"))
            chip.clicked.connect(self._on_category_clicked)
            chip.checked_changed.connect(self._on_category_checked)
            cat_strip_row.addWidget(chip, stretch=1)
            self._category_rows[cat_name] = chip

        vbox.addLayout(cat_strip_row)

        # 5. Scan Results Workspace Panel (Full-width Live Table + Clear Results + Bottom Output Save Bar)
        self.results_workspace = QFrame()
        self.results_workspace.setObjectName("ResultsWorkspace")
        self.results_workspace.setMinimumHeight(210)
        rw_vbox = QVBoxLayout(self.results_workspace)
        rw_vbox.setContentsMargins(12, 8, 12, 10)
        rw_vbox.setSpacing(6)

        toolbar_row = QHBoxLayout()
        toolbar_row.setSpacing(8)

        self.folder_hdr_icon = QLabel()
        toolbar_row.addWidget(self.folder_hdr_icon)

        self.lbl_scan_results = QLabel("Scan Results")
        toolbar_row.addWidget(self.lbl_scan_results)

        self.lbl_scan_results_sub = QLabel("— Found 0 recoverable files (0 B).")
        toolbar_row.addWidget(self.lbl_scan_results_sub)
        toolbar_row.addStretch(1)

        self.search_input = QLineEdit()
        self.search_input.setObjectName("SearchFilesEdit")
        self.search_input.setFixedHeight(30)
        self.search_input.setPlaceholderText("🔍  Search files...")
        self.search_input.setMinimumWidth(175)
        self.search_input.setMaximumWidth(240)
        self.search_input.textChanged.connect(self.apply_filters)
        toolbar_row.addWidget(self.search_input)

        self.type_filter_combo = QComboBox()
        self.type_filter_combo.setObjectName("TypeFilterCombo")
        self.type_filter_combo.setFixedHeight(30)
        self.type_filter_combo.setMinimumWidth(115)
        self.type_filter_combo.setMaximumWidth(145)
        self.type_filter_combo.addItems(
            [
                "All Types",
                "JPG",
                "PNG",
                "GIF",
                "BMP",
                "TIFF",
                "WEBP",
                "HEIC",
                "PDF",
                "DOCX",
                "XLSX",
                "PPTX",
                "TXT",
                "MP4",
                "MOV",
                "AVI",
                "MKV",
                "MP3",
                "WAV",
                "FLAC",
                "ZIP",
                "7Z",
                "RAR",
                "GZ",
            ]
        )
        self.type_filter_combo.currentTextChanged.connect(self.apply_filters)
        toolbar_row.addWidget(self.type_filter_combo)

        self.clear_results_btn = QPushButton("Clear Results")
        self.clear_results_btn.setObjectName("OutlinedActionBtn")
        self.clear_results_btn.setFixedHeight(30)
        self.clear_results_btn.setMinimumWidth(106)
        self.clear_results_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.clear_results_btn.setToolTip("Clear current scan results and reset counts")
        self.clear_results_btn.clicked.connect(self.clear_scan_results)
        toolbar_row.addWidget(self.clear_results_btn)

        rw_vbox.addLayout(toolbar_row)

        self.results_table = QTableWidget(0, 7)
        self.results_table.setObjectName("ResultsTable")
        self.results_table.setHorizontalHeaderLabels(
            ["", "Name", "Original Path", "Size", "Type", "Date Modified", "Status"]
        )
        self.results_table.verticalHeader().setVisible(False)
        self.results_table.verticalHeader().setDefaultSectionSize(30)
        self.results_table.setShowGrid(False)
        self.results_table.setAlternatingRowColors(True)
        self.results_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.results_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.results_table.setEditTriggers(QAbstractItemView.EditTriggers.NoEditTriggers)
        self.results_table.setSortingEnabled(True)
        self.results_table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.results_table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)

        hdr_view = self.results_table.horizontalHeader()
        hdr_view.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        hdr_view.setMinimumSectionSize(55)
        hdr_view.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.results_table.setColumnWidth(0, 32)
        hdr_view.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        self.results_table.setColumnWidth(1, 205)
        hdr_view.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hdr_view.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        self.results_table.setColumnWidth(3, 90)
        hdr_view.setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)
        self.results_table.setColumnWidth(4, 72)
        hdr_view.setSectionResizeMode(5, QHeaderView.ResizeMode.Interactive)
        self.results_table.setColumnWidth(5, 142)
        hdr_view.setSectionResizeMode(6, QHeaderView.ResizeMode.Interactive)
        self.results_table.setColumnWidth(6, 105)

        self.results_table.itemChanged.connect(self._on_table_item_checked)
        rw_vbox.addWidget(self.results_table, stretch=1)

        self.output_dir_card = OutputSaveBarWidget(initial_dir=self._output_dir)
        self.output_dir_card.directory_changed.connect(self._on_output_dir_edited)
        self.output_dir_card.browse_requested.connect(self.browse_output_directory)
        self.output_dir_card.open_requested.connect(self._open_output_directory)
        self.output_dir_card.save_requested.connect(self.save_selected_files)
        rw_vbox.addWidget(self.output_dir_card)

        vbox.addWidget(self.results_workspace, stretch=1)
        return page

    # =========================================================================
    # THEME & NAVIGATION MANAGEMENT
    # =========================================================================

    def apply_theme(self, is_dark: bool) -> None:
        self._is_dark = is_dark
        self._palette = ThemeManager.get_palette(is_dark)
        self.db.set_setting("theme_dark_v2", is_dark)
        self.theme_switch.set_dark(is_dark)
        self.setStyleSheet(ThemeManager.build_stylesheet(self._palette))

        p = self._palette
        self.brand_logo_lbl.setPixmap(create_recoverx_wordmark_pixmap(42, is_dark=is_dark))
        self.brand_sub.setStyleSheet(
            f"font-size: 11px; font-weight: 600; color: {p.text_secondary}; background: transparent;"
        )
        self.theme_lbl.setStyleSheet(
            f"font-size: 12.5px; font-weight: 600; color: {p.text_primary}; background: transparent;"
        )
        self.safe_title_lbl.setStyleSheet(
            f"font-size: 12px; font-weight: 700; color: {p.text_primary}; background: transparent;"
        )
        self.safe_desc_lbl.setStyleSheet(
            f"font-size: 10.5px; color: {p.text_secondary}; background: transparent;"
        )

        for hdr_lbl in (self.lbl_select_drive, self.lbl_choose_mode, self.lbl_scan_results):
            hdr_lbl.setStyleSheet(
                f"font-size: 14.5px; font-weight: 700; color: {p.text_primary}; background: transparent;"
            )
        for sub_lbl in (self.lbl_select_drive_sub, self.lbl_choose_mode_sub, self.lbl_scan_results_sub):
            sub_lbl.setStyleSheet(
                f"font-size: 12px; color: {p.text_secondary}; background: transparent;"
            )

        sec_icon_color = "#E2E8F0" if is_dark else "#0F172A"
        self.drive_hdr_icon.setPixmap(create_vector_icon("drive_header", 22, sec_icon_color))
        self.mode_hdr_icon.setPixmap(create_vector_icon("gear_header", 22, sec_icon_color))
        self.folder_hdr_icon.setPixmap(create_vector_icon("folder_header", 22, sec_icon_color))

        self.hero_banner.apply_palette(p)
        self.output_dir_card.apply_palette(p)
        self.bottom_status.apply_palette(p)
        self.scan_view.apply_palette(p)
        self.reports_view.apply_palette(p)
        self.about_view.apply_palette(p)

        for name, btn in self.nav_buttons.items():
            btn.set_state(btn._active or (name == "Recover" and self.main_stack.currentIndex() == 0), p)
        for card in self._drive_card_widgets:
            card.set_selected(
                self._selected_device is not None and card.device.path == self._selected_device.path,
                p,
            )
        for mode, mcard in self._mode_cards.items():
            mcard.set_selected(mode == self._selected_mode, p)
        for cname, chip in self._category_rows.items():
            chip.set_active(cname == self._active_category, p)

    def switch_section(self, section_name: str) -> None:
        mapping = {
            "Recover": 0,
            "Scan": 1,
            "Reports": 2,
            "About": 3,
        }
        idx = mapping.get(section_name, 0)
        self.main_stack.setCurrentIndex(idx)
        for name, btn in self.nav_buttons.items():
            btn.set_state(name == section_name, self._palette)
        if section_name == "Scan":
            if self._all_entries:
                self.scan_view.set_entries(self._all_entries)
            else:
                self.scan_view.clear_live_entries()
        elif section_name == "Reports":
            self.reports_view.refresh_history()

    # =========================================================================
    # CLEAR RESULTS & OUTPUT DIRECTORY WORKFLOW
    # =========================================================================

    def clear_scan_results(self) -> None:
        if self._scan_worker is not None and self._scan_worker.isRunning():
            self.stop_active_scan()

        self._all_entries.clear()
        self._filtered_entries.clear()
        self._current_session = None
        self._selected_file_types.clear()
        self._active_category = "All Files"

        for cname, chip in self._category_rows.items():
            chip.set_checked(False, emit_signal=False)
            chip.set_active(cname == "All Files", self._palette)
            chip.set_count(0)

        self.results_table.setRowCount(0)
        self.scan_view.clear_live_entries()
        self.lbl_scan_results_sub.setText("— Found 0 recoverable files (0 B).")
        self.bottom_status.set_scanning_progress(0, 0, 0, 0.0, 0.0, active=False)
        self._refresh_save_bar_state()

    def _on_output_dir_edited(self, new_dir: str) -> None:
        cleaned = new_dir.strip()
        if cleaned:
            self._output_dir = cleaned
            self.db.set_setting("output_directory", cleaned)

    def browse_output_directory(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self,
            "Select Safe Output Directory for Recovered Files",
            self._output_dir if os.path.isdir(self._output_dir) else str(Path.home()),
        )
        if chosen:
            self._output_dir = chosen
            self.output_dir_card.set_path(chosen)
            self.db.set_setting("output_directory", chosen)

    def _open_output_directory(self) -> None:
        out_path = Path(self.output_dir_card.path() or self._output_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(out_path.resolve())))

    def _refresh_save_bar_state(self) -> None:
        checked_types = [
            cname for cname, chip in self._category_rows.items()
            if chip.is_checked() and cname != "All Files"
        ]
        if self._category_rows["All Files"].is_checked() and not checked_types:
            checked_types = ["All Files"]
        selected_items = [e for e in self._all_entries if e.selected]
        if not checked_types and selected_items:
            checked_types = sorted({e.category.value for e in selected_items})
        sel_bytes = sum(e.size_bytes for e in selected_items)
        self.output_dir_card.update_selection_state(
            selected_types_count=len(checked_types),
            selected_files_count=len(selected_items),
            selected_bytes=sel_bytes,
        )

    # =========================================================================
    # DRIVE & CONNECTED PERIPHERAL SELECTION
    # =========================================================================

    def refresh_drives(self) -> None:
        self._last_drive_signature = self.discovery.get_connected_drive_signature()
        self._devices = self.discovery.enumerate_all()

        while self.drive_cards_layout.count():
            item = self.drive_cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._drive_card_widgets.clear()

        if self._selected_device is not None:
            still_present = any(d.path == self._selected_device.path for d in self._devices)
            if not still_present:
                self._selected_device = None

        if self._selected_device is None and self._devices:
            self._selected_device = self._devices[0]

        for dev in self._devices:
            is_sel = self._selected_device is not None and dev.path == self._selected_device.path
            card = DriveCardWidget(dev, selected=is_sel)
            card.set_selected(is_sel, self._palette)
            card.clicked.connect(self.on_drive_selected)
            self.drive_cards_layout.addWidget(card)
            self._drive_card_widgets.append(card)

        self.drive_cards_layout.addStretch(1)

    def on_drive_selected(self, device: DeviceInfo) -> None:
        self._selected_device = device
        for card in self._drive_card_widgets:
            card.set_selected(card.device.path == device.path, self._palette)

    def on_scan_mode_selected(self, mode: ScanMode) -> None:
        self._selected_mode = mode
        for m, card in self._mode_cards.items():
            card.set_selected(m == mode, self._palette)

    # =========================================================================
    # SCAN EXECUTION WITH PRE-SCAN CATEGORY FILTERING & LIVE STREAMING
    # =========================================================================

    def start_scan(self) -> None:
        if self._scan_worker is not None and self._scan_worker.isRunning():
            QMessageBox.information(
                self,
                "Scan in Progress",
                "A scan is currently running. Click Stop to cancel it first.",
            )
            return

        if self._selected_device is None:
            QMessageBox.warning(
                self,
                "No Drive Selected",
                "Please select a drive or connected peripheral to scan.",
            )
            return

        confirm_phys = False
        if self._selected_device.device_type == DeviceType.PHYSICAL_DISK:
            ans = QMessageBox.question(
                self,
                "Physical Disk Read-Only Confirmation",
                f"You are about to scan raw physical disk:\n{self._selected_device.name} ({self._selected_device.path})\n\n"
                "RecoverX will access this device strictly in READ-ONLY mode. Proceed?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if ans != QMessageBox.StandardButton.Yes:
                return
            confirm_phys = True

        pre_selected_cats: Set[str] = {
            cname for cname, chip in self._category_rows.items()
            if chip.is_checked() and cname != "All Files"
        }
        if self._category_rows["All Files"].is_checked():
            pre_selected_cats.clear()

        self._all_entries.clear()
        self._filtered_entries.clear()
        self.results_table.setRowCount(0)
        self.scan_view.clear_live_entries()
        self._update_category_counts()
        self._refresh_save_bar_state()

        if len(pre_selected_cats) == 1:
            only_cat = next(iter(pre_selected_cats))
            self._active_category = only_cat
            for cname, chip in self._category_rows.items():
                chip.set_active(cname == only_cat, self._palette)
        else:
            self._active_category = "All Files"
            for cname, chip in self._category_rows.items():
                chip.set_active(cname == "All Files", self._palette)

        self.hero_banner.set_scanning_active(True)
        self.bottom_status.set_scanning_progress(0, 0, 0, 0.0, 0.0, active=True)

        self._scan_worker = ScanWorker(
            engine=self.engine,
            device=self._selected_device,
            scan_mode=self._selected_mode,
            confirm_physical_access=confirm_phys,
            target_categories=pre_selected_cats if pre_selected_cats else None,
        )
        self._scan_worker.progress_updated.connect(self._on_scan_progress)
        self._scan_worker.batch_discovered.connect(self._on_scan_batch_discovered)
        self._scan_worker.scan_completed.connect(self._on_scan_completed)
        self._scan_worker.scan_failed.connect(self._on_scan_failed)
        self._scan_worker.start()

    def stop_active_scan(self) -> None:
        if self._scan_worker is not None and self._scan_worker.isRunning():
            self._scan_worker.cancel()
            self.hero_banner.set_scanning_active(False)
            self.bottom_status.status_lbl.setText("Ready")

    def _on_scan_progress(
        self,
        cur: int,
        tot: int,
        msg: str,
        found_count: int,
        found_bytes: int,
        elapsed: float,
        est: float,
    ) -> None:
        pct = int(round((cur / float(max(1, tot))) * 100))
        self.bottom_status.set_scanning_progress(pct, found_count, found_bytes, elapsed, est, active=True)

    def _on_scan_batch_discovered(self, new_entries: List[RecoveredFileEntry]) -> None:
        self.results_table.setUpdatesEnabled(False)
        self.results_table.setSortingEnabled(False)
        self.results_table.blockSignals(True)
        appended = False
        for e in new_entries:
            if e.category.value in self._selected_file_types or "All Files" in self._selected_file_types:
                e.selected = True
            self._all_entries.append(e)
            if self._matches_current_filter(e):
                self._filtered_entries.append(e)
                row_idx = self.results_table.rowCount()
                self.results_table.insertRow(row_idx)
                self._set_table_row_cells(row_idx, e)
                appended = True
        if appended:
            self.results_table.scrollToBottom()
        self.results_table.blockSignals(False)
        self.results_table.setUpdatesEnabled(True)

        self.scan_view.append_live_entries(new_entries)

        total_b = sum(x.size_bytes for x in self._all_entries)
        self.lbl_scan_results_sub.setText(
            f"— Live discovery: {len(self._all_entries):,} recoverable files ({format_file_size(total_b)})."
        )
        self._update_category_counts()
        self._refresh_save_bar_state()

    def _on_scan_completed(self, session: ScanSessionRecord, entries: List[RecoveredFileEntry]) -> None:
        self.hero_banner.set_scanning_active(False)
        self._current_session = session
        if len(entries) != len(self._all_entries):
            self._all_entries = list(entries)
            for e in self._all_entries:
                if e.category.value in self._selected_file_types or "All Files" in self._selected_file_types:
                    e.selected = True
            self.apply_filters()
            self.scan_view.set_entries(self._all_entries)
        else:
            self.results_table.setSortingEnabled(True)

        total_b = sum(e.size_bytes for e in self._all_entries)
        self.lbl_scan_results_sub.setText(
            f"— Found {len(self._all_entries):,} recoverable files ({format_file_size(total_b)}). Check file types above to save."
        )
        self._update_category_counts()
        self._refresh_save_bar_state()
        self.reports_view.refresh_history()
        self.bottom_status.set_scanning_progress(
            100 if session.status == "Completed" else self.bottom_status.progress_bar.value(),
            len(self._all_entries),
            total_b,
            0.0,
            0.0,
            active=False,
        )

    def _on_scan_failed(self, error_msg: str) -> None:
        self.hero_banner.set_scanning_active(False)
        self.bottom_status.stop_btn.setEnabled(False)
        self.bottom_status.status_lbl.setText("Ready")
        self.reports_view.refresh_history()
        QMessageBox.critical(self, "Scan Error", error_msg)

    def _load_saved_session(self, session_id: str) -> None:
        sessions = [s for s in self.db.list_sessions() if s.session_id == session_id]
        if not sessions:
            return
        self._current_session = sessions[0]
        self._all_entries = self.db.load_session_findings(session_id)
        total_b = sum(e.size_bytes for e in self._all_entries)
        self.lbl_scan_results_sub.setText(
            f"— Found {len(self._all_entries):,} recoverable files ({format_file_size(total_b)})."
        )
        self._update_category_counts()
        self.apply_filters()
        self.scan_view.set_entries(self._all_entries)
        self.reports_view.refresh_history()
        self._refresh_save_bar_state()
        self.switch_section("Recover")

    # =========================================================================
    # HORIZONTAL FILE-TYPE SELECTION & FILTERING
    # =========================================================================

    def _update_category_counts(self) -> None:
        counts: Dict[str, int] = {k: 0 for k in self._category_rows}
        counts["All Files"] = len(self._all_entries)
        for e in self._all_entries:
            cat_key = e.category.value
            counts[cat_key] = counts.get(cat_key, 0) + 1
        for k, widget in self._category_rows.items():
            widget.set_count(counts.get(k, 0))

    def _on_category_clicked(self, category_label: str) -> None:
        self._active_category = category_label
        for cname, chip in self._category_rows.items():
            chip.set_active(cname == category_label, self._palette)
        self.apply_filters()

    def _on_category_checked(self, category_label: str, checked: bool) -> None:
        if category_label == "All Files":
            if checked:
                self._selected_file_types = {c for c in self._category_rows.keys()}
            else:
                self._selected_file_types.clear()
            for cname, chip in self._category_rows.items():
                chip.set_checked(checked, emit_signal=False)
            for e in self._all_entries:
                e.selected = checked
        else:
            if checked:
                self._selected_file_types.add(category_label)
            else:
                self._selected_file_types.discard(category_label)
                self._selected_file_types.discard("All Files")
                self._category_rows["All Files"].set_checked(False, emit_signal=False)

            for e in self._all_entries:
                if e.category.value == category_label:
                    e.selected = checked

        self._populate_results_views()
        self._refresh_save_bar_state()

    def _matches_current_filter(self, e: RecoveredFileEntry) -> bool:
        query = self.search_input.text().strip().lower()
        ext_filter = self.type_filter_combo.currentText()
        if self._active_category != "All Files" and e.category.value != self._active_category:
            return False
        if ext_filter != "All Types" and e.extension.upper() != ext_filter.upper():
            return False
        if query and query not in e.name.lower() and query not in e.original_path.lower():
            return False
        return True

    def apply_filters(self) -> None:
        self._filtered_entries = [e for e in self._all_entries if self._matches_current_filter(e)]
        self._populate_results_views()

    def _set_table_row_cells(self, row_idx: int, entry: RecoveredFileEntry) -> None:
        chk_item = QTableWidgetItem()
        chk_item.setFlags(
            Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        )
        chk_item.setCheckState(Qt.CheckState.Checked if entry.selected else Qt.CheckState.Unchecked)
        chk_item.setData(Qt.ItemDataRole.UserRole, entry.id)
        self.results_table.setItem(row_idx, 0, chk_item)

        ic_kind = icon_kind_for_entry(entry.extension, entry.category.value)
        ic = QIcon(create_vector_icon(ic_kind, 20))
        name_item = QTableWidgetItem(ic, entry.name)
        name_item.setData(Qt.ItemDataRole.UserRole, entry.id)
        self.results_table.setItem(row_idx, 1, name_item)

        path_item = QTableWidgetItem(entry.original_path)
        path_item.setToolTip(entry.original_path)
        self.results_table.setItem(row_idx, 2, path_item)

        size_item = QTableWidgetItem(entry.size_Formatted)
        size_item.setData(Qt.ItemDataRole.UserRole, entry.size_bytes)
        self.results_table.setItem(row_idx, 3, size_item)

        type_item = QTableWidgetItem(entry.extension)
        self.results_table.setItem(row_idx, 4, type_item)

        date_item = QTableWidgetItem(entry.modified_formatted)
        self.results_table.setItem(row_idx, 5, date_item)

        status_item = QTableWidgetItem(f"●  {entry.status.value}")
        if entry.status == IntegrityStatus.GOOD:
            status_item.setForeground(QColor(self._palette.status_good))
        elif entry.status == IntegrityStatus.PARTIAL:
            status_item.setForeground(QColor(self._palette.status_partial))
        else:
            status_item.setForeground(QColor(self._palette.status_corrupted))
        status_item.setToolTip(entry.status_detail)
        self.results_table.setItem(row_idx, 6, status_item)

    def _populate_results_views(self) -> None:
        self.results_table.setUpdatesEnabled(False)
        self.results_table.setSortingEnabled(False)
        self.results_table.blockSignals(True)
        self.results_table.setRowCount(len(self._filtered_entries))

        for row_idx, entry in enumerate(self._filtered_entries):
            self._set_table_row_cells(row_idx, entry)

        self.results_table.blockSignals(False)
        self.results_table.setSortingEnabled(True)
        self.results_table.setUpdatesEnabled(True)

    def _on_table_item_checked(self, item: QTableWidgetItem) -> None:
        if item.column() != 0:
            return
        entry_id = item.data(Qt.ItemDataRole.UserRole)
        checked = item.checkState() == Qt.CheckState.Checked
        target_cat: Optional[str] = None
        for e in self._all_entries:
            if e.id == entry_id:
                e.selected = checked
                target_cat = e.category.value
                break

        if target_cat and target_cat in self._category_rows:
            any_in_cat = any(x.selected for x in self._all_entries if x.category.value == target_cat)
            self._category_rows[target_cat].set_checked(any_in_cat, emit_signal=False)
            if any_in_cat:
                self._selected_file_types.add(target_cat)
            else:
                self._selected_file_types.discard(target_cat)
                self._selected_file_types.discard("All Files")
                self._category_rows["All Files"].set_checked(False, emit_signal=False)

        self._refresh_save_bar_state()

    # =========================================================================
    # SAVE SELECTED FILE TYPES TO OUTPUT DIRECTORY SUBFOLDERS
    # =========================================================================

    def save_selected_files(self) -> None:
        if self._selected_device is None:
            return

        selected_entries = [e for e in self._all_entries if e.selected]
        if not selected_entries:
            QMessageBox.information(
                self,
                "Select File Types to Save",
                "Please check one or more file types (such as Images, Videos, or Documents) in the file-type bar above before clicking Save.",
            )
            return

        dest_dir = self.output_dir_card.path() or self._output_dir
        if not dest_dir:
            self.browse_output_directory()
            dest_dir = self.output_dir_card.path()
            if not dest_dir:
                return

        allow_same = False
        if is_same_storage_device(self._selected_device, dest_dir):
            warn = QMessageBox.warning(
                self,
                "Warning: Output Directory Is on Source Volume",
                f"The selected Output Directory:\n{dest_dir}\n\n"
                f"resides on the same volume as source '{self._selected_device.name}'. "
                "Writing recovered files back to the source volume can overwrite unallocated clusters.\n\n"
                "Do you want to choose a different Output Directory now?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if warn == QMessageBox.StandardButton.Yes:
                self.browse_output_directory()
                dest_dir = self.output_dir_card.path()
                if not dest_dir or is_same_storage_device(self._selected_device, dest_dir):
                    return
            else:
                allow_same = True

        session_id = self._current_session.session_id if self._current_session else "manual-session"
        self._recovery_worker = RecoveryWorker(
            engine=self.engine,
            device=self._selected_device,
            entries=selected_entries,
            destination_dir=dest_dir,
            session_id=session_id,
            preserve_structure=True,
            allow_same_device=allow_same,
            confirm_physical_access=True,
        )
        self._recovery_worker.progress_updated.connect(
            lambda cur, tot, msg: self.bottom_status.status_lbl.setText(f"Saving [{cur}/{tot}]...")
        )
        self._recovery_worker.recovery_completed.connect(self._on_recovery_completed)
        self._recovery_worker.recovery_failed.connect(
            lambda err: QMessageBox.critical(self, "Save Failed", err)
        )
        self._recovery_worker.start()

    def _on_recovery_completed(self, log_rec, outcomes: list) -> None:
        self.reports_view.refresh_history()
        self.bottom_status.status_lbl.setText("Ready")
        subfolders = sorted({Path(o.output_path).parent.name for o in outcomes if o.output_path})
        folders_str = ", ".join(subfolders) if subfolders else "Category Subfolders"
        QMessageBox.information(
            self,
            "Files Saved Successfully",
            f"Saved {log_rec.succeeded + log_rec.partial} recovered files into:\n"
            f"{log_rec.destination_dir}\n\n"
            f"Organized under subfolders: {folders_str}\n"
            f"• Intact: {log_rec.succeeded}\n"
            f"• Partial: {log_rec.partial}\n"
            f"• Skipped / Failed: {log_rec.skipped + log_rec.failed}",
        )
