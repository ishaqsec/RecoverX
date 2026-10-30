"""Base Data Structures and Interfaces for File-System Recovery & Carving."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, List, Optional

from devices.reader import ReadOnlyDeviceReader


class IntegrityStatus(str, Enum):
    GOOD = "Good"           # Metadata/structure verified intact (Recoverable)
    PARTIAL = "Partial"     # Partially overwritten, truncated, or missing clusters
    CORRUPTED = "Corrupted" # Header found or record exists, but structural check failed
    UNKNOWN = "Unknown"     # Format lacks structural checksum/EOF verification


class RecoveryMethod(str, Enum):
    NTFS_MFT = "NTFS MFT Metadata"
    FAT32_DIR = "FAT32 Directory Entry"
    EXFAT_DIR = "exFAT Entry Set"
    EXT4_INODE = "EXT4 Inode / Extent"
    SIGNATURE_CARVING = "Signature Carving"


class FileCategory(str, Enum):
    IMAGES = "Images"
    VIDEOS = "Videos"
    DOCUMENTS = "Documents"
    AUDIO = "Audio"
    ARCHIVES = "Archives"
    OTHER = "Other Files"


EXTENSION_CATEGORY_MAP = {
    # Images
    "JPG": FileCategory.IMAGES,
    "JPEG": FileCategory.IMAGES,
    "PNG": FileCategory.IMAGES,
    "GIF": FileCategory.IMAGES,
    "BMP": FileCategory.IMAGES,
    "TIFF": FileCategory.IMAGES,
    "TIF": FileCategory.IMAGES,
    "WEBP": FileCategory.IMAGES,
    "HEIC": FileCategory.IMAGES,
    "HEIF": FileCategory.IMAGES,
    # Videos
    "MP4": FileCategory.VIDEOS,
    "MOV": FileCategory.VIDEOS,
    "AVI": FileCategory.VIDEOS,
    "MKV": FileCategory.VIDEOS,
    "WEBM": FileCategory.VIDEOS,
    "3GP": FileCategory.VIDEOS,
    # Documents
    "PDF": FileCategory.DOCUMENTS,
    "DOCX": FileCategory.DOCUMENTS,
    "XLSX": FileCategory.DOCUMENTS,
    "PPTX": FileCategory.DOCUMENTS,
    "TXT": FileCategory.DOCUMENTS,
    "CSV": FileCategory.DOCUMENTS,
    "MD": FileCategory.DOCUMENTS,
    "RTF": FileCategory.DOCUMENTS,
    # Audio
    "MP3": FileCategory.AUDIO,
    "WAV": FileCategory.AUDIO,
    "FLAC": FileCategory.AUDIO,
    "OGG": FileCategory.AUDIO,
    "M4A": FileCategory.AUDIO,
    "AAC": FileCategory.AUDIO,
    # Archives
    "ZIP": FileCategory.ARCHIVES,
    "7Z": FileCategory.ARCHIVES,
    "RAR": FileCategory.ARCHIVES,
    "GZ": FileCategory.ARCHIVES,
    "GZIP": FileCategory.ARCHIVES,
    "TAR": FileCategory.ARCHIVES,
}


def categorize_extension(ext: str) -> FileCategory:
    clean = ext.upper().lstrip(".")
    return EXTENSION_CATEGORY_MAP.get(clean, FileCategory.OTHER)


def format_file_size(num_bytes: int) -> str:
    if num_bytes < 1024:
        return f"{num_bytes} B"
    elif num_bytes < 1024 ** 2:
        kb = num_bytes / 1024.0
        return f"{int(round(kb))} KB" if kb >= 10 else f"{kb:.1f} KB"
    elif num_bytes < 1024 ** 3:
        mb = num_bytes / (1024.0 ** 2)
        return f"{mb:.1f} MB"
    else:
        gb = num_bytes / (1024.0 ** 3)
        return f"{gb:.2f} GB"


@dataclass
class DataRun:
    """Represents a contiguous byte range on the source device or disk image."""
    device_offset: int
    length: int
    sparse: bool = False


@dataclass
class RecoveredFileEntry:
    """Represents a single discovered deleted or carved file."""
    id: str
    name: str
    extension: str
    size_bytes: int
    original_path: str
    modified_time: Optional[datetime]
    created_time: Optional[datetime] = None
    accessed_time: Optional[datetime] = None
    recovery_method: RecoveryMethod = RecoveryMethod.SIGNATURE_CARVING
    status: IntegrityStatus = IntegrityStatus.GOOD
    status_detail: str = "Intact metadata and clusters available"
    category: FileCategory = FileCategory.OTHER
    resident_data: Optional[bytes] = None
    data_runs: List[DataRun] = field(default_factory=list)
    source_device_path: str = ""
    inode_or_cluster: int = 0
    is_deleted: bool = True
    selected: bool = False
    sha256: str = ""

    def __post_init__(self):
        if not self.extension and "." in self.name:
            self.extension = self.name.rsplit(".", 1)[-1].upper()
        else:
            self.extension = self.extension.extension if hasattr(self.extension, "extension") else str(self.extension).upper().lstrip(".")
        self.category = categorize_extension(self.extension)

    @property
    def size_Formatted(self) -> str:
        return format_file_size(self.size_bytes)

    @property
    def modified_formatted(self) -> str:
        if not self.modified_time:
            return "Unknown"
        return self.modified_time.strftime("%b %d, %Y  %H:%M")

    @property
    def primary_offset(self) -> int:
        if self.data_runs:
            return self.data_runs[0].device_offset
        return self.inode_or_cluster

    def extract_bytes(self, reader: ReadOnlyDeviceReader, max_bytes: Optional[int] = None) -> bytes:
        """Read actual file content from resident bytes or non-resident data runs."""
        target_len = self.size_bytes if max_bytes is None else min(self.size_bytes, max_bytes)
        if target_len <= 0:
            return b""
        if self.resident_data is not None:
            return self.resident_data[:target_len]

        out = bytearray()
        for run in self.data_runs:
            if len(out) >= target_len:
                break
            needed = min(run.length, target_len - len(out))
            if run.sparse:
                out.extend(b"\x00" * needed)
            else:
                chunk = reader.read_at(run.device_offset, needed)
                out.extend(chunk)
                if len(chunk) < needed:
                    break
        return bytes(out[:target_len])


class FileSystemParser(ABC):
    """Abstract base class for NTFS, FAT32, exFAT, and EXT4 parsers."""

    def __init__(self, reader: ReadOnlyDeviceReader, partition_offset: int = 0):
        self.reader = reader
        self.partition_offset = partition_offset

    @abstractmethod
    def detect(self) -> bool:
        """Return True if the partition contains a valid signature for this filesystem."""

    @abstractmethod
    def scan_deleted(
        self,
        progress_cb: Optional[Callable[[int, int, str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        include_active: bool = False,
    ) -> List[RecoveredFileEntry]:
        """Parse filesystem metadata and return discovered deleted (and optionally active) file records."""
