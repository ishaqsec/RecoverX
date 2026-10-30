"""Clean Vector Icon Renderers, Gradient Ribbon Logo Loader, and Asset Manifest Loader for PySide6 UI."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, Optional

try:
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import (
        QColor,
        QIcon,
        QLinearGradient,
        QPainter,
        QPainterPath,
        QPen,
        QPixmap,
    )
except ImportError:
    QPixmap = Any  # type: ignore
    QIcon = Any  # type: ignore


ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"


def load_asset_manifest() -> Dict[str, Any]:
    manifest_path = ASSETS_DIR / "ASSET_MANIFEST.json"
    if manifest_path.exists():
        with open(manifest_path, "r", encoding="utf-8") as fp:
            return json.load(fp)
    return {"assets": []}


def create_recoverx_wordmark_pixmap(height: int = 38, is_dark: bool = False) -> "QPixmap":
    """
    Load the official RecoverX Gradient Ribbon + Wordmark logo (`RecoverX Gradient Ribbon Logo.png`)
    scaled smoothly to `height` for either Light Mode (`recoverx_wordmark_light.png`) or
    Dark Mode (`recoverx_wordmark_dark.png`).
    """
    fname = "recoverx_wordmark_dark.png" if is_dark else "recoverx_wordmark_light.png"
    logo_path = ASSETS_DIR / fname
    if logo_path.exists():
        src = QPixmap(str(logo_path))
        if not src.isNull():
            return src.scaledToHeight(height, Qt.TransformationMode.SmoothTransformation)
    return create_vector_icon("recoverx_logo", height)


def create_pakistan_flag_pixmap(width: int = 28, height: int = 19) -> "QPixmap":
    png_path = ASSETS_DIR / "pakistan_flag.png"
    if png_path.exists():
        src = QPixmap(str(png_path))
        if not src.isNull():
            return src.scaled(
                width,
                height,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )

    pix = QPixmap(width, height)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    w, h = float(width), float(height)
    p.fillRect(QRectF(0, 0, w * 0.25, h), QColor("#FFFFFF"))
    p.fillRect(QRectF(w * 0.25, 0, w * 0.75, h), QColor("#01411C"))
    p.end()
    return pix


def create_red_heart_pixmap(size: int = 18) -> "QPixmap":
    png_path = ASSETS_DIR / "red_heart.png"
    if png_path.exists():
        src = QPixmap(str(png_path))
        if not src.isNull():
            return src.scaled(
                size,
                size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    return pix


def create_vector_icon(
    kind: str,
    size: int = 24,
    color_hex: str = "#0570FA",
    bg_hex: Optional[str] = None,
) -> "QPixmap":
    """Render crisp, resolution-independent icons and load the gradient ribbon R emblem."""
    if kind == "recoverx_logo":
        ribbon_path = ASSETS_DIR / "recoverx_ribbon_icon.png"
        if ribbon_path.exists():
            src = QPixmap(str(ribbon_path))
            if not src.isNull():
                return src.scaled(
                    size,
                    size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
    if kind == "pakistan_flag":
        return create_pakistan_flag_pixmap(int(round(size * 1.45)), size)
    if kind == "red_heart":
        return create_red_heart_pixmap(size)

    pix = QPixmap(size, size)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    fg = QColor(color_hex)
    pen = QPen(
        fg,
        max(1.6, size * 0.08),
        Qt.PenStyle.SolidLine,
        Qt.PenCapStyle.RoundCap,
        Qt.PenJoinStyle.RoundJoin,
    )
    p.setPen(pen)

    if bg_hex:
        p.setBrush(QColor(bg_hex))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(1, 1, size - 2, size - 2), size * 0.25, size * 0.25)
        p.setPen(pen)

    s = float(size)

    if kind == "recoverx_logo":
        grad = QLinearGradient(0, 0, s, s)
        grad.setColorAt(0.0, QColor("#00D4FF"))
        grad.setColorAt(1.0, QColor("#0055FF"))
        p.setBrush(grad)
        p.setPen(Qt.PenStyle.NoPen)
        path = QPainterPath()
        path.addRoundedRect(QRectF(s * 0.08, s * 0.08, s * 0.84, s * 0.84), s * 0.22, s * 0.22)
        p.drawPath(path)

    elif kind == "home":
        path = QPainterPath()
        path.moveTo(s * 0.16, s * 0.48)
        path.lineTo(s * 0.50, s * 0.18)
        path.lineTo(s * 0.84, s * 0.48)
        p.drawPath(path)
        p.drawRoundedRect(QRectF(s * 0.26, s * 0.46, s * 0.48, s * 0.36), 2, 2)

    elif kind == "search":
        p.drawEllipse(QRectF(s * 0.18, s * 0.18, s * 0.46, s * 0.46))
        p.drawLine(QPointF(s * 0.58, s * 0.58), QPointF(s * 0.82, s * 0.82))

    elif kind == "preview":
        p.drawRoundedRect(QRectF(s * 0.14, s * 0.18, s * 0.72, s * 0.64), 3, 3)
        p.drawEllipse(QRectF(s * 0.26, s * 0.28, s * 0.13, s * 0.13))
        path = QPainterPath()
        path.moveTo(s * 0.20, s * 0.72)
        path.lineTo(s * 0.42, s * 0.50)
        path.lineTo(s * 0.58, s * 0.64)
        path.lineTo(s * 0.76, s * 0.46)
        p.drawPath(path)

    elif kind == "reports":
        p.drawRoundedRect(QRectF(s * 0.22, s * 0.14, s * 0.56, s * 0.72), 3, 3)
        p.drawLine(QPointF(s * 0.34, s * 0.36), QPointF(s * 0.66, s * 0.36))
        p.drawLine(QPointF(s * 0.34, s * 0.50), QPointF(s * 0.66, s * 0.50))
        p.drawLine(QPointF(s * 0.34, s * 0.64), QPointF(s * 0.54, s * 0.64))

    elif kind == "about":
        p.drawEllipse(QRectF(s * 0.16, s * 0.16, s * 0.68, s * 0.68))
        p.drawLine(QPointF(s * 0.50, s * 0.46), QPointF(s * 0.50, s * 0.68))
        p.drawEllipse(QRectF(s * 0.48, s * 0.31, s * 0.04, s * 0.04))

    elif kind == "drive_header":
        p.drawRoundedRect(QRectF(s * 0.14, s * 0.20, s * 0.72, s * 0.60), 5, 5)
        p.drawLine(QPointF(s * 0.16, s * 0.56), QPointF(s * 0.84, s * 0.56))
        p.drawEllipse(QRectF(s * 0.64, s * 0.64, s * 0.06, s * 0.06))
        p.drawLine(QPointF(s * 0.26, s * 0.67), QPointF(s * 0.46, s * 0.67))

    elif kind == "gear_header":
        cx, cy = s * 0.50, s * 0.50
        p.drawEllipse(QPointF(cx, cy), s * 0.15, s * 0.15)
        p.drawEllipse(QPointF(cx, cy), s * 0.30, s * 0.30)
        for deg in range(0, 360, 45):
            rad = math.radians(deg)
            p.drawLine(
                QPointF(cx + math.cos(rad) * s * 0.30, cy + math.sin(rad) * s * 0.30),
                QPointF(cx + math.cos(rad) * s * 0.40, cy + math.sin(rad) * s * 0.40),
            )

    elif kind == "folder_header":
        path = QPainterPath()
        path.moveTo(s * 0.12, s * 0.24)
        path.lineTo(s * 0.38, s * 0.24)
        path.lineTo(s * 0.46, s * 0.34)
        path.lineTo(s * 0.88, s * 0.34)
        path.lineTo(s * 0.88, s * 0.78)
        path.lineTo(s * 0.12, s * 0.78)
        path.closeSubpath()
        p.drawPath(path)

    elif kind == "refresh":
        p.drawArc(QRectF(s * 0.20, s * 0.20, s * 0.60, s * 0.60), 30 * 16, 290 * 16)
        p.drawLine(QPointF(s * 0.74, s * 0.22), QPointF(s * 0.82, s * 0.36))
        p.drawLine(QPointF(s * 0.66, s * 0.36), QPointF(s * 0.82, s * 0.36))

    elif kind == "shield":
        p.setBrush(QColor("#0570FA"))
        p.setPen(Qt.PenStyle.NoPen)
        path = QPainterPath()
        path.moveTo(s * 0.50, s * 0.08)
        path.lineTo(s * 0.86, s * 0.22)
        path.lineTo(s * 0.86, s * 0.52)
        path.quadTo(s * 0.86, s * 0.82, s * 0.50, s * 0.94)
        path.quadTo(s * 0.14, s * 0.82, s * 0.14, s * 0.52)
        path.lineTo(s * 0.14, s * 0.22)
        path.closeSubpath()
        p.drawPath(path)
        chk_pen = QPen(
            QColor("#FFFFFF"),
            max(2.0, s * 0.09),
            Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
            Qt.PenJoinStyle.RoundJoin,
        )
        p.setPen(chk_pen)
        p.drawLine(QPointF(s * 0.35, s * 0.52), QPointF(s * 0.46, s * 0.63))
        p.drawLine(QPointF(s * 0.46, s * 0.63), QPointF(s * 0.67, s * 0.40))

    elif kind == "bolt":
        p.setBrush(fg)
        p.setPen(Qt.PenStyle.NoPen)
        path = QPainterPath()
        path.moveTo(s * 0.56, s * 0.14)
        path.lineTo(s * 0.26, s * 0.54)
        path.lineTo(s * 0.48, s * 0.54)
        path.lineTo(s * 0.42, s * 0.86)
        path.lineTo(s * 0.74, s * 0.46)
        path.lineTo(s * 0.52, s * 0.46)
        path.closeSubpath()
        p.drawPath(path)

    elif kind == "scan_image":
        p.drawRoundedRect(QRectF(s * 0.22, s * 0.16, s * 0.56, s * 0.68), 4, 4)
        p.drawRoundedRect(QRectF(s * 0.30, s * 0.24, s * 0.40, s * 0.26), 2, 2)
        p.drawEllipse(QRectF(s * 0.34, s * 0.62, s * 0.08, s * 0.08))
        p.drawEllipse(QRectF(s * 0.58, s * 0.62, s * 0.08, s * 0.08))

    elif kind == "windows_drive":
        p.setBrush(QColor("#0078D4"))
        p.setPen(Qt.PenStyle.NoPen)
        gap = s * 0.05
        half = (s * 0.68 - gap) / 2.0
        x0, y0 = s * 0.16, s * 0.16
        p.drawRoundedRect(QRectF(x0, y0 + 2, half, half - 2), 2, 2)
        p.drawRoundedRect(QRectF(x0 + half + gap, y0, half, half), 2, 2)
        p.drawRoundedRect(QRectF(x0, y0 + half + gap, half, half - 2), 2, 2)
        p.drawRoundedRect(QRectF(x0 + half + gap, y0 + half + gap, half, half), 2, 2)

    elif kind == "hdd":
        p.setBrush(QColor("#64748B"))
        p.setPen(QPen(QColor("#475569"), 1.2))
        body = QPainterPath()
        body.moveTo(s * 0.22, s * 0.22)
        body.lineTo(s * 0.78, s * 0.22)
        body.lineTo(s * 0.86, s * 0.62)
        body.lineTo(s * 0.14, s * 0.62)
        body.closeSubpath()
        p.drawPath(body)
        p.setBrush(QColor("#1E293B"))
        p.drawRoundedRect(QRectF(s * 0.14, s * 0.56, s * 0.72, s * 0.22), 4, 4)
        p.setBrush(QColor("#38BDF8"))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QRectF(s * 0.68, s * 0.63, s * 0.08, s * 0.08))
        p.setBrush(QColor("#94A3B8"))
        p.drawEllipse(QRectF(s * 0.54, s * 0.64, s * 0.06, s * 0.06))

    elif kind == "usb":
        p.setBrush(QColor("#CBD5E1"))
        p.setPen(QPen(QColor("#64748B"), 1.3))
        p.drawRoundedRect(QRectF(s * 0.34, s * 0.12, s * 0.32, s * 0.22), 2, 2)
        p.setBrush(QColor("#475569"))
        p.drawRect(QRectF(s * 0.39, s * 0.17, s * 0.06, s * 0.07))
        p.drawRect(QRectF(s * 0.55, s * 0.17, s * 0.06, s * 0.07))
        p.setBrush(QColor("#64748B"))
        p.drawRoundedRect(QRectF(s * 0.25, s * 0.32, s * 0.50, s * 0.54), 7, 7)
        p.setPen(QPen(QColor("#1E293B"), 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(s * 0.50, s * 0.47), QPointF(s * 0.50, s * 0.59))
        p.drawLine(QPointF(s * 0.44, s * 0.53), QPointF(s * 0.56, s * 0.53))
        p.drawLine(QPointF(s * 0.36, s * 0.72), QPointF(s * 0.64, s * 0.72))

    elif kind == "folder" or kind == "cat_all":
        p.setBrush(QColor("#38BDF8"))
        p.setPen(Qt.PenStyle.NoPen)
        path = QPainterPath()
        path.moveTo(s * 0.10, s * 0.24)
        path.lineTo(s * 0.40, s * 0.24)
        path.lineTo(s * 0.48, s * 0.34)
        path.lineTo(s * 0.90, s * 0.34)
        path.lineTo(s * 0.90, s * 0.80)
        path.lineTo(s * 0.10, s * 0.80)
        path.closeSubpath()
        p.drawPath(path)

    elif kind == "cat_images":
        p.setBrush(QColor("#0EA5E9"))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(s * 0.12, s * 0.14, s * 0.76, s * 0.72), 4, 4)
        p.setBrush(QColor("#FFFFFF"))
        p.drawEllipse(QRectF(s * 0.24, s * 0.26, s * 0.14, s * 0.14))
        m_path = QPainterPath()
        m_path.moveTo(s * 0.18, s * 0.74)
        m_path.lineTo(s * 0.42, s * 0.46)
        m_path.lineTo(s * 0.58, s * 0.62)
        m_path.lineTo(s * 0.70, s * 0.50)
        m_path.lineTo(s * 0.82, s * 0.74)
        m_path.closeSubpath()
        p.drawPath(m_path)

    elif kind == "cat_videos":
        p.setBrush(QColor("#EF4444"))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(s * 0.14, s * 0.12, s * 0.72, s * 0.76), 4, 4)
        p.setBrush(QColor("#FFFFFF"))
        tri = QPainterPath()
        tri.moveTo(s * 0.38, s * 0.32)
        tri.lineTo(s * 0.68, s * 0.50)
        tri.lineTo(s * 0.38, s * 0.68)
        tri.closeSubpath()
        p.drawPath(tri)

    elif kind == "cat_documents":
        p.setBrush(QColor("#6366F1"))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(s * 0.16, s * 0.10, s * 0.68, s * 0.80), 4, 4)
        p.setPen(QPen(QColor("#FFFFFF"), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(s * 0.30, s * 0.36), QPointF(s * 0.70, s * 0.36))
        p.drawLine(QPointF(s * 0.30, s * 0.52), QPointF(s * 0.70, s * 0.52))
        p.drawLine(QPointF(s * 0.30, s * 0.68), QPointF(s * 0.54, s * 0.68))

    elif kind == "cat_audio":
        p.setPen(
            QPen(
                QColor("#EC4899"),
                max(2.0, s * 0.10),
                Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap,
                Qt.PenJoinStyle.RoundJoin,
            )
        )
        p.setBrush(QColor("#EC4899"))
        p.drawLine(QPointF(s * 0.40, s * 0.70), QPointF(s * 0.40, s * 0.24))
        p.drawLine(QPointF(s * 0.76, s * 0.64), QPointF(s * 0.76, s * 0.18))
        p.drawLine(QPointF(s * 0.40, s * 0.24), QPointF(s * 0.76, s * 0.18))
        p.drawEllipse(QRectF(s * 0.20, s * 0.60, s * 0.22, s * 0.18))
        p.drawEllipse(QRectF(s * 0.56, s * 0.54, s * 0.22, s * 0.18))

    elif kind == "cat_archives":
        p.setBrush(QColor("#F59E0B"))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(s * 0.14, s * 0.14, s * 0.72, s * 0.72), 4, 4)
        p.setPen(QPen(QColor("#FFFFFF"), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(s * 0.50, s * 0.26), QPointF(s * 0.50, s * 0.66))
        p.drawLine(QPointF(s * 0.36, s * 0.52), QPointF(s * 0.50, s * 0.66))
        p.drawLine(QPointF(s * 0.64, s * 0.52), QPointF(s * 0.50, s * 0.66))

    elif kind == "cat_other":
        p.setBrush(QColor("#F59E0B"))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(s * 0.16, s * 0.12, s * 0.68, s * 0.76), 4, 4)
        p.setPen(QPen(QColor("#FFFFFF"), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QPointF(s * 0.30, s * 0.40), QPointF(s * 0.70, s * 0.40))
        p.drawLine(QPointF(s * 0.30, s * 0.58), QPointF(s * 0.60, s * 0.58))

    elif kind == "pdf_badge":
        p.setBrush(QColor("#EF4444"))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(s * 0.16, s * 0.10, s * 0.68, s * 0.80), 4, 4)
        p.setPen(QPen(QColor("#FFFFFF"), 1.5))
        p.drawLine(QPointF(s * 0.30, s * 0.38), QPointF(s * 0.70, s * 0.38))
        p.drawLine(QPointF(s * 0.30, s * 0.54), QPointF(s * 0.70, s * 0.54))
        p.drawLine(QPointF(s * 0.30, s * 0.70), QPointF(s * 0.54, s * 0.70))

    elif kind == "txt_badge":
        p.setBrush(QColor("#64748B"))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(s * 0.16, s * 0.10, s * 0.68, s * 0.80), 4, 4)
        p.setPen(QPen(QColor("#FFFFFF"), 1.5))
        p.drawLine(QPointF(s * 0.30, s * 0.38), QPointF(s * 0.70, s * 0.38))
        p.drawLine(QPointF(s * 0.30, s * 0.54), QPointF(s * 0.70, s * 0.54))
        p.drawLine(QPointF(s * 0.30, s * 0.70), QPointF(s * 0.54, s * 0.70))

    elif kind == "file_badge":
        p.setBrush(fg)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QRectF(s * 0.16, s * 0.10, s * 0.68, s * 0.80), 4, 4)
        p.setPen(QPen(QColor("#FFFFFF"), 1.5))
        p.drawLine(QPointF(s * 0.30, s * 0.38), QPointF(s * 0.70, s * 0.38))
        p.drawLine(QPointF(s * 0.30, s * 0.54), QPointF(s * 0.70, s * 0.54))
        p.drawLine(QPointF(s * 0.30, s * 0.70), QPointF(s * 0.56, s * 0.70))

    p.end()
    return pix


def icon_kind_for_entry(extension: str, category_val: str) -> str:
    ext = extension.upper().lstrip(".")
    if ext == "PDF":
        return "pdf_badge"
    if ext in ("TXT", "LOG", "MD", "CSV"):
        return "txt_badge"
    mapping = {
        "Images": "cat_images",
        "Videos": "cat_videos",
        "Documents": "cat_documents",
        "Audio": "cat_audio",
        "Archives": "cat_archives",
        "Other Files": "cat_other",
    }
    return mapping.get(category_val, "file_badge")
