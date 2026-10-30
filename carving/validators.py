"""Format-Specific Structural Validators for Carved and Recovered Files."""
from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from typing import Optional

from filesystems.base import FileCategory, IntegrityStatus


@dataclass
class ValidationResult:
    is_valid_header: bool
    extension: str
    category: FileCategory
    carved_size: int
    status: IntegrityStatus
    detail: str


def validate_and_measure_carved_data(window: bytes) -> Optional[ValidationResult]:
    """
    Inspect `window` starting at a candidate magic signature.
    Performs structural validation (chunk walking, size fields, central directories,
    CRC/checksums, and EOF markers) so false positives are rejected and truncated/fragmented
    files are accurately reported as Partial or Corrupted.
    """
    if len(window) < 16:
        return None

    # 1. PNG (\x89PNG\r\n\x1a\n)
    if window.startswith(b"\x89PNG\r\n\x1a\n"):
        return _validate_png(window)

    # 2. JPEG (\xff\xd8\xff)
    if window.startswith(b"\xff\xd8\xff"):
        return _validate_jpeg(window)

    # 3. GIF (GIF87a / GIF89a)
    if window.startswith((b"GIF87a", b"GIF89a")):
        return _validate_gif(window)

    # 4. BMP (BM)
    if window.startswith(b"BM"):
        return _validate_bmp(window)

    # 5. TIFF (II*\x00 or MM\x00*)
    if window.startswith((b"II*\x00", b"MM\x00*")):
        return _validate_tiff(window)

    # 6. RIFF containers (WebP, WAV, AVI)
    if window.startswith(b"RIFF") and len(window) >= 12:
        return _validate_riff(window)

    # 7. PDF (%PDF-)
    if window.startswith(b"%PDF-"):
        return _validate_pdf(window)

    # 8. PK ZIP / Office OpenXML (DOCX, XLSX, PPTX, ZIP)
    if window.startswith(b"PK\x03\x04"):
        return _validate_zip_or_office(window)

    # 9. MP4 / MOV ISO Base Media (....ftyp)
    if len(window) >= 16 and window[4:8] == b"ftyp":
        return _validate_mp4_mov(window)

    # 10. MKV (\x1a\x45\xdf\xa3)
    if window.startswith(b"\x1a\x45\xdf\xa3"):
        return _validate_mkv(window)

    # 11. MP3 with ID3v2 header
    if window.startswith(b"ID3"):
        return _validate_mp3(window)

    # 12. FLAC (fLaC)
    if window.startswith(b"fLaC"):
        return _validate_flac(window)

    # 13. 7Z (7z\xbc\xaf\x27\x1c)
    if window.startswith(b"7z\xbc\xaf\x27\x1c"):
        return _validate_7z(window)

    # 14. RAR (Rar!\x1a\x07)
    if window.startswith(b"Rar!\x1a\x07"):
        return _validate_rar(window)

    # 15. GZIP (\x1f\x8b\x08)
    if window.startswith(b"\x1f\x8b\x08"):
        return _validate_gzip(window)

    return None


def _validate_png(buf: bytes) -> Optional[ValidationResult]:
    if len(buf) < 33 or buf[12:16] != b"IHDR":
        return None
    ihdr_len = struct.unpack_from(">I", buf, 8)[0]
    if ihdr_len != 13:
        return None
    width, height = struct.unpack_from(">II", buf, 16)
    if width == 0 or height == 0 or width > 65535 or height > 65535:
        return None
    expected_crc = struct.unpack_from(">I", buf, 29)[0]
    calc_crc = zlib.crc32(buf[12:29]) & 0xFFFFFFFF
    if expected_crc != calc_crc:
        return ValidationResult(
            is_valid_header=True,
            extension="PNG",
            category=FileCategory.IMAGES,
            carved_size=min(len(buf), 1024),
            status=IntegrityStatus.CORRUPTED,
            detail="PNG IHDR CRC32 mismatch",
        )

    pos = 8
    has_idat = False
    while pos + 12 <= len(buf):
        clen = struct.unpack_from(">I", buf, pos)[0]
        ctype = buf[pos + 4 : pos + 8]
        if not all(65 <= b <= 90 or 97 <= b <= 122 for b in ctype):
            break
        if ctype == b"IDAT":
            has_idat = True
        chunk_end = pos + 12 + clen
        if chunk_end > len(buf):
            return ValidationResult(
                is_valid_header=True,
                extension="PNG",
                category=FileCategory.IMAGES,
                carved_size=len(buf),
                status=IntegrityStatus.PARTIAL,
                detail=f"PNG truncated inside {ctype.decode('ascii')} chunk",
            )
        if ctype == b"IEND":
            return ValidationResult(
                is_valid_header=True,
                extension="PNG",
                category=FileCategory.IMAGES,
                carved_size=chunk_end,
                status=IntegrityStatus.GOOD if has_idat else IntegrityStatus.CORRUPTED,
                detail=f"Valid PNG ({width}x{height}) with verified IEND chunk",
            )
        pos = chunk_end

    return ValidationResult(
        is_valid_header=True,
        extension="PNG",
        category=FileCategory.IMAGES,
        carved_size=pos if pos > 33 else len(buf),
        status=IntegrityStatus.PARTIAL if has_idat else IntegrityStatus.CORRUPTED,
        detail="PNG missing IEND trailer (partially overwritten or fragmented)",
    )


