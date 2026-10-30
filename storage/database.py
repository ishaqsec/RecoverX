"""SQLite Persistence Layer for Scan Sessions, Findings, Settings, and Recovery History."""
from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from filesystems.base import (
    DataRun,
    FileCategory,
    IntegrityStatus,
    RecoveredFileEntry,
    RecoveryMethod,
)


@dataclass
class ScanSessionRecord:
    session_id: str
    device_id: str
    device_name: str
    device_path: str
    filesystem: str
    scan_mode: str
    methods_used: List[str]
    start_time: str
    end_time: Optional[str] = None
    status: str = "Running"
    last_offset: int = 0
    total_bytes: int = 0
    files_discovered: int = 0
    recoverable_bytes: int = 0
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


@dataclass
class RecoveryLogRecord:
    recovery_id: str
    session_id: str
    timestamp: str
    source_device: str
    destination_dir: str
    total_selected: int
    succeeded: int
    partial: int
    skipped: int
    failed: int
    file_outcomes: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


class RecoverXDatabase:
    """Thread-safe SQLite storage for scan sessions, findings, settings, and recovery audit logs."""

    def __init__(self, db_path: Optional[str] = None):
        import tempfile
        self._lock = threading.RLock()
        if db_path is None:
            default_dir = Path.home() / ".recoverx"
            default_dir.mkdir(parents=True, exist_ok=True)
            db_path = str(default_dir / "recoverx_state.db")
        self.db_path = db_path
        try:
            self._init_schema()
        except sqlite3.OperationalError:
            fallback_dir = Path(tempfile.gettempdir()) / "recoverx_data"
            fallback_dir.mkdir(parents=True, exist_ok=True)
            self.db_path = str(fallback_dir / "recoverx_state.db")
            self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS scan_sessions (
                    session_id TEXT PRIMARY KEY,
                    device_id TEXT NOT NULL,
                    device_name TEXT NOT NULL,
                    device_path TEXT NOT NULL,
                    filesystem TEXT NOT NULL,
                    scan_mode TEXT NOT NULL,
                    methods_used TEXT NOT NULL,
                    start_time TEXT NOT NULL,
                    end_time TEXT,
                    status TEXT NOT NULL,
                    last_offset INTEGER DEFAULT 0,
                    total_bytes INTEGER DEFAULT 0,
                    files_discovered INTEGER DEFAULT 0,
                    recoverable_bytes INTEGER DEFAULT 0,
                    warnings TEXT DEFAULT '[]',
                    errors TEXT DEFAULT '[]'
                );

                CREATE TABLE IF NOT EXISTS scan_findings (
                    session_id TEXT NOT NULL,
                    entry_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    extension TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    original_path TEXT NOT NULL,
                    modified_time TEXT,
                    recovery_method TEXT NOT NULL,
                    status TEXT NOT NULL,
                    status_detail TEXT NOT NULL,
                    category TEXT NOT NULL,
                    data_runs_json TEXT NOT NULL,
                    source_device_path TEXT NOT NULL,
                    inode_or_cluster INTEGER DEFAULT 0,
                    PRIMARY KEY (session_id, entry_id)
                );

                CREATE TABLE IF NOT EXISTS recovery_history (
                    recovery_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    source_device TEXT NOT NULL,
                    destination_dir TEXT NOT NULL,
                    total_selected INTEGER NOT NULL,
                    succeeded INTEGER NOT NULL,
                    partial INTEGER NOT NULL,
                    skipped INTEGER NOT NULL,
                    failed INTEGER NOT NULL,
                    file_outcomes_json TEXT NOT NULL,
                    warnings_json TEXT NOT NULL
                );
                """
            )

    def get_setting(self, key: str, default: Any = None) -> Any:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
            if row is None:
                return default
            try:
                return json.loads(row["value"])
            except json.JSONDecodeError:
                return row["value"]

    def set_setting(self, key: str, value: Any) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, json.dumps(value)),
            )

    def save_session(self, session: ScanSessionRecord) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO scan_sessions (
                    session_id, device_id, device_name, device_path, filesystem,
                    scan_mode, methods_used, start_time, end_time, status,
                    last_offset, total_bytes, files_discovered, recoverable_bytes,
                    warnings, errors
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    end_time = excluded.end_time,
                    status = excluded.status,
                    last_offset = excluded.last_offset,
                    files_discovered = excluded.files_discovered,
                    recoverable_bytes = excluded.recoverable_bytes,
                    methods_used = excluded.methods_used,
                    warnings = excluded.warnings,
                    errors = excluded.errors
                """,
                (
                    session.session_id,
                    session.device_id,
                    session.device_name,
                    session.device_path,
                    session.filesystem,
                    session.scan_mode,
                    json.dumps(session.methods_used),
                    session.start_time,
                    session.end_time,
                    session.status,
                    session.last_offset,
                    session.total_bytes,
                    session.files_discovered,
                    session.recoverable_bytes,
                    json.dumps(session.warnings),
                    json.dumps(session.errors),
                ),
            )

    def save_findings(self, session_id: str, entries: List[RecoveredFileEntry]) -> None:
        with self._lock, self._connect() as conn:
            rows = []
            for e in entries:
                runs_data = [
                    {"device_offset": r.device_offset, "length": r.length, "sparse": r.sparse}
                    for r in e.data_runs
                ]
                rows.append(
                    (
                        session_id,
                        e.id,
                        e.name,
                        e.extension,
                        e.size_bytes,
                        e.original_path,
                        e.modified_time.isoformat() if e.modified_time else None,
                        e.recovery_method.value,
                        e.status.value,
                        e.status_detail,
                        e.category.value,
                        json.dumps(runs_data),
                        e.source_device_path,
                        e.inode_or_cluster,
                    )
                )
            conn.executemany(
                """
                INSERT OR REPLACE INTO scan_findings (
                    session_id, entry_id, name, extension, size_bytes, original_path,
                    modified_time, recovery_method, status, status_detail, category,
                    data_runs_json, source_device_path, inode_or_cluster
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

    def load_session_findings(self, session_id: str) -> List[RecoveredFileEntry]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM scan_findings WHERE session_id = ? ORDER BY rowid ASC",
                (session_id,),
            ).fetchall()
            entries: List[RecoveredFileEntry] = []
            for r in rows:
                runs = [
                    DataRun(
                        device_offset=d["device_offset"],
                        length=d["length"],
                        sparse=d.get("sparse", False),
                    )
                    for d in json.loads(r["data_runs_json"])
                ]
                mod_dt = datetime.fromisoformat(r["modified_time"]) if r["modified_time"] else None
                entries.append(
                    RecoveredFileEntry(
                        id=r["entry_id"],
                        name=r["name"],
                        extension=r["extension"],
                        size_bytes=r["size_bytes"],
                        original_path=r["original_path"],
                        modified_time=mod_dt,
                        recovery_method=RecoveryMethod(r["recovery_method"]),
                        status=IntegrityStatus(r["status"]),
                        status_detail=r["status_detail"],
                        category=FileCategory(r["category"]),
                        data_runs=runs,
                        source_device_path=r["source_device_path"],
                        inode_or_cluster=r["inode_or_cluster"],
                    )
                )
            return entries

    def list_sessions(self) -> List[ScanSessionRecord]:
        with self._lock, self._connect() as conn:
            rows = conn.execute("SELECT * FROM scan_sessions ORDER BY start_time DESC").fetchall()
            out: List[ScanSessionRecord] = []
            for r in rows:
                out.append(
                    ScanSessionRecord(
                        session_id=r["session_id"],
                        device_id=r["device_id"],
                        device_name=r["device_name"],
                        device_path=r["device_path"],
                        filesystem=r["filesystem"],
                        scan_mode=r["scan_mode"],
                        methods_used=json.loads(r["methods_used"]),
                        start_time=r["start_time"],
                        end_time=r["end_time"],
                        status=r["status"],
                        last_offset=r["last_offset"],
                        total_bytes=r["total_bytes"],
                        files_discovered=r["files_discovered"],
                        recoverable_bytes=r["recoverable_bytes"],
                        warnings=json.loads(r["warnings"]),
                        errors=json.loads(r["errors"]),
                    )
                )
            return out

    def save_recovery_log(self, log: RecoveryLogRecord) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO recovery_history (
                    recovery_id, session_id, timestamp, source_device, destination_dir,
                    total_selected, succeeded, partial, skipped, failed,
                    file_outcomes_json, warnings_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    log.recovery_id,
                    log.session_id,
                    log.timestamp,
                    log.source_device,
                    log.destination_dir,
                    log.total_selected,
                    log.succeeded,
                    log.partial,
                    log.skipped,
                    log.failed,
                    json.dumps(log.file_outcomes),
                    json.dumps(log.warnings),
                ),
            )

    def list_recovery_logs(self) -> List[RecoveryLogRecord]:
        with self._lock, self._connect() as conn:
            rows = conn.execute("SELECT * FROM recovery_history ORDER BY timestamp DESC").fetchall()
            out: List[RecoveryLogRecord] = []
            for r in rows:
                out.append(
                    RecoveryLogRecord(
                        recovery_id=r["recovery_id"],
                        session_id=r["session_id"],
                        timestamp=r["timestamp"],
                        source_device=r["source_device"],
                        destination_dir=r["destination_dir"],
                        total_selected=r["total_selected"],
                        succeeded=r["succeeded"],
                        partial=r["partial"],
                        skipped=r["skipped"],
                        failed=r["failed"],
                        file_outcomes=json.loads(r["file_outcomes_json"]),
                        warnings=json.loads(r["warnings_json"]),
                    )
                )
            return out

    def clear_reports(self) -> None:
        """Clear saved recovery logs and session warnings/errors from the database."""
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM recovery_history")
            conn.execute("UPDATE scan_sessions SET warnings = '[]', errors = '[]'")

    def clear_all_session_and_report_records(self) -> None:
        """Clear all previous scan findings, scan sessions, and recovery history so opening the tool starts clean."""
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM scan_findings")
            conn.execute("DELETE FROM scan_sessions")
            conn.execute("DELETE FROM recovery_history")
