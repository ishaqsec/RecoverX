"""NTFS Master File Table ($MFT) & USN Change Journal ($UsnJrnl:$J) Deleted-Record Parser (1MB Buffered I/O)."""
from __future__ import annotations

import logging
import struct
from datetime import datetime, timedelta, timezone
from typing import Callable, Dict, List, Optional, Tuple

from devices.reader import ReadOnlyDeviceReader
from .base import (
    DataRun,
    FileSystemParser,
    IntegrityStatus,
    RecoveredFileEntry,
    RecoveryMethod,
)

logger = logging.getLogger("recoverx.filesystems.ntfs")

NTFS_EPOCH = datetime(1601, 1, 1, tzinfo=timezone.utc)

ATTR_STANDARD_INFORMATION = 0x10
ATTR_FILE_NAME = 0x30
ATTR_DATA = 0x80
ATTR_END = 0xFFFFFFFF

USN_REASON_FILE_DELETE = 0x00000200


def ntfs_time_to_datetime(filetime: int) -> Optional[datetime]:
    """Convert Windows 64-bit FILETIME (100-ns intervals since 1601-01-01) to UTC datetime."""
    if filetime <= 0:
        return None
    try:
        microseconds = filetime // 10
        dt = NTFS_EPOCH + timedelta(microseconds=microseconds)
        if 1970 <= dt.year <= 2100:
            return dt
    except (OverflowError, ValueError):
        pass
    return None


def parse_usn_journal_records(raw_journal: bytes) -> Dict[int, Tuple[str, int, Optional[datetime]]]:
    """
    Parse NTFS `$UsnJrnl:$J` (`USN_RECORD_V2`) stream for `USN_REASON_FILE_DELETE` events.
    """
    deleted_map: Dict[int, Tuple[str, int, Optional[datetime]]] = {}
    n = len(raw_journal)
    pos = 0
    while pos + 60 <= n:
        rec_len, major_ver, minor_ver = struct.unpack_from("<IHH", raw_journal, pos)
        if rec_len < 60 or rec_len > 1024 or major_ver != 2 or pos + rec_len > n:
            pos += 8
            continue
        file_ref, parent_ref, _usn, ts_ft, reason, _src_info, _sec_id, _fattr, fn_len, fn_off = (
            struct.unpack_from("<QQQQIIIIHH", raw_journal, pos + 8)
        )
        if (reason & USN_REASON_FILE_DELETE) and fn_len > 0 and pos + fn_off + fn_len <= pos + rec_len:
            mft_num = file_ref & 0x0000FFFFFFFFFFFF
            parent_num = parent_ref & 0x0000FFFFFFFFFFFF
            fname = raw_journal[pos + fn_off : pos + fn_off + fn_len].decode("utf-16le", errors="ignore").strip("\x00")
            if fname:
                deleted_map[mft_num] = (fname, parent_num, ntfs_time_to_datetime(ts_ft))
        pos += (rec_len + 7) & ~7
    return deleted_map


def decode_ntfs_data_runs(
    runlist_bytes: bytes,
    cluster_size: int,
    partition_offset: int,
) -> List[DataRun]:
    """Decode variable-length NTFS non-resident data runs (mapping pairs) into physical byte offsets."""
    runs: List[DataRun] = []
    idx = 0
    current_lcn = 0
    n = len(runlist_bytes)

    while idx < n:
        header = runlist_bytes[idx]
        idx += 1
        if header == 0x00:
            break
        len_size = header & 0x0F
        off_size = (header >> 4) & 0x0F
        if len_size == 0 or idx + len_size + off_size > n:
            break

        run_clusters = int.from_bytes(runlist_bytes[idx : idx + len_size], byteorder="little", signed=False)
        idx += len_size

        if off_size == 0:
            runs.append(DataRun(device_offset=0, length=run_clusters * cluster_size, sparse=True))
        else:
            delta_lcn = int.from_bytes(runlist_bytes[idx : idx + off_size], byteorder="little", signed=True)
            idx += off_size
            current_lcn += delta_lcn
            if current_lcn >= 0 and run_clusters > 0:
                phys_offset = partition_offset + (current_lcn * cluster_size)
                runs.append(DataRun(device_offset=phys_offset, length=run_clusters * cluster_size, sparse=False))

    return runs


