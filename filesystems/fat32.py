"""FAT32 Directory Entry, VFAT Long File Name, and Cluster Chain Recovery Parser."""
from __future__ import annotations

import logging
import struct
from datetime import datetime, timezone
from typing import Callable, List, Optional, Set, Tuple

from devices.reader import ReadOnlyDeviceReader
from .base import (
    DataRun,
    FileSystemParser,
    IntegrityStatus,
    RecoveredFileEntry,
    RecoveryMethod,
)

logger = logging.getLogger("recoverx.filesystems.fat32")


def dos_datetime_to_dt(date_word: int, time_word: int) -> Optional[datetime]:
    if date_word == 0:
        return None
    year = ((date_word >> 9) & 0x7F) + 1980
    month = (date_word >> 5) & 0x0F
    day = date_word & 0x1F
    hour = (time_word >> 11) & 0x1F
    minute = (time_word >> 5) & 0x3F
    second = (time_word & 0x1F) * 2
    try:
        return datetime(year, max(1, min(12, month)), max(1, min(31, day)), min(23, hour), min(59, minute), min(59, second), tzinfo=timezone.utc)
    except ValueError:
        return None


def extract_lfn_chars(entry: bytes) -> str:
    """Extract 13 UTF-16LE characters from a 32-byte VFAT Long File Name directory entry."""
    raw_utf16 = entry[1:11] + entry[14:26] + entry[28:32]
    chars = []
    for i in range(0, len(raw_utf16), 2):
        code = struct.unpack_from("<H", raw_utf16, i)[0]
        if code in (0x0000, 0xFFFF):
            break
        chars.append(chr(code))
    return "".join(chars)


