"""Theme-Aware Secondary Views:
1. ScanDetailView ('Scan' tab): Live Found Data table + Visual Preview (Images, Videos, PDFs — No text preview).
2. ReportsView ('Reports' tab): Saved Data Records, Failed/Warnings/Errors, Clear Reports button, TXT-only Export (No Found Data, No Text Log).
3. AboutView ('About' tab): Minimal 'About RecoverX', 'Developed by Muhammad Ishaq.' (clickable popup), and core info only.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Dict, List, Optional

from PySide6.QtCore import QEvent, QPoint, QRect, QRectF, Qt, QUrl, Signal
from PySide6.QtGui import (
    QColor,
    QCursor,
    QDesktopServices,
    QIcon,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from filesystems.base import IntegrityStatus, RecoveredFileEntry, format_file_size
from preview.handler import PreviewHandler
from reports.exporter import ReportExporter
from storage.database import RecoverXDatabase, ScanSessionRecord
from .icons import ASSETS_DIR, create_vector_icon, icon_kind_for_entry
from .theme import LIGHT_PALETTE, ThemePalette


class AuthorProfilePopupModal(QDialog):
    """
    Popout Profile Modal matching `RecoverX About Profile Popup.png`:
    - Opens when the user clicks 'Muhammad Ishaq.' in the About section.
    - Displays `assets/author_profile_popup.png` with smooth high-DPI scaling and interactive
      Close ('×'), LinkedIn, GitHub, and Email buttons.
    - Closes automatically whenever the user clicks the mouse anywhere outside the popup card!
    """

    LINKEDIN_URL = "https://www.linkedin.com/in/muhammad-ishaq-4b3010390/"
    GITHUB_URL = "https://github.com/ishaqsec"
    EMAIL_URL = "https://mail.google.com/mail/?view=cm&fs=1&to=reachout2ishaq@gmail.com"

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("AuthorProfilePopupModal")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setModal(True)
        self.setMouseTracking(True)

        self._popup_pix = QPixmap(str(ASSETS_DIR / "author_profile_popup.png"))
        self._hover_zone: Optional[str] = None

        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

        self._sync_to_parent_geometry()

    def _sync_to_parent_geometry(self) -> None:
        parent_win = self.parentWidget().window() if self.parentWidget() else None
        if parent_win is not None:
            top_left = parent_win.mapToGlobal(QPoint(0, 0))
            self.setGeometry(top_left.x(), top_left.y(), parent_win.width(), parent_win.height())
        else:
            self.resize(960, 720)

    def card_rect(self) -> QRect:
        w = self.width()
        h = self.height()
        orig_w = max(1, self._popup_pix.width() if not self._popup_pix.isNull() else 871)
        orig_h = max(1, self._popup_pix.height() if not self._popup_pix.isNull() else 1095)
        aspect = orig_w / float(orig_h)

        target_h = min(640, max(440, int(h * 0.88)))
        target_w = int(round(target_h * aspect))
        if target_w > int(w * 0.90):
            target_w = int(w * 0.90)
            target_h = int(round(target_w / aspect))

        cx = (w - target_w) // 2
        cy = (h - target_h) // 2
        return QRect(cx, cy, target_w, target_h)

    def _zone_rects(self, crect: QRect) -> dict[str, QRectF]:
        x0 = float(crect.x())
        y0 = float(crect.y())
        cw = float(crect.width())
        ch = float(crect.height())
        return {
            "close": QRectF(x0 + cw * 0.870, y0 + ch * 0.018, cw * 0.105, ch * 0.084),
            "linkedin": QRectF(x0 + cw * 0.038, y0 + ch * 0.806, cw * 0.304, ch * 0.086),
            "github": QRectF(x0 + cw * 0.358, y0 + ch * 0.806, cw * 0.294, ch * 0.086),
            "email": QRectF(x0 + cw * 0.670, y0 + ch * 0.806, cw * 0.292, ch * 0.086),
        }

    def _hit_test_zone(self, pos: QPoint) -> Optional[str]:
        crect = self.card_rect()
        pt = QRectF(pos.x(), pos.y(), 1, 1).topLeft()
        for name, zrect in self._zone_rects(crect).items():
            if zrect.contains(pt):
                return name
        return None

    def eventFilter(self, watched, event) -> bool:
        if event.type() == QEvent.Type.MouseButtonPress and self.isVisible():
            try:
                global_pt = event.globalPosition().toPoint()
            except AttributeError:
                global_pt = event.globalPos()
            local_pt = self.mapFromGlobal(global_pt)
            if not self.card_rect().contains(local_pt):
                self.close()
                return True
        return super().eventFilter(watched, event)

    def mouseMoveEvent(self, event) -> None:
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        zone = self._hit_test_zone(pos)
        if zone != self._hover_zone:
            self._hover_zone = zone
            if zone is not None:
                self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            else:
                self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
            self.update()
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
            crect = self.card_rect()
            if not crect.contains(pos):
                self.close()
                return

            zone = self._hit_test_zone(pos)
            if zone == "close":
                self.close()
                return
            elif zone == "linkedin":
                QDesktopServices.openUrl(QUrl(self.LINKEDIN_URL))
                return
            elif zone == "github":
                QDesktopServices.openUrl(QUrl(self.GITHUB_URL))
                return
            elif zone == "email":
                QDesktopServices.openUrl(QUrl(self.EMAIL_URL))
                return
        super().mousePressEvent(event)

    def closeEvent(self, event) -> None:
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        super().closeEvent(event)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        p.fillRect(self.rect(), QColor(15, 23, 42, 115))

        crect = self.card_rect()
        if not self._popup_pix.isNull():
            scaled = self._popup_pix.scaled(
                crect.width(),
                crect.height(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            p.drawPixmap(crect.x(), crect.y(), scaled)
        else:
            p.setBrush(QColor("#F8FBFF"))
            p.setPen(QPen(QColor("#0570FA"), 2.0))
            p.drawRoundedRect(QRectF(crect), 18, 18)

        if self._hover_zone:
            zrect = self._zone_rects(crect).get(self._hover_zone)
            if zrect is not None:
                p.setPen(QPen(QColor(5, 112, 250, 180), 1.8))
                p.setBrush(QColor(5, 112, 250, 18))
                rad = zrect.height() / 2.0 if self._hover_zone == "close" else 10.0
                p.drawRoundedRect(zrect, rad, rad)

        p.end()


class ClickableAuthorLinkButton(QPushButton):
    """Clickable 'Muhammad Ishaq.' button styled as an interactive accent link."""

    def __init__(self, text: str = "Muhammad Ishaq.", parent: Optional[QWidget] = None):
        super().__init__(text, parent)
        self.setFlat(True)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setToolTip("Click to view Muhammad Ishaq's profile")


class ScanDetailView(QFrame):
    """
    Live Found Data & Visual Preview Workspace ('Scan' nav tab):
    - Shows discovered files live in real time during a scan (never pre-loads old records on startup).
    - Allows clicking any discovered file to view its visual preview (Images, Videos, PDFs).
    - Includes a search filter and 'Clear Results' button.
    """

    resume_session_requested = Signal(str)
    clear_requested = Signal()

    def __init__(self, db: RecoverXDatabase, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.db = db
        self._palette = LIGHT_PALETTE
        self._entries: List[RecoveredFileEntry] = []
        self._filtered_entries: List[RecoveredFileEntry] = []
        self._entry_by_id: Dict[str, RecoveredFileEntry] = {}
        self.setObjectName("SectionPanel")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        hdr_row = QHBoxLayout()
        hdr_row.setSpacing(10)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        self.hdr = QLabel("Live Scan Discovery & Preview")
        title_col.addWidget(self.hdr)
        self.sub = QLabel(
            "Watch found data appear live during scanning and click any discovered file below to preview it."
        )
        self.sub.setWordWrap(True)
        title_col.addWidget(self.sub)
        hdr_row.addLayout(title_col, stretch=1)

        self.search_edit = QLineEdit()
        self.search_edit.setObjectName("SearchFilesEdit")
        self.search_edit.setFixedHeight(30)
        self.search_edit.setMinimumWidth(190)
        self.search_edit.setMaximumWidth(250)
        self.search_edit.setPlaceholderText("🔍  Filter found files...")
        self.search_edit.textChanged.connect(self._apply_live_filter)
        hdr_row.addWidget(self.search_edit)

        self.clear_btn = QPushButton("Clear Results")
        self.clear_btn.setObjectName("OutlinedActionBtn")
        self.clear_btn.setFixedHeight(30)
        self.clear_btn.setMinimumWidth(106)
        self.clear_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.clear_btn.clicked.connect(self.clear_requested.emit)
        hdr_row.addWidget(self.clear_btn)

        layout.addLayout(hdr_row)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setChildrenCollapsible(False)

        left_frame = QWidget()
        left_vbox = QVBoxLayout(left_frame)
        left_vbox.setContentsMargins(0, 0, 4, 0)
        left_vbox.setSpacing(6)

        self.live_count_lbl = QLabel("Found Data: 0 recoverable files (0 B)")
        left_vbox.addWidget(self.live_count_lbl)

        self.live_found_table = QTableWidget(0, 6)
        self.live_found_table.setObjectName("ResultsTable")
        self.live_found_table.setHorizontalHeaderLabels(
            ["Name", "Category", "Size", "Type", "Status", "Original Path"]
        )
        self.live_found_table.verticalHeader().setVisible(False)
        self.live_found_table.verticalHeader().setDefaultSectionSize(30)
        self.live_found_table.setShowGrid(False)
        self.live_found_table.setAlternatingRowColors(True)
        self.live_found_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.live_found_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.live_found_table.setEditTriggers(QAbstractItemView.EditTriggers.NoEditTriggers)
        self.live_found_table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.live_found_table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)

        th = self.live_found_table.horizontalHeader()
        th.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        th.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.live_found_table.setColumnWidth(0, 185)
        th.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        self.live_found_table.setColumnWidth(1, 95)
        th.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        self.live_found_table.setColumnWidth(2, 82)
        th.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        self.live_found_table.setColumnWidth(3, 65)
        th.setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)
        self.live_found_table.setColumnWidth(4, 90)
        th.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)

        self.live_found_table.itemSelectionChanged.connect(self._on_file_selected_for_preview)
        left_vbox.addWidget(self.live_found_table, stretch=1)
        self.splitter.addWidget(left_frame)

        self.preview_card = QFrame()
        self.preview_card.setObjectName("SafeReadOnlyCard")
        self.preview_card.setMinimumWidth(310)
        p_vbox = QVBoxLayout(self.preview_card)
        p_vbox.setContentsMargins(14, 12, 14, 12)
        p_vbox.setSpacing(10)

        self.preview_hdr_lbl = QLabel("File Preview")
        p_vbox.addWidget(self.preview_hdr_lbl)

        self.preview_meta_lbl = QLabel("Select any found file on the left to view its preview.")
        self.preview_meta_lbl.setWordWrap(True)
        p_vbox.addWidget(self.preview_meta_lbl)

        self.preview_image_lbl = QLabel("No file selected")
        self.preview_image_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_image_lbl.setMinimumHeight(240)
        p_vbox.addWidget(self.preview_image_lbl, stretch=1)

        self.splitter.addWidget(self.preview_card)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 2)
        self.splitter.setSizes([620, 380])
        layout.addWidget(self.splitter, stretch=1)

        self.apply_palette(LIGHT_PALETTE)

    def clear_live_entries(self) -> None:
        self._entries.clear()
        self._filtered_entries.clear()
        self._entry_by_id.clear()
        self.live_found_table.setRowCount(0)
        self.live_count_lbl.setText("Found Data: 0 recoverable files (0 B)")
        self.preview_hdr_lbl.setText("File Preview")
        self.preview_meta_lbl.setText("Select any found file on the left to view its preview.")
        self.preview_image_lbl.setPixmap(QPixmap())
        self.preview_image_lbl.setText("No file selected")

    def set_entries(self, entries: List[RecoveredFileEntry]) -> None:
        self._entries = list(entries)
        self._entry_by_id = {e.id: e for e in self._entries}
        self._apply_live_filter()
        if self.live_found_table.rowCount() > 0 and self.live_found_table.currentRow() < 0:
            self.live_found_table.selectRow(0)

    def append_live_entries(self, new_entries: List[RecoveredFileEntry]) -> None:
        self.live_found_table.setUpdatesEnabled(False)
        self.live_found_table.blockSignals(True)
        q = self.search_edit.text().strip().lower()
        for e in new_entries:
            self._entries.append(e)
            self._entry_by_id[e.id] = e
            if not q or q in e.name.lower() or q in e.original_path.lower() or q in e.category.value.lower():
                self._filtered_entries.append(e)
                row_idx = self.live_found_table.rowCount()
                self.live_found_table.insertRow(row_idx)
                self._set_row_cells(row_idx, e)
        self.live_found_table.scrollToBottom()
        self.live_found_table.blockSignals(False)
        self.live_found_table.setUpdatesEnabled(True)

        total_b = sum(x.size_bytes for x in self._entries)
        self.live_count_lbl.setText(
            f"Found Data: {len(self._entries):,} recoverable files ({format_file_size(total_b)})"
        )
        if self.live_found_table.rowCount() > 0 and self.live_found_table.currentRow() < 0:
            self.live_found_table.selectRow(0)

    def _apply_live_filter(self) -> None:
        q = self.search_edit.text().strip().lower()
        if not q:
            self._filtered_entries = list(self._entries)
        else:
            self._filtered_entries = [
                e for e in self._entries
                if q in e.name.lower() or q in e.original_path.lower() or q in e.category.value.lower()
            ]
        self.live_found_table.setUpdatesEnabled(False)
        self.live_found_table.blockSignals(True)
        self.live_found_table.setRowCount(len(self._filtered_entries))
        for r, e in enumerate(self._filtered_entries):
            self._set_row_cells(r, e)
        self.live_found_table.blockSignals(False)
        self.live_found_table.setUpdatesEnabled(True)

        total_b = sum(x.size_bytes for x in self._entries)
        self.live_count_lbl.setText(
            f"Found Data: {len(self._entries):,} recoverable files ({format_file_size(total_b)})"
        )

    def _set_row_cells(self, row_idx: int, entry: RecoveredFileEntry) -> None:
        ic_kind = icon_kind_for_entry(entry.extension, entry.category.value)
        ic = QIcon(create_vector_icon(ic_kind, 18))
        name_item = QTableWidgetItem(ic, entry.name)
        name_item.setData(Qt.ItemDataRole.UserRole, entry.id)
        self.live_found_table.setItem(row_idx, 0, name_item)

        self.live_found_table.setItem(row_idx, 1, QTableWidgetItem(entry.category.value))
        self.live_found_table.setItem(row_idx, 2, QTableWidgetItem(entry.size_Formatted))
        self.live_found_table.setItem(row_idx, 3, QTableWidgetItem(entry.extension))

        st_item = QTableWidgetItem(f"● {entry.status.value}")
        if entry.status == IntegrityStatus.GOOD:
            st_item.setForeground(QColor(self._palette.status_good))
        elif entry.status == IntegrityStatus.PARTIAL:
            st_item.setForeground(QColor(self._palette.status_partial))
        else:
            st_item.setForeground(QColor(self._palette.status_corrupted))
        self.live_found_table.setItem(row_idx, 4, st_item)

        path_item = QTableWidgetItem(entry.original_path)
        path_item.setToolTip(entry.original_path)
        self.live_found_table.setItem(row_idx, 5, path_item)

    def _on_file_selected_for_preview(self) -> None:
        row = self.live_found_table.currentRow()
        if row < 0 or row >= self.live_found_table.rowCount():
            return
        item0 = self.live_found_table.item(row, 0)
        if item0 is None:
            return
        eid = item0.data(Qt.ItemDataRole.UserRole)
        entry = self._entry_by_id.get(str(eid))
        if entry is None:
            return
        self.preview_entry(entry)

    def preview_entry(self, entry: RecoveredFileEntry) -> None:
        pdata = PreviewHandler.generate_preview(entry)
        self.preview_hdr_lbl.setText(f"Preview: {pdata.title}")
        self.preview_meta_lbl.setText(
            f"{pdata.subtitle}   |   Status: {entry.status.value}\nPath: {entry.original_path}"
        )

        if pdata.image_png_bytes:
            pix = QPixmap()
            pix.loadFromData(pdata.image_png_bytes)
            if not pix.isNull():
                scaled = pix.scaled(
                    max(260, self.preview_image_lbl.width() - 16),
                    max(220, self.preview_image_lbl.height() - 16),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self.preview_image_lbl.setText("")
                self.preview_image_lbl.setPixmap(scaled)
            else:
                self.preview_image_lbl.setPixmap(QPixmap())
                self.preview_image_lbl.setText("Visual preview unavailable")
        else:
            self.preview_image_lbl.setPixmap(QPixmap())
            ic_kind = icon_kind_for_entry(entry.extension, entry.category.value)
            self.preview_image_lbl.setPixmap(create_vector_icon(ic_kind, 72))

    def refresh_sessions(self) -> None:
        """Keep Scan view clean if no active session entries exist (never auto-load old sessions)."""
        if not self._entries:
            self.clear_live_entries()

    def apply_palette(self, palette: ThemePalette) -> None:
        self._palette = palette
        accent = "#38BDF8" if palette.is_dark else "#0570FA"
        self.hdr.setStyleSheet(
            f"font-size: 19px; font-weight: 800; color: {palette.text_primary}; background: transparent;"
        )
        self.sub.setStyleSheet(
            f"font-size: 12.5px; color: {palette.text_secondary}; background: transparent;"
        )
        self.live_count_lbl.setStyleSheet(
            f"font-size: 12.5px; font-weight: 700; color: {accent}; background: transparent;"
        )
        self.preview_hdr_lbl.setStyleSheet(
            f"font-size: 15px; font-weight: 800; color: {palette.text_primary}; background: transparent;"
        )
        self.preview_meta_lbl.setStyleSheet(
            f"font-size: 11.5px; color: {palette.text_secondary}; background: transparent;"
        )
        img_bg = "#0C1320" if palette.is_dark else "#F1F6FC"
        self.preview_image_lbl.setStyleSheet(
            f"background-color: {img_bg}; border: 1px solid {palette.card_border}; "
            f"border-radius: 8px; color: {palette.text_muted}; font-size: 12px;"
        )


class ReportsView(QFrame):
    """
    Saved Data Records & Warnings/Errors View ('Reports' nav tab):
    - Shows ONLY Saved Data Records and Failed Recoveries / Warnings / Errors
      (does NOT show Found Data, as Found Data is already shown in the Scan section).
    - Text log box removed.
    - Includes 'Clear Reports' button and 'Export TXT Report' button.
    """

    def __init__(
        self,
        db: RecoverXDatabase,
        get_current_context: Callable[[], tuple[Optional[ScanSessionRecord], List[RecoveredFileEntry]]],
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.db = db
        self.get_current_context = get_current_context
        self._palette = LIGHT_PALETTE
        self.setObjectName("SectionPanel")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        hdr_row = QHBoxLayout()
        hdr_row.setSpacing(10)
        self.hdr = QLabel("Recovery Reports — Saved Data Records & Warnings")
        hdr_row.addWidget(self.hdr)
        hdr_row.addStretch(1)

        self.btn_refresh = QPushButton("Refresh Report")
        self.btn_refresh.setObjectName("OutlinedActionBtn")
        self.btn_refresh.setFixedHeight(32)
        self.btn_refresh.setMinimumWidth(118)
        self.btn_refresh.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_refresh.clicked.connect(self.refresh_history)
        hdr_row.addWidget(self.btn_refresh)

        self.btn_clear_reports = QPushButton("Clear Reports")
        self.btn_clear_reports.setObjectName("OutlinedActionBtn")
        self.btn_clear_reports.setFixedHeight(32)
        self.btn_clear_reports.setMinimumWidth(118)
        self.btn_clear_reports.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_clear_reports.clicked.connect(self.clear_all_reports)
        hdr_row.addWidget(self.btn_clear_reports)

        self.btn_txt = QPushButton("Export TXT Report")
        self.btn_txt.setObjectName("PrimaryActionBtn")
        self.btn_txt.setFixedHeight(32)
        self.btn_txt.setMinimumWidth(148)
        self.btn_txt.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_txt.clicked.connect(self._export_txt_report)
        hdr_row.addWidget(self.btn_txt)
        layout.addLayout(hdr_row)

        self.sub = QLabel(
            "Review your saved recovery records, destination subfolder locations, and any failed recoveries, warnings, or errors."
        )
        self.sub.setWordWrap(True)
        layout.addWidget(self.sub)

        kpi_row = QHBoxLayout()
        kpi_row.setSpacing(10)

        self.kpi_saved_card = QFrame()
        self.kpi_saved_card.setObjectName("SafeReadOnlyCard")
        ks_l = QVBoxLayout(self.kpi_saved_card)
        ks_l.setContentsMargins(14, 8, 14, 8)
        self.lbl_kpi_saved = QLabel("Saved Data: 0 files saved (0 intact, 0 partial)")
        ks_l.addWidget(self.lbl_kpi_saved)
        kpi_row.addWidget(self.kpi_saved_card, stretch=1)

        self.kpi_failed_card = QFrame()
        self.kpi_failed_card.setObjectName("SafeReadOnlyCard")
        kf_l = QVBoxLayout(self.kpi_failed_card)
        kf_l.setContentsMargins(14, 8, 14, 8)
        self.lbl_kpi_failed = QLabel("Failed / Skipped: 0 files")
        kf_l.addWidget(self.lbl_kpi_failed)
        kpi_row.addWidget(self.kpi_failed_card, stretch=1)

        self.kpi_warn_card = QFrame()
        self.kpi_warn_card.setObjectName("SafeReadOnlyCard")
        kw_l = QVBoxLayout(self.kpi_warn_card)
        kw_l.setContentsMargins(14, 8, 14, 8)
        self.lbl_kpi_warn = QLabel("Warnings & Errors: 0 alerts")
        kw_l.addWidget(self.lbl_kpi_warn)
        kpi_row.addWidget(self.kpi_warn_card, stretch=1)

        layout.addLayout(kpi_row)

        # Saved Data & Warnings/Errors Table (Full height — no text log box below)
        self.records_table = QTableWidget(0, 6)
        self.records_table.setObjectName("ResultsTable")
        self.records_table.setHorizontalHeaderLabels(
            [
                "Record Type",
                "File / Batch",
                "Category / Subfolder",
                "Size",
                "Status / Outcome",
                "Saved Path, Warning, or Error Details",
            ]
        )
        self.records_table.verticalHeader().setVisible(False)
        self.records_table.verticalHeader().setDefaultSectionSize(30)
        self.records_table.setAlternatingRowColors(True)
        self.records_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.records_table.setEditTriggers(QAbstractItemView.EditTriggers.NoEditTriggers)
        self.records_table.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.records_table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)

        rth = self.records_table.horizontalHeader()
        rth.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        rth.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self.records_table.setColumnWidth(0, 130)
        rth.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        self.records_table.setColumnWidth(1, 195)
        rth.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        self.records_table.setColumnWidth(2, 125)
        rth.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        self.records_table.setColumnWidth(3, 90)
        rth.setSectionResizeMode(4, QHeaderView.ResizeMode.Interactive)
        self.records_table.setColumnWidth(4, 125)
        rth.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)

        layout.addWidget(self.records_table, stretch=1)

        self.apply_palette(LIGHT_PALETTE)
        self.refresh_history()

    def clear_all_reports(self) -> None:
        """Clear all saved recovery logs and warnings/errors from the database and table."""
        self.db.clear_reports()
        session, _ = self.get_current_context()
        if session is not None:
            session.warnings.clear()
            session.errors.clear()
        self.refresh_history()

    def refresh_history(self) -> None:
        session, _entries = self.get_current_context()
        all_sessions = self.db.list_sessions()
        logs = self.db.list_recovery_logs()

        total_saved = sum(l.succeeded + l.partial for l in logs)
        total_intact = sum(l.succeeded for l in logs)
        total_partial = sum(l.partial for l in logs)
        total_failed = sum(l.failed + l.skipped for l in logs)

        rows_data: List[tuple[str, str, str, str, str, str, str]] = []
        warn_count = 0

        # 1. Saved Data & Failed Recovery Outcomes
        for l in logs:
            for w in l.warnings:
                warn_count += 1
                rows_data.append(
                    (
                        "Warning",
                        l.recovery_id,
                        "Recovery Batch",
                        "—",
                        "Warning",
                        w,
                        "partial",
                    )
                )
            for item in l.file_outcomes:
                outcome = item.get("outcome", "Succeeded")
                fname = item.get("file_name", "")
                b_written = int(item.get("bytes_written", 0))
                out_path = item.get("output_path", "") or l.destination_dir
                msg = item.get("message", "")
                if outcome in ("Succeeded", "Partial"):
                    rec_type = "Saved Data"
                    if outcome == "Partial":
                        warn_count += 1
                else:
                    rec_type = "Failed / Skipped"
                    warn_count += 1
                color_kind = "good" if outcome == "Succeeded" else ("partial" if outcome == "Partial" else "bad")
                rows_data.append(
                    (
                        rec_type,
                        fname,
                        Path(out_path).parent.name if out_path else "Saved",
                        format_file_size(b_written),
                        outcome,
                        f"{out_path} ({msg})" if msg else out_path,
                        color_kind,
                    )
                )

        # 2. Scan Warnings & Errors (without listing Found Data rows)
        for s in all_sessions[:5]:
            for w in s.warnings:
                warn_count += 1
                rows_data.append(
                    (
                        "Scan Warning",
                        s.device_name,
                        s.scan_mode,
                        "—",
                        "Warning",
                        w,
                        "partial",
                    )
                )
            for err in s.errors:
                warn_count += 1
                rows_data.append(
                    (
                        "Scan Error",
                        s.device_name,
                        s.scan_mode,
                        "—",
                        "Error",
                        err,
                        "bad",
                    )
                )

        self.lbl_kpi_saved.setText(
            f"Saved Data: {total_saved:,} files saved ({total_intact:,} intact, {total_partial:,} partial)"
        )
        self.lbl_kpi_failed.setText(f"Failed / Skipped: {total_failed:,} files")
        self.lbl_kpi_warn.setText(f"Warnings & Errors: {warn_count:,} alerts")

        self.records_table.setUpdatesEnabled(False)
        self.records_table.setRowCount(len(rows_data))
        for r, (rtype, fname, cat, sz, st_txt, path_txt, c_kind) in enumerate(rows_data):
            self.records_table.setItem(r, 0, QTableWidgetItem(rtype))
            self.records_table.setItem(r, 1, QTableWidgetItem(fname))
            self.records_table.setItem(r, 2, QTableWidgetItem(cat))
            self.records_table.setItem(r, 3, QTableWidgetItem(sz))

            st_item = QTableWidgetItem(f"● {st_txt}")
            if c_kind == "good":
                st_item.setForeground(QColor(self._palette.status_good))
            elif c_kind == "partial":
                st_item.setForeground(QColor(self._palette.status_partial))
            else:
                st_item.setForeground(QColor(self._palette.status_corrupted))
            self.records_table.setItem(r, 4, st_item)

            p_item = QTableWidgetItem(path_txt)
            p_item.setToolTip(path_txt)
            self.records_table.setItem(r, 5, p_item)
        self.records_table.setUpdatesEnabled(True)

    def _export_txt_report(self) -> None:
        session, entries = self.get_current_context()
        all_sessions = self.db.list_sessions()
        logs = self.db.list_recovery_logs()

        sid = session.session_id if session else "Summary"
        default_name = f"RecoverX_Report_{sid}.txt"
        out_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export TXT Recovery Report",
            default_name,
            "Text Report (*.txt)",
        )
        if not out_path:
            return

        saved = ReportExporter.export_txt(
            output_path=out_path,
            session=session,
            entries=entries,
            recovery_logs=logs,
            all_sessions=all_sessions[:5],
        )
        QMessageBox.information(
            self,
            "TXT Report Exported",
            f"Recovery report exported successfully to:\n{saved}",
        )

    def apply_palette(self, palette: ThemePalette) -> None:
        self._palette = palette
        self.hdr.setStyleSheet(
            f"font-size: 19px; font-weight: 800; color: {palette.text_primary}; background: transparent;"
        )
        self.sub.setStyleSheet(
            f"font-size: 12.5px; color: {palette.text_secondary}; background: transparent;"
        )
        self.lbl_kpi_saved.setStyleSheet(
            f"font-size: 13px; font-weight: 700; color: {palette.status_good}; background: transparent;"
        )
        self.lbl_kpi_failed.setStyleSheet(
            f"font-size: 13px; font-weight: 700; color: {palette.status_corrupted}; background: transparent;"
        )
        self.lbl_kpi_warn.setStyleSheet(
            f"font-size: 13px; font-weight: 700; color: {palette.status_partial}; background: transparent;"
        )


class AboutView(QFrame):
    """
    Minimal, Clean 'About RecoverX' View ('About' nav tab):
    - Keeps ONLY 'About RecoverX', 'Developed by Muhammad Ishaq.' (with a period '.' after
      Muhammad Ishaq, where Muhammad Ishaq. is clickable to pop out the profile modal),
      and the essential RecoverX description.
    """

    def __init__(self, db: Optional[RecoverXDatabase] = None, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.db = db
        self._active_popup: Optional[AuthorProfilePopupModal] = None
        self.setObjectName("SectionPanel")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(12)

        self.hdr = QLabel("About RecoverX")
        outer.addWidget(self.hdr)

        dev_row = QHBoxLayout()
        dev_row.setContentsMargins(0, 0, 0, 4)
        dev_row.setSpacing(5)

        self.dev_prefix_lbl = QLabel("Developed by")
        dev_row.addWidget(self.dev_prefix_lbl)

        self.author_link_btn = ClickableAuthorLinkButton("Muhammad Ishaq.")
        self.author_link_btn.clicked.connect(self.show_author_profile_popup)
        dev_row.addWidget(self.author_link_btn)

        dev_row.addStretch(1)
        outer.addLayout(dev_row)

        self.intro_lbl = QLabel(
            "RecoverX — Advanced Data Recovery Tool is a fast, safe, and easy-to-use Windows application "
            "designed to help you find and restore accidentally deleted photos, videos, documents, audio, "
            "and archives into organized folders while keeping your source storage strictly read-only."
        )
        self.intro_lbl.setWordWrap(True)
        outer.addWidget(self.intro_lbl)

        outer.addStretch(1)
        self.apply_palette(LIGHT_PALETTE)

    def show_author_profile_popup(self) -> None:
        if self._active_popup is not None and self._active_popup.isVisible():
            self._active_popup.close()
        parent_win = self.window() or self
        self._active_popup = AuthorProfilePopupModal(parent=parent_win)
        self._active_popup.exec()

    def apply_palette(self, palette: ThemePalette) -> None:
        accent = "#38BDF8" if palette.is_dark else "#0570FA"
        hover_accent = "#7DD3FC" if palette.is_dark else "#0051D5"
        self.hdr.setStyleSheet(
            f"font-size: 22px; font-weight: 800; color: {palette.text_primary}; background: transparent;"
        )
        self.dev_prefix_lbl.setStyleSheet(
            f"font-size: 15px; font-weight: 600; color: {palette.text_secondary}; background: transparent;"
        )
        self.author_link_btn.setStyleSheet(
            f"QPushButton {{"
            f"  font-size: 15px; font-weight: 800; color: {accent}; "
            f"  background: transparent; border: none; padding: 0px; text-decoration: underline;"
            f"}}"
            f"QPushButton:hover {{"
            f"  color: {hover_accent};"
            f"}}"
        )
        self.intro_lbl.setStyleSheet(
            f"font-size: 14px; color: {palette.text_primary}; background: transparent; line-height: 1.5;"
        )
