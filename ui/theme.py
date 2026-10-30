"""Exact Dark & Light Theme Palettes and Enhanced Stylesheets (with Rich Button Hover Colors & Modern Pill Scrollbars) for RecoverX."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ThemePalette:
    name: str
    is_dark: bool
    window_bg: str
    sidebar_bg: str
    panel_bg: str
    card_bg: str
    card_hover_bg: str
    card_selected_bg: str
    card_border: str
    card_selected_border: str
    primary_blue: str
    primary_blue_hover: str
    accent_blue_text: str
    text_primary: str
    text_secondary: str
    text_muted: str
    table_header_bg: str
    table_row_hover: str
    table_row_selected: str
    table_grid_line: str
    status_bar_bg: str
    status_good: str
    status_partial: str
    status_corrupted: str
    stop_btn_bg: str
    stop_btn_border: str
    stop_btn_text: str
    input_bg: str
    input_border: str


DARK_PALETTE = ThemePalette(
    name="dark",
    is_dark=True,
    window_bg="#0B121E",
    sidebar_bg="#0A111B",
    panel_bg="#0E1624",
    card_bg="#141E30",
    card_hover_bg="#1D2E4A",
    card_selected_bg="#162B4D",
    card_border="#223049",
    card_selected_border="#0577FC",
    primary_blue="#0570FA",
    primary_blue_hover="#0EA5E9",
    accent_blue_text="#0E84FF",
    text_primary="#F8FAFC",
    text_secondary="#94A3B8",
    text_muted="#64748B",
    table_header_bg="#111A2B",
    table_row_hover="#152238",
    table_row_selected="#0C2249",
    table_grid_line="#1B263B",
    status_bar_bg="#111927",
    status_good="#10B981",
    status_partial="#F59E0B",
    status_corrupted="#EF4444",
    stop_btn_bg="#240B16",
    stop_btn_border="#991B1B",
    stop_btn_text="#F87171",
    input_bg="#111A2B",
    input_border="#24344E",
)

LIGHT_PALETTE = ThemePalette(
    name="light",
    is_dark=False,
    window_bg="#F3F8FD",
    sidebar_bg="#F8FBFF",
    panel_bg="#FFFFFF",
    card_bg="#FFFFFF",
    card_hover_bg="#E8F3FF",
    card_selected_bg="#EBF5FF",
    card_border="#DCE6F2",
    card_selected_border="#067CFD",
    primary_blue="#067CFD",
    primary_blue_hover="#0284C7",
    accent_blue_text="#0570FA",
    text_primary="#0F172A",
    text_secondary="#475569",
    text_muted="#64748B",
    table_header_bg="#F4F8FC",
    table_row_hover="#F1F7FF",
    table_row_selected="#E1EFFD",
    table_grid_line="#E2E8F0",
    status_bar_bg="#FFFFFF",
    status_good="#10B981",
    status_partial="#F59E0B",
    status_corrupted="#EF4444",
    stop_btn_bg="#FFF1F2",
    stop_btn_border="#F43F5E",
    stop_btn_text="#E11D48",
    input_bg="#F8FAFC",
    input_border="#CBD5E1",
)


class ThemeManager:
    """Generates complete Qt StyleSheets (QSS) for RecoverX Dark and Light modes."""

    @staticmethod
    def get_palette(is_dark: bool = True) -> ThemePalette:
        return DARK_PALETTE if is_dark else LIGHT_PALETTE

    @classmethod
    def build_stylesheet(cls, p: ThemePalette) -> str:
        chk_border = "#475569" if p.is_dark else "#94A3B8"
        chk_bg = "#111A2B" if p.is_dark else "#FFFFFF"
        outline_border = "#38BDF8" if p.is_dark else "#0570FA"
        outline_fg = "#38BDF8" if p.is_dark else "#0570FA"
        outline_hover_bg = (
            "qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #17365D, stop:1 #1E40AF)"
            if p.is_dark
            else "qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #DCEEFF, stop:1 #BAE6FD)"
        )
        outline_hover_fg = "#FFFFFF" if p.is_dark else "#003EA6"
        outline_hover_border = "#7DD3FC" if p.is_dark else "#0284C7"
        outline_pressed_bg = "#1E3A8A" if p.is_dark else "#93C5FD"
        disabled_bg = "#1E293B" if p.is_dark else "#CBD5E1"
        disabled_fg = "#64748B" if p.is_dark else "#94A3B8"
        sb_track = "#101929" if p.is_dark else "#EDF3FA"
        sb_handle = "#334766" if p.is_dark else "#94A3B8"
        sb_handle_hover = "#38BDF8" if p.is_dark else "#0570FA"
        sb_handle_pressed = "#0284C7" if p.is_dark else "#0353C4"
        return f"""
        QMainWindow, QWidget#MainRoot {{
            background-color: {p.window_bg};
            color: {p.text_primary};
            font-family: "Segoe UI", "Inter", "Noto Sans", sans-serif;
            font-size: 13px;
        }}
        QSplitter::handle {{
            background-color: transparent;
        }}
        QSplitter::handle:hover {{
            background-color: {p.primary_blue};
        }}
        QCheckBox {{
            spacing: 6px;
            background: transparent;
        }}
        QCheckBox::indicator {{
            width: 16px;
            height: 16px;
            border-radius: 4px;
            border: 1.5px solid {chk_border};
            background-color: {chk_bg};
        }}
        QCheckBox::indicator:hover {{
            border-color: {p.primary_blue};
            background-color: {p.card_hover_bg};
        }}
        QCheckBox::indicator:checked {{
            background-color: {p.primary_blue};
            border-color: {p.primary_blue};
        }}
        QFrame#SidebarFrame {{
            background-color: {p.sidebar_bg};
            border-right: 1px solid {p.card_border};
        }}
        QFrame#HeroBanner {{
            background-color: {p.panel_bg};
            border: 1px solid {p.card_border};
            border-radius: 12px;
        }}
        QFrame#SectionPanel, QFrame#ResultsWorkspace, QFrame#OutputDirectoryCard, QFrame#InfoCard {{
            background-color: {p.panel_bg};
            border: 1px solid {p.card_border};
            border-radius: 12px;
        }}
        QFrame#SafeReadOnlyCard {{
            background-color: {p.card_bg};
            border: 1px solid {p.card_border};
            border-radius: 10px;
        }}
        QFrame#BottomStatusBar {{
            background-color: {p.status_bar_bg};
            border: 1px solid {p.card_border};
            border-radius: 10px;
        }}
        QLineEdit#SearchFilesEdit, QLineEdit#OutputDirEdit {{
            background-color: {p.input_bg};
            color: {p.text_primary};
            border: 1px solid {p.input_border};
            border-radius: 7px;
            padding: 4px 10px;
            font-size: 12.5px;
        }}
        QLineEdit#SearchFilesEdit:hover, QLineEdit#OutputDirEdit:hover {{
            border: 1.5px solid {outline_border};
        }}
        QLineEdit#SearchFilesEdit:focus, QLineEdit#OutputDirEdit:focus {{
            border: 1.5px solid {p.primary_blue};
        }}
        QComboBox#TypeFilterCombo {{
            background-color: {p.input_bg};
            color: {p.text_primary};
            border: 1px solid {p.input_border};
            border-radius: 7px;
            padding: 4px 10px;
            font-size: 12.5px;
        }}
        QComboBox#TypeFilterCombo:hover {{
            border: 1.5px solid {outline_border};
            background-color: {p.card_hover_bg};
        }}
        QComboBox#TypeFilterCombo::drop-down {{
            border: none;
            width: 22px;
        }}
        QComboBox QAbstractItemView {{
            background-color: {p.card_bg};
            color: {p.text_primary};
            selection-background-color: {p.primary_blue};
            border: 1px solid {p.card_border};
        }}
        /* Primary Start Scan Button with Vibrant Electric Cyan-Blue Hover Transition */
        QPushButton#PrimaryStartScanBtn {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #0570FA, stop:0.55 #0E84FF, stop:1 #025CE2);
            color: #FFFFFF;
            border: 1.5px solid #2589FF;
            border-radius: 10px;
            font-size: 15.5px;
            font-weight: 700;
            padding: 8px 20px;
        }}
        QPushButton#PrimaryStartScanBtn:hover {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #0051D5, stop:0.45 #0284C7, stop:1 #06B6D4);
            color: #FFFFFF;
            border: 2px solid #38BDF8;
        }}
        QPushButton#PrimaryStartScanBtn:pressed {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #003EA6, stop:1 #0353C4);
            border: 2px solid #0284C7;
            padding-top: 10px;
            padding-left: 22px;
        }}
        /* Primary Action Buttons (Save, Export TXT Report) */
        QPushButton#PrimaryActionBtn {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0570FA, stop:1 #0E84FF);
            color: #FFFFFF;
            border: 1.5px solid #025CE2;
            border-radius: 7px;
            font-size: 12.5px;
            font-weight: 700;
            padding: 5px 16px;
        }}
        QPushButton#PrimaryActionBtn:hover {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0051D5, stop:0.5 #0284C7, stop:1 #06B6D4);
            color: #FFFFFF;
            border: 1.5px solid #38BDF8;
        }}
        QPushButton#PrimaryActionBtn:pressed {{
            background-color: #003EA6;
            border-color: #0284C7;
        }}
        QPushButton#PrimaryActionBtn:disabled {{
            background-color: {disabled_bg};
            color: {disabled_fg};
            border: 1px solid {p.card_border};
        }}
        /* Outlined Action Buttons (Refresh Drives, Clear Results, Browse, Open Folder, Clear Reports) */
        QPushButton#OutlinedActionBtn {{
            background-color: {p.card_bg};
            color: {outline_fg};
            border: 1.5px solid {outline_border};
            border-radius: 7px;
            font-size: 12px;
            font-weight: 600;
            padding: 4px 12px;
        }}
        QPushButton#OutlinedActionBtn:hover {{
            background: {outline_hover_bg};
            color: {outline_hover_fg};
            border: 1.8px solid {outline_hover_border};
        }}
        QPushButton#OutlinedActionBtn:pressed {{
            background-color: {outline_pressed_bg};
            border-color: {p.primary_blue};
        }}
        QPushButton#SecondaryActionBtn {{
            background-color: {p.card_bg};
            color: {p.text_primary};
            border: 1.5px solid {p.input_border};
            border-radius: 7px;
            font-size: 12px;
            font-weight: 600;
            padding: 5px 12px;
        }}
        QPushButton#SecondaryActionBtn:hover {{
            background: {outline_hover_bg};
            color: {outline_hover_fg};
            border: 1.8px solid {outline_hover_border};
        }}
        /* Stop Scan Button */
        QPushButton#StopScanBtn {{
            background-color: {p.stop_btn_bg};
            color: {p.stop_btn_text};
            border: 1.5px solid {p.stop_btn_border};
            border-radius: 7px;
            font-size: 12px;
            font-weight: 600;
            padding: 4px 14px;
        }}
        QPushButton#StopScanBtn:hover {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #DC2626, stop:1 #F43F5E);
            color: #FFFFFF;
            border: 1.5px solid #B91C1C;
        }}
        QPushButton#StopScanBtn:pressed {{
            background-color: #991B1B;
            color: #FFFFFF;
        }}
        QPushButton#StopScanBtn:disabled {{
            background-color: {p.card_bg};
            color: {disabled_fg};
            border: 1px solid {p.card_border};
        }}
        QTableWidget#ResultsTable {{
            background-color: {p.panel_bg};
            alternate-background-color: {p.card_bg};
            color: {p.text_primary};
            border: 1px solid {p.card_border};
            border-radius: 8px;
            gridline-color: {p.table_grid_line};
            selection-background-color: {p.table_row_selected};
            selection-color: {p.text_primary};
            font-size: 12.5px;
        }}
        QTableWidget#ResultsTable::item {{
            padding: 4px 8px;
            border-bottom: 1px solid {p.table_grid_line};
        }}
        QTableWidget#ResultsTable::item:hover {{
            background-color: {p.table_row_hover};
        }}
        QTableWidget#ResultsTable::item:selected {{
            background-color: {p.table_row_selected};
            color: {p.text_primary};
        }}
        QHeaderView::section {{
            background-color: {p.table_header_bg};
            color: {p.text_secondary};
            font-size: 12px;
            font-weight: 600;
            padding: 6px 8px;
            border: none;
            border-bottom: 1px solid {p.card_border};
        }}
        QTextEdit#ThemedTextBox {{
            background-color: {p.card_bg};
            color: {p.text_primary};
            border: 1px solid {p.card_border};
            border-radius: 8px;
            padding: 8px;
        }}
        /* Sleek Modern Pill Scrollbars for Scan Results & Panels */
        QScrollBar:vertical {{
            background: {sb_track};
            width: 11px;
            margin: 3px 2px 3px 2px;
            border-radius: 5px;
        }}
        QScrollBar::handle:vertical {{
            background: {sb_handle};
            min-height: 36px;
            border-radius: 3.5px;
        }}
        QScrollBar::handle:vertical:hover {{
            background: {sb_handle_hover};
        }}
        QScrollBar::handle:vertical:pressed {{
            background: {sb_handle_pressed};
        }}
        QScrollBar:horizontal {{
            background: {sb_track};
            height: 11px;
            margin: 2px 3px 2px 3px;
            border-radius: 5px;
        }}
        QScrollBar::handle:horizontal {{
            background: {sb_handle};
            min-width: 36px;
            border-radius: 3.5px;
        }}
        QScrollBar::handle:horizontal:hover {{
            background: {sb_handle_hover};
        }}
        QScrollBar::handle:horizontal:pressed {{
            background: {sb_handle_pressed};
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
            height: 0px;
            width: 0px;
            border: none;
            background: none;
        }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical,
        QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
            background: transparent;
        }}
        """
