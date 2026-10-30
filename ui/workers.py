"""Background Worker Threads for Non-Blocking Scans and File Restorations."""
from __future__ import annotations

import threading
import time
from typing import List, Optional, Set

from PySide6.QtCore import QThread, Signal

from devices.discovery import DeviceInfo
from filesystems.base import RecoveredFileEntry
from recovery.engine import RecoveryEngine, ScanMode


class ScanWorker(QThread):
    """Runs `RecoveryEngine.run_scan` on a background thread with 45ms throttled UI signals."""

    progress_updated = Signal(int, int, str, int, int, float, float)
    batch_discovered = Signal(list)
    scan_completed = Signal(object, list)
    scan_failed = Signal(str)

    def __init__(
        self,
        engine: RecoveryEngine,
        device: DeviceInfo,
        scan_mode: ScanMode,
        confirm_physical_access: bool = False,
        include_active_files: bool = False,
        resume_offset: int = 0,
        target_categories: Optional[Set[str]] = None,
    ):
        super().__init__()
        self.engine = engine
        self.device = device
        self.scan_mode = scan_mode
        self.confirm_physical_access = confirm_physical_access
        self.include_active_files = include_active_files
        self.resume_offset = resume_offset
        self.target_categories = set(target_categories) if target_categories else None
        self._cancel_event = threading.Event()
        self._start_ts = 0.0
        self._last_emit_count = 0
        self._last_signal_ts = 0.0

    def cancel(self) -> None:
        self._cancel_event.set()

    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def run(self) -> None:
        self._start_ts = time.monotonic()
        self._last_signal_ts = 0.0

        def _on_progress(cur: int, tot: int, msg: str, current_list: List[RecoveredFileEntry]) -> None:
            now = time.monotonic()
            is_final = cur >= tot
            if not is_final and len(current_list) > 5 and (now - self._last_signal_ts) < 0.045:
                return
            self._last_signal_ts = now

            elapsed = max(0.001, now - self._start_ts)
            ratio = min(1.0, max(0.0, cur / float(max(1, tot))))
            est_rem = (elapsed / ratio) * (1.0 - ratio) if ratio > 0.02 else 0.0
            total_bytes_found = sum(e.size_bytes for e in current_list)
            self.progress_updated.emit(
                cur,
                max(1, tot),
                msg,
                len(current_list),
                total_bytes_found,
                elapsed,
                est_rem,
            )
            if len(current_list) > self._last_emit_count:
                new_items = current_list[self._last_emit_count :]
                self._last_emit_count = len(current_list)
                self.batch_discovered.emit(list(new_items))

        try:
            session, entries = self.engine.run_scan(
                device=self.device,
                scan_mode=self.scan_mode,
                confirm_physical_access=self.confirm_physical_access,
                include_active_files=self.include_active_files,
                resume_offset=self.resume_offset,
                target_categories=self.target_categories,
                progress_cb=_on_progress,
                cancel_check=self.is_cancelled,
            )
            if len(entries) > self._last_emit_count:
                remaining = entries[self._last_emit_count :]
                self._last_emit_count = len(entries)
                self.batch_discovered.emit(list(remaining))
            self.scan_completed.emit(session, entries)
        except Exception as exc:
            self.scan_failed.emit(str(exc))


class RecoveryWorker(QThread):
    """Runs `RecoveryEngine.recover_files` on a background thread."""

    progress_updated = Signal(int, int, str)
    recovery_completed = Signal(object, list)
    recovery_failed = Signal(str)

    def __init__(
        self,
        engine: RecoveryEngine,
        device: DeviceInfo,
        entries: List[RecoveredFileEntry],
        destination_dir: str,
        session_id: str,
        preserve_structure: bool = True,
        allow_same_device: bool = False,
        confirm_physical_access: bool = False,
    ):
        super().__init__()
        self.engine = engine
        self.device = device
        self.entries = entries
        self.destination_dir = destination_dir
        self.session_id = session_id
        self.preserve_structure = preserve_structure
        self.allow_same_device = allow_same_device
        self.confirm_physical_access = confirm_physical_access
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    def run(self) -> None:
        try:
            log_rec, outcomes = self.engine.recover_files(
                device=self.device,
                entries=self.entries,
                destination_dir=self.destination_dir,
                session_id=self.session_id,
                preserve_structure=self.preserve_structure,
                allow_same_device=self.allow_same_device,
                confirm_physical_access=self.confirm_physical_access,
                progress_cb=lambda c, t, m: self.progress_updated.emit(c, t, m),
                cancel_check=self.is_cancelled,
            )
            self.recovery_completed.emit(log_rec, outcomes)
        except Exception as exc:
            self.recovery_failed.emit(str(exc))
