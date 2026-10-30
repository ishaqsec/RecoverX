"""Safe Visual File Preview Handler (Images, PDF First-Page, and Video Frame/Container Previews)."""
from __future__ import annotations

import io
import os
import struct
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional, Tuple

from PIL import Image, ImageDraw

from devices.reader import ReadOnlyDeviceReader
from filesystems.base import RecoveredFileEntry
from recovery.engine import read_adb_file_bytes


class PreviewKind(str, Enum):
    IMAGE = "image"
    VIDEO = "video"
    TEXT = "text"
    PDF = "pdf"
    ARCHIVE = "archive"
    HEX = "hex"


@dataclass
class PreviewData:
    kind: PreviewKind
    title: str
    subtitle: str
    image_png_bytes: Optional[bytes] = None
    text_content: str = ""
    hex_dump: str = ""
    page_count: int = 0
    dimensions: str = ""
    is_safe: bool = True


def _extract_embedded_jpeg_or_png(raw: bytes) -> Optional[Image.Image]:
    """Scan container bytes (e.g., MP4/MOV covr/mdat or MKV attachment) for an embedded JPEG or PNG frame."""
    # 1. Check for embedded JPEG frame (\xff\xd8\xff ... \xff\xd9)
    start = raw.find(b"\xff\xd8\xff")
    while start != -1 and start < len(raw) - 128:
        end = raw.find(b"\xff\xd9", start + 4)
        if end != -1 and (end + 2 - start) <= 4 * 1024 * 1024:
            candidate = raw[start : end + 2]
            try:
                with Image.open(io.BytesIO(candidate)) as im:
                    if im.width >= 32 and im.height >= 32:
                        return im.convert("RGBA").copy()
            except Exception:
                pass
        start = raw.find(b"\xff\xd8\xff", start + 4)

    # 2. Check for embedded PNG frame
    png_sig = b"\x89PNG\r\n\x1a\n"
    p_start = raw.find(png_sig)
    if p_start != -1:
        p_end = raw.find(b"IEND\xaeB`\x82", p_start + 8)
        if p_end != -1:
            candidate = raw[p_start : p_end + 8]
            try:
                with Image.open(io.BytesIO(candidate)) as im:
                    if im.width >= 32 and im.height >= 32:
                        return im.convert("RGBA").copy()
            except Exception:
                pass
    return None


def _parse_mp4_metadata(raw: bytes) -> Tuple[str, str]:
    """Extract ISO BMFF / QuickTime brand and tkhd video dimensions if present."""
    brand = "ISO Media"
    dims = ""
    if len(raw) >= 12 and raw[4:8] == b"ftyp":
        b_raw = raw[8:12].decode("ascii", errors="ignore").strip()
        if b_raw:
            brand = f"ISO/{b_raw.upper()}"

    tkhd_pos = raw.find(b"tkhd")
    while tkhd_pos != -1 and tkhd_pos + 84 <= len(raw):
        version = raw[tkhd_pos + 4]
        w_off = tkhd_pos + (88 if version == 1 else 76)
        if w_off + 8 <= len(raw):
            w_fixed, h_fixed = struct.unpack_from(">II", raw, w_off)
            w_px = w_fixed >> 16
            h_px = h_fixed >> 16
            if 64 <= w_px <= 7680 and 64 <= h_px <= 4320:
                dims = f"{w_px}×{h_px}"
                break
        tkhd_pos = raw.find(b"tkhd", tkhd_pos + 4)

    return brand, dims