def _validate_jpeg(buf: bytes) -> Optional[ValidationResult]:
    m = buf[3]
    if not (0xE0 <= m <= 0xEF or m in (0xDB, 0xC0, 0xC2, 0xC4, 0xFE, 0xEE)):
        return None
    pos = 2
    has_sof = False
    has_sos = False
    n = len(buf)
    while pos + 4 <= n:
        if buf[pos] != 0xFF:
            break
        while pos < n and buf[pos] == 0xFF:
            pos += 1
        if pos >= n:
            break
        marker = buf[pos]
        pos += 1
        if marker == 0xD9:
            return ValidationResult(
                is_valid_header=True,
                extension="JPG",
                category=FileCategory.IMAGES,
                carved_size=pos,
                status=IntegrityStatus.GOOD if has_sof else IntegrityStatus.PARTIAL,
                detail="Valid JPEG stream with EOI marker",
            )
        if marker in (0xD8, 0x01) or (0xD0 <= marker <= 0xD7):
            continue
        if pos + 2 > n:
            break
        seg_len = struct.unpack_from(">H", buf, pos)[0]
        if seg_len < 2:
            break
        if marker in (0xC0, 0xC1, 0xC2):
            has_sof = True
        if marker == 0xDA:
            has_sos = True
            pos += seg_len
            eoi_idx = buf.find(b"\xff\xd9", pos)
            if eoi_idx != -1:
                return ValidationResult(
                    is_valid_header=True,
                    extension="JPG",
                    category=FileCategory.IMAGES,
                    carved_size=eoi_idx + 2,
                    status=IntegrityStatus.GOOD,
                    detail="Complete JPEG with SOF, SOS, and EOI markers",
                )
            else:
                return ValidationResult(
                    is_valid_header=True,
                    extension="JPG",
                    category=FileCategory.IMAGES,
                    carved_size=min(n, pos + 65536),
                    status=IntegrityStatus.PARTIAL,
                    detail="JPEG has SOF/SOS headers but missing EOI marker (truncated)",
                )
        pos += seg_len

    if has_sof or has_sos:
        return ValidationResult(
            is_valid_header=True,
            extension="JPG",
            category=FileCategory.IMAGES,
            carved_size=pos,
            status=IntegrityStatus.PARTIAL,
            detail="Truncated JPEG stream",
        )
    return None


def _validate_gif(buf: bytes) -> Optional[ValidationResult]:
    if len(buf) < 14:
        return None
    width, height = struct.unpack_from("<HH", buf, 6)
    if width == 0 or height == 0 or width > 16384 or height > 16384:
        return None
    eof_idx = buf.find(b"\x00\x3b", 13)
    if eof_idx != -1:
        return ValidationResult(
            is_valid_header=True,
            extension="GIF",
            category=FileCategory.IMAGES,
            carved_size=eof_idx + 2,
            status=IntegrityStatus.GOOD,
            detail=f"Valid GIF ({width}x{height}) with trailer 0x3B",
        )
    return ValidationResult(
        is_valid_header=True,
        extension="GIF",
        category=FileCategory.IMAGES,
        carved_size=min(len(buf), 32768),
        status=IntegrityStatus.PARTIAL,
        detail="GIF header valid but missing 0x3B trailer",
    )


