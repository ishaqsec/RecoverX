"""Extensible File Signature Registry for Signature-Based Carving."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from filesystems.base import FileCategory


@dataclass
class FileSignature:
    format_id: str
    extension: str
    category: FileCategory
    header: bytes
    header_offset: int = 0
    footer: Optional[bytes] = None
    max_size: int = 50 * 1024 * 1024  # 50 MB default max carve size
    min_size: int = 32
    description: str = ""
    sector_aligned_only: bool = False


class SignatureRegistry:
    """Registry of file signatures supporting custom user-registered formats."""

    def __init__(self) -> None:
        self._signatures: Dict[str, FileSignature] = {}
        self._register_defaults()

    def register(self, sig: FileSignature) -> None:
        self._signatures[sig.format_id.upper()] = sig

    def unregister(self, format_id: str) -> None:
        self._signatures.pop(format_id.upper(), None)

    def get(self, format_id: str) -> Optional[FileSignature]:
        return self._signatures.get(format_id.upper())

    def all_signatures(self, enabled_categories: Optional[List[FileCategory]] = None) -> List[FileSignature]:
        sigs = list(self._signatures.values())
        if enabled_categories is not None:
            cat_set = set(enabled_categories)
            sigs = [s for s in sigs if s.category in cat_set]
        return sigs

    def _register_defaults(self) -> None:
        defaults = [
            # Images
            FileSignature(
                format_id="JPG",
                extension="JPG",
                category=FileCategory.IMAGES,
                header=b"\xff\xd8\xff",
                footer=b"\xff\xd9",
                max_size=25 * 1024 * 1024,
                min_size=128,
                description="JPEG Digital Image",
            ),
            FileSignature(
                format_id="PNG",
                extension="PNG",
                category=FileCategory.IMAGES,
                header=b"\x89PNG\r\n\x1a\n",
                footer=b"IEND\xae\x42\x60\x82",
                max_size=25 * 1024 * 1024,
                min_size=67,
                description="Portable Network Graphics Image",
            ),
            FileSignature(
                format_id="GIF89",
                extension="GIF",
                category=FileCategory.IMAGES,
                header=b"GIF89a",
                footer=b"\x00\x3b",
                max_size=15 * 1024 * 1024,
                min_size=32,
                description="GIF89a Animated/Static Image",
            ),
            FileSignature(
                format_id="GIF87",
                extension="GIF",
                category=FileCategory.IMAGES,
                header=b"GIF87a",
                footer=b"\x00\x3b",
                max_size=15 * 1024 * 1024,
                min_size=32,
                description="GIF87a Image",
            ),
            FileSignature(
                format_id="BMP",
                extension="BMP",
                category=FileCategory.IMAGES,
                header=b"BM",
                max_size=30 * 1024 * 1024,
                min_size=54,
                description="Windows Bitmap Image",
                sector_aligned_only=True,
            ),
            FileSignature(
                format_id="TIFF_LE",
                extension="TIFF",
                category=FileCategory.IMAGES,
                header=b"II*\x00",
                max_size=50 * 1024 * 1024,
                min_size=64,
                description="TIFF Image (Little-Endian)",
            ),
            FileSignature(
                format_id="TIFF_BE",
                extension="TIFF",
                category=FileCategory.IMAGES,
                header=b"MM\x00*",
                max_size=50 * 1024 * 1024,
                min_size=64,
                description="TIFF Image (Big-Endian)",
            ),
            FileSignature(
                format_id="WEBP",
                extension="WEBP",
                category=FileCategory.IMAGES,
                header=b"RIFF",
                max_size=20 * 1024 * 1024,
                min_size=32,
                description="WebP Image (RIFF container)",
            ),
            # Documents
            FileSignature(
                format_id="PDF",
                extension="PDF",
                category=FileCategory.DOCUMENTS,
                header=b"%PDF-",
                footer=b"%%EOF",
                max_size=50 * 1024 * 1024,
                min_size=120,
                description="Portable Document Format",
            ),
            # ZIP / Office OpenXML (DOCX, XLSX, PPTX, ZIP)
            FileSignature(
                format_id="ZIP_CONTAINER",
                extension="ZIP",
                category=FileCategory.ARCHIVES,
                header=b"PK\x03\x04",
                footer=b"PK\x05\x06",
                max_size=100 * 1024 * 1024,
                min_size=64,
                description="ZIP Archive / Office OpenXML Container (DOCX/XLSX/PPTX)",
            ),
            # Videos
            FileSignature(
                format_id="MP4_ISO",
                extension="MP4",
                category=FileCategory.VIDEOS,
                header=b"ftyp",
                header_offset=4,
                max_size=200 * 1024 * 1024,
                min_size=64,
                description="MP4 / QuickTime MOV ISO Base Media Video",
            ),
            FileSignature(
                format_id="MKV",
                extension="MKV",
                category=FileCategory.VIDEOS,
                header=b"\x1a\x45\xdf\xa3",
                max_size=200 * 1024 * 1024,
                min_size=64,
                description="Matroska Multimedia Container",
            ),
            # Audio
            FileSignature(
                format_id="MP3_ID3",
                extension="MP3",
                category=FileCategory.AUDIO,
                header=b"ID3",
                max_size=30 * 1024 * 1024,
                min_size=128,
                description="MPEG-1/2 Audio Layer III (ID3v2)",
            ),
            FileSignature(
                format_id="FLAC",
                extension="FLAC",
                category=FileCategory.AUDIO,
                header=b"fLaC",
                max_size=80 * 1024 * 1024,
                min_size=64,
                description="Free Lossless Audio Codec",
            ),
            # Archives
            FileSignature(
                format_id="7Z",
                extension="7Z",
                category=FileCategory.ARCHIVES,
                header=b"7z\xbc\xaf\x27\x1c",
                max_size=100 * 1024 * 1024,
                min_size=48,
                description="7-Zip Compressed Archive",
            ),
            FileSignature(
                format_id="RAR",
                extension="RAR",
                category=FileCategory.ARCHIVES,
                header=b"Rar!\x1a\x07",
                max_size=100 * 1024 * 1024,
                min_size=48,
                description="RAR Compressed Archive",
            ),
            FileSignature(
                format_id="GZIP",
                extension="GZ",
                category=FileCategory.ARCHIVES,
                header=b"\x1f\x8b\x08",
                max_size=50 * 1024 * 1024,
                min_size=32,
                description="GZIP Compressed Stream",
                sector_aligned_only=True,
            ),
        ]
        for sig in defaults:
            self.register(sig)


DEFAULT_REGISTRY = SignatureRegistry()
