"""Chunked Streaming Signature-Based File Carver with Native C Acceleration & Real-Time Streaming."""
from __future__ import annotations

import ctypes
import logging
import struct
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional, Set, Tuple

from devices.reader import ReadOnlyDeviceReader
from filesystems.base import (
    DataRun,
    FileCategory,
    IntegrityStatus,
    RecoveredFileEntry,
    RecoveryMethod,
)
from .signatures import DEFAULT_REGISTRY, SignatureRegistry
from .validators import validate_and_measure_carved_data

logger = logging.getLogger("recoverx.carving.carver")


class FileCarver:
    """
    Scans raw disk or partition regions in memory-bounded chunks using either the compiled
    C accelerator (`libfast_scanner.so` / `fast_scanner.dll`) or a fast prefix scanner,
    validates candidate headers/structures, supports fragmented stream reassembly, and
    streams discovered entries live via `on_entry_found`.
    """

    def __init__(
        self,
        reader: ReadOnlyDeviceReader,
        registry: Optional[SignatureRegistry] = None,
        chunk_size: int = 1024 * 1024,
        overlap: int = 128 * 1024,
    ):
        self.reader = reader
        self.registry = registry or DEFAULT_REGISTRY
        self.chunk_size = chunk_size
        self.overlap = overlap
        self._c_lib = self._load_native_scanner()

    @staticmethod
    def _load_native_scanner():
        base_dir = Path(__file__).parent
        for lib_name in ("fast_scanner.dll", "libfast_scanner.so", "libfast_scanner.dylib"):
            lib_path = base_dir / lib_name
            if lib_path.exists():
                try:
                    lib = ctypes.CDLL(str(lib_path))
                    lib.scan_chunk_prefixes.argtypes = [
                        ctypes.c_char_p,
                        ctypes.c_size_t,
                        ctypes.POINTER(ctypes.c_int32),
                        ctypes.c_size_t,
                    ]
                    lib.scan_chunk_prefixes.restype = ctypes.c_size_t
                    return lib
                except OSError as exc:
                    logger.debug("Fallback from %s: %s", lib_name, exc)
        return None

    def _find_candidate_offsets(self, buf: bytes) -> List[int]:
        if self._c_lib is not None and len(buf) >= 16:
            max_hits = 16384
            out_arr = (ctypes.c_int32 * max_hits)()
            count = self._c_lib.scan_chunk_prefixes(buf, len(buf), out_arr, max_hits)
            return [out_arr[i] for i in range(count)]

        candidates: Set[int] = set()
        prefixes = [
            (b"\xff\xd8\xff", 0),
            (b"\x89PNG\r\n\x1a\n", 0),
            (b"GIF87a", 0),
            (b"GIF89a", 0),
            (b"BM", 0),
            (b"II*\x00", 0),
            (b"MM\x00*", 0),
            (b"RIFF", 0),
            (b"%PDF-", 0),
            (b"PK\x03\x04", 0),
            (b"ftyp", 4),
            (b"\x1a\x45\xdf\xa3", 0),
            (b"ID3", 0),
            (b"fLaC", 0),
            (b"7z\xbc\xaf\x27\x1c", 0),
            (b"Rar!\x1a\x07", 0),
            (b"\x1f\x8b\x08", 0),
        ]
        for magic, magic_off in prefixes:
            start = 0
            while True:
                idx = buf.find(magic, start)
                if idx == -1:
                    break
                real_off = idx - magic_off
                if real_off >= 0:
                    candidates.add(real_off)
                start = idx + 1
        return sorted(candidates)

    def reassemble_fragmented_runs(
        self,
        abs_offset: int,
        initial_size: int,
        extension: str,
        cluster_size: int = 4096,
    ) -> Optional[Tuple[List[DataRun], int, str]]:
        ext = extension.upper()
        if ext == "JPG":
            head_end = abs_offset + initial_size
            probe_buf = self.reader.read_at(head_end, cluster_size * 8)
            for skip_clusters in range(1, 5):
                cand_start = skip_clusters * cluster_size
                if cand_start >= len(probe_buf):
                    break
                eoi_idx = probe_buf.find(b"\xff\xd9", cand_start)
                if eoi_idx != -1 and (eoi_idx - cand_start) > 64:
                    tail_len = (eoi_idx - cand_start) + 2
                    runs = [
                        DataRun(device_offset=abs_offset, length=initial_size),
                        DataRun(device_offset=head_end + cand_start, length=tail_len),
                    ]
                    return (
                        runs,
                        initial_size + tail_len,
                        f"Reassembled fragmented JPEG across 2 cluster runs ({initial_size + tail_len} B)",
                    )
        elif ext in ("MP4", "MOV"):
            head_end = abs_offset + initial_size
            probe_buf = self.reader.read_at(head_end, cluster_size * 8)
            for atom_tag in (b"mdat", b"moov"):
                tag_pos = probe_buf.find(atom_tag, cluster_size)
                if tag_pos >= 4 and (tag_pos - 4) % cluster_size == 0:
                    atom_start = tag_pos - 4
                    atom_sz = struct.unpack_from(">I", probe_buf, atom_start)[0]
                    if 8 < atom_sz <= 64 * 1024 * 1024:
                        runs = [
                            DataRun(device_offset=abs_offset, length=initial_size),
                            DataRun(device_offset=head_end + atom_start, length=atom_sz),
                        ]
                        return (
                            runs,
                            initial_size + atom_sz,
                            f"Reassembled fragmented {ext} container across 2 cluster runs",
                        )
        return None

    def scan(
        self,
        start_offset: int = 0,
        end_offset: Optional[int] = None,
        known_offsets: Optional[Set[int]] = None,
        known_ranges: Optional[List[Tuple[int, int]]] = None,
        enabled_categories: Optional[List[FileCategory]] = None,
        progress_cb: Optional[Callable[[int, int, str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
        on_entry_found: Optional[Callable[[RecoveredFileEntry], None]] = None,
    ) -> List[RecoveredFileEntry]:
        discovered: List[RecoveredFileEntry] = []
        seen_offsets: Set[int] = set(known_offsets or set())
        total_len = (end_offset or self.reader.size) - start_offset
        total_len = max(1, total_len)

        carve_index = 1
        active_until_offset = -1

        for chunk_offset, chunk_bytes in self.reader.iter_chunks(
            chunk_size=self.chunk_size,
            overlap=self.overlap,
            start_offset=start_offset,
            end_offset=end_offset,
        ):
            if cancel_check and cancel_check():
                break

            done = min(total_len, max(0, chunk_offset - start_offset + len(chunk_bytes)))
            if progress_cb:
                progress_cb(done, total_len, f"Carving signatures at offset 0x{chunk_offset:08X}")

            rel_offsets = self._find_candidate_offsets(chunk_bytes)
            for rel in rel_offsets:
                abs_offset = chunk_offset + rel
                if abs_offset < active_until_offset or abs_offset in seen_offsets:
                    continue
                if known_ranges and any(rs <= abs_offset < re for rs, re in known_ranges):
                    continue

                window = chunk_bytes[rel:]
                if len(window) < 65536:
                    window = self.reader.read_at(abs_offset, 256 * 1024)

                vres = validate_and_measure_carved_data(window)
                if vres is None or not vres.is_valid_header or vres.carved_size < 24:
                    continue

                if enabled_categories is not None and vres.category not in enabled_categories:
                    continue

                data_runs = [DataRun(device_offset=abs_offset, length=vres.carved_size)]
                carved_size = vres.carved_size
                status = vres.status
                detail = vres.detail

                if status == IntegrityStatus.PARTIAL and vres.extension in ("JPG", "MP4", "MOV"):
                    reassembled = self.reassemble_fragmented_runs(
                        abs_offset, carved_size, vres.extension
                    )
                    if reassembled is not None:
                        data_runs, carved_size, detail = reassembled
                        status = IntegrityStatus.GOOD

                seen_offsets.add(abs_offset)
                active_until_offset = abs_offset + vres.carved_size

                fname = f"Carved_{carve_index:04d}.{vres.extension.lower()}"
                carve_index += 1
                c_entry = RecoveredFileEntry(
                    id=f"carve:0x{abs_offset:08x}",
                    name=fname,
                    extension=vres.extension,
                    size_bytes=carved_size,
                    original_path=f"Carved\\{vres.category.value}\\{fname}",
                    modified_time=datetime.now(timezone.utc),
                    recovery_method=RecoveryMethod.SIGNATURE_CARVING,
                    status=status,
                    status_detail=detail,
                    category=vres.category,
                    data_runs=data_runs,
                    source_device_path=self.reader.device.path,
                    inode_or_cluster=abs_offset,
                    is_deleted=True,
                )
                discovered.append(c_entry)
                if on_entry_found is not None:
                    on_entry_found(c_entry)

        return discovered