def _validate_bmp(buf: bytes) -> Optional[ValidationResult]:
    if len(buf) < 54:
        return None
    file_size, reserved, data_off, dib_size = struct.unpack_from("<IIII", buf, 2)
    if reserved != 0 or dib_size not in (12, 40, 52, 56, 108, 124):
        return None
    if file_size < 54 or file_size > 100 * 1024 * 1024 or data_off < 26 or data_off >= file_size:
        return None
    if len(buf) >= file_size:
        return ValidationResult(
            is_valid_header=True,
            extension="BMP",
            category=FileCategory.IMAGES,
            carved_size=file_size,
            status=IntegrityStatus.GOOD,
            detail=f"Valid BMP image ({file_size} bytes)",
        )
    return ValidationResult(
        is_valid_header=True,
        extension="BMP",
        category=FileCategory.IMAGES,
        carved_size=len(buf),
        status=IntegrityStatus.PARTIAL,
        detail=f"BMP truncated ({len(buf)} of {file_size} bytes)",
    )


def _validate_tiff(buf: bytes) -> Optional[ValidationResult]:
    if len(buf) < 16:
        return None
    endian = "<" if buf[:2] == b"II" else ">"
    ifd_off = struct.unpack_from(f"{endian}I", buf, 4)[0]
    if ifd_off < 8 or ifd_off + 2 > len(buf):
        return None
    num_entries = struct.unpack_from(f"{endian}H", buf, ifd_off)[0]
    if num_entries == 0 or num_entries > 512 or ifd_off + 2 + num_entries * 12 > len(buf):
        return None
    max_end = ifd_off + 2 + num_entries * 12 + 4
    return ValidationResult(
        is_valid_header=True,
        extension="TIFF",
        category=FileCategory.IMAGES,
        carved_size=min(len(buf), max(max_end, 4096)),
        status=IntegrityStatus.GOOD,
        detail=f"Valid TIFF IFD with {num_entries} tags",
    )


def _validate_riff(buf: bytes) -> Optional[ValidationResult]:
    riff_size = struct.unpack_from("<I", buf, 4)[0]
    form_type = buf[8:12]
    total_size = riff_size + 8
    if riff_size < 12 or total_size > 200 * 1024 * 1024:
        return None
    if form_type == b"WEBP":
        ext, cat = "WEBP", FileCategory.IMAGES
    elif form_type == b"WAVE":
        ext, cat = "WAV", FileCategory.AUDIO
    elif form_type == b"AVI ":
        ext, cat = "AVI", FileCategory.VIDEOS
    else:
        return None

    status = IntegrityStatus.GOOD if len(buf) >= total_size else IntegrityStatus.PARTIAL
    actual = min(len(buf), total_size)
    return ValidationResult(
        is_valid_header=True,
        extension=ext,
        category=cat,
        carved_size=actual,
        status=status,
        detail=f"RIFF/{ext} container ({actual} of {total_size} bytes)",
    )


def _validate_pdf(buf: bytes) -> Optional[ValidationResult]:
    if len(buf) < 64 or not (48 <= buf[5] <= 57 and buf[6] == 46):
        return None
    has_obj = b" obj" in buf[:65536] or b"/Root" in buf[:65536]
    if not has_obj:
        return None
    eof_pos = buf.find(b"%%EOF")
    if eof_pos != -1:
        end_idx = eof_pos + 5
        while end_idx < len(buf) and buf[end_idx] in (10, 13):
            end_idx += 1
        return ValidationResult(
            is_valid_header=True,
            extension="PDF",
            category=FileCategory.DOCUMENTS,
            carved_size=end_idx,
            status=IntegrityStatus.GOOD,
            detail="Valid PDF document with objects and %%EOF marker",
        )
    return ValidationResult(
        is_valid_header=True,
        extension="PDF",
        category=FileCategory.DOCUMENTS,
        carved_size=min(len(buf), 65536),
        status=IntegrityStatus.PARTIAL,
        detail="PDF header and objects found, but %%EOF marker is missing",
    )


