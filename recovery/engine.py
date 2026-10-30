"""Modular Scan Orchestrator — Real-Time Streaming & Strictly Deleted/Recycled/Trashed/Unallocated Recovery."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import re
import sqlite3
import struct
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Callable, List, Optional, Set, Tuple

from carving.carver import FileCarver
from carving.signatures import DEFAULT_REGISTRY, SignatureRegistry
from carving.validators import validate_recovered_bytes
from devices.discovery import CREATE_NO_WINDOW, DeviceInfo, find_adb_executable
from devices.reader import DeviceAccessError, ReadOnlyDeviceReader
from filesystems.base import (
    FileCategory,
    IntegrityStatus,
    RecoveredFileEntry,
    RecoveryMethod,
    categorize_extension,
)
from filesystems.exfat import ExFATParser
from filesystems.ext4 import EXT4Parser
from filesystems.fat32 import FAT32Parser
from filesystems.ntfs import NTFSMftParser
from storage.database import RecoverXDatabase, RecoveryLogRecord, ScanSessionRecord

logger = logging.getLogger("recoverx.recovery.engine")


class ScanMode(str, Enum):
    QUICK_SCAN = "Quick Scan"
    DEEP_SCAN = "Deep Scan"
    FILE_CARVING = "File Carving"
    SCAN_IMAGE_FILE = "Scan Image File"


class DestinationSameDeviceError(ValueError):
    """Raised when the recovery destination is on the same device as the source without explicit override."""


@dataclass
class RecoveryOutcome:
    file_id: str
    file_name: str
    outcome: str  # "Succeeded", "Partial", "Skipped", "Failed"
    output_path: str
    bytes_written: int
    sha256: str
    verified_integrity: str
    message: str


def is_same_storage_device(source_device: DeviceInfo, destination_dir: str) -> bool:
    if source_device.path.startswith(("adb://", "wpd://", "iosbackup://")):
        return False
    try:
        dest_resolved = Path(destination_dir).resolve()
        src_path = (
            Path(source_device.path).resolve()
            if os.path.exists(source_device.path)
            else Path(source_device.path)
        )

        if source_device.mount_point and os.path.exists(source_device.mount_point):
            mnt = Path(source_device.mount_point).resolve()
            if dest_resolved == mnt or mnt in dest_resolved.parents:
                if source_device.device_type.value == "Disk Image":
                    return dest_resolved == src_path
                return True

        if len(source_device.path) >= 2 and ":" in source_device.path:
            src_drive = source_device.path.replace("\\\\.\\", "")[:2].upper()
            dest_drive = str(dest_resolved)[:2].upper()
            if src_drive == dest_drive:
                return True

        if os.path.exists(source_device.path) and source_device.device_type.value != "Disk Image":
            src_stat = os.stat(source_device.path)
            dest_check = dest_resolved if dest_resolved.exists() else dest_resolved.parent
            if dest_check.exists():
                dest_stat = os.stat(dest_check)
                if src_stat.st_dev == dest_stat.st_dev or (
                    src_stat.st_rdev != 0 and src_stat.st_rdev == dest_stat.st_dev
                ):
                    return True
    except OSError:
        pass
    return False


def sanitize_filename_only(name: str) -> str:
    cleaned = re.sub(r"^[A-Za-z]:[\\/]*", "", name)
    parts = [p for p in re.split(r"[\\/]+", cleaned) if p and p not in (".", "..")]
    base = parts[-1] if parts else "Recovered_File.bin"
    base = re.sub(r"^\.trashed-\d+-", "", base)
    safe = re.sub(r'[<>:"|?*\x00-\x1f]', "_", base).strip()
    return safe or "Recovered_File.bin"


def category_subfolder_relpath(entry: RecoveredFileEntry) -> Path:
    folder_name = entry.category.value if entry.category else "Other Files"
    safe_file = sanitize_filename_only(entry.name or entry.original_path)
    return Path(folder_name) / safe_file


def resolve_collision_path(target_path: Path) -> Path:
    if not target_path.exists():
        return target_path
    stem = target_path.stem
    suffix = target_path.suffix
    parent = target_path.parent
    counter = 1
    while True:
        candidate = parent / f"{stem}_recovered_{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1


def _parse_windows_recycle_bin_i_file(i_file_path: Path) -> Optional[Tuple[str, int, Optional[datetime]]]:
    try:
        raw = i_file_path.read_bytes()
        if len(raw) < 28:
            return None
        ver, orig_size, del_ft = struct.unpack_from("<QQQ", raw, 0)
        del_dt = None
        if del_ft > 0:
            try:
                del_dt = datetime(1601, 1, 1, tzinfo=timezone.utc) + timedelta(microseconds=del_ft // 10)
            except Exception:
                pass
        if ver == 2 and len(raw) >= 28:
            char_cnt = struct.unpack_from("<I", raw, 24)[0]
            orig_path = raw[28 : 28 + char_cnt * 2].decode("utf-16le", errors="ignore").rstrip("\x00")
            return (orig_path, orig_size, del_dt)
        elif ver == 1:
            orig_path = raw[24:544].decode("utf-16le", errors="ignore").rstrip("\x00")
            return (orig_path, orig_size, del_dt)
    except OSError:
        pass
    return None


def read_adb_file_bytes(adb_uri: str, max_bytes: Optional[int] = None) -> bytes:
    if not adb_uri.startswith("adb://"):
        return b""
    rest = adb_uri[len("adb://") :]
    if "/" not in rest:
        return b""
    serial, remote_path = rest.split("/", 1)
    remote_path = "/" + remote_path.lstrip("/")
    adb_exe = find_adb_executable() or "adb"
    try:
        cmd = [adb_exe, "-s", serial, "exec-out", f"cat '{remote_path}'"]
        if max_bytes is not None and max_bytes > 0:
            cmd = [
                adb_exe,
                "-s",
                serial,
                "exec-out",
                f"dd if='{remote_path}' bs=65536 count={(max_bytes // 65536) + 1} 2>/dev/null",
            ]
        proc = subprocess.run(
            cmd,
            capture_output=True,
            timeout=15.0,
            creationflags=CREATE_NO_WINDOW,
        )
        if proc.returncode == 0 and proc.stdout:
            return proc.stdout[:max_bytes] if max_bytes else proc.stdout
    except Exception:
        pass
    return b""


class RecoveryEngine:
    """
    Coordinates read-only filesystem deleted-record parsing (NTFS, FAT32, exFAT, EXT4),
    signature-based file carving of unallocated clusters, and deleted/trashed/recycled
    item discovery — strictly excluding active existing user files.
    """

    def __init__(
        self,
        db: Optional[RecoverXDatabase] = None,
        registry: Optional[SignatureRegistry] = None,
    ):
        self.db = db or RecoverXDatabase()
        self.registry = registry or DEFAULT_REGISTRY

    def _detect_partition_offset(self, reader: ReadOnlyDeviceReader) -> int:
        header = reader.read_at(0, 4096)
        if len(header) >= 512:
            if header[3:11] in (b"NTFS    ", b"EXFAT   ") or header[82:90] == b"FAT32   ":
                return 0
            if len(header) >= 1082 and struct.unpack_from("<H", header, 1080)[0] == 0xEF53:
                return 0
            if header[510:512] == b"\x55\xaa":
                lba_start = int.from_bytes(header[454:458], "little")
                if 0 < lba_start < 65536:
                    return lba_start * 512
        return 0

    def _scan_adb_internal_storage(
        self,
        device: DeviceInfo,
        scan_mode: ScanMode,
        discovered: List[RecoveredFileEntry],
        allowed_categories: Optional[Set[str]] = None,
        progress_cb: Optional[Callable[[int, int, str, List[RecoveredFileEntry]], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> None:
        """
        Scan ONLY deleted, trashed (`.trashed-*`), recycled (`.Trash`, `.globalTrash`, `RecycleBin`),
        lost (`LOST.DIR`), and orphaned thumbnail/recovery cache records on cable-connected ADB internal storage.
        Uses Android Toybox-compatible `find ... -exec stat -c '%s|%Y|%n' {} +` so it works on all Android versions.
        """
        adb_exe = device.metadata.get("adb_exe") or find_adb_executable() or "adb"
        serial = device.metadata.get("adb_serial") or ""
        if not serial and device.path.startswith("adb://"):
            serial = device.path[len("adb://") :].split("/", 1)[0]
        if not serial:
            return

        max_items = 500 if scan_mode == ScanMode.QUICK_SCAN else 2000
        deleted_roots = (
            "/storage/emulated/0/.Trash "
            "/storage/emulated/0/DCIM/.globalTrash "
            "/storage/emulated/0/DCIM/.thumbnails "
            "/storage/emulated/0/Pictures/.thumbnails "
            "/storage/emulated/0/LOST.DIR "
            "/storage/emulated/0/RecycleBin "
            "/storage/emulated/0/.RecycleBin "
            "/storage/emulated/0/Android/data/com.miui.gallery/files/gallery_disk_cache "
            "/storage/emulated/0/Android/data/com.sec.android.gallery3d/files/.Trash "
            "/storage/emulated/0/Android/data/com.google.android.apps.nbu.files/files/.Trash"
        )
        shell_cmd = (
            f"(find {deleted_roots} -type f -exec stat -c '%s|%Y|%n' {{}} + 2>/dev/null; "
            f"find /storage/emulated/0 \\( -name '.trashed-*' -o -name '*.trashed*' \\) -type f -exec stat -c '%s|%Y|%n' {{}} + 2>/dev/null)"
        )
        try:
            proc = subprocess.Popen(
                [adb_exe, "-s", serial, "shell", shell_cmd],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=CREATE_NO_WINDOW,
            )
            seen_remote: Set[str] = set()
            count = 0
            if proc.stdout is not None:
                for raw_line in proc.stdout:
                    if cancel_check and cancel_check():
                        proc.terminate()
                        break
                    line = raw_line.strip()
                    if not line:
                        continue
                    fsize = 0
                    mod_dt = datetime.now(timezone.utc)
                    rpath = line
                    if "|" in line:
                        parts = line.split("|", 2)
                        if len(parts) == 3:
                            try:
                                fsize = int(parts[0])
                            except ValueError:
                                fsize = 0
                            try:
                                mod_dt = datetime.fromtimestamp(float(parts[1]), tz=timezone.utc)
                            except ValueError:
                                pass
                            rpath = parts[2]
                    if rpath in seen_remote:
                        continue
                    seen_remote.add(rpath)

                    fname = rpath.rsplit("/", 1)[-1]
                    if "." not in fname:
                        continue
                    clean_display_name = re.sub(r"^\.trashed-\d+-", "", fname)
                    ext = clean_display_name.rsplit(".", 1)[-1].upper() if "." in clean_display_name else ""
                    cat_enum = categorize_extension(ext)
                    if allowed_categories and cat_enum.value not in allowed_categories:
                        continue

                    if fsize <= 0:
                        continue

                    entry = RecoveredFileEntry(
                        id=f"adb:{len(discovered) + 1}",
                        name=clean_display_name,
                        extension=ext,
                        size_bytes=fsize,
                        original_path=rpath,
                        modified_time=mod_dt,
                        recovery_method=RecoveryMethod.NTFS_MFT,
                        status=IntegrityStatus.GOOD,
                        status_detail="Deleted / Trashed internal storage record",
                        category=cat_enum,
                        source_device_path=f"adb://{serial}{rpath}",
                        is_deleted=True,
                        selected=bool(allowed_categories),
                    )
                    discovered.append(entry)
                    count += 1
                    if progress_cb:
                        progress_cb(min(max_items, count), max_items, f"Discovered {clean_display_name}", discovered)
                    if len(discovered) >= max_items:
                        proc.terminate()
                        break
        except Exception as exc:
            logger.debug("ADB deleted storage scan finished: %s", exc)

    def _scan_wpd_internal_storage(
        self,
        device: DeviceInfo,
        scan_mode: ScanMode,
        discovered: List[RecoveredFileEntry],
        allowed_categories: Optional[Set[str]] = None,
        progress_cb: Optional[Callable[[int, int, str, List[RecoveredFileEntry]], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> None:
        """
        Scan ONLY deleted/trashed/recycle/thumbnail/lost folders on a WPD/MTP connected device
        (`.Trash`, `.trashed-*`, `.thumbnails`, `.globalTrash`, `LOST.DIR`, `RecycleBin`),
        never fetching normal existing active files.
        """
        if platform.system() != "Windows":
            return
        dev_name = device.metadata.get("wpd_device_name") or device.path.replace("wpd://", "")
        stage_dir = Path(tempfile.gettempdir()) / "recoverx_usb_stage" / re.sub(r"\W+", "_", dev_name)
        stage_dir.mkdir(parents=True, exist_ok=True)
        max_items = 250 if scan_mode == ScanMode.QUICK_SCAN else 750

        ps_script = f"""
