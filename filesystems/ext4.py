"""EXT4 Superblock, Group Descriptor, Unlinked Directory Slack, and Extent Tree Recovery Parser."""
from __future__ import annotations

import logging
import struct
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Tuple

from devices.reader import ReadOnlyDeviceReader
from .base import (
    DataRun,
    FileSystemParser,
    IntegrityStatus,
    RecoveredFileEntry,
    RecoveryMethod,
)

logger = logging.getLogger("recoverx.filesystems.ext4")

EXT4_SUPER_MAGIC = 0xEF53
EXT4_EXTENT_MAGIC = 0xF30A
EXT4_EXTENTS_FL = 0x00080000
S_IFMT = 0xF000
S_IFREG = 0x8000
S_IFDIR = 0x4000


class EXT4Parser(FileSystemParser):
    """
    Parses Linux / Android EXT4 filesystems:
    - Validates EXT4 Superblock at `partition_offset + 1024` (`s_magic == 0xEF53`).
    - Reads Block Group Descriptors (32-byte or 64-byte) to locate Inode Tables.
    - Scans directory blocks (including slack space inside `rec_len` gaps) to recover
      original filenames of unlinked/deleted directory entries.
    - Parses deleted inodes (`i_dtime > 0` or `i_links_count == 0` with non-zero size
      and intact extent tree `0xF30A` or direct block pointers) in 256 KB buffered batches.
    """

    def __init__(self, reader: ReadOnlyDeviceReader, partition_offset: int = 0):
        super().__init__(reader, partition_offset)
        self.inodes_count: int = 0
        self.blocks_count: int = 0
        self.block_size: int = 4096
        self.blocks_per_group: int = 32768
        self.inodes_per_group: int = 8192
        self.inode_size: int = 256
        self.desc_size: int = 32
        self.first_data_block: int = 0
        self.feature_incompat: int = 0

    def detect(self) -> bool:
        sb = self.reader.read_at(self.partition_offset + 1024, 1024)
        if len(sb) < 256:
            return False
        magic = struct.unpack_from("<H", sb, 0x38)[0]
        if magic != EXT4_SUPER_MAGIC:
            return False

        self.inodes_count = struct.unpack_from("<I", sb, 0x00)[0]
        blocks_lo = struct.unpack_from("<I", sb, 0x04)[0]
        self.first_data_block = struct.unpack_from("<I", sb, 0x14)[0]
        log_block_size = struct.unpack_from("<I", sb, 0x18)[0]
        if log_block_size > 6:
            return False
        self.block_size = 1024 << log_block_size
        self.blocks_per_group = struct.unpack_from("<I", sb, 0x20)[0]
        self.inodes_per_group = struct.unpack_from("<I", sb, 0x28)[0]
        rev_level = struct.unpack_from("<I", sb, 0x4C)[0]
        if rev_level >= 1:
            self.inode_size = struct.unpack_from("<H", sb, 0x58)[0] or 128
            self.feature_incompat = struct.unpack_from("<I", sb, 0x60)[0]
            if self.feature_incompat & 0x80:  # INCOMPAT_64BIT
                desc_sz = struct.unpack_from("<H", sb, 0xFE)[0]
                self.desc_size = desc_sz if desc_sz in (32, 64) else 64
                blocks_hi = struct.unpack_from("<I", sb, 0x150)[0]
                self.blocks_count = (blocks_hi << 32) | blocks_lo
            else:
                self.desc_size = 32
                self.blocks_count = blocks_lo
        else:
            self.inode_size = 128
            self.desc_size = 32
            self.blocks_count = blocks_lo

        return self.inodes_count > 0 and self.blocks_count > 0 and self.inodes_per_group > 0

    def _read_group_inode_tables(self) -> List[int]:
        if self.blocks_per_group <= 0:
            return []
        num_groups = max(1, (self.blocks_count + self.blocks_per_group - 1) // self.blocks_per_group)
        num_groups = min(num_groups, 4096)
        gdt_block = 2 if self.block_size == 1024 else 1
        gdt_offset = self.partition_offset + gdt_block * self.block_size
        gdt_bytes = self.reader.read_at(gdt_offset, num_groups * self.desc_size)

        inode_tables: List[int] = []
        for g in range(num_groups):
            base = g * self.desc_size
            if base + 32 > len(gdt_bytes):
                break
            it_lo = struct.unpack_from("<I", gdt_bytes, base + 0x08)[0]
            it_hi = 0
            if self.desc_size >= 64 and base + 64 <= len(gdt_bytes):
                it_hi = struct.unpack_from("<I", gdt_bytes, base + 0x28)[0]
            it_block = (it_hi << 32) | it_lo
            if 0 < it_block < self.blocks_count:
                inode_tables.append(it_block)
        return inode_tables

    def _parse_inode_runs(self, raw_inode: bytes, file_size: int) -> List[DataRun]:
        if len(raw_inode) < 100 or file_size <= 0:
            return []
        flags = struct.unpack_from("<I", raw_inode, 0x20)[0]
        i_block = raw_inode[0x28 : 0x28 + 60]
        runs: List[DataRun] = []

        # 1. EXT4 Extent Tree (eh_magic == 0xF30A)
        eh_magic, eh_entries, _eh_max, eh_depth = struct.unpack_from("<HHHH", i_block, 0)
        if (flags & EXT4_EXTENTS_FL) or eh_magic == EXT4_EXTENT_MAGIC:
            if eh_magic != EXT4_EXTENT_MAGIC:
                return []
            if eh_depth == 0:
                for idx in range(min(4, eh_entries)):
                    off = 12 + idx * 12
                    if off + 12 > len(i_block):
                        break
                    _ee_block, ee_len, ee_start_hi, ee_start_lo = struct.unpack_from("<IHHI", i_block, off)
                    actual_blocks = ee_len & 0x7FFF
                    start_blk = (ee_start_hi << 32) | ee_start_lo
                    if actual_blocks > 0 and 0 < start_blk < self.blocks_count:
                        runs.append(
                            DataRun(
                                device_offset=self.partition_offset + start_blk * self.block_size,
                                length=actual_blocks * self.block_size,
                            )
                        )
            elif eh_depth == 1 and eh_entries > 0:
                # Single-level extent index node
                _ei_block, ei_leaf_lo, ei_leaf_hi, _unused = struct.unpack_from("<IIHH", i_block, 12)
                leaf_blk = (ei_leaf_hi << 32) | ei_leaf_lo
                if 0 < leaf_blk < self.blocks_count:
                    leaf_data = self.reader.read_at(
                        self.partition_offset + leaf_blk * self.block_size,
                        self.block_size,
                    )
                    if len(leaf_data) >= 24:
                        l_magic, l_entries, _l_max, l_depth = struct.unpack_from("<HHHH", leaf_data, 0)
                        if l_magic == EXT4_EXTENT_MAGIC and l_depth == 0:
                            for idx in range(min(128, l_entries)):
                                off = 12 + idx * 12
                                if off + 12 > len(leaf_data):
                                    break
                                _eb, elen, es_hi, es_lo = struct.unpack_from("<IHHI", leaf_data, off)
                                ab = elen & 0x7FFF
                                sblk = (es_hi << 32) | es_lo
                                if ab > 0 and 0 < sblk < self.blocks_count:
                                    runs.append(
                                        DataRun(
                                            device_offset=self.partition_offset + sblk * self.block_size,
                                            length=ab * self.block_size,
                                        )
                                    )
            return runs

        # 2. Direct Block Pointers (i_block[0..11])
        for idx in range(12):
            blk = struct.unpack_from("<I", i_block, idx * 4)[0]
            if blk == 0 or blk >= self.blocks_count:
                break
            dev_off = self.partition_offset + blk * self.block_size
            if runs and runs[-1].device_offset + runs[-1].length == dev_off:
                runs[-1].length += self.block_size
            else:
                runs.append(DataRun(device_offset=dev_off, length=self.block_size))
        return runs

    def _scan_directory_block_for_names(
        self,
        block_bytes: bytes,
        parent_path: str,
        inode_names: Dict[int, Tuple[str, str]],
    ) -> None:
        pos = 0
        limit = len(block_bytes)
        while pos + 8 <= limit:
            inode_num, rec_len, name_len, file_type = struct.unpack_from("<IHBB", block_bytes, pos)
            if rec_len < 8 or pos + rec_len > limit:
                break
            if name_len > 0 and pos + 8 + name_len <= limit:
                raw_name = block_bytes[pos + 8 : pos + 8 + name_len].decode("utf-8", errors="ignore").strip("\x00")
                if raw_name and raw_name not in (".", "..") and inode_num > 0:
                    inode_names[inode_num] = (raw_name, f"{parent_path}/{raw_name}")

            # Check slack space inside rec_len for unlinked/deleted directory entries
            actual_entry_len = ((8 + name_len + 3) // 4) * 4
            slack_pos = pos + actual_entry_len
            while slack_pos + 8 < pos + rec_len:
                d_ino, d_rec_len, d_name_len, _d_ft = struct.unpack_from("<IHBB", block_bytes, slack_pos)
                if d_name_len == 0 or slack_pos + 8 + d_name_len > pos + rec_len:
                    break
                cand_name = block_bytes[slack_pos + 8 : slack_pos + 8 + d_name_len].decode("utf-8", errors="ignore").strip("\x00")
                if cand_name and cand_name not in (".", "..") and all(32 <= ord(c) < 127 for c in cand_name):
                    if d_ino > 0 and d_ino <= self.inodes_count:
                        inode_names[d_ino] = (cand_name, f"{parent_path}/{cand_name}")
                    step = ((8 + d_name_len + 3) // 4) * 4
                    slack_pos += max(8, step)
                else:
                    break

            pos += rec_len

    @staticmethod
    def _guess_extension_from_magic(header: bytes) -> str:
        if header.startswith(b"\xff\xd8\xff"):
            return "JPG"
        if header.startswith(b"\x89PNG\r\n\x1a\n"):
            return "PNG"
        if header.startswith(b"%PDF-"):
            return "PDF"
        if len(header) >= 12 and header[4:8] == b"ftyp":
            brand = header[8:12]
            if brand in (b"heic", b"heix", b"mif1"):
                return "HEIC"
            if brand == b"qt  ":
                return "MOV"
            return "MP4"
        if header.startswith(b"PK\x03\x04"):
            return "ZIP"
        if header.startswith(b"ID3") or header[:2] in (b"\xff\xfb", b"\xff\xf3"):
            return "MP3"
        if header.startswith(b"RIFF") and header[8:12] == b"WAVE":
            return "WAV"
        if header.startswith(b"SQLite format 3"):
            return "DB"
        return "BIN"

    def scan_deleted(
        self,
        progress_cb: Optional[Callable[[int, int, str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        include_active: bool = False,
        on_entry_found: Optional[Callable[[RecoveredFileEntry], None]] = None,
    ) -> List[RecoveredFileEntry]:
        if not self.detect():
            return []

        inode_tables = self._read_group_inode_tables()
        if not inode_tables:
            return []

        inode_names: Dict[int, Tuple[str, str]] = {}
        entries: List[RecoveredFileEntry] = []

        # Pass 1: Read root & top-level directory blocks to map deleted filenames in directory slack
        first_it_off = self.partition_offset + inode_tables[0] * self.block_size
        root_inode_raw = self.reader.read_at(first_it_off + self.inode_size, self.inode_size)
        if len(root_inode_raw) >= 128:
            root_size = struct.unpack_from("<I", root_inode_raw, 0x04)[0]
            root_runs = self._parse_inode_runs(root_inode_raw, max(self.block_size, root_size))
            for r in root_runs[:8]:
                dir_bytes = self.reader.read_at(r.device_offset, min(r.length, self.block_size * 4))
                for b_off in range(0, len(dir_bytes), self.block_size):
                    self._scan_directory_block_for_names(
                        dir_bytes[b_off : b_off + self.block_size],
                        "/userdata",
                        inode_names,
                    )

        # Pass 2: Scan Inode Tables in 256 KB buffered batches for deleted files
        batch_bytes = 256 * 1024
        inodes_per_batch = max(1, batch_bytes // self.inode_size)
        total_groups = len(inode_tables)

        for g_idx, it_block in enumerate(inode_tables):
            if cancel_check and cancel_check():
                break
            group_base_inode = g_idx * self.inodes_per_group + 1
            table_byte_off = self.partition_offset + it_block * self.block_size
            idx_in_group = 0
            max_group_inodes = min(self.inodes_per_group, 16384)

            while idx_in_group < max_group_inodes:
                if cancel_check and cancel_check():
                    break
                count = min(inodes_per_batch, max_group_inodes - idx_in_group)
                buf = self.reader.read_at(
                    table_byte_off + idx_in_group * self.inode_size,
                    count * self.inode_size,
                )
                if len(buf) < self.inode_size:
                    break

                actual_cnt = len(buf) // self.inode_size
                for k in range(actual_cnt):
                    ino_num = group_base_inode + idx_in_group + k
                    if ino_num < 11:
                        continue
                    raw_ino = buf[k * self.inode_size : (k + 1) * self.inode_size]
                    i_mode = struct.unpack_from("<H", raw_ino, 0x00)[0]
                    size_lo = struct.unpack_from("<I", raw_ino, 0x04)[0]
                    i_mtime = struct.unpack_from("<I", raw_ino, 0x10)[0]
                    i_dtime = struct.unpack_from("<I", raw_ino, 0x14)[0]
                    i_links = struct.unpack_from("<H", raw_ino, 0x1A)[0]
                    size_hi = struct.unpack_from("<I", raw_ino, 0x6C)[0] if len(raw_ino) >= 0x70 else 0
                    file_size = (size_hi << 32) | size_lo

                    # If this is a directory inode, scan its first block for slack entries
                    if (i_mode & S_IFMT) == S_IFDIR and file_size > 0:
                        d_runs = self._parse_inode_runs(raw_ino, self.block_size)
                        if d_runs:
                            d_blk = self.reader.read_at(d_runs[0].device_offset, self.block_size)
                            _, dir_path = inode_names.get(ino_num, ("dir", f"/userdata/dir_{ino_num}"))
                            self._scan_directory_block_for_names(d_blk, dir_path, inode_names)
                        continue

                    is_deleted_inode = (i_dtime > 0) or (i_links == 0)
                    if not is_deleted_inode and not include_active:
                        continue
                    if file_size <= 0 or file_size > 8 * (1024 ** 3):
                        continue
                    if (i_mode != 0) and ((i_mode & S_IFMT) not in (0, S_IFREG)):
                        continue

                    runs = self._parse_inode_runs(raw_ino, file_size)
                    if not runs:
                        continue

                    mapped_bytes = sum(r.length for r in runs)
                    if mapped_bytes >= file_size:
                        status = IntegrityStatus.GOOD
                        detail = "Deleted EXT4 inode with intact extent tree"
                    else:
                        status = IntegrityStatus.PARTIAL
                        detail = f"Partial EXT4 extent tree ({mapped_bytes}/{file_size} B)"

                    name_info = inode_names.get(ino_num)
                    if name_info and "." in name_info[0]:
                        fname, orig_path = name_info
                        ext = fname.rsplit(".", 1)[-1].upper()
                    else:
                        sample_hdr = self.reader.read_at(runs[0].device_offset, 32)
                        ext = self._guess_extension_from_magic(sample_hdr)
                        if name_info:
                            fname = f"{name_info[0]}.{ext.lower()}"
                            orig_path = f"{name_info[1]}.{ext.lower()}"
                        else:
                            fname = f"Deleted_Inode_{ino_num}.{ext.lower()}"
                            orig_path = f"/userdata/Deleted_Inode_{ino_num}.{ext.lower()}"

                    ts_val = i_dtime or i_mtime
                    mod_dt = (
                        datetime.fromtimestamp(ts_val, tz=timezone.utc)
                        if ts_val > 0
                        else datetime.now(timezone.utc)
                    )

                    entry = RecoveredFileEntry(
                        id=f"ext4:{ino_num}",
                        name=fname,
                        extension=ext,
                        size_bytes=file_size,
                        original_path=orig_path,
                        modified_time=mod_dt,
                        recovery_method=RecoveryMethod.EXT4_INODE,
                        status=status,
                        status_detail=detail,
                        data_runs=runs,
                        source_device_path=self.reader.device.path,
                        inode_or_cluster=ino_num,
                        is_deleted=is_deleted_inode,
                    )
                    entries.append(entry)
                    if on_entry_found is not None:
                        on_entry_found(entry)

                idx_in_group += actual_cnt
                if progress_cb:
                    progress_cb(
                        g_idx * max_group_inodes + idx_in_group,
                        max(1, total_groups * max_group_inodes),
                        f"Scanning EXT4 Inode Table (Group {g_idx + 1}/{total_groups})",
                    )

        return entries