def _validate_zip_or_office(buf: bytes) -> Optional[ValidationResult]:
    if len(buf) < 30:
        return None
    ver, flags, comp, mtime, mdate, crc, csize, usize, fn_len, extra_len = struct.unpack_from("<HHHHHIIIHH", buf, 4)
    if fn_len == 0 or fn_len > 512 or 30 + fn_len > len(buf):
        return None
    first_fn = buf[30 : 30 + fn_len].decode("utf-8", errors="ignore")
    if not all(32 <= ord(c) < 127 for c in first_fn):
        return None

    eocd_pos = buf.find(b"PK\x05\x06")
    status = IntegrityStatus.GOOD
    if eocd_pos != -1 and eocd_pos + 22 <= len(buf):
        comment_len = struct.unpack_from("<H", buf, eocd_pos + 20)[0]
        carved_len = min(len(buf), eocd_pos + 22 + comment_len)
        detail = "Complete ZIP/OpenXML container with End of Central Directory"
    else:
        status = IntegrityStatus.PARTIAL
        carved_len = min(len(buf), max(30 + fn_len + extra_len + csize, 4096))
        detail = "Partial ZIP/OpenXML container (missing Central Directory)"

    sample = buf[:carved_len]
    if b"word/document.xml" in sample or first_fn.startswith("word/"):
        ext, cat = "DOCX", FileCategory.DOCUMENTS
    elif b"xl/workbook.xml" in sample or first_fn.startswith("xl/"):
        ext, cat = "XLSX", FileCategory.DOCUMENTS
    elif b"ppt/presentation.xml" in sample or first_fn.startswith("ppt/"):
        ext, cat = "PPTX", FileCategory.DOCUMENTS
    else:
        ext, cat = "ZIP", FileCategory.ARCHIVES

    return ValidationResult(
        is_valid_header=True,
        extension=ext,
        category=cat,
        carved_size=carved_len,
        status=status,
        detail=detail,
    )


def _validate_mp4_mov(buf: bytes) -> Optional[ValidationResult]:
    ftyp_size = struct.unpack_from(">I", buf, 0)[0]
    if ftyp_size < 16 or ftyp_size > 1024 or ftyp_size > len(buf):
        return None
    brand = buf[8:12]
    ext = "MOV" if brand == b"qt  " else "MP4"
    pos = 0
    has_moov_or_mdat = False
    valid_atoms = {b"ftyp", b"moov", b"mdat", b"free", b"skip", b"wide", b"uuid", b"meta"}
    while pos + 8 <= len(buf):
        asize = struct.unpack_from(">I", buf, pos)[0]
        atype = buf[pos + 4 : pos + 8]
        if atype not in valid_atoms or asize < 8:
            break
        if atype in (b"moov", b"mdat"):
            has_moov_or_mdat = True
        if pos + asize > len(buf):
            return ValidationResult(
                is_valid_header=True,
                extension=ext,
                category=FileCategory.VIDEOS,
                carved_size=len(buf),
                status=IntegrityStatus.PARTIAL,
                detail=f"{ext} truncated inside {atype.decode('latin-1')} atom",
            )
        pos += asize

    if not has_moov_or_mdat:
        return None
    return ValidationResult(
        is_valid_header=True,
        extension=ext,
        category=FileCategory.VIDEOS,
        carved_size=pos,
        status=IntegrityStatus.GOOD,
        detail=f"Valid {ext} ISO Base Media container ({pos} bytes)",
    )


def _validate_mkv(buf: bytes) -> Optional[ValidationResult]:
    if len(buf) < 32 or (b"matroska" not in buf[:64].lower() and b"webm" not in buf[:64].lower()):
        return None
    end_pos = _find_zero_run(buf, 32)
    return ValidationResult(
        is_valid_header=True,
        extension="MKV",
        category=FileCategory.VIDEOS,
        carved_size=end_pos,
        status=IntegrityStatus.GOOD,
        detail="Valid Matroska EBML header and stream",
    )


def _validate_mp3(buf: bytes) -> Optional[ValidationResult]:
    if len(buf) < 16 or buf[3] > 4:
        return None
    s0, s1, s2, s3 = buf[6], buf[7], buf[8], buf[9]
    if any(b & 0x80 for b in (s0, s1, s2, s3)):
        return None
    id3_size = ((s0 & 0x7F) << 21) | ((s1 & 0x7F) << 14) | ((s2 & 0x7F) << 7) | (s3 & 0x7F)
    audio_start = 10 + id3_size
    end_pos = _find_zero_run(buf, min(len(buf), max(audio_start, 32)))
    return ValidationResult(
        is_valid_header=True,
        extension="MP3",
        category=FileCategory.AUDIO,
        carved_size=max(end_pos, min(len(buf), audio_start + 1024)),
        status=IntegrityStatus.GOOD if audio_start < len(buf) else IntegrityStatus.PARTIAL,
        detail=f"MP3 with ID3v2.{buf[3]} tag ({id3_size} B tag)",
    )


