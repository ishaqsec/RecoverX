"""Exportable Recovery Reports (Plain Text .TXT focused on Saved Data & Warnings/Errors)."""
from __future__ import annotations

import csv
import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from filesystems.base import RecoveredFileEntry
from storage.database import RecoveryLogRecord, ScanSessionRecord


class ReportExporter:
    """
    Generates structured recovery reports for Saved Data Records and Failed/Warnings/Errors.
    """

    @staticmethod
    def build_report_payload(
        session: ScanSessionRecord,
        entries: List[RecoveredFileEntry],
        recovery_logs: Optional[List[RecoveryLogRecord]] = None,
    ) -> Dict[str, Any]:
        logs = recovery_logs or []
        total_succeeded = sum(l.succeeded for l in logs)
        total_partial = sum(l.partial for l in logs)
        total_skipped = sum(l.skipped for l in logs)
        total_failed = sum(l.failed for l in logs)

        return {
            "report_generator": "RecoverX — Advanced Data Recovery Tool",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "integrity_disclaimer": (
                "SHA-256 digests identify recovered output bytes and support comparison against "
                "known reference hashes. A hash of recovered output alone does not prove original "
                "pre-deletion identity without an original reference hash."
            ),
            "scan_session": {
                "session_id": session.session_id,
                "source_device_id": session.device_id,
                "source_device_name": session.device_name,
                "source_device_path": session.device_path,
                "filesystem": session.filesystem,
                "scan_mode": session.scan_mode,
                "methods_used": session.methods_used,
                "start_time": session.start_time,
                "completion_time": session.end_time,
                "status": session.status,
                "files_discovered": len(entries),
                "total_recoverable_bytes": sum(e.size_bytes for e in entries),
                "warnings": session.warnings,
                "errors": session.errors,
            },
            "recovery_summary": {
                "batches_run": len(logs),
                "files_recovered_total": total_succeeded + total_partial,
                "successful_recoveries": total_succeeded,
                "partial_recoveries": total_partial,
                "skipped_recoveries": total_skipped,
                "failed_recoveries": total_failed,
                "output_locations": list({l.destination_dir for l in logs}),
            },
            "recovery_batches": [
                {
                    "recovery_id": l.recovery_id,
                    "timestamp": l.timestamp,
                    "destination_dir": l.destination_dir,
                    "total_selected": l.total_selected,
                    "succeeded": l.succeeded,
                    "partial": l.partial,
                    "skipped": l.skipped,
                    "failed": l.failed,
                    "warnings": l.warnings,
                    "outcomes": l.file_outcomes,
                }
                for l in logs
            ],
        }

    @classmethod
    def format_txt_report(
        cls,
        session: Optional[ScanSessionRecord],
        entries: List[RecoveredFileEntry],
        recovery_logs: Optional[List[RecoveryLogRecord]] = None,
        all_sessions: Optional[List[ScanSessionRecord]] = None,
    ) -> str:
        """
        Build a structured Plain Text (.txt) report showing:
          1. Recovery Summary
          2. Saved Data Records (Recovered Files & Subfolders)
          3. Failed Recoveries, Warnings, and Errors
        (Excludes duplicate Found Data listings, which are displayed in the Scan section.)
        """
        logs = recovery_logs or []
        sessions_list = all_sessions or ([session] if session else [])
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        total_saved = sum(l.succeeded + l.partial for l in logs)
        total_intact = sum(l.succeeded for l in logs)
        total_partial_saved = sum(l.partial for l in logs)
        total_failed_saved = sum(l.failed + l.skipped for l in logs)

        issues_list: List[str] = []
        for s in sessions_list:
            for w in s.warnings:
                issues_list.append(f"[SCAN WARNING | {s.session_id}] {w}")
            for err in s.errors:
                issues_list.append(f"[SCAN ERROR   | {s.session_id}] {err}")

        for l in logs:
            for w in l.warnings:
                issues_list.append(f"[SAVE WARNING | {l.recovery_id}] {w}")
            for item in l.file_outcomes:
                out_status = item.get("outcome", "")
                if out_status in ("Failed", "Skipped", "Partial"):
                    issues_list.append(
                        f"[{out_status.upper():<12} | {item.get('file_name', '')}] "
                        f"{item.get('message', '')} -> {item.get('output_path', 'N/A')}"
                    )

        lines: List[str] = [
            "=" * 88,
            "RECOVERX — ADVANCED DATA RECOVERY TOOL | RECOVERY REPORT (.TXT)",
            f"Generated At: {now_str}",
            "=" * 88,
            "",
            "1. RECOVERY SUMMARY",
            "-" * 88,
            f"Saved Data Count    : {total_saved:,} file(s) saved ({total_intact:,} Intact, {total_partial_saved:,} Partial)",
            f"Failed / Skipped    : {total_failed_saved:,} file(s)",
            f"Warnings & Errors   : {len(issues_list):,} item(s)",
            "",
            "2. SAVED DATA RECORDS (RECOVERED FILES HISTORY)",
            "-" * 88,
        ]

        if logs:
            for l in logs:
                lines.append(
                    f"Batch ID: {l.recovery_id} | Date: {l.timestamp[:19].replace('T', ' ')} | "
                    f"Source: {l.source_device} | Output Folder: {l.destination_dir}"
                )
                lines.append(
                    f"Summary : Saved={l.succeeded + l.partial} (Intact={l.succeeded}, Partial={l.partial}), "
                    f"Failed={l.failed}, Skipped={l.skipped}"
                )
                for item in l.file_outcomes:
                    lines.append(
                        f"  • [{item.get('outcome', 'Saved'):<9}] {item.get('file_name', ''):<26} -> "
                        f"{item.get('output_path', '')} ({item.get('bytes_written', 0):,} B)"
                    )
                lines.append("-" * 88)
        else:
            lines.append("No saved data batches recorded yet.")

        lines.extend(
            [
                "",
                "3. FAILED RECOVERIES, WARNINGS & ERRORS",
                "-" * 88,
            ]
        )
        if issues_list:
            for issue in issues_list:
                lines.append(f"  ! {issue}")
        else:
            lines.append("  No errors, failed recoveries, or warnings recorded.")

        lines.append("=" * 88)
        return "\n".join(lines)

    @classmethod
    def export_txt(
        cls,
        output_path: str,
        session: Optional[ScanSessionRecord],
        entries: List[RecoveredFileEntry],
        recovery_logs: Optional[List[RecoveryLogRecord]] = None,
        all_sessions: Optional[List[ScanSessionRecord]] = None,
    ) -> str:
        text_report = cls.format_txt_report(
            session=session,
            entries=entries,
            recovery_logs=recovery_logs,
            all_sessions=all_sessions,
        )
        p = Path(output_path)
        if p.suffix.lower() != ".txt":
            p = p.with_suffix(".txt")
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as fp:
            fp.write(text_report)
        return str(p)

    @classmethod
    def export_json(
        cls,
        output_path: str,
        session: ScanSessionRecord,
        entries: List[RecoveredFileEntry],
        recovery_logs: Optional[List[RecoveryLogRecord]] = None,
    ) -> str:
        payload = cls.build_report_payload(session, entries, recovery_logs)
        p = Path(output_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as fp:
            json.dump(payload, fp, indent=2)
        return str(p)

    @classmethod
    def export_csv(
        cls,
        output_path: str,
        session: ScanSessionRecord,
        entries: List[RecoveredFileEntry],
        recovery_logs: Optional[List[RecoveryLogRecord]] = None,
    ) -> str:
        p = Path(output_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        outcome_map: Dict[str, Dict[str, Any]] = {}
        for log in recovery_logs or []:
            for item in log.file_outcomes:
                outcome_map[item.get("file_id", "")] = item

        with open(p, "w", newline="", encoding="utf-8") as fp:
            writer = csv.writer(fp)
            writer.writerow(
                [
                    "Session ID",
                    "Source Device",
                    "Scan Mode",
                    "File ID",
                    "File Name",
                    "Extension",
                    "Category",
                    "Size (Bytes)",
                    "Original Path",
                    "Modified Time",
                    "Recovery Method",
                    "Estimated Integrity",
                    "Structural Evidence",
                    "Recovery Outcome",
                    "Output Path",
                    "Output SHA-256",
                ]
            )
            for e in entries:
                out_info = outcome_map.get(e.id, {})
                writer.writerow(
                    [
                        session.session_id,
                        session.device_name,
                        session.scan_mode,
                        e.id,
                        e.name,
                        e.extension,
                        e.category.value,
                        e.size_bytes,
                        e.original_path,
                        e.modified_time.isoformat() if e.modified_time else "",
                        e.recovery_method.value,
                        e.status.value,
                        e.status_detail,
                        out_info.get("outcome", "Not Restored"),
                        out_info.get("output_path", ""),
                        out_info.get("sha256", e.sha256 or ""),
                    ]
                )
        return str(p)

    @classmethod
    def export_html(
        cls,
        output_path: str,
        session: ScanSessionRecord,
        entries: List[RecoveredFileEntry],
        recovery_logs: Optional[List[RecoveryLogRecord]] = None,
    ) -> str:
        payload = cls.build_report_payload(session, entries, recovery_logs)
        p = Path(output_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        s = payload["scan_session"]
        r = payload["recovery_summary"]
        html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>RecoverX Report — {html.escape(s['session_id'])}</title></head>
<body><h1>RecoverX Report ({r['successful_recoveries']} saved)</h1></body>
</html>"""
        with open(p, "w", encoding="utf-8") as fp:
            fp.write(html_doc)
        return str(p)
