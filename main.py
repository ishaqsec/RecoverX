#!/usr/bin/env python3
"""
RecoverX — Advanced Data Recovery & Digital Forensics Suite
Main Entry Point (PySide6 Windows Desktop GUI, CLI Mode, and Self-Test Runner).
"""
from __future__ import annotations

import argparse
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys
import traceback
import unittest
import warnings

warnings.filterwarnings("ignore", category=SyntaxWarning)

ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from devices.discovery import DriveDiscovery
from recovery.engine import RecoveryEngine, ScanMode
from reports.exporter import ReportExporter
from storage.database import RecoverXDatabase
from tests.fixture_generator import generate_all_sample_images


def setup_logging(verbose: bool = False) -> Path:
    """Configure structured rotating logging without exposing sensitive recovered file contents."""
    log_dir = Path.home() / ".recoverx"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "recoverx.log"
        fh = RotatingFileHandler(log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
    except OSError:
        import tempfile
        log_dir = Path(tempfile.gettempdir()) / "recoverx_data"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "recoverx.log"
        fh = RotatingFileHandler(log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")

    level = logging.DEBUG if verbose else logging.INFO
    fmt = logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s")

    root_logger = logging.getLogger("recoverx")
    root_logger.setLevel(level)
    root_logger.handlers.clear()

    fh.setFormatter(fmt)
    root_logger.addHandler(fh)

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    root_logger.addHandler(sh)
    return log_file


def ensure_sample_fixtures() -> Path:
    """Ensure disposable test disk images exist in `sample_images/` for `--self-test`."""
    sample_dir = ROOT_DIR / "sample_images"
    ntfs_img = sample_dir / "Local_Disk_C_NTFS.img"
    if not ntfs_img.exists():
        generate_all_sample_images(str(sample_dir))
    return sample_dir


def run_cli_mode(args: argparse.Namespace) -> int:
    ensure_sample_fixtures()
    db = RecoverXDatabase()
    engine = RecoveryEngine(db=db)
    discovery = DriveDiscovery()

    target_path = args.scan
    if not os.path.exists(target_path):
        print(f"[ERROR] Source image or device not found: {target_path}", file=sys.stderr)
        return 1

    dev = discovery.add_disk_image(target_path)
    mode_map = {
        "quick": ScanMode.QUICK_SCAN,
        "deep": ScanMode.DEEP_SCAN,
        "carve": ScanMode.FILE_CARVING,
        "image": ScanMode.SCAN_IMAGE_FILE,
    }
    scan_mode = mode_map.get(args.mode.lower(), ScanMode.DEEP_SCAN)
    print(f"[RecoverX] Scanning '{dev.name}' ({dev.filesystem}) in {scan_mode.value} mode (Read-Only)...")

    session, entries = engine.run_scan(
        device=dev,
        scan_mode=scan_mode,
        confirm_physical_access=args.confirm_physical,
    )
    print(f"[RecoverX] Scan {session.status}: discovered {len(entries)} recoverable files.")
    for idx, e in enumerate(entries, start=1):
        print(
            f"  {idx:02d}. {e.name:<24} | {e.size_Formatted:<10} | {e.extension:<5} | "
            f"{e.recovery_method.value:<22} | {e.status.value} ({e.status_detail})"
        )

    if args.recover_to:
        log_rec, outcomes = engine.recover_files(
            device=dev,
            entries=entries,
            destination_dir=args.recover_to,
            session_id=session.session_id,
            confirm_physical_access=args.confirm_physical,
        )
        print(
            f"[RecoverX] Recovery batch {log_rec.recovery_id}: "
            f"Succeeded={log_rec.succeeded}, Partial={log_rec.partial}, "
            f"Skipped={log_rec.skipped}, Failed={log_rec.failed}"
        )

    if args.export_report:
        out_p = args.export_report
        logs = db.list_recovery_logs()
        if out_p.endswith(".csv"):
            ReportExporter.export_csv(out_p, session, entries, logs)
        elif out_p.endswith(".html"):
            ReportExporter.export_html(out_p, session, entries, logs)
        else:
            ReportExporter.export_json(out_p, session, entries, logs)
        print(f"[RecoverX] Exported forensic report to: {out_p}")

    return 0


def run_self_test() -> int:
    ensure_sample_fixtures()
    suite = unittest.defaultTestLoader.discover(
        str(ROOT_DIR / "tests"),
        pattern="test_*.py",
        top_level_dir=str(ROOT_DIR),
    )
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return 0 if result.wasSuccessful() else 1


def _install_qt_exception_hook() -> None:
    orig_hook = sys.excepthook

    def _hook(exc_type, exc_value, exc_tb):
        traceback.print_exception(exc_type, exc_value, exc_tb, file=sys.stderr)
        orig_hook(exc_type, exc_value, exc_tb)

    sys.excepthook = _hook


def main() -> int:
    parser = argparse.ArgumentParser(
        description="RecoverX — Advanced Data Recovery & Digital Forensics Suite"
    )
    parser.add_argument("--self-test", action="store_true", help="Run automated disposable disk-image test suite")
    parser.add_argument("--scan", type=str, help="Run headless read-only scan on a disk image or device path")
    parser.add_argument("--mode", type=str, default="deep", choices=["quick", "deep", "carve", "image"], help="Scan mode for --scan")
    parser.add_argument("--recover-to", type=str, help="Safe destination directory to restore discovered files")
    parser.add_argument("--export-report", type=str, help="Export report to .json, .csv, or .html path")
    parser.add_argument("--confirm-physical", action="store_true", help="Confirm read-only access to physical disks")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")
    args = parser.parse_args()

    setup_logging(verbose=args.verbose)

    if args.self_test:
        return run_self_test()

    if args.scan:
        return run_cli_mode(args)

    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtWidgets import QApplication
        from ui.main_window import RecoverXMainWindow
    except ImportError as exc:
        print(
            f"[RecoverX] PySide6 is required to launch the desktop GUI ({exc}).\n"
            "Install dependencies with: pip install -r requirements.txt\n"
            "Or run headless verification with: python main.py --self-test",
            file=sys.stderr,
        )
        return 1

    _install_qt_exception_hook()

    try:
        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )

        app = QApplication(sys.argv)
        app.setApplicationName("RecoverX")
        app.setOrganizationName("RecoverX Digital Forensics")

        window = RecoverXMainWindow()
        window.show()
        window.raise_()
        window.activateWindow()
        return app.exec()
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        logging.getLogger("recoverx").error("Fatal GUI error: %s", exc, exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