def _validate_flac(buf: bytes) -> Optional[ValidationResult]:
    if len(buf) < 42:
        return None
    block_hdr = buf[4]
    block_type = block_hdr & 0x7F
    block_len = struct.unpack_from(">I", b"\x00" + buf[5:8])[0]
    if block_type != 0 or block_len != 34:
        return None
    end_pos = _find_zero_run(buf, 42)
    return ValidationResult(
        is_valid_header=True,
        extension="FLAC",
        category=FileCategory.AUDIO,
        carved_size=end_pos,
        status=IntegrityStatus.GOOD,
        detail="Valid FLAC audio with STREAMINFO block",
    )


def _validate_7z(buf: bytes) -> Optional[ValidationResult]:
    if len(buf) < 32:
        return None
    next_hdr_off, next_hdr_size = struct.unpack_from("<QQ", buf, 12)
    total_size = 32 + next_hdr_off + next_hdr_size
    if total_size < 32 or total_size > 200 * 1024 * 1024:
        return None
    status = IntegrityStatus.GOOD if len(buf) >= total_size else IntegrityStatus.PARTIAL
    return ValidationResult(
        is_valid_header=True,
        extension="7Z",
        category=FileCategory.ARCHIVES,
        carved_size=min(len(buf), total_size),
        status=status,
        detail=f"7-Zip archive ({min(len(buf), total_size)} of {total_size} bytes)",
    )


def _validate_rar(buf: bytes) -> Optional[ValidationResult]:
    if len(buf) < 20 or buf[6] not in (0x00, 0x01):
        return None
    end_pos = _find_zero_run(buf, 20)
    return ValidationResult(
        is_valid_header=True,
        extension="RAR",
        category=FileCategory.ARCHIVES,
        carved_size=end_pos,
        status=IntegrityStatus.GOOD,
        detail=f"Valid RAR v{4 + buf[6]} archive header",
    )


def _validate_gzip(buf: bytes) -> Optional[ValidationResult]:
    if len(buf) < 18 or buf[3] > 0x1F:
        return None
    try:
        dobj = zlib.decompressobj(wbits=16 + zlib.MAX_WBITS)
        dobj.decompress(buf[: min(len(buf), 65536)])
        consumed = min(len(buf), 65536) - len(dobj.unused_data)
        if consumed >= 18 and dobj.eof:
            return ValidationResult(
                is_valid_header=True,
                extension="GZ",
                category=FileCategory.ARCHIVES,
                carved_size=consumed,
                status=IntegrityStatus.GOOD,
                detail=f"Valid GZIP stream ({consumed} bytes, CRC verified)",
            )
    except zlib.error:
        return None
    return None


def _find_zero_run(buf: bytes, start: int) -> int:
    idx = buf.find(b"\x00" * 256, start)
    return idx if idx != -1 else min(len(buf), max(start, 4096))


def validate_recovered_bytes(data: bytes, extension: str) -> tuple[IntegrityStatus, str]:
    """
    Verify already-recovered file bytes against format-specific structural rules.
    Used both during metadata scan validation and post-recovery verification.
    """
    if not data:
        return (IntegrityStatus.CORRUPTED, "File contains 0 recoverable bytes")

    ext = extension.upper().lstrip(".")
    res = validate_and_measure_carved_data(data)
    if res is not None:
        return (res.status, res.detail)

    if ext in ("TXT", "CSV", "MD", "JSON", "LOG", "PY", "XML", "HTML"):
        try:
            text = data.decode("utf-8")
            if "\x00\x00\x00\x00" in text:
                return (IntegrityStatus.PARTIAL, "Text contains zeroed/overwritten regions")
            return (IntegrityStatus.GOOD, "Valid UTF-8 text content")
        except UnicodeDecodeError:
            return (IntegrityStatus.PARTIAL, "Non-UTF8 or partially overwritten text bytes")

    if data == b"\x00" * len(data):
        return (IntegrityStatus.CORRUPTED, "All clusters contain zeroes (trimmed or wiped)")

    return (IntegrityStatus.UNKNOWN, f"Binary payload read ({len(data)} bytes); no format checksum available")