def _render_video_preview_png(
    entry: RecoveredFileEntry,
    raw: bytes,
) -> Tuple[bytes, str]:
    """Render a visual video frame/thumbnail preview card (with embedded frame if available)."""
    ext = entry.extension.upper().lstrip(".")
    brand, dims = _parse_mp4_metadata(raw)
    embedded_frame = _extract_embedded_jpeg_or_png(raw)

    width, height = 520, 320
    canvas = Image.new("RGBA", (width, height), (14, 22, 36, 255))
    draw = ImageDraw.Draw(canvas)

    # Subtle gradient backdrop
    for y in range(height):
        r = int(14 + (y / height) * 12)
        g = int(24 + (y / height) * 22)
        b = int(42 + (y / height) * 38)
        draw.line([(0, y), (width, y)], fill=(r, g, b, 255))

    if embedded_frame is not None:
        ew, eh = embedded_frame.size
        if not dims:
            dims = f"{ew}×{eh}"
        thumb = embedded_frame.copy()
        thumb.thumbnail((width - 56, height - 64))
        tx = (width - thumb.width) // 2
        ty = (height - 36 - thumb.height) // 2 + 8
        canvas.paste(thumb, (tx, ty), thumb)
    else:
        # Draw sleek cinema screen frame
        screen_rect = (38, 22, width - 38, height - 54)
        draw.rounded_rectangle(screen_rect, radius=12, fill=(20, 34, 58, 255), outline=(56, 189, 248, 120), width=2)

    # Top and bottom filmstrip perforations along left/right rails
    for rail_x in (12, width - 24):
        for hole_y in range(20, height - 52, 26):
            draw.rounded_rectangle(
                (rail_x, hole_y, rail_x + 12, hole_y + 14),
                radius=3,
                fill=(56, 189, 248, 65),
                outline=(56, 189, 248, 110),
            )

    # Center translucent play circle + triangle
    cx, cy = width // 2, (height - 32) // 2
    r_play = 32
    draw.ellipse(
        (cx - r_play, cy - r_play, cx + r_play, cy + r_play),
        fill=(5, 112, 250, 215),
        outline=(255, 255, 255, 230),
        width=2,
    )
    draw.polygon(
        [(cx - 9, cy - 14), (cx - 9, cy + 14), (cx + 15, cy)],
        fill=(255, 255, 255, 255),
    )

    # Bottom metadata scrub bar
    bar_top = height - 42
    draw.rectangle((0, bar_top, width, height), fill=(10, 17, 28, 235))
    draw.rounded_rectangle((16, bar_top + 10, width - 16, bar_top + 15), radius=2, fill=(36, 54, 82, 255))
    draw.rounded_rectangle((16, bar_top + 10, int(width * 0.42), bar_top + 15), radius=2, fill=(14, 165, 233, 255))

    meta_parts = [f"{ext} Video", brand]
    if dims:
        meta_parts.append(dims)
    meta_parts.append(entry.size_Formatted)
    subtitle_str = " · ".join(meta_parts)

    out_buf = io.BytesIO()
    canvas.save(out_buf, format="PNG")
    return out_buf.getvalue(), subtitle_str