class NTFSMftParser(FileSystemParser):
    """
    Parses NTFS Boot Sector, Master File Table ($MFT), and USN Change Journal ($UsnJrnl:$J)
    using 1 MB buffered sequential reads for high-speed scanning on large Windows volumes.
    """

    MFT_READ_BUFFER_SIZE = 1024 * 1024  # Read 1,024 MFT records per sequential syscall

    def __init__(self, reader: ReadOnlyDeviceReader, partition_offset: int = 0):
        super().__init__(reader, partition_offset)
        self.bytes_per_sector: int = 512
        self.sectors_per_cluster: int = 8
        self.cluster_size: int = 4096
        self.mft_lcn: int = 0
        self.mft_record_size: int = 1024
        self.total_sectors: int = 0

    def detect(self) -> bool:
        boot = self.reader.read_at(self.partition_offset, 512)
        if len(boot) < 512:
            return False
        if boot[3:11] != b"NTFS    ":
            return False
        return self._parse_bpb(boot)

    def _parse_bpb(self, boot: bytes) -> bool:
        try:
            self.bytes_per_sector = struct.unpack_from("<H", boot, 11)[0]
            spc = struct.unpack_from("<B", boot, 13)[0]
            if spc > 128:
                self.sectors_per_cluster = 1 << (256 - spc)
            else:
                self.sectors_per_cluster = spc
            if self.bytes_per_sector not in (512, 1024, 2048, 4096) or self.sectors_per_cluster == 0:
                return False
            self.cluster_size = self.bytes_per_sector * self.sectors_per_cluster
            self.total_sectors = struct.unpack_from("<Q", boot, 40)[0]
            self.mft_lcn = struct.unpack_from("<Q", boot, 48)[0]
            clusters_per_rec = struct.unpack_from("<b", boot, 64)[0]
            if clusters_per_rec < 0:
                self.mft_record_size = 1 << (-clusters_per_rec)
            else:
                self.mft_record_size = clusters_per_rec * self.cluster_size
            if self.mft_record_size <= 0 or self.mft_record_size > 65536:
                self.mft_record_size = 1024
            return True
        except struct.error:
            return False

    @staticmethod
    def _apply_usa_fixup(raw_record: bytes, sector_size: int = 512) -> Tuple[Optional[bytes], bool]:
        if len(raw_record) < 48 or raw_record[:4] != b"FILE":
            return (None, False)
        usa_offset, usa_count = struct.unpack_from("<HH", raw_record, 4)
        if usa_offset < 42 or usa_count < 2 or usa_offset + usa_count * 2 > len(raw_record):
            return (bytes(raw_record), True)

        buf = bytearray(raw_record)
        usn = buf[usa_offset : usa_offset + 2]
        usa_intact = True
        num_sectors = min(usa_count - 1, len(buf) // sector_size)
        for sec_idx in range(num_sectors):
            sec_end = (sec_idx + 1) * sector_size - 2
            if buf[sec_end : sec_end + 2] != usn:
                usa_intact = False
            fixup_pos = usa_offset + 2 * (sec_idx + 1)
            buf[sec_end : sec_end + 2] = buf[fixup_pos : fixup_pos + 2]
        return (bytes(buf), usa_intact)

    def _get_mft_runs(self) -> List[DataRun]:
        mft_start_offset = self.partition_offset + (self.mft_lcn * self.cluster_size)
        rec0_raw = self.reader.read_at(mft_start_offset, self.mft_record_size)
        rec0, _ = self._apply_usa_fixup(rec0_raw, self.bytes_per_sector)
        if rec0:
            parsed = self._parse_mft_record(rec0, 0)
            if parsed and parsed.get("data_runs"):
                return parsed["data_runs"]
        fallback_len = min(
            4096 * self.mft_record_size,
            max(self.mft_record_size * 64, self.reader.size - mft_start_offset),
        )
        return [DataRun(device_offset=mft_start_offset, length=fallback_len)]

    def _parse_mft_record(self, rec: bytes, record_number: int) -> Optional[dict]:
        flags = struct.unpack_from("<H", rec, 22)[0]
        attr_offset = struct.unpack_from("<H", rec, 20)[0]
        bytes_in_use = struct.unpack_from("<I", rec, 24)[0]
        if attr_offset >= len(rec) or attr_offset < 40:
            return None

        is_in_use = bool(flags & 0x0001)
        is_dir = bool(flags & 0x0002)

        info: dict = {
            "record_number": record_number,
            "is_in_use": is_in_use,
            "is_dir": is_dir,
            "name": "",
            "namespace": -1,
            "parent_ref": None,
            "created": None,
            "modified": None,
            "accessed": None,
            "size": 0,
            "resident_data": None,
            "data_runs": [],
            "usn_journal_runs": [],
        }

        pos = attr_offset
        limit = min(len(rec), bytes_in_use if bytes_in_use <= len(rec) else len(rec))

        while pos + 16 <= limit:
            attr_type, attr_len = struct.unpack_from("<II", rec, pos)
            if attr_type == ATTR_END or attr_len == 0 or pos + attr_len > limit:
                break
            non_resident = rec[pos + 8]
            name_len = rec[pos + 9]
            name_off = struct.unpack_from("<H", rec, pos + 10)[0]

            attr_name = ""
            if name_len > 0 and pos + name_off + name_len * 2 <= pos + attr_len:
                attr_name = rec[pos + name_off : pos + name_off + name_len * 2].decode("utf-16le", errors="ignore")

            if non_resident == 0 and pos + 24 <= pos + attr_len:
                val_len = struct.unpack_from("<I", rec, pos + 16)[0]
                val_off = struct.unpack_from("<H", rec, pos + 20)[0]
                val_start = pos + val_off
                val_end = min(pos + attr_len, val_start + val_len)
                val_bytes = rec[val_start:val_end]

                if attr_type == ATTR_STANDARD_INFORMATION and len(val_bytes) >= 32:
                    c_ft, m_ft, _, a_ft = struct.unpack_from("<QQQQ", val_bytes, 0)
                    info["created"] = ntfs_time_to_datetime(c_ft)
                    info["modified"] = ntfs_time_to_datetime(m_ft)
                    info["accessed"] = ntfs_time_to_datetime(a_ft)

                elif attr_type == ATTR_FILE_NAME and len(val_bytes) >= 66:
                    parent_raw = struct.unpack_from("<Q", val_bytes, 0)[0]
                    parent_mft_num = parent_raw & 0x0000FFFFFFFFFFFF
                    c_ft, m_ft, _, a_ft = struct.unpack_from("<QQQQ", val_bytes, 8)
                    real_size = struct.unpack_from("<Q", val_bytes, 48)[0]
                    fn_len = val_bytes[64]
                    fn_ns = val_bytes[65]
                    raw_name = val_bytes[66 : 66 + fn_len * 2]
                    decoded_name = raw_name.decode("utf-16le", errors="ignore")
                    if decoded_name and (info["namespace"] == 2 or info["name"] == "" or fn_ns in (0, 1, 3)):
                        info["name"] = decoded_name
                        info["namespace"] = fn_ns
                        info["parent_ref"] = parent_mft_num
                        if not info["modified"]:
                            info["modified"] = ntfs_time_to_datetime(m_ft)
                        if not info["created"]:
                            info["created"] = ntfs_time_to_datetime(c_ft)
                        if info["size"] == 0 and real_size > 0:
                            info["size"] = real_size

                elif attr_type == ATTR_DATA and attr_name == "":
                    info["resident_data"] = bytes(val_bytes)
                    info["size"] = len(val_bytes)

            elif non_resident == 1 and attr_type == ATTR_DATA and pos + 64 <= pos + attr_len:
                runlist_off = struct.unpack_from("<H", rec, pos + 32)[0]
                alloc_size, real_size, _init_size = struct.unpack_from("<QQQ", rec, pos + 40)
                runlist_bytes = rec[pos + runlist_off : pos + attr_len]
                runs = decode_ntfs_data_runs(runlist_bytes, self.cluster_size, self.partition_offset)
                if attr_name == "":
                    info["data_runs"].extend(runs)
                    info["size"] = real_size if real_size > 0 else alloc_size
                elif attr_name == "$J":
                    info["usn_journal_runs"].extend(runs)

            pos += attr_len

        return info

    def _build_entry(
        self,
        parsed: dict,
        usa_ok: bool,
        dir_map: Dict[int, Tuple[str, Optional[int]]],
        usn_deleted_map: Dict[int, Tuple[str, int, Optional[datetime]]],
    ) -> RecoveredFileEntry:
        rec_no = parsed["record_number"]
        if rec_no in usn_deleted_map and not parsed["parent_ref"]:
            _, u_parent, _ = usn_deleted_map[rec_no]
            parsed["parent_ref"] = u_parent

        path_parts = [parsed["name"]]
        parent = parsed["parent_ref"]
        visited = set()
        while parent is not None and parent in dir_map and parent not in visited:
            visited.add(parent)
            dname, next_parent = dir_map[parent]
            if dname:
                path_parts.append(dname)
            parent = next_parent
        full_path = "C:\\" + "\\".join(reversed(path_parts))

        status = IntegrityStatus.GOOD
        status_detail = "MFT record intact; data clusters available"
        size = parsed["size"]

        if not usa_ok:
            status = IntegrityStatus.CORRUPTED
            status_detail = "MFT record has Update Sequence Array sector mismatch"
        elif parsed["resident_data"] is not None:
            status = IntegrityStatus.GOOD
            status_detail = "Resident data preserved directly inside MFT record"
        elif parsed["data_runs"]:
            total_run_bytes = sum(r.length for r in parsed["data_runs"])
            first_run = parsed["data_runs"][0]
            if first_run.device_offset + min(first_run.length, 4096) > self.reader.size:
                status = IntegrityStatus.CORRUPTED
                status_detail = "Data run points beyond volume boundary"
            elif total_run_bytes < size:
                status = IntegrityStatus.PARTIAL
                status_detail = f"Partial runlist ({total_run_bytes} of {size} bytes mapped)"
            else:
                sample = self.reader.read_at(first_run.device_offset, min(512, max(1, size)))
                if size > 0 and sample == b"\x00" * len(sample):
                    status = IntegrityStatus.PARTIAL
                    status_detail = "Starting cluster appears zeroed or trimmed"
        elif size > 0:
            status = IntegrityStatus.CORRUPTED
            status_detail = "Non-resident runlist stripped upon deletion"

        ext = parsed["name"].rsplit(".", 1)[-1].upper() if "." in parsed["name"] else ""
        return RecoveredFileEntry(
            id=f"ntfs:mft:{parsed['record_number']}",
            name=parsed["name"],
            extension=ext,
            size_bytes=size,
            original_path=full_path,
            modified_time=parsed["modified"] or parsed["created"],
            created_time=parsed["created"],
            accessed_time=parsed["accessed"],
            recovery_method=RecoveryMethod.NTFS_MFT,
            status=status,
            status_detail=status_detail,
            resident_data=parsed["resident_data"],
            data_runs=parsed["data_runs"],
            source_device_path=self.reader.device.path,
            inode_or_cluster=parsed["record_number"],
            is_deleted=not parsed["is_in_use"],
        )

    def scan_deleted(
        self,
        progress_cb: Optional[Callable[[int, int, str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        include_active: bool = False,
        on_entry_found: Optional[Callable[[RecoveredFileEntry], None]] = None,
    ) -> List[RecoveredFileEntry]:
        if not self.detect():
            return []

        mft_runs = self._get_mft_runs()
        total_mft_bytes = sum(r.length for r in mft_runs)
        total_records = max(1, total_mft_bytes // self.mft_record_size)

        dir_map: Dict[int, Tuple[str, Optional[int]]] = {5: ("", None)}
        usn_deleted_map: Dict[int, Tuple[str, int, Optional[datetime]]] = {}
        results: List[RecoveredFileEntry] = []
        rec_num = 0
        rec_size = self.mft_record_size
        batch_bytes_len = max(rec_size * 64, (self.MFT_READ_BUFFER_SIZE // rec_size) * rec_size)

        for run in mft_runs:
            offset = run.device_offset
            end_offset = offset + run.length
            while offset < end_offset:
                if cancel_check and cancel_check():
                    return results

                to_read = min(batch_bytes_len, end_offset - offset)
                batch_buf = self.reader.read_at(offset, to_read)
                if len(batch_buf) < rec_size:
                    break
                offset += len(batch_buf)

                for buf_pos in range(0, len(batch_buf) - rec_size + 1, rec_size):
                    if cancel_check and cancel_check():
                        return results
                    raw_rec = batch_buf[buf_pos : buf_pos + rec_size]
                    current_rec_num = rec_num
                    rec_num += 1

                    if progress_cb and current_rec_num % 128 == 0:
                        progress_cb(current_rec_num, total_records, f"Scanning NTFS MFT record #{current_rec_num}")

                    if raw_rec[:4] != b"FILE":
                        continue

                    fixed_rec, usa_ok = self._apply_usa_fixup(raw_rec, self.bytes_per_sector)
                    if not fixed_rec:
                        continue

                    parsed = self._parse_mft_record(fixed_rec, current_rec_num)
                    if not parsed:
                        continue

                    if parsed["name"] == "$UsnJrnl" and parsed.get("usn_journal_runs"):
                        for jrun in parsed["usn_journal_runs"][:4]:
                            if not jrun.sparse and jrun.length > 0:
                                jbytes = self.reader.read_at(jrun.device_offset, min(jrun.length, 512 * 1024))
                                usn_deleted_map.update(parse_usn_journal_records(jbytes))
                        continue

                    if not parsed["name"] and current_rec_num in usn_deleted_map:
                        u_name, u_parent, u_dt = usn_deleted_map[current_rec_num]
                        parsed["name"] = u_name
                        parsed["parent_ref"] = u_parent
                        if not parsed["modified"]:
                            parsed["modified"] = u_dt

                    if not parsed["name"]:
                        continue

                    name = parsed["name"]
                    if current_rec_num < 16 or name.startswith("$"):
                        continue

                    if parsed["is_dir"]:
                        dir_map[current_rec_num] = (name, parsed["parent_ref"])
                        continue

                    if not parsed["is_in_use"] or include_active:
                        entry = self._build_entry(parsed, usa_ok, dir_map, usn_deleted_map)
                        results.append(entry)
                        if on_entry_found is not None:
                            on_entry_found(entry)

        return results
