"""Custom Native PySide6 Widgets with 360-Degree Rotating 3D Neon Orbit Hero, Category Chips, and Outlined Controls."""
from __future__ import annotations

import math
from typing import List, Optional

from PySide6.QtCore import QPointF, QRectF, QTimer, Qt, Signal
from PySide6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QFontMetrics,
    QIcon,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from devices.discovery import DeviceInfo, DeviceType
from filesystems.base import format_file_size
from recovery.engine import ScanMode
from .icons import ASSETS_DIR, create_vector_icon
from .theme import LIGHT_PALETTE, ThemePalette


def _make_font(pt_size: float, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    """Create a QFont safely using `setPointSizeF(float)` so PySide6 on Python 3.12+ never receives a float in `QFont(str, int)`."""
    font = QFont("Segoe UI")
    font.setPointSizeF(float(pt_size))
    font.setWeight(weight)
    return font


class ThemeToggleSwitch(QWidget):
    """
    Compact sun icon + pill toggle switch placed inside the left sidebar panel.
    Defaults to Light Mode (`is_dark=False`).
    """

    toggled = Signal(bool)

    def __init__(self, is_dark: bool = False, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._is_dark = is_dark
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setMouseTracking(True)
        self.setFixedSize(74, 26)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setToolTip("Switch between Light and Dark theme")

    def set_dark(self, is_dark: bool) -> None:
        if self._is_dark != is_dark:
            self._is_dark = is_dark
            self.update()

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_dark = not self._is_dark
            self.toggled.emit(self._is_dark)
            self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        hovered = self.underMouse()
        sun_color = QColor("#38BDF8" if hovered else "#94A3B8") if self._is_dark else QColor("#0284C7" if hovered else "#0570FA")
        p.setPen(QPen(sun_color, 1.7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.setBrush(Qt.BrushStyle.NoBrush)
        cx, cy = 12.0, 13.0
        p.drawEllipse(QPointF(cx, cy), 3.4, 3.4)
        for angle_deg in range(0, 360, 45):
            rad = math.radians(angle_deg)
            p.drawLine(
                QPointF(cx + math.cos(rad) * 5.0, cy + math.sin(rad) * 5.0),
                QPointF(cx + math.cos(rad) * 7.0, cy + math.sin(rad) * 7.0),
            )

        track_rect = QRectF(30, 4, 40, 18)
        if hovered:
            track_color = QColor("#0EA5E9") if self._is_dark else QColor("#0284C7")
            border_color = QColor("#38BDF8") if self._is_dark else QColor("#0369A1")
        else:
            track_color = QColor("#0570FA") if self._is_dark else QColor("#3B82F6")
            border_color = QColor("#1E3A8A" if self._is_dark else "#2563EB")
        p.setPen(QPen(border_color, 1.2))
        p.setBrush(track_color)
        p.drawRoundedRect(track_rect, 9, 9)

        knob_x = 53.0 if self._is_dark else 32.0
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#FFFFFF"))
        p.drawEllipse(QRectF(knob_x, 6, 14, 14))
        p.end()


class SidebarNavButton(QPushButton):
    """
    Enhanced Left Sidebar Navigation Button (Recover, Scan, Reports, About):
    - 46px height, 22px vector icon in a 32x32 rounded badge, 11.5pt font, left accent bar, and crisp hover border.
    """

    def __init__(self, label: str, icon_kind: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.label_text = label
        self.icon_kind = icon_kind
        self._active = False
        self._palette = LIGHT_PALETTE
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setMouseTracking(True)
        self.setFixedHeight(46)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

    def set_state(self, active: bool, palette: ThemePalette) -> None:
        self._active = active
        self._palette = palette
        self.update()

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(0, 0, self.width(), self.height())
        hovered = self.underMouse()

        if self._active:
            bg = (
                QColor("#0284C7" if hovered else "#0565FC")
                if self._palette.is_dark
                else QColor("#CFE8FF" if hovered else "#DCEEFF")
            )
            border_pen = QPen(QColor("#38BDF8" if self._palette.is_dark else "#0570FA"), 1.4)
            p.setBrush(bg)
            p.setPen(border_pen)
            p.drawRoundedRect(rect.adjusted(2, 2, -2, -2), 10, 10)

            accent_bar = QColor("#FFFFFF") if self._palette.is_dark else QColor("#0565FC")
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(accent_bar)
            p.drawRoundedRect(QRectF(5, 11, 4, self.height() - 22), 2, 2)

            fg_hex = "#FFFFFF" if self._palette.is_dark else "#0565FC"
            icon_bg = QColor(255, 255, 255, 42) if self._palette.is_dark else QColor(5, 101, 252, 34)
        else:
            if hovered:
                hover_bg = QColor(self._palette.card_hover_bg)
                hover_border = QPen(QColor("#38BDF8" if self._palette.is_dark else "#60A5FA"), 1.3)
                p.setBrush(hover_bg)
                p.setPen(hover_border)
                p.drawRoundedRect(rect.adjusted(2, 2, -2, -2), 10, 10)
                fg_hex = "#38BDF8" if self._palette.is_dark else "#0570FA"
                icon_bg = QColor("#1E3A5F") if self._palette.is_dark else QColor("#DCEEFF")
            else:
                fg_hex = "#CBD5E1" if self._palette.is_dark else "#1E293B"
                icon_bg = QColor("#152238") if self._palette.is_dark else QColor("#EEF4FB")

        badge_y = (self.height() - 32.0) / 2.0
        p.setBrush(icon_bg)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(14, badge_y, 32, 32), 8, 8)

        icon_pix = create_vector_icon(self.icon_kind, 22, fg_hex)
        p.drawPixmap(19, int((self.height() - 22) / 2), icon_pix)

        p.setPen(QColor(fg_hex))
        font = _make_font(
            11.5,
            QFont.Weight.Bold if (self._active or hovered) else QFont.Weight.DemiBold,
        )
        p.setFont(font)
        p.drawText(
            QRectF(54, 0, self.width() - 58, self.height()),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            self.label_text,
        )
        p.end()


class AnimatedNeonOrbitWidget(QWidget):
    """
    360-Degree Rotating 3D Neon Orbit Hard Drive & Media Icons Animation:
    - Central 3D isometric hard drive (`orbit_hdd_clean.png`) with a spinning metallic platter sheen.
    - Dual tilted 3D neon elliptical orbit rings (`#38BDF8` & `#0570FA`) with glowing energy nodes.
    - All 4 extracted 3D neon glass tiles (`orbit_tile_image.png`, `orbit_tile_doc.png`,
      `orbit_tile_video.png`, `orbit_tile_audio.png`) continuously rotate 360° around the
      central hard drive in 3D perspective (passing behind the drive when `sin(theta) < 0`
      and in front of the drive when `sin(theta) >= 0`).
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setMinimumWidth(240)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self._hdd_pix = QPixmap(str(ASSETS_DIR / "orbit_hdd_clean.png"))
        self._tiles: List[QPixmap] = [
            QPixmap(str(ASSETS_DIR / "orbit_tile_image.png")),
            QPixmap(str(ASSETS_DIR / "orbit_tile_doc.png")),
            QPixmap(str(ASSETS_DIR / "orbit_tile_video.png")),
            QPixmap(str(ASSETS_DIR / "orbit_tile_audio.png")),
        ]
        self._fallback_pix = QPixmap(str(ASSETS_DIR / "neon_orbit_hero.png"))

        self._orbit_angle: float = 0.0
        self._platter_angle_deg: float = 0.0
        self._fast_mode: bool = False

        self._timer = QTimer(self)
        self._timer.setInterval(30)  # ~33 FPS smooth 360° orbital rotation
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def set_scanning_active(self, active: bool) -> None:
        self._fast_mode = active

    def _tick(self) -> None:
        orbit_step = 0.085 if self._fast_mode else 0.032
        platter_step = 14.0 if self._fast_mode else 4.5
        self._orbit_angle = (self._orbit_angle + orbit_step) % (math.pi * 2.0)
        self._platter_angle_deg = (self._platter_angle_deg + platter_step) % 360.0
        self.update()

    def _draw_orbit_half(
        self,
        p: QPainter,
        cx: float,
        cy: float,
        rx: float,
        ry: float,
        front_half: bool,
    ) -> None:
        p.save()
        p.translate(cx, cy)
        p.rotate(-6.0)

        rect_outer = QRectF(-rx, -ry, rx * 2.0, ry * 2.0)
        rect_inner = QRectF(-rx * 0.84, -ry * 0.84, rx * 1.68, ry * 1.68)

        start_deg = 180 if front_half else 0
        span_deg = 180

        pen_outer = QPen(QColor(14, 165, 233, 195 if front_half else 115), 1.6)
        p.setPen(pen_outer)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(rect_outer, start_deg * 16, span_deg * 16)

        pen_inner = QPen(QColor(56, 189, 248, 155 if front_half else 90), 1.1)
        p.setPen(pen_inner)
        p.drawArc(rect_inner, start_deg * 16, span_deg * 16)

        p.setPen(Qt.PenStyle.NoPen)
        for k in range(6):
            node_ang = (self._orbit_angle * 1.35 + k * (math.pi / 3.0)) % (math.pi * 2.0)
            nz = math.sin(node_ang)
            is_node_front = nz >= 0.0
            if is_node_front != front_half:
                continue
            nx = math.cos(node_ang) * rx
            ny = nz * ry
            p.setBrush(QColor(56, 189, 248, 95))
            p.drawEllipse(QPointF(nx, ny), 4.5, 4.5)
            p.setBrush(QColor(224, 242, 254, 245))
            p.drawEllipse(QPointF(nx, ny), 2.2, 2.2)

        p.restore()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        w = float(self.width())
        h = float(self.height())

        if self._hdd_pix.isNull() or any(t.isNull() for t in self._tiles):
            if not self._fallback_pix.isNull():
                scaled = self._fallback_pix.scaledToHeight(
                    int(max(68.0, h - 4.0)),
                    Qt.TransformationMode.SmoothTransformation,
                )
                p.drawPixmap(int(w - scaled.width() - 8), int((h - scaled.height()) / 2.0), scaled)
            p.end()
            return

        scene_w = min(w - 8.0, max(210.0, h * 2.45))
        cx = w - scene_w * 0.52 - 6.0
        cy = h * 0.54
        rx = scene_w * 0.41
        ry = max(20.0, h * 0.30)

        tile_states = []
        base_tile_h = max(26.0, h * 0.40)
        for idx, tile_pix in enumerate(self._tiles):
            theta = (self._orbit_angle + idx * (math.pi / 2.0)) % (math.pi * 2.0)
            raw_x = math.cos(theta) * rx
            raw_y = math.sin(theta) * ry
            tilt_rad = math.radians(-6.0)
            tx = cx + raw_x * math.cos(tilt_rad) - raw_y * math.sin(tilt_rad)
            ty = cy + raw_x * math.sin(tilt_rad) + raw_y * math.cos(tilt_rad) - 4.0
            z_depth = math.sin(theta)
            depth_scale = 0.78 + 0.26 * ((z_depth + 1.0) / 2.0)
            target_th = int(round(base_tile_h * depth_scale))
            scaled_tile = tile_pix.scaledToHeight(
                max(18, target_th),
                Qt.TransformationMode.SmoothTransformation,
            )
            tile_states.append((z_depth, tx, ty, scaled_tile))

        tile_states.sort(key=lambda item: item[0])

        self._draw_orbit_half(p, cx, cy, rx, ry, front_half=False)
        for z_depth, tx, ty, scaled_tile in tile_states:
            if z_depth < 0.0:
                p.setOpacity(0.86 + 0.14 * (z_depth + 1.0))
                p.drawPixmap(
                    int(round(tx - scaled_tile.width() / 2.0)),
                    int(round(ty - scaled_tile.height() / 2.0)),
                    scaled_tile,
                )
        p.setOpacity(1.0)

        hdd_target_h = int(round(max(46.0, h * 0.68)))
        hdd_scaled = self._hdd_pix.scaledToHeight(
            hdd_target_h,
            Qt.TransformationMode.SmoothTransformation,
        )
        hdd_x = int(round(cx - hdd_scaled.width() / 2.0))
        hdd_y = int(round(cy - hdd_scaled.height() / 2.0 + 5.0))
        p.drawPixmap(hdd_x, hdd_y, hdd_scaled)

        p.save()
        platter_cx = hdd_x + hdd_scaled.width() * 0.495
        platter_cy = hdd_y + hdd_scaled.height() * 0.395
        platter_r = hdd_scaled.width() * 0.24
        p.translate(platter_cx, platter_cy)
        p.scale(1.0, 0.56)
        p.rotate(self._platter_angle_deg)
        sweep_pen = QPen(QColor(255, 255, 255, 115), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        p.setPen(sweep_pen)
        p.drawArc(QRectF(-platter_r * 0.72, -platter_r * 0.72, platter_r * 1.44, platter_r * 1.44), 20 * 16, 65 * 16)
        p.drawArc(QRectF(-platter_r * 0.72, -platter_r * 0.72, platter_r * 1.44, platter_r * 1.44), 200 * 16, 65 * 16)
        p.restore()

        self._draw_orbit_half(p, cx, cy, rx, ry, front_half=True)
        for z_depth, tx, ty, scaled_tile in tile_states:
            if z_depth >= 0.0:
                p.drawPixmap(
                    int(round(tx - scaled_tile.width() / 2.0)),
                    int(round(ty - scaled_tile.height() / 2.0)),
                    scaled_tile,
                )

        p.end()


class HeroBannerWidget(QFrame):
    """Hero Banner featuring 'Recover What Matters' and the rotating AnimatedNeonOrbitWidget."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("HeroBanner")
        self.setMinimumHeight(86)
        self.setMaximumHeight(104)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._palette = LIGHT_PALETTE

        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 6, 8, 6)
        layout.setSpacing(12)

        left_col = QVBoxLayout()
        left_col.setSpacing(2)
        left_col.addStretch(1)

        self.title_lbl = QLabel()
        self.title_lbl.setTextFormat(Qt.TextFormat.RichText)
        left_col.addWidget(self.title_lbl)

        self.subtitle_lbl = QLabel(
            "Scan your drives, select recoverable file types, and save them into organized folders."
        )
        self.subtitle_lbl.setWordWrap(True)
        left_col.addWidget(self.subtitle_lbl)
        left_col.addStretch(1)

        layout.addLayout(left_col, stretch=3)

        self.orbit_anim = AnimatedNeonOrbitWidget()
        layout.addWidget(self.orbit_anim, stretch=2)

        self.apply_palette(LIGHT_PALETTE)

    def set_scanning_active(self, active: bool) -> None:
        self.orbit_anim.set_scanning_active(active)

    def apply_palette(self, palette: ThemePalette) -> None:
        self._palette = palette
        rec_color = "#FFFFFF" if palette.is_dark else "#0F172A"
        blue_color = "#0E84FF" if palette.is_dark else "#0570FA"
        self.title_lbl.setText(
            f'<span style="font-size:25px; font-weight:800; color:{rec_color};">Recover </span>'
            f'<span style="font-size:25px; font-weight:800; color:{blue_color};">What Matters</span>'
        )
        self.subtitle_lbl.setStyleSheet(
            f"font-size: 12.5px; color: {palette.text_secondary}; background: transparent;"
        )


class DriveCardWidget(QFrame):
    """
    Selectable Drive Card (`80px` height, `240..320px` width) with adaptive font sizing and rich hover border.
    """

    clicked = Signal(object)

    def __init__(self, device: DeviceInfo, selected: bool = False, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.device = device
        self.selected = selected
        self._palette = LIGHT_PALETTE
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setMouseTracking(True)
        self.setFixedHeight(80)
        self.setMinimumWidth(240)
        self.setMaximumWidth(320)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setToolTip(f"{device.name} — {device.capacity_summary} ({device.filesystem})")

    def set_selected(self, selected: bool, palette: ThemePalette) -> None:
        self.selected = selected
        self._palette = palette
        self.update()

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.device)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(1.5, 1.5, self.width() - 3.0, self.height() - 3.0)
        hovered = self.underMouse()

        if self.selected:
            bg = QColor(self._palette.card_hover_bg if hovered else self._palette.card_selected_bg)
            border = QPen(QColor("#0284C7" if hovered else self._palette.card_selected_border), 2.0)
        elif hovered:
            bg = QColor(self._palette.card_hover_bg)
            border = QPen(QColor("#38BDF8" if self._palette.is_dark else "#0570FA"), 1.6)
        else:
            bg = QColor(self._palette.card_bg)
            border = QPen(QColor(self._palette.card_border), 1.2)

        p.setBrush(bg)
        p.setPen(border)
        p.drawRoundedRect(rect, 10, 10)

        if "C:" in self.device.name or "Local Disk" in self.device.name or "Windows" in self.device.name:
            icon_kind = "windows_drive"
        elif self.device.device_type == DeviceType.REMOVABLE_DRIVE or "USB" in self.device.name:
            icon_kind = "usb"
        else:
            icon_kind = "hdd"
        icon_pix = create_vector_icon(icon_kind, 36)
        p.drawPixmap(12, int((self.height() - 36) / 2), icon_pix)

        ind_rect = QRectF(self.width() - 25, 8, 15, 15)
        if self.selected:
            p.setBrush(QColor("#0577FC"))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(ind_rect)
            chk_pen = QPen(
                QColor("#FFFFFF"),
                1.8,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin,
            )
            p.setPen(chk_pen)
            p.drawLine(QPointF(ind_rect.left() + 3.5, ind_rect.top() + 7.5), QPointF(ind_rect.left() + 6.5, ind_rect.top() + 10.5))
            p.drawLine(QPointF(ind_rect.left() + 6.5, ind_rect.top() + 10.5), QPointF(ind_rect.left() + 11.5, ind_rect.top() + 4.5))
        else:
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor("#0570FA" if hovered else self._palette.text_muted), 1.4))
            p.drawEllipse(ind_rect)

        avail_title_w = max(60.0, self.width() - 84.0)
        f_title = _make_font(9.8, QFont.Weight.Bold)
        if QFontMetrics(f_title).horizontalAdvance(self.device.name) > avail_title_w:
            f_title.setPointSizeF(8.8)
        p.setPen(QColor(self._palette.text_primary))
        p.setFont(f_title)
        p.drawText(
            QRectF(56, 6, avail_title_w, 20),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            self.device.name,
        )

        bar_y = 30.0
        bar_rect = QRectF(56, bar_y, max(40.0, self.width() - 68), 6.0)
        p.setBrush(QColor("#25334A" if self._palette.is_dark else "#DCE6F2"))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(bar_rect, 3.0, 3.0)

        fill_w = max(10.0, bar_rect.width() * self.device.usage_ratio)
        fill_rect = QRectF(56, bar_y, min(bar_rect.width(), fill_w), 6.0)
        p.setBrush(QColor("#0EA5E9" if hovered else "#0577FC"))
        p.drawRoundedRect(fill_rect, 3.0, 3.0)

        f_sub = _make_font(8.6)
        p.setFont(f_sub)
        p.setPen(QColor(self._palette.text_secondary))
        p.drawText(
            QRectF(56, 40, self.width() - 62, 18),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            self.device.capacity_summary,
        )
        p.drawText(
            QRectF(56, 58, self.width() - 62, 18),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            self.device.filesystem,
        )
        p.end()


class ScanModeCardWidget(QFrame):
    """Selectable Scan Mode Card (`60px` height) with zero text cutoff and vivid hover feedback."""

    clicked = Signal(object)

    def __init__(
        self,
        mode: ScanMode,
        subtitle: str,
        icon_kind: str,
        selected: bool = False,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.mode = mode
        self.subtitle = subtitle
        self.icon_kind = icon_kind
        self.selected = selected
        self._palette = LIGHT_PALETTE
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setMouseTracking(True)
        self.setFixedHeight(60)
        self.setMinimumWidth(230)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

    def set_selected(self, selected: bool, palette: ThemePalette) -> None:
        self.selected = selected
        self._palette = palette
        self.update()

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.mode)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(1.5, 1.5, self.width() - 3.0, self.height() - 3.0)
        hovered = self.underMouse()

        if self.selected:
            bg = QColor(self._palette.card_hover_bg if hovered else self._palette.card_selected_bg)
            border = QPen(QColor("#0284C7" if hovered else self._palette.card_selected_border), 2.0)
        elif hovered:
            bg = QColor(self._palette.card_hover_bg)
            border = QPen(QColor("#38BDF8" if self._palette.is_dark else "#0570FA"), 1.6)
        else:
            bg = QColor(self._palette.card_bg)
            border = QPen(QColor(self._palette.card_border), 1.2)

        p.setBrush(bg)
        p.setPen(border)
        p.drawRoundedRect(rect, 10, 10)

        badge_y = (self.height() - 34.0) / 2.0
        badge_rect = QRectF(12, badge_y, 34, 34)
        p.setBrush(
            QColor("#0284C7" if hovered else ("#17376E" if self._palette.is_dark else "#DCEEFF"))
        )
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(badge_rect)

        icon_pix = create_vector_icon(
            self.icon_kind,
            19,
            "#FFFFFF" if hovered else ("#38BDF8" if self._palette.is_dark else "#0570FA"),
        )
        p.drawPixmap(int(badge_rect.left() + 7.5), int(badge_rect.top() + 7.5), icon_pix)

        ind_rect = QRectF(self.width() - 24, 8, 14, 14)
        if self.selected:
            p.setBrush(QColor("#0577FC"))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(ind_rect)
            chk_pen = QPen(
                QColor("#FFFFFF"),
                1.7,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin,
            )
            p.setPen(chk_pen)
            p.drawLine(QPointF(ind_rect.left() + 3.2, ind_rect.top() + 7.0), QPointF(ind_rect.left() + 6.0, ind_rect.top() + 9.8))
            p.drawLine(QPointF(ind_rect.left() + 6.0, ind_rect.top() + 9.8), QPointF(ind_rect.left() + 10.8, ind_rect.top() + 4.2))
        else:
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor("#0570FA" if hovered else self._palette.text_muted), 1.4))
            p.drawEllipse(ind_rect)

        p.setPen(QColor(self._palette.text_primary))
        p.setFont(_make_font(10.0, QFont.Weight.Bold))
        p.drawText(
            QRectF(54, 7, self.width() - 80, 20),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            self.mode.value,
        )

        p.setPen(QColor(self._palette.text_secondary))
        sub_font = _make_font(8.8)
        avail_sub_w = max(80.0, self.width() - 60.0)
        if QFontMetrics(sub_font).horizontalAdvance(self.subtitle) > avail_sub_w:
            sub_font.setPointSizeF(8.1)
        p.setFont(sub_font)
        p.drawText(
            QRectF(54, 29, avail_sub_w, 24),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            self.subtitle,
        )
        p.end()