$ErrorActionPreference='SilentlyContinue'
$sh = New-Object -ComObject Shell.Application
$ns = $sh.NameSpace(17)
$targetDev = $null
foreach($it in $ns.Items()){{
  if($it.Name -eq '{dev_name.replace("'", "''")}'){{ $targetDev = $it; break }}
}}
if(-not $targetDev){{ exit 0 }}
$stageFolder = $sh.NameSpace('{str(stage_dir).replace("'", "''")}')
$count = 0
function Walk-Deleted($folder, $relPrefix, $depth, $inTrash){{
  if($depth -gt 5 -or $script:count -ge {max_items}){{ return }}
  foreach($item in $folder.Items()){{
    if($script:count -ge {max_items}){{ return }}
    $nm = $item.Name
    if($item.IsFolder){{
      $isDelDir = $inTrash -or ($nm -match '^(\\.Trash|\\.globalTrash|\\.thumbnails|LOST\\.DIR|RecycleBin|\\.RecycleBin|Trash)$')
      if($isDelDir -or $depth -le 2){{
        $sub = $item.GetFolder()
        if($sub){{ Walk-Deleted $sub ($relPrefix + '/' + $nm) ($depth + 1) $isDelDir }}
      }}
    }} else {{
      $isDelFile = $inTrash -or ($nm -match '^\\.trashed-')
      if($isDelFile -and ($nm -match '\\.')){{
        $stageFolder.CopyHere($item, 20)
        $stagedPath = Join-Path '{str(stage_dir).replace("'", "''")}' $nm
        if(Test-Path $stagedPath){{
          $fi = Get-Item $stagedPath
          $obj = [PSCustomObject]@{{
            Name = $nm
            OrigPath = ($relPrefix + '/' + $nm)
            StagedPath = $stagedPath
            Size = $fi.Length
          }}
          Write-Output ($obj | ConvertTo-Json -Compress)
          $script:count++
        }}
      }}
    }}
  }}
}}
$rootFolder = $targetDev.GetFolder()
if($rootFolder){{ Walk-Deleted $rootFolder '{dev_name.replace("'", "''")}' 0 $false }}
"""
        try:
            proc = subprocess.Popen(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=CREATE_NO_WINDOW,
            )
            idx = 0
            if proc.stdout is not None:
                for raw_line in proc.stdout:
                    if cancel_check and cancel_check():
                        proc.terminate()
                        break
                    line = raw_line.strip()
                    if not line.startswith("{"):
                        continue
                    try:
                        item = json.loads(line)
                    except Exception:
                        continue
                    raw_fname = str(item.get("Name") or "")
                    fname = sanitize_filename_only(raw_fname)
                    staged_p = str(item.get("StagedPath") or "")
                    orig_p = str(item.get("OrigPath") or staged_p)
                    fsize = int(item.get("Size") or 0)
                    if not fname or "." not in fname or fsize <= 0:
                        continue
                    ext = fname.rsplit(".", 1)[-1].upper()
                    cat_enum = categorize_extension(ext)
                    if allowed_categories and cat_enum.value not in allowed_categories:
                        continue

                    entry = RecoveredFileEntry(
                        id=f"wpd:{len(discovered) + 1}",
                        name=fname,
                        extension=ext,
                        size_bytes=fsize,
                        original_path=orig_p,
                        modified_time=datetime.now(timezone.utc),
                        recovery_method=RecoveryMethod.NTFS_MFT,
                        status=IntegrityStatus.GOOD,
                        status_detail="Deleted / Trashed internal storage record",
                        category=cat_enum,
                        source_device_path=staged_p,
                        is_deleted=True,
                        selected=bool(allowed_categories),
                    )
                    discovered.append(entry)
                    idx += 1
                    if progress_cb:
                        progress_cb(min(max_items, idx), max_items, f"Discovered {fname}", discovered)
        except Exception as exc:
            logger.debug("WPD deleted storage scan finished: %s", exc)

    def _scan_ios_backup_storage(
        self,
        device: DeviceInfo,
        scan_mode: ScanMode,
        discovered: List[RecoveredFileEntry],
        allowed_categories: Optional[Set[str]] = None,
        progress_cb: Optional[Callable[[int, int, str, List[RecoveredFileEntry]], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> None:
        """
        Scan unencrypted iOS MobileSync backup (`Manifest.db`) for trashed, recently deleted,
        and orphaned media blobs (`Media/PhotoData/Trash`, `RecentlyDeleted`, orphaned hashed blobs).
        """
        backup_dir = Path(device.metadata.get("backup_dir") or device.path.replace("iosbackup://", ""))
        manifest_db = Path(device.metadata.get("manifest_db") or (backup_dir / "Manifest.db"))
        if not manifest_db.is_file():
            return

        max_items = 500 if scan_mode == ScanMode.QUICK_SCAN else 2000
        seen_hashes: Set[str] = set()
        count = 0

        try:
            conn = sqlite3.connect(f"file:{manifest_db}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
            try:
                rows = conn.execute(
                    "SELECT fileID, domain, relativePath, flags FROM Files "
                    "WHERE flags = 1 AND ("
                    "  relativePath LIKE '%Trash%' OR "
                    "  relativePath LIKE '%Deleted%' OR "
                    "  relativePath LIKE '%Thumbnails%' OR "
                    "  relativePath LIKE '%.trashed%'"
                    ")"
                ).fetchall()
                for row in rows:
                    if cancel_check and cancel_check():
                        break
                    file_id = str(row["fileID"] or "")
                    rel_path = str(row["relativePath"] or "")
                    if not file_id or len(file_id) < 2:
                        continue
                    blob_path = backup_dir / file_id[:2] / file_id
                    if not blob_path.is_file():
                        blob_path = backup_dir / file_id
                        if not blob_path.is_file():
                            continue
                    seen_hashes.add(file_id)
                    fname = sanitize_filename_only(Path(rel_path).name or f"{file_id}.bin")
                    if "." not in fname:
                        continue
                    ext = fname.rsplit(".", 1)[-1].upper()
                    cat_enum = categorize_extension(ext)
                    if allowed_categories and cat_enum.value not in allowed_categories:
                        continue
                    st = blob_path.stat()
                    if st.st_size <= 0:
                        continue
                    entry = RecoveredFileEntry(
                        id=f"ios:{len(discovered) + 1}",
                        name=fname,
                        extension=ext,
                        size_bytes=st.st_size,
                        original_path=rel_path or str(blob_path),
                        modified_time=datetime.fromtimestamp(st.st_mtime, tz=timezone.utc),
                        recovery_method=RecoveryMethod.EXT4_INODE,
                        status=IntegrityStatus.GOOD,
                        status_detail="Deleted / Trashed mobile backup record",
                        category=cat_enum,
                        source_device_path=str(blob_path),
                        is_deleted=True,
                        selected=bool(allowed_categories),
                    )
                    discovered.append(entry)
                    count += 1
                    if progress_cb:
                        progress_cb(min(max_items, count), max_items, f"Discovered {fname}", discovered)
                    if len(discovered) >= max_items:
                        break
            finally:
                conn.close()
        except Exception as exc:
            logger.debug("iOS backup Manifest.db scan finished: %s", exc)

    def _scan_mounted_volume_live(
        self,
        device: DeviceInfo,
        scan_mode: ScanMode,
        discovered: List[RecoveredFileEntry],
        allowed_categories: Optional[Set[str]] = None,
        progress_cb: Optional[Callable[[int, int, str, List[RecoveredFileEntry]], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> None:
        """
        Scan ONLY deleted, recycled, trashed, or orphaned recovery containers on a mounted volume:
          - Windows `$Recycle.Bin` (`$Rxxxxxx` deleted files paired with `$Ixxxxxx` metadata)
          - Legacy `RECYCLER` / `Recycled`
          - Removable/External/Phone trash & lost cluster directories (`.Trash`, `.Trash-1000`,
            `.Trashes`, `LOST.DIR`, `FOUND.000`, `FOUND.001`, `DCIM/.globalTrash`, `DCIM/.thumbnails`)
        Strictly does NOT scan or return currently existing active files in user folders!
        """
        root_str = device.mount_point or device.path
        if not root_str or not os.path.isdir(root_str):
            return

        root_path = Path(root_str)
        max_items = 400 if scan_mode == ScanMode.QUICK_SCAN else 1200
        scanned_count = 0
        seen_paths = {e.source_device_path for e in discovered if e.source_device_path}

        deleted_containers = (
            "$Recycle.Bin",
            "RECYCLER",
            "Recycled",
            ".Trash",
            ".Trash-1000",
            ".Trashes",
            "LOST.DIR",
            "FOUND.000",
            "FOUND.001",
            "DCIM/.globalTrash",
            "DCIM/.thumbnails",
            "Pictures/.thumbnails",
        )

        for trash_name in deleted_containers:
            recycle_dir = root_path / trash_name
            if not (recycle_dir.exists() and recycle_dir.is_dir()):
                continue
            try:
                for dirpath, _dirnames, filenames in os.walk(str(recycle_dir), onerror=lambda _e: None):
                    if cancel_check and cancel_check():
                        return
                    for fn in filenames:
                        if cancel_check and cancel_check():
                            return
                        if fn.startswith("$I") or fn.lower() in ("desktop.ini", "thumbs.db"):
                            continue
                        child = Path(dirpath) / fn
                        if str(child) in seen_paths:
                            continue
                        seen_paths.add(str(child))
                        orig_path = str(child)
                        del_dt = None
                        try:
                            st = child.stat()
                            fsize = st.st_size
                            if fsize <= 0:
                                continue
                            del_dt = datetime.fromtimestamp(st.st_mtime, tz=timezone.utc)
                        except OSError:
                            continue

                        if fn.startswith("$R"):
                            i_twin = child.with_name("$I" + fn[2:])
                            if i_twin.exists():
                                parsed_i = _parse_windows_recycle_bin_i_file(i_twin)
                                if parsed_i:
                                    orig_path, _, parsed_dt = parsed_i
                                    if parsed_dt:
                                        del_dt = parsed_dt

                        fname = sanitize_filename_only(Path(orig_path).name or fn)
                        if "." not in fname:
                            continue
                        ext = fname.rsplit(".", 1)[-1].upper()
                        cat_enum = categorize_extension(ext)
                        if allowed_categories and cat_enum.value not in allowed_categories:
                            continue

                        entry = RecoveredFileEntry(
                            id=f"recycle:{len(discovered) + 1}",
                            name=fname,
                            extension=ext,
                            size_bytes=fsize,
                            original_path=orig_path,
                            modified_time=del_dt,
                            recovery_method=RecoveryMethod.NTFS_MFT,
                            status=IntegrityStatus.GOOD,
                            status_detail="Deleted record metadata and clusters intact",
                            category=cat_enum,
                            source_device_path=str(child),
                            is_deleted=True,
                            selected=bool(allowed_categories),
                        )
                        discovered.append(entry)
                        scanned_count += 1
                        if progress_cb:
                            progress_cb(
                                min(max_items, scanned_count),
                                max_items,
                                f"Discovered deleted file {fname}",
                                discovered,
                            )
                        if len(discovered) >= max_items:
                            return
            except OSError:
                pass

    def run_scan(
        self,
        device: DeviceInfo,
        scan_mode: ScanMode = ScanMode.QUICK_SCAN,
        confirm_physical_access: bool = False,
        include_active_files: bool = False,
        resume_offset: int = 0,
        target_categories: Optional[Set[str]] = None,
        progress_cb: Optional[Callable[[int, int, str, List[RecoveredFileEntry]], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> Tuple[ScanSessionRecord, List[RecoveredFileEntry]]:
        allowed_cats: Optional[Set[str]] = None
        if target_categories and "All Files" not in target_categories:
            allowed_cats = set(target_categories)

        session_id = f"scan-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
        session = ScanSessionRecord(
            session_id=session_id,
            device_id=device.id,
            device_name=device.name,
            device_path=device.path,
            filesystem=device.filesystem,
            scan_mode=scan_mode.value,
            methods_used=[],
            start_time=datetime.now(timezone.utc).isoformat(),
            status="Running",
            last_offset=resume_offset,
            total_bytes=device.total_bytes,
        )
        self.db.save_session(session)

        discovered: List[RecoveredFileEntry] = []
        known_offsets: Set[int] = set()
        known_ranges: List[Tuple[int, int]] = []

        try:
            if device.path.startswith("adb://"):
                session.methods_used.append("Internal Storage Deleted Scanner")
                self._scan_adb_internal_storage(
                    device=device,
                    scan_mode=scan_mode,
                    discovered=discovered,
                    allowed_categories=allowed_cats,
                    progress_cb=progress_cb,
                    cancel_check=cancel_check,
                )
            elif device.path.startswith("wpd://"):
                session.methods_used.append("Internal Storage Deleted Scanner")
                self._scan_wpd_internal_storage(
                    device=device,
                    scan_mode=scan_mode,
                    discovered=discovered,
                    allowed_categories=allowed_cats,
                    progress_cb=progress_cb,
                    cancel_check=cancel_check,
                )
            elif device.path.startswith("iosbackup://"):
                session.methods_used.append("Internal Storage Deleted Scanner")
                self._scan_ios_backup_storage(
                    device=device,
                    scan_mode=scan_mode,
                    discovered=discovered,
                    allowed_categories=allowed_cats,
                    progress_cb=progress_cb,
                    cancel_check=cancel_check,
                )
            else:
                raw_succeeded = False
                try:
                    with ReadOnlyDeviceReader(device, confirm_physical_access=confirm_physical_access) as reader:
                        raw_succeeded = True
                        session.total_bytes = reader.size
                        part_offset = self._detect_partition_offset(reader)

                        if scan_mode in (ScanMode.QUICK_SCAN, ScanMode.DEEP_SCAN, ScanMode.SCAN_IMAGE_FILE):
                            parsers = [
                                ("NTFS MFT Parser", NTFSMftParser(reader, part_offset)),
                                ("FAT32 Directory Parser", FAT32Parser(reader, part_offset)),
                                ("exFAT Directory Parser", ExFATParser(reader, part_offset)),
                                ("EXT4 Inode & Extent Parser", EXT4Parser(reader, part_offset)),
                            ]
                            fs_matched = False
                            for label, parser in parsers:
                                if parser.detect():
                                    fs_matched = True
                                    session.methods_used.append(label)

                                    def _fs_prog(cur: int, tot: int, msg: str) -> None:
                                        if progress_cb:
                                            pct_cur = cur if scan_mode == ScanMode.QUICK_SCAN else cur // 2
                                            progress_cb(pct_cur, max(1, tot), msg, discovered)

                                    def _on_fs_entry(entry: RecoveredFileEntry) -> None:
                                        for r in entry.data_runs:
                                            known_offsets.add(r.device_offset)
                                            known_ranges.append((r.device_offset, r.device_offset + r.length))
                                        if allowed_cats and entry.category.value not in allowed_cats:
                                            return
                                        if entry.size_bytes > 0 and entry.status != IntegrityStatus.CORRUPTED:
                                            sample = entry.extract_bytes(reader, max_bytes=256 * 1024)
                                            v_status, v_detail = validate_recovered_bytes(sample, entry.extension)
                                            if v_status == IntegrityStatus.CORRUPTED:
                                                entry.status = IntegrityStatus.CORRUPTED
                                                entry.status_detail = v_detail
                                            elif v_status == IntegrityStatus.PARTIAL and entry.status == IntegrityStatus.GOOD:
                                                entry.status = IntegrityStatus.PARTIAL
                                                entry.status_detail = v_detail
                                            elif v_status == IntegrityStatus.GOOD and entry.status == IntegrityStatus.GOOD:
                                                entry.status_detail = f"{entry.status_detail} ({v_detail})"
                                        if allowed_cats:
                                            entry.selected = True
                                        discovered.append(entry)
                                        if progress_cb:
                                            progress_cb(len(discovered), max(1, len(discovered) + 10), f"Discovered {entry.name}", discovered)

                                    if isinstance(parser, (NTFSMftParser, EXT4Parser)):
                                        parser.scan_deleted(
                                            progress_cb=_fs_prog,
                                            cancel_check=cancel_check,
                                            include_active=False,
                                            on_entry_found=_on_fs_entry,
                                        )
                                    else:
                                        fs_entries = parser.scan_deleted(
                                            progress_cb=_fs_prog,
                                            cancel_check=cancel_check,
                                            include_active=False,
                                        )
                                        for entry in fs_entries:
                                            _on_fs_entry(entry)
                                    break

                            if not fs_matched and scan_mode == ScanMode.QUICK_SCAN:
                                session.warnings.append(
                                    "No intact NTFS, FAT32, exFAT, or EXT4 boot sector found; use Deep Scan for raw signature recovery."
                                )

                        run_carver = scan_mode in (ScanMode.DEEP_SCAN, ScanMode.FILE_CARVING) or (
                            scan_mode == ScanMode.SCAN_IMAGE_FILE and len(discovered) == 0
                        )
                        if scan_mode == ScanMode.SCAN_IMAGE_FILE and "Signature Carving Engine" not in session.methods_used:
                            run_carver = True

                        if run_carver and not (cancel_check and cancel_check()):
                            session.methods_used.append("Signature Carving Engine")
                            carver = FileCarver(reader, registry=self.registry)

                            def _carve_prog(cur: int, tot: int, msg: str) -> None:
                                session.last_offset = resume_offset + cur
                                if progress_cb:
                                    progress_cb(cur, max(1, tot), msg, discovered)

                            def _on_carved_entry(c_entry: RecoveredFileEntry) -> None:
                                if allowed_cats and c_entry.category.value not in allowed_cats:
                                    return
                                if allowed_cats:
                                    c_entry.selected = True
                                discovered.append(c_entry)
                                if progress_cb:
                                    progress_cb(session.last_offset, max(1, reader.size), f"Carved {c_entry.name}", discovered)

                            enabled_cat_enums: Optional[List[FileCategory]] = None
                            if allowed_cats:
                                enabled_cat_enums = [c for c in FileCategory if c.value in allowed_cats]

                            carver.scan(
                                start_offset=resume_offset,
                                known_offsets=known_offsets,
                                known_ranges=known_ranges,
                                enabled_categories=enabled_cat_enums,
                                progress_cb=_carve_prog,
                                cancel_check=cancel_check,
                                on_entry_found=_on_carved_entry,
                            )

                        session.last_offset = reader.size
                except DeviceAccessError as raw_exc:
                    if device.mount_point and os.path.isdir(device.mount_point) and not device.is_encrypted:
                        logger.info("Scanning deleted/recycle records on %s (%s)", device.name, raw_exc)
                        session.methods_used.append("Recycle Bin & Deleted Records Scanner")
                        session.warnings.append(
                            f"Raw sector access on {device.name} requires Administrator privileges; scanned Recycle Bin and deleted containers."
                        )
                        self._scan_mounted_volume_live(
                            device=device,
                            scan_mode=scan_mode,
                            discovered=discovered,
                            allowed_categories=allowed_cats,
                            progress_cb=progress_cb,
                            cancel_check=cancel_check,
                        )
                    else:
                        raise

                if (
                    raw_succeeded
                    and device.device_type.value != "Disk Image"
                    and device.mount_point
                    and os.path.isdir(device.mount_point)
                    and not (cancel_check and cancel_check())
                ):
                    self._scan_mounted_volume_live(
                        device=device,
                        scan_mode=scan_mode,
                        discovered=discovered,
                        allowed_categories=allowed_cats,
                        progress_cb=progress_cb,
                        cancel_check=cancel_check,
                    )

            if cancel_check and cancel_check():
                session.status = "Cancelled"
                session.warnings.append(f"Scan cancelled by user at offset 0x{session.last_offset:08X}.")
            else:
                session.status = "Completed"

        except Exception as exc:
            session.status = "Failed"
            session.errors.append(str(exc))
            logger.error("Scan failed on %s: %s", device.name, exc)
            raise
        finally:
            session.end_time = datetime.now(timezone.utc).isoformat()
            session.files_discovered = len(discovered)
            session.recoverable_bytes = sum(e.size_bytes for e in discovered)
            self.db.save_session(session)
            if discovered:
                self.db.save_findings(session.session_id, discovered)

        return (session, discovered)

    def recover_files(
        self,
        device: DeviceInfo,
        entries: List[RecoveredFileEntry],
        destination_dir: str,
        session_id: str = "manual-session",
        preserve_structure: bool = True,
        allow_same_device: bool = False,
        confirm_physical_access: bool = False,
        progress_cb: Optional[Callable[[int, int, str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> Tuple[RecoveryLogRecord, List[RecoveryOutcome]]:
        if is_same_storage_device(device, destination_dir) and not allow_same_device:
            raise DestinationSameDeviceError(
                f"Safety Warning: Destination '{destination_dir}' is on the same storage volume as "
                f"source '{device.name}'. Writing directly to the source volume risks overwriting "
                "recoverable deleted data."
            )

        dest_root = Path(destination_dir)
        dest_root.mkdir(parents=True, exist_ok=True)

        outcomes: List[RecoveryOutcome] = []
        warnings: List[str] = []
        if is_same_storage_device(device, destination_dir):
            warnings.append("User overrode same-device warning; files written to same logical volume.")

        succeeded = 0
        partial = 0
        skipped = 0
        failed = 0

        reader: Optional[ReadOnlyDeviceReader] = None
        try:
            if os.path.exists(device.path) and os.path.isfile(device.path):
                reader = ReadOnlyDeviceReader(device, confirm_physical_access=confirm_physical_access).open()
        except Exception:
            reader = None

        try:
            total = len(entries)
            for idx, entry in enumerate(entries, start=1):
                if cancel_check and cancel_check():
                    skipped += total - idx + 1
                    warnings.append("Recovery batch cancelled by user.")
                    break

                if progress_cb:
                    progress_cb(idx, total, f"Saving {entry.name}...")

                if entry.status == IntegrityStatus.CORRUPTED and entry.size_bytes == 0:
                    skipped += 1
                    outcomes.append(
                        RecoveryOutcome(
                            file_id=entry.id,
                            file_name=entry.name,
                            outcome="Skipped",
                            output_path="",
                            bytes_written=0,
                            sha256="",
                            verified_integrity=IntegrityStatus.CORRUPTED.value,
                            message="Skipped unrecoverable corrupted record (0 mapped bytes)",
                        )
                    )
                    continue

                if preserve_structure:
                    rel_path = category_subfolder_relpath(entry)
                else:
                    rel_path = Path(sanitize_filename_only(entry.name or entry.original_path))
                target_file = resolve_collision_path(dest_root / rel_path)

                try:
                    target_file.parent.mkdir(parents=True, exist_ok=True)
                    if reader is not None and (entry.resident_data is not None or entry.data_runs):
                        raw_data = entry.extract_bytes(reader)
                    elif entry.source_device_path and entry.source_device_path.startswith("adb://"):
                        raw_data = read_adb_file_bytes(entry.source_device_path)
                    elif entry.source_device_path and os.path.isfile(entry.source_device_path):
                        with open(entry.source_device_path, "rb") as src_fp:
                            raw_data = src_fp.read(entry.size_bytes)
                    else:
                        with ReadOnlyDeviceReader(device, confirm_physical_access=confirm_physical_access) as tmp_r:
                            raw_data = entry.extract_bytes(tmp_r)

                    with open(target_file, "wb") as out_fp:
                        out_fp.write(raw_data)

                    digest = hashlib.sha256(raw_data).hexdigest()
                    entry.sha256 = digest
                    v_status, v_detail = validate_recovered_bytes(raw_data, entry.extension)

                    if entry.modified_time is not None:
                        try:
                            ts = entry.modified_time.timestamp()
                            os.utime(target_file, (ts, ts))
                        except OSError:
                            pass

                    if entry.status == IntegrityStatus.PARTIAL or v_status in (
                        IntegrityStatus.PARTIAL,
                        IntegrityStatus.CORRUPTED,
                    ):
                        partial += 1
                        outcome_label = "Partial"
                    else:
                        succeeded += 1
                        outcome_label = "Succeeded"

                    outcomes.append(
                        RecoveryOutcome(
                            file_id=entry.id,
                            file_name=entry.name,
                            outcome=outcome_label,
                            output_path=str(target_file),
                            bytes_written=len(raw_data),
                            sha256=digest,
                            verified_integrity=v_status.value,
                            message=v_detail,
                        )
                    )
                except OSError as exc:
                    failed += 1
                    outcomes.append(
                        RecoveryOutcome(
                            file_id=entry.id,
                            file_name=entry.name,
                            outcome="Failed",
                            output_path=str(target_file),
                            bytes_written=0,
                            sha256="",
                            verified_integrity="Write Error",
                            message=f"Destination write failed: {exc}",
                        )
                    )
        finally:
            if reader is not None:
                reader.close()

        log_record = RecoveryLogRecord(
            recovery_id=f"rec-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}",
            session_id=session_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            source_device=f"{device.name} ({device.path})",
            destination_dir=str(dest_root),
            total_selected=len(entries),
            succeeded=succeeded,
            partial=partial,
            skipped=skipped,
            failed=failed,
            file_outcomes=[
                {
                    "file_id": o.file_id,
                    "file_name": o.file_name,
                    "outcome": o.outcome,
                    "output_path": o.output_path,
                    "bytes_written": o.bytes_written,
                    "sha256": o.sha256,
                    "verified_integrity": o.verified_integrity,
                    "message": o.message,
                }
                for o in outcomes
            ],
            warnings=warnings,
        )
        self.db.save_recovery_log(log_record)
        return (log_record, outcomes)
