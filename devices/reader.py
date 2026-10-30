"""Safe Read-Only Device & Disk-Image Reader with Alignment and Write Guards."""
from __future__ import annotations

import logging
import os
from typing import Iterator, Optional, Tuple

from .discovery import DeviceInfo, DeviceType

logger = logging.getLogger("recoverx.devices.reader")


class DeviceAccessError(OSError):
    """Raised when a device or disk image cannot be accessed safely."""


class PhysicalDiskConfirmationRequired(PermissionError):
    """Raised when attempting to open a physical disk without explicit user confirmation."""


class ReadOnlyDeviceReader:
    """
    Strictly read-only binary reader for physical drives, logical volumes, and disk images.
    - Never opens files/devices with write flags.
    - Performs 512/4096-byte sector-aligned reads when accessing raw block devices.
    - Explicitly rejects any write/modify method calls.
    """

    SECTOR_ALIGNMENT = 4096

    def __init__(
        self,
        device: DeviceInfo,
        confirm_physical_access: bool = False,
    ):
        self.device = device
        self.confirm_physical_access = confirm_physical_access
        self._fd: Optional[int] = None
        self._size: int = device.total_bytes
        self._pos: int = 0

    def open(self) -> "ReadOnlyDeviceReader":
        if self.device.device_type == DeviceType.PHYSICAL_DISK and not self.confirm_physical_access:
            raise PhysicalDiskConfirmationRequired(
                f"Explicit confirmation is required before accessing physical disk: {self.device.name} ({self.device.path})"
            )
        if self.device.is_encrypted:
            raise DeviceAccessError(
                f"Device '{self.device.name}' is encrypted ({self.device.filesystem}). "
                "RecoverX does not bypass operating-system encryption."
            )
        if not self.device.path or not os.path.exists(self.device.path):
            raise DeviceAccessError(f"Source path does not exist or is unmounted: {self.device.path}")

        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
        try:
            self._fd = os.open(self.device.path, flags)
        except PermissionError as exc:
            raise DeviceAccessError(
                f"Permission denied opening '{self.device.path}' in read-only mode. "
                "Run RecoverX as Administrator for raw volume access."
            ) from exc
        except OSError as exc:
            raise DeviceAccessError(f"Failed to open '{self.device.path}': {exc}") from exc

        # Determine exact byte size if possible
        try:
            end_pos = os.lseek(self._fd, 0, os.SEEK_END)
            if end_pos > 0:
                self._size = end_pos
            os.lseek(self._fd, 0, os.SEEK_SET)
        except OSError:
            pass

        self._pos = 0
        logger.info(
            "Opened source '%s' (%s) strictly in READ-ONLY mode (%d bytes).",
            self.device.name,
            self.device.path,
            self._size,
        )
        return self

    def close(self) -> None:
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            finally:
                self._fd = None

    def __enter__(self) -> "ReadOnlyDeviceReader":
        return self.open()

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    @property
    def size(self) -> int:
        return self._size

    def write(self, *args, **kwargs) -> None:
        raise PermissionError("RecoverX Safety Guarantee: Write operations on source devices are strictly prohibited.")

    def truncate(self, *args, **kwargs) -> None:
        raise PermissionError("RecoverX Safety Guarantee: Truncate operations on source devices are strictly prohibited.")

    def read_at(self, offset: int, length: int) -> bytes:
        r"""
        Read `length` bytes starting at `offset` using sector-aligned reads so both
        disk images and Windows raw volume handles (`\\.\C:`) succeed reliably.
        """
        if self._fd is None:
            raise DeviceAccessError("Reader is not open.")
        if length <= 0 or offset < 0:
            return b""

        align = self.SECTOR_ALIGNMENT
        aligned_start = (offset // align) * align
        prefix_skip = offset - aligned_start
        total_needed = prefix_skip + length
        aligned_length = ((total_needed + align - 1) // align) * align

        try:
            os.lseek(self._fd, aligned_start, os.SEEK_SET)
            buf = bytearray()
            remaining = aligned_length
            while remaining > 0:
                chunk = os.read(self._fd, min(remaining, 1024 * 1024))
                if not chunk:
                    break
                buf.extend(chunk)
                remaining -= len(chunk)
            return bytes(buf[prefix_skip : prefix_skip + length])
        except OSError as exc:
            raise DeviceAccessError(f"Read error at offset {offset} (len {length}): {exc}") from exc

    def iter_chunks(
        self,
        chunk_size: int = 1024 * 1024,
        overlap: int = 65536,
        start_offset: int = 0,
        end_offset: Optional[int] = None,
    ) -> Iterator[Tuple[int, bytes]]:
        """
        Yields `(chunk_offset, chunk_bytes)` across the device with configurable overlap
        so file signatures straddling chunk boundaries are never missed.
        """
        if self._fd is None:
            raise DeviceAccessError("Reader is not open.")
        limit = end_offset if end_offset is not None and end_offset > 0 else self._size
        aligned_chunk = max(self.SECTOR_ALIGNMENT, (chunk_size // self.SECTOR_ALIGNMENT) * self.SECTOR_ALIGNMENT)
        pos = max(0, start_offset)
        prev_tail = b""
        prev_tail_offset = pos

        while pos < limit or limit == 0:
            to_read = aligned_chunk if limit == 0 else min(aligned_chunk, limit - pos)
            if to_read <= 0:
                break
            data = self.read_at(pos, to_read)
            if not data:
                break
            if prev_tail:
                combined = prev_tail + data
                yield (prev_tail_offset, combined)
            else:
                yield (pos, data)

            if len(data) < to_read:
                break

            if overlap > 0 and len(data) > overlap:
                prev_tail = data[-overlap:]
                prev_tail_offset = pos + len(data) - overlap
            else:
                prev_tail = b""
                prev_tail_offset = pos + len(data)

            pos += len(data)