class CategoryChipWidget(QFrame):
    """
    Horizontal File-Type Chip placed below the Scan Mode buttons with adaptive font sizing and rich hover state.
    """

    clicked = Signal(str)
    checked_changed = Signal(str, bool)

    CATEGORY_ICON_KIND = {
        "All Files": "cat_all",
        "Images": "cat_images",
        "Videos": "cat_videos",
        "Documents": "cat_documents",
        "Audio": "cat_audio",
        "Archives": "cat_archives",
        "Other Files": "cat_other",
    }

    def __init__(self, category_label: str, active: bool = False, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.category_label = category_label
        self.count = 0
        self.active = active
        self._checked = False
        self._palette = LIGHT_PALETTE
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setMouseTracking(True)
        self.setFixedHeight(38)
        self.setMinimumWidth(116)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._icon_pix = create_vector_icon(self.CATEGORY_ICON_KIND.get(category_label, "cat_other"), 16)

    def is_checked(self) -> bool:
        return self._checked

    def set_checked(self, checked: bool, emit_signal: bool = False) -> None:
        if self._checked != checked:
            self._checked = checked
            self.update()
            if emit_signal:
                self.checked_changed.emit(self.category_label, self._checked)

    def set_count(self, count: int) -> None:
        self.count = count
        self.setToolTip(f"{self.category_label} ({self.count:,} files)")
        self.update()

    def set_active(self, active: bool, palette: ThemePalette) -> None:
        self.active = active
        self._palette = palette
        self.update()

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._checked = not self._checked
            self.checked_changed.emit(self.category_label, self._checked)
            self.clicked.emit(self.category_label)
            self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(1.0, 1.0, self.width() - 2.0, self.height() - 2.0)
        hovered = self.underMouse()

        if self._checked:
            bg = QColor("#1D3F73" if hovered else "#15315B") if self._palette.is_dark else QColor("#CFE8FF" if hovered else "#E0F0FF")
            border = QPen(QColor("#0284C7" if hovered else "#0577FC"), 1.8)
        elif self.active or hovered:
            bg = QColor(self._palette.card_hover_bg)
            border = QPen(QColor("#38BDF8" if self._palette.is_dark else "#0570FA"), 1.5)
        else:
            bg = QColor(self._palette.card_bg)
            border = QPen(QColor(self._palette.card_border), 1.1)

        p.setBrush(bg)
        p.setPen(border)
        p.drawRoundedRect(rect, 8, 8)

        chk_rect = QRectF(7, (self.height() - 15.0) / 2.0, 15, 15)
        if self._checked:
            p.setBrush(QColor("#0284C7" if hovered else "#0570FA"))
            p.setPen(QPen(QColor("#0284C7" if hovered else "#0570FA"), 1.5))
            p.drawRoundedRect(chk_rect, 4.0, 4.0)
            chk_pen = QPen(
                QColor("#FFFFFF"),
                1.9,
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin,
            )
            p.setPen(chk_pen)
            p.drawLine(QPointF(chk_rect.left() + 3.2, chk_rect.top() + 7.6), QPointF(chk_rect.left() + 6.3, chk_rect.top() + 10.8))
            p.drawLine(QPointF(chk_rect.left() + 6.3, chk_rect.top() + 10.8), QPointF(chk_rect.left() + 11.8, chk_rect.top() + 4.4))
        else:
            p.setBrush(QColor("#0E1624" if self._palette.is_dark else "#FFFFFF"))
            p.setPen(QPen(QColor("#0570FA" if hovered else ("#64748B" if self._palette.is_dark else "#94A3B8")), 1.4))
            p.drawRoundedRect(chk_rect, 4.0, 4.0)

        p.drawPixmap(26, int((self.height() - 16) / 2), self._icon_pix)

        fg_color = (
            QColor("#FFFFFF" if self._palette.is_dark else "#0565FC")
            if (self._checked or self.active or hovered)
            else QColor(self._palette.text_primary)
        )
        p.setPen(fg_color)

        display_str = f"{self.category_label} ({self.count:,})"
        text_x = 46.0
        avail_w = max(40.0, self.width() - text_x - 4.0)

        font = _make_font(
            9.0,
            QFont.Weight.Bold if (self._checked or self.active or hovered) else QFont.Weight.DemiBold,
        )
        if QFontMetrics(font).horizontalAdvance(display_str) > avail_w:
            font.setPointSizeF(8.2)
            if QFontMetrics(font).horizontalAdvance(display_str) > avail_w:
                font.setPointSizeF(7.6)

        p.setFont(font)
        p.drawText(
            QRectF(text_x, 0, avail_w, self.height()),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            display_str,
        )
        p.end()


CategoryRowWidget = CategoryChipWidget


class OutputSaveBarWidget(QFrame):
    """
    Post-Scan Output Directory & Save Bar located at the bottom of Scan Results.
    """

    directory_changed = Signal(str)
    browse_requested = Signal()
    open_requested = Signal()
    save_requested = Signal()

    def __init__(self, initial_dir: str = "", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("OutputDirectoryCard")
        self.setFixedHeight(48)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._palette = LIGHT_PALETTE

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 6, 12, 6)
        layout.setSpacing(8)

        self.icon_lbl = QLabel()
        self.icon_lbl.setFixedSize(22, 22)
        layout.addWidget(self.icon_lbl)

        self.title_lbl = QLabel("Output Directory:")
        self.title_lbl.setMinimumWidth(112)
        layout.addWidget(self.title_lbl)

        self.path_edit = QLineEdit(initial_dir)
        self.path_edit.setObjectName("OutputDirEdit")
        self.path_edit.setFixedHeight(30)
        self.path_edit.setPlaceholderText("Choose destination folder to save recovered files...")
        self.path_edit.setToolTip(initial_dir)
        self.path_edit.textChanged.connect(self._on_text_changed)
        layout.addWidget(self.path_edit, stretch=1)

        self.browse_btn = QPushButton("Browse...")
        self.browse_btn.setObjectName("OutlinedActionBtn")
        self.browse_btn.setFixedHeight(30)
        self.browse_btn.setMinimumWidth(86)
        self.browse_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.browse_btn.clicked.connect(self.browse_requested.emit)
        layout.addWidget(self.browse_btn)

        self.open_btn = QPushButton("Open Folder")
        self.open_btn.setObjectName("OutlinedActionBtn")
        self.open_btn.setFixedHeight(30)
        self.open_btn.setMinimumWidth(98)
        self.open_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.open_btn.setToolTip("Open Output Directory in File Explorer")
        self.open_btn.clicked.connect(self.open_requested.emit)
        layout.addWidget(self.open_btn)

        self.selection_lbl = QLabel("Select file types to enable Save")
        self.selection_lbl.setMinimumWidth(175)
        layout.addWidget(self.selection_lbl)

        self.save_btn = QPushButton("  Save")
        self.save_btn.setObjectName("PrimaryActionBtn")
        self.save_btn.setFixedHeight(32)
        self.save_btn.setMinimumWidth(108)
        self.save_btn.setIcon(QIcon(create_vector_icon("folder_header", 16, "#FFFFFF")))
        self.save_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.save_btn.setEnabled(False)
        self.save_btn.setToolTip("Check one or more file types above to activate Save")
        self.save_btn.clicked.connect(self.save_requested.emit)
        layout.addWidget(self.save_btn)

        self.apply_palette(LIGHT_PALETTE)

    def _on_text_changed(self, txt: str) -> None:
        self.path_edit.setToolTip(txt)
        self.directory_changed.emit(txt)

    def path(self) -> str:
        return self.path_edit.text().strip()

    def set_path(self, new_path: str) -> None:
        self.path_edit.setText(new_path)
        self.path_edit.setToolTip(new_path)

    def update_selection_state(
        self,
        selected_types_count: int,
        selected_files_count: int,
        selected_bytes: int,
    ) -> None:
        can_save = selected_types_count > 0 and selected_files_count > 0
        if can_save:
            self.selection_lbl.setText(
                f"{selected_types_count} type(s) · {selected_files_count:,} files ({format_file_size(selected_bytes)})"
            )
        elif selected_types_count > 0:
            self.selection_lbl.setText(f"{selected_types_count} type(s) checked (ready to scan/save)")
        else:
            self.selection_lbl.setText("Select file types to enable Save")
        self.save_btn.setEnabled(can_save)

    def apply_palette(self, palette: ThemePalette) -> None:
        self._palette = palette
        fg = "#38BDF8" if palette.is_dark else "#0570FA"
        self.icon_lbl.setPixmap(create_vector_icon("folder_header", 20, fg))
        self.title_lbl.setStyleSheet(
            f"font-size: 12.5px; font-weight: 700; color: {palette.text_primary}; background: transparent;"
        )
        self.selection_lbl.setStyleSheet(
            f"font-size: 11.5px; font-weight: 600; color: {palette.text_secondary}; background: transparent; padding: 0 4px;"
        )


OutputDirectoryCardWidget = OutputSaveBarWidget


class StatusGreenDotWidget(QWidget):
    """Small green status dot next to 'Ready' in the bottom status bar."""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._color = QColor("#10B981")
        self.setFixedSize(14, 14)

    def set_color(self, hex_color: str) -> None:
        self._color = QColor(hex_color)
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        halo = QColor(self._color)
        halo.setAlpha(55)
        p.setBrush(halo)
        p.drawEllipse(QRectF(1.0, 1.0, 12.0, 12.0))
        p.setBrush(self._color)
        p.drawEllipse(QRectF(3.0, 3.0, 8.0, 8.0))
        p.end()


class BottomStatusBar(QFrame):
    """Sleek Bottom Status Bar (`38px` height) with zero text cutoff."""

    stop_requested = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("BottomStatusBar")
        self.setFixedHeight(38)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 4, 12, 4)
        layout.setSpacing(10)

        self.dot_widget = StatusGreenDotWidget()
        layout.addWidget(self.dot_widget)

        self.status_lbl = QLabel("Ready")
        self.status_lbl.setMinimumWidth(185)
        layout.addWidget(self.status_lbl)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(7)
        layout.addWidget(self.progress_bar, stretch=1)

        self.pct_lbl = QLabel("0%")
        self.pct_lbl.setMinimumWidth(38)
        self.pct_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.pct_lbl)

        self.timer_lbl = QLabel("Elapsed: 00:00:00  |  Est: --:--:--")
        self.timer_lbl.setMinimumWidth(210)
        layout.addWidget(self.timer_lbl)

        self.stop_btn = QPushButton("■  Stop")
        self.stop_btn.setObjectName("StopScanBtn")
        self.stop_btn.setFixedHeight(26)
        self.stop_btn.setMinimumWidth(78)
        self.stop_btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_requested.emit)
        layout.addWidget(self.stop_btn)

        self.apply_palette(LIGHT_PALETTE)

    @staticmethod
    def _fmt_sec(sec: float) -> str:
        s = max(0, int(round(sec)))
        hh = s // 3600
        mm = (s % 3600) // 60
        ss = s % 60
        return f"{hh:02d}:{mm:02d}:{ss:02d}"

    def set_scanning_progress(
        self,
        percent: int,
        found_count: int,
        found_bytes: int,
        elapsed_sec: float,
        est_sec: float,
        active: bool = True,
    ) -> None:
        pct = max(0, min(100, percent))
        self.progress_bar.setValue(pct)
        self.pct_lbl.setText(f"{pct}%")
        self.stop_btn.setEnabled(active)
        if active:
            self.status_lbl.setText(f"Scanning... ({found_count:,} found, {format_file_size(found_bytes)})")
            est_str = self._fmt_sec(est_sec) if est_sec > 0 else "--:--:--"
            self.timer_lbl.setText(f"Elapsed: {self._fmt_sec(elapsed_sec)}  |  Est: {est_str}")
        else:
            self.status_lbl.setText("Ready")
            self.timer_lbl.setText("Elapsed: 00:00:00  |  Est: --:--:--")

    def apply_palette(self, palette: ThemePalette) -> None:
        self.status_lbl.setStyleSheet(
            f"font-size: 12.5px; font-weight: 700; color: {palette.text_primary}; background: transparent;"
        )
        self.pct_lbl.setStyleSheet(
            f"font-size: 12px; font-weight: 700; color: {palette.accent_blue_text}; background: transparent;"
        )
        self.timer_lbl.setStyleSheet(
            f"font-size: 11.5px; color: {palette.text_secondary}; background: transparent;"
        )
        track_bg = "#1D2A3F" if palette.is_dark else "#E2ECF7"
        self.progress_bar.setStyleSheet(
            f"QProgressBar {{ background-color: {track_bg}; border: none; border-radius: 3.5px; }}"
            f"QProgressBar::chunk {{ background-color: #0577FC; border-radius: 3.5px; }}"
        )