class FAT32Parser(FileSystemParser):
    """
    Parses FAT32 volumes:
    - Reads BIOS Parameter Block (BPB) and File Allocation Table (FAT1).
    - Walks directory cluster chains starting at `BPB_RootClus`.
    - Reconstructs VFAT Long File Names (attribute `0x0F`) for both active and deleted (`0xE5`) entries.
    - Recovers deleted `0xE5` directory entries using FAT cluster chains or contiguous unallocated cluster runs.
    """

    def __init__(self, reader: ReadOnlyDeviceReader, partition_offset: int = 0):
        super().__init__(reader, partition_offset)
        self.bytes_per_sector: int = 512
        self.sectors_per_cluster: int = 8
        self.reserved_sectors: int = 32
        self.num_fats: int = 2
        self.sectors_per_fat: int = 0
        self.root_cluster: int = 2
        self.cluster_size: int = 4096
        self.fat_offset: int = 0
        self.data_heap_offset: int = 0
        self.total_clusters: int = 0

    def detect(self) -> bool:
        boot = self.reader.read_at(self.partition_offset, 512)
        if len(boot) < 512 or boot[510:512] != b"\x55\xaa":
            return False
        if boot[82:90] != b"FAT32   ":
            return False
        return self._parse_bpb(boot)

    def _parse_bpb(self, boot: bytes) -> bool:
        try:
            self.bytes_per_sector = struct.unpack_from("<H", boot, 11)[0]
            self.sectors_per_cluster = boot[13]
            self.reserved_sectors = struct.unpack_from("<H", boot, 14)[0]
            self.num_fats = boot[16]
            total_sec_16 = struct.unpack_from("<H", boot, 19)[0]
            total_sec_32 = struct.unpack_from("<I", boot, 32)[0]
            total_sectors = total_sec_32 if total_sec_32 > 0 else total_sec_16
            self.sectors_per_fat = struct.unpack_from("<I", boot, 36)[0]
            self.root_cluster = struct.unpack_from("<I", boot, 44)[0]

            if self.bytes_per_sector not in (512, 1024, 2048, 4096) or self.sectors_per_cluster == 0:
                return False
            self.cluster_size = self.bytes_per_sector * self.sectors_per_cluster
            self.fat_offset = self.partition_offset + (self.reserved_sectors * self.bytes_per_sector)
            data_start_sector = self.reserved_sectors + (self.num_fats * self.sectors_per_fat)
            self.data_heap_offset = self.partition_offset + (data_start_sector * self.bytes_per_sector)
            data_sectors = max(0, total_sectors - data_start_sector)
            self.total_clusters = data_sectors // self.sectors_per_cluster
            return self.sectors_per_fat > 0 and self.root_cluster >= 2
        except struct.error:
            return False

    def cluster_to_offset(self, cluster: int) -> int:
        return self.data_heap_offset + (cluster - 2) * self.cluster_size

    def _read_fat_table(self) -> List[int]:
        fat_bytes_len = min(self.sectors_per_fat * self.bytes_per_sector, 16 * 1024 * 1024)
        raw = self.reader.read_at(self.fat_offset, fat_bytes_len)
        count = len(raw) // 4
        if count == 0:
            return []
        return [x & 0x0FFFFFFF for x in struct.unpack(f"<{count}I", raw[: count * 4])]

    def _get_cluster_chain(self, fat: List[int], start_cluster: int, max_clusters: int = 16384) -> List[int]:
        chain = []
        curr = start_cluster
        visited = set()
        while 2 <= curr < len(fat) and curr not in visited and len(chain) < max_clusters:
            visited.add(curr)
            chain.append(curr)
            nxt = fat[curr]
            if nxt >= 0x0FFFFFF8 or nxt == 0:
                break
            curr = nxt
        return chain

    def _build_runs_for_deleted(
        self,
        fat: List[int],
        first_cluster: int,
        file_size: int,
    ) -> Tuple[List[DataRun], IntegrityStatus, str]:
        if file_size == 0:
            return ([], IntegrityStatus.GOOD, "Empty 0-byte file")
        if first_cluster < 2 or first_cluster >= self.total_clusters + 2:
            return ([], IntegrityStatus.CORRUPTED, f"Invalid starting cluster ({first_cluster})")

        needed_clusters = (file_size + self.cluster_size - 1) // self.cluster_size
        # When FAT32 deletes a file, it typically zeroes its FAT entries (fat[c] == 0).
        # If FAT still holds a chain, follow it; otherwise walk contiguous unallocated (fat[c] == 0) clusters.
        clusters: List[int] = []
        if first_cluster < len(fat) and fat[first_cluster] not in (0, 0x0FFFFFF7):
            clusters = self._get_cluster_chain(fat, first_cluster, max_clusters=needed_clusters)

        reallocated_conflict = False
        if len(clusters) < needed_clusters:
            clusters = []
            for c in range(first_cluster, min(self.total_clusters + 2, first_cluster + needed_clusters)):
                if c < len(fat) and fat[c] not in (0, 0x0FFFFFF8, 0x0FFFFFFF) and c != first_cluster:
                    reallocated_conflict = True
                    break
                clusters.append(c)

        if not clusters:
            return ([], IntegrityStatus.CORRUPTED, "All clusters reallocated")

        # Coalesce contiguous clusters into DataRuns
        runs: List[DataRun] = []
        run_start = clusters[0]
        run_len = 1
        for c in clusters[1:]:
            if c == run_start + run_len:
                run_len += 1
            else:
                runs.append(DataRun(device_offset=self.cluster_to_offset(run_start), length=run_len * self.cluster_size))
                run_start = c
                run_len = 1
        runs.append(DataRun(device_offset=self.cluster_to_offset(run_start), length=run_len * self.cluster_size))

        total_bytes = sum(r.length for r in runs)
        if reallocated_conflict or total_bytes < file_size:
            return (
                runs,
                IntegrityStatus.PARTIAL,
                f"Recovered {min(total_bytes, file_size)} of {file_size} bytes (subsequent clusters reallocated)",
            )
        return (runs, IntegrityStatus.GOOD, "Deleted directory entry and contiguous clusters intact")

    def scan_deleted(
        self,
        progress_cb: Optional[Callable[[int, int, str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        include_active: bool = False,
    ) -> List[RecoveredFileEntry]:
        if not self.detect():
            return []

        fat = self._read_fat_table()
        results: List[RecoveredFileEntry] = []
        visited_dirs: Set[int] = set()
        dir_queue: List[Tuple[int, str]] = [(self.root_cluster, "E:\\")]

        steps = 0
        while dir_queue:
            if cancel_check and cancel_check():
                return []
            dir_clus, dir_path = dir_queue.pop(0)
            if dir_clus in visited_dirs or dir_clus < 2:
                continue
            visited_dirs.add(dir_clus)
            steps += 1
            if progress_cb:
                progress_cb(steps, max(steps + len(dir_queue), 10), f"Scanning FAT32 directory {dir_path}")

            chain = self._get_cluster_chain(fat, dir_clus, max_clusters=256)
            if not chain:
                chain = [dir_clus]

            dir_buf = bytearray()
            for c in chain:
                dir_buf.extend(self.reader.read_at(self.cluster_to_offset(c), self.cluster_size))

            lfn_parts: List[str] = []
            for off in range(0, len(dir_buf), 32):
                entry = bytes(dir_buf[off : off + 32])
                first_byte = entry[0]
                if first_byte == 0x00:
                    break
                attr = entry[11]
                # VFAT LFN entry
                if attr == 0x0F:
                    part = extract_lfn_chars(entry)
                    lfn_parts.insert(0, part)
                    continue

                # Volume label or special entry
                if attr & 0x08:
                    lfn_parts.clear()
                    continue

                is_deleted = first_byte == 0xE5
                is_dir = bool(attr & 0x10)

                # Decode 8.3 short name
                raw_base = entry[0:8]
                raw_ext = entry[8:11]
                if is_deleted:
                    # First character was overwritten by 0xE5; restore with '_' if no LFN
                    base_str = "_" + raw_base[1:].decode("latin-1", errors="ignore").rstrip()
                else:
                    base_str = raw_base.decode("latin-1", errors="ignore").rstrip()
                ext_str = raw_ext.decode("latin-1", errors="ignore").rstrip()
                short_name = f"{base_str}.{ext_str}" if ext_str else base_str

                full_name = "".join(lfn_parts).strip() if lfn_parts else short_name
                lfn_parts.clear()

                if full_name in (".", "..", ""):
                    continue

                hi_clus = struct.unpack_from("<H", entry, 20)[0]
                lo_clus = struct.unpack_from("<H", entry, 26)[0]
                first_cluster = (hi_clus << 16) | lo_clus
                file_size = struct.unpack_from("<I", entry, 28)[0]

                c_time = struct.unpack_from("<H", entry, 14)[0]
                c_date = struct.unpack_from("<H", entry, 16)[0]
                m_time = struct.unpack_from("<H", entry, 22)[0]
                m_date = struct.unpack_from("<H", entry, 24)[0]
                created_dt = dos_datetime_to_dt(c_date, c_time)
                modified_dt = dos_datetime_to_dt(m_date, m_time) or created_dt

                if is_dir:
                    if first_cluster >= 2 and first_cluster not in visited_dirs:
                        dir_queue.append((first_cluster, f"{dir_path}{full_name}\\"))
                    continue

                if is_deleted or include_active:
                    runs, status, status_detail = self._build_runs_for_deleted(fat, first_cluster, file_size)
                    ext = full_name.rsplit(".", 1)[-1].upper() if "." in full_name else ext_str.upper()
                    results.append(
                        RecoveredFileEntry(
                            id=f"fat32:{dir_clus}:{off}",
                            name=full_name,
                            extension=ext,
                            size_bytes=file_size,
                            original_path=f"{dir_path}{full_name}",
                            modified_time=modified_dt,
                            created_time=created_dt,
                            recovery_method=RecoveryMethod.FAT32_DIR,
                            status=status,
                            status_detail=status_detail,
                            data_runs=runs,
                            source_device_path=self.reader.device.path,
                            inode_or_cluster=first_cluster,
                            is_deleted=is_deleted,
                        )
                    )

        return results