class PreviewHandler:
    """
    Safely parses recovered bytes in-memory for visual preview without executing active content.
    """

    MAX_PREVIEW_BYTES = 8 * 1024 * 1024  # 8 MB cap for safe in-memory preview

    @classmethod
    def extract_entry_preview_bytes(
        cls,
        entry: RecoveredFileEntry,
        reader: Optional[ReadOnlyDeviceReader] = None,
        device: Optional[Any] = None,
    ) -> bytes:
        if reader is not None and (entry.resident_data is not None or entry.data_runs):
            return entry.extract_bytes(reader, max_bytes=cls.MAX_PREVIEW_BYTES)

        if entry.resident_data is not None:
            return entry.resident_data[: cls.MAX_PREVIEW_BYTES]

        if entry.data_runs:
            dev_path = entry.source_device_path or (device.path if device else "")
            if device is not None:
                try:
                    with ReadOnlyDeviceReader(device, confirm_physical_access=True) as tmp_r:
                        return entry.extract_bytes(tmp_r, max_bytes=cls.MAX_PREVIEW_BYTES)
                except Exception:
                    pass
            if dev_path and os.path.isfile(dev_path):
                try:
                    from devices.discovery import DeviceInfo, DeviceType
                    fallback_dev = DeviceInfo(
                        id="preview:img",
                        name=os.path.basename(dev_path),
                        path=dev_path,
                        device_type=DeviceType.DISK_IMAGE,
                    )
                    with ReadOnlyDeviceReader(fallback_dev, confirm_physical_access=True) as tmp_r:
                        return entry.extract_bytes(tmp_r, max_bytes=cls.MAX_PREVIEW_BYTES)
                except Exception:
                    pass

        if entry.source_device_path and entry.source_device_path.startswith("adb://"):
            return read_adb_file_bytes(entry.source_device_path, max_bytes=cls.MAX_PREVIEW_BYTES)

        if entry.source_device_path and os.path.isfile(entry.source_device_path):
            try:
                with open(entry.source_device_path, "rb") as fp:
                    return fp.read(min(cls.MAX_PREVIEW_BYTES, max(1, entry.size_bytes or cls.MAX_PREVIEW_BYTES)))
            except OSError:
                pass

        return b""

    @classmethod
    def generate_preview(
        cls,
        entry: RecoveredFileEntry,
        reader: Optional[ReadOnlyDeviceReader] = None,
        device: Optional[Any] = None,
    ) -> PreviewData:
        raw = cls.extract_entry_preview_bytes(entry, reader=reader, device=device)
        ext = entry.extension.upper().lstrip(".")

        if not raw:
            return PreviewData(
                kind=PreviewKind.HEX,
                title=entry.name,
                subtitle=f"{entry.category.value} ({ext}) — {entry.size_Formatted}",
            )

        # 1. Image formats
        if ext in ("JPG", "JPEG", "PNG", "GIF", "BMP", "TIFF", "TIF", "WEBP"):
            try:
                with Image.open(io.BytesIO(raw)) as img:
                    w, h = img.size
                    mode = img.mode
                    preview_img = img.convert("RGBA")
                    preview_img.thumbnail((720, 480))
                    out_buf = io.BytesIO()
                    preview_img.save(out_buf, format="PNG")
                    return PreviewData(
                        kind=PreviewKind.IMAGE,
                        title=entry.name,
                        subtitle=f"{ext} Image ({w}×{h}, {mode}) — {entry.size_Formatted}",
                        image_png_bytes=out_buf.getvalue(),
                        dimensions=f"{w}x{h}",
                    )
            except Exception as exc:
                return PreviewData(
                    kind=PreviewKind.HEX,
                    title=entry.name,
                    subtitle=f"Partial {ext} Image ({exc})",
                )

        # 2. Video formats (First-Frame / Embedded Cover Extraction + Cinema Preview Card)
        if ext in ("MP4", "MOV", "AVI", "MKV", "WEBM", "3GP") or (len(raw) >= 12 and raw[4:8] == b"ftyp"):
            try:
                vid_png, vid_sub = _render_video_preview_png(entry, raw)
                return PreviewData(
                    kind=PreviewKind.VIDEO,
                    title=entry.name,
                    subtitle=vid_sub,
                    image_png_bytes=vid_png,
                )
            except Exception:
                pass

        # 3. PDF visual page preview
        if ext == "PDF" or raw.startswith(b"%PDF-"):
            pdf_png: Optional[bytes] = None
            pages = 0
            try:
                import pypdfium2 as pdfium
                doc = pdfium.PdfDocument(raw)
                pages = len(doc)
                if pages > 0:
                    page = doc[0]
                    pil_image = page.render(scale=1.2).to_pil()
                    out_buf = io.BytesIO()
                    pil_image.save(out_buf, format="PNG")
                    pdf_png = out_buf.getvalue()
                doc.close()
            except Exception:
                pass

            if not pages:
                try:
                    import pypdf
                    pdf_reader = pypdf.PdfReader(io.BytesIO(raw))
                    pages = len(pdf_reader.pages)
                except Exception:
                    pass

            return PreviewData(
                kind=PreviewKind.PDF,
                title=entry.name,
                subtitle=f"PDF Document ({pages or 1} page{'s' if pages != 1 else ''}) — {entry.size_Formatted}",
                image_png_bytes=pdf_png,
                page_count=pages or 1,
            )

        # 4. Other formats (Visual card + metadata summary only, no text preview dump)
        return PreviewData(
            kind=PreviewKind.ARCHIVE if ext in ("DOCX", "XLSX", "PPTX", "ZIP") else PreviewKind.HEX,
            title=entry.name,
            subtitle=f"{entry.category.value} · {ext} ({entry.size_Formatted})",
        )
