"""exFAT Directory Entry Set, Stream Extension, and Cluster Heap Recovery Parser."""
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
from .fat32 import dos_datetime_to_dt

logger = logging.getLogger("recoverx.filesystems.exfat")


class ExFATParser(FileSystemParser):
    """
    Parses exFAT volumes per Microsoft exFAT specification:
    - Validates `EXFAT   ` OEM signature in Main Boot Sector.
    - Computes `fat_offset`, `cluster_heap_offset`, `cluster_size`, and `root_dir_cluster`.
    - Scans directory entry sets for deleted File Directory Entries (`0x05`),
      deleted Stream Extension Entries (`0x40`), and deleted File Name Entries (`0x41`),
      as well as active sets (`0x85`, `0xC0`, `0xC1`) when requested.
    """

    def __init__(self, reader: ReadOnlyDeviceReader, partition_offset: int = 0):
        super().__init__(reader, partition_offset)
        self.bytes_per_sector: int = 512
        self.sectors_per_cluster: int = 8
        self.cluster_size: int = 4096
        self.fat_offset_bytes: int = 0
        self.fat_length_bytes: int = 0
        self.cluster_heap_offset_bytes: int = 0
        self.cluster_count: int = 0
        self.root_dir_cluster: int = 2

    def detect(self) -> bool:
        boot = self.reader.read_at(self.partition_offset, 512)
        if len(boot) < 512 or boot[3:11] != b"EXFAT   ":
            return False
        return self._parse_bpb(boot)

    def _parse_bpb(self, boot: bytes) -> bool:
        try:
            fat_off_sec = struct.unpack_from("<I", boot, 80)[0]
            fat_len_sec = struct.unpack_from("<I", boot, 84)[0]
            heap_off_sec = struct.unpack_from("<I", boot, 88)[0]
            self.cluster_count = struct.unpack_from("<I", boot, 92)[0]
            self.root_dir_cluster = struct.unpack_from("<I", boot, 96)[0]
            bps_shift = boot[108]
            spc_shift = boot[109]
            if not (9 <= bps_shift <= 12) or spc_shift > 25:
                return False
            self.bytes_per_sector = 1 << bps_shift
            self.sectors_per_cluster = 1 << spc_shift
            self.cluster_size = self.bytes_per_sector * self.sectors_per_cluster
            self.fat_offset_bytes = self.partition_offset + (fat_off_sec * self.bytes_per_sector)
            self.fat_length_bytes = fat_len_sec * self.bytes_per_sector
            self.cluster_heap_offset_bytes = self.partition_offset + (heap_off_sec * self.bytes_per_sector)
            return self.cluster_count > 0 and self.root_dir_cluster >= 2
        except struct.error:
            return False

    def cluster_to_offset(self, cluster: int) -> int:
        return self.cluster_heap_offset_bytes + (cluster - 2) * self.cluster_size

    def _read_fat(self) -> List[int]:
        to_read = min(self.fat_length_bytes, 16 * 1024 * 1024)
        raw = self.reader.read_at(self.fat_offset_bytes, to_read)
        count = len(raw) // 4
        if count == 0:
            return []
        return list(struct.unpack(f"<{count}I", raw[: count * 4]))

    def _build_runs(
        self,
        fat: List[int],
        first_cluster: int,
        data_length: int,
        no_fat_chain: bool,
    ) -> Tuple[List[DataRun], IntegrityStatus, str]:
        if data_length == 0:
            return ([], IntegrityStatus.GOOD, "Empty 0-byte file")
        if first_cluster < 2 or first_cluster >= self.cluster_count + 2:
            return ([], IntegrityStatus.CORRUPTED, f"Invalid first cluster ({first_cluster})")

        needed_clusters = (data_length + self.cluster_size - 1) // self.cluster_size
        if no_fat_chain or first_cluster >= len(fat) or fat[first_cluster] == 0:
            avail_clusters = min(needed_clusters, max(0, (self.cluster_count + 2) - first_cluster))
            byte_len = avail_clusters * self.cluster_size
            runs = [DataRun(device_offset=self.cluster_to_offset(first_cluster), length=byte_len)]
            if byte_len < data_length:
                return (runs, IntegrityStatus.PARTIAL, f"Contiguous stream truncated ({byte_len} of {data_length} B)")
            return (runs, IntegrityStatus.GOOD, "exFAT contiguous stream clusters intact")

        # Follow FAT chain
        clusters = []
        curr = first_cluster
        visited = set()
        while 2 <= curr < len(fat) and curr not in visited and len(clusters) < needed_clusters:
            visited.add(curr)
            clusters.append(curr)
            nxt = fat[curr]
            if nxt in (0, 0xFFFFFFF7, 0xFFFFFFFF) or nxt >= 0xFFFFFFF8:
                break
            curr = nxt

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
        total_mapped = sum(r.length for r in runs)
        if total_mapped < data_length:
            return (runs, IntegrityStatus.PARTIAL, f"Partial exFAT cluster chain ({total_mapped} of {data_length} B)")
        return (runs, IntegrityStatus.GOOD, "exFAT FAT cluster chain intact")

    def scan_deleted(
        self,
        progress_cb: Optional[Callable[[int, int, str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        include_active: bool = False,
    ) -> List[RecoveredFileEntry]:
        if not self.detect():
            return []

        fat = self._read_fat()
        results: List[RecoveredFileEntry] = []
        visited_dirs: Set[int] = set()
        dir_queue: List[Tuple[int, str]] = [(self.root_dir_cluster, "E:\\")]

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
                progress_cb(steps, max(steps + len(dir_queue), 8), f"Scanning exFAT directory {dir_path}")

            dir_bytes = self.reader.read_at(self.cluster_to_offset(dir_clus), self.cluster_size * 4)
            idx = 0
            n = len(dir_bytes)

            while idx + 32 <= n:
                etype = dir_bytes[idx]
                if etype == 0x00:
                    break

                # File Directory Entry: 0x85 (in-use) or 0x05 (deleted)
                if etype in (0x05, 0x85):
                    is_deleted = etype == 0x05
                    secondary_count = dir_bytes[idx + 1]
                    file_attrs = struct.unpack_from("<H", dir_bytes, idx + 4)[0]
                    is_dir = bool(file_attrs & 0x0010)
                    create_ts = struct.unpack_from("<I", dir_bytes, idx + 8)[0]
                    mod_ts = struct.unpack_from("<I", dir_bytes, idx + 12)[0]
                    created_dt = dos_datetime_to_dt((create_ts >> 16) & 0xFFFF, create_ts & 0xFFFF)
                    modified_dt = dos_datetime_to_dt((mod_ts >> 16) & 0xFFFF, mod_ts & 0xFFFF) or created_dt

                    # Parse secondary entries (Stream Extension 0x40/0xC0 + File Name 0x41/0xC1)
                    stream_flags = 0
                    first_cluster = 0
                    valid_data_len = 0
                    data_len = 0
                    name_parts: List[str] = []
                    expected_name_len = 0
                    has_stream = False

                    max_sec = min(secondary_count, (n - idx) // 32 - 1)
                    for s in range(1, max_sec + 1):
                        sec = dir_bytes[idx + s * 32 : idx + (s + 1) * 32]
                        stype = sec[0]
                        if stype in (0x40, 0xC0):
                            has_stream = True
                            stream_flags = sec[1]
                            expected_name_len = sec[3]
                            valid_data_len = struct.unpack_from("<Q", sec, 8)[0]
                            first_cluster = struct.unpack_from("<I", sec, 20)[0]
                            data_len = struct.unpack_from("<Q", sec, 24)[0]
                        elif stype in (0x41, 0xC1):
                            raw_fn = sec[2:32]
                            part = raw_fn.decode("utf-16le", errors="ignore").rstrip("\x00")
                            name_parts.append(part)

                    full_name = "".join(name_parts)
                    if expected_name_len > 0:
                        full_name = full_name[:expected_name_len]

                    if has_stream and full_name:
                        no_fat_chain = bool(stream_flags & 0x02)
                        actual_size = valid_data_len if valid_data_len > 0 else data_len
                        if is_dir:
                            if first_cluster >= 2 and first_cluster not in visited_dirs:
                                dir_queue.append((first_cluster, f"{dir_path}{full_name}\\"))
                        elif is_deleted or include_active:
                            runs, status, status_detail = self._build_runs(
                                fat, first_cluster, actual_size, no_fat_chain
                            )
                            ext = full_name.rsplit(".", 1)[-1].upper() if "." in full_name else ""
                            results.append(
                                RecoveredFileEntry(
                                    id=f"exfat:{dir_clus}:{idx}",
                                    name=full_name,
                                    extension=ext,
                                    size_bytes=actual_size,
                                    original_path=f"{dir_path}{full_name}",
                                    modified_time=modified_dt,
                                    created_time=created_dt,
                                    recovery_method=RecoveryMethod.EXFAT_DIR,
                                    status=status,
                                    status_detail=status_detail,
                                    data_runs=runs,
                                    source_device_path=self.reader.device.path,
                                    inode_or_cluster=first_cluster,
                                    is_deleted=is_deleted,
                                )
                            )
                    idx += (max_sec + 1) * 32
                    continue

                idx += 32

        return results
