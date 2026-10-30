"""
Comprehensive Reproducible Automated Test Suite for RecoverX.
Tests all recovery requirements using disposable binary disk images with known original files.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import struct
import sys
import tempfile
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from carving.validators import validate_and_measure_carved_data
from devices.discovery import (
    DeviceInfo,
    DeviceType,
    DriveDiscovery,
    detect_image_filesystem,
)
from devices.reader import (
    DeviceAccessError,
    PhysicalDiskConfirmationRequired,
    ReadOnlyDeviceReader,
)
from filesystems.base import IntegrityStatus, RecoveryMethod
from preview.handler import PreviewHandler, PreviewKind
from recovery.engine import (
    DestinationSameDeviceError,
    RecoveryEngine,
    ScanMode,
)
from reports.exporter import ReportExporter
from storage.database import RecoverXDatabase
from tests.fixture_generator import generate_all_sample_images
from ui.theme import DARK_PALETTE, LIGHT_PALETTE, ThemeManager


class RecoverXTestSuite(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp_root = tempfile.mkdtemp(prefix="recoverx_tests_")
        cls.images_dir = os.path.join(cls.temp_root, "images")
        cls.paths, cls.artifacts = generate_all_sample_images(cls.images_dir)
        cls.db_path = os.path.join(cls.temp_root, "test_state.db")
        cls.db = RecoverXDatabase(cls.db_path)
        cls.engine = RecoveryEngine(db=cls.db)
        cls.discovery = DriveDiscovery()

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls.temp_root, ignore_errors=True)

    def test_01_read_only_device_safety_and_physical_guard(self) -> None:
        """Verify read-only mode enforcement, write blocking, and physical disk confirmation requirement."""
        phys_dev = DeviceInfo(
            id="phys:0",
            name="Physical Disk 0",
            path=self.paths["ntfs"],
            device_type=DeviceType.PHYSICAL_DISK,
            filesystem="NTFS",
            total_bytes=os.path.getsize(self.paths["ntfs"]),
        )
        with self.assertRaises(PhysicalDiskConfirmationRequired):
            with ReadOnlyDeviceReader(phys_dev, confirm_physical_access=False):
                pass

        with ReadOnlyDeviceReader(phys_dev, confirm_physical_access=True) as reader:
            with self.assertRaises(PermissionError):
                reader.write(b"malicious_write")
            with self.assertRaises(PermissionError):
                reader.truncate(0)
            boot = reader.read_at(0, 512)
            self.assertEqual(boot[3:11], b"NTFS    ")

        enc_dev = DeviceInfo(
            id="enc:0",
            name="BitLocker Volume",
            path=self.paths["ntfs"],
            device_type=DeviceType.LOGICAL_VOLUME,
            filesystem="BitLocker Encrypted",
            is_encrypted=True,
        )
        with self.assertRaises(DeviceAccessError):
            with ReadOnlyDeviceReader(enc_dev):
                pass

    def test_02_ntfs_quick_scan_metadata_and_exact_byte_recovery(self) -> None:
        """Test NTFS $MFT Quick Scan for resident, non-resident, directory paths, and partial files."""
        ntfs_dev = self.discovery.add_disk_image(self.paths["ntfs"])
        self.assertEqual(ntfs_dev.filesystem, "NTFS")

        session, entries = self.engine.run_scan(ntfs_dev, scan_mode=ScanMode.QUICK_SCAN)
        self.assertEqual(session.status, "Completed")
        by_name = {e.name: e for e in entries}

        # Verify active file is NOT returned as recovered
        self.assertNotIn("Active_System_Config.ini", by_name)
        for e in entries:
            self.assertTrue(e.is_deleted)

        self.assertIn("Old_File.txt", by_name)
        txt_entry = by_name["Old_File.txt"]
        self.assertEqual(txt_entry.status, IntegrityStatus.GOOD)
        self.assertEqual(txt_entry.recovery_method, RecoveryMethod.NTFS_MFT)

        self.assertIn("Vacation_Photo.jpg", by_name)
        jpg_entry = by_name["Vacation_Photo.jpg"]
        self.assertEqual(jpg_entry.status, IntegrityStatus.GOOD)
        self.assertIn("Photos\\Vacation_Photo.jpg", jpg_entry.original_path)

        self.assertIn("Project_Report.pdf", by_name)
        pdf_entry = by_name["Project_Report.pdf"]
        self.assertEqual(pdf_entry.status, IntegrityStatus.GOOD)

        self.assertIn("Document.docx", by_name)
        docx_entry = by_name["Document.docx"]
        self.assertEqual(docx_entry.status, IntegrityStatus.PARTIAL)

        restore_dir = os.path.join(self.temp_root, "restore_ntfs")
        log_rec, outcomes = self.engine.recover_files(
            device=ntfs_dev,
            entries=[txt_entry, jpg_entry, pdf_entry, docx_entry],
            destination_dir=restore_dir,
            session_id=session.session_id,
        )
        self.assertEqual(log_rec.succeeded, 3)
        self.assertEqual(log_rec.partial, 1)

        out_map = {o.file_name: o for o in outcomes}
        expected_subfolders = {
            "Old_File.txt": "Documents",
            "Vacation_Photo.jpg": "Images",
            "Project_Report.pdf": "Documents",
            "Document.docx": "Documents",
        }
        for fname in ("Old_File.txt", "Vacation_Photo.jpg", "Project_Report.pdf"):
            expected = self.artifacts[fname]
            outcome = out_map[fname]
            self.assertEqual(outcome.sha256, expected.sha256)
            self.assertEqual(Path(outcome.output_path).parent.name, expected_subfolders[fname])
            with open(outcome.output_path, "rb") as fp:
                restored_bytes = fp.read()
            self.assertEqual(restored_bytes, expected.payload)

    def test_03_deep_scan_carving_unallocated_and_false_positive_rejection(self) -> None:
        """
        Test Deep Scan on NTFS image: recovers both MFT deleted files AND unallocated
        'Photo_001.png' (whose directory entry was removed), while rejecting the false-positive
        invalid JPEG signature at 0x00070000.
        """
        ntfs_dev = self.discovery.add_disk_image(self.paths["ntfs"])
        session, entries = self.engine.run_scan(ntfs_dev, scan_mode=ScanMode.DEEP_SCAN)
        carved_pngs = [
            e for e in entries
            if e.recovery_method == RecoveryMethod.SIGNATURE_CARVING and e.extension == "PNG"
        ]
        self.assertGreaterEqual(len(carved_pngs), 1)

        with ReadOnlyDeviceReader(ntfs_dev) as reader:
            raw_png = carved_pngs[0].extract_bytes(reader)
        self.assertEqual(hashlib.sha256(raw_png).hexdigest(), self.artifacts["Photo_001.png"].sha256)
        self.assertEqual(raw_png, self.artifacts["Photo_001.png"].payload)

        bad_offsets = [e for e in entries if e.primary_offset == 0x00070000]
        self.assertEqual(len(bad_offsets), 0)

        self.assertIsNone(validate_and_measure_carved_data(b"\xff\xd8\xff\x00NOT_A_JPEG_STREAM"))
        self.assertIsNone(validate_and_measure_carved_data(b"%PDF-1.4\nNO_OBJECTS_AT_ALL"))

    def test_04_fat32_deleted_entries_and_vfat_lfn_recovery(self) -> None:
        """Test FAT32 parser on deleted 0xE5 entries with VFAT Long File Names & Video Preview."""
        fat_dev = self.discovery.add_disk_image(self.paths["fat32"])
        self.assertEqual(fat_dev.filesystem, "FAT32")

        session, entries = self.engine.run_scan(fat_dev, scan_mode=ScanMode.QUICK_SCAN)
        by_name = {e.name: e for e in entries}
        self.assertIn("Archive.zip", by_name)
        self.assertIn("Family_Video.mp4", by_name)

        # Verify visual video preview generation for MP4
        vid_entry = by_name["Family_Video.mp4"]
        pdata = PreviewHandler.generate_preview(vid_entry, device=fat_dev)
        self.assertEqual(pdata.kind, PreviewKind.VIDEO)
        self.assertIsNotNone(pdata.image_png_bytes)
        self.assertTrue(pdata.image_png_bytes.startswith(b"\x89PNG\r\n\x1a\n"))

        restore_dir = os.path.join(self.temp_root, "restore_fat32")
        _, outcomes = self.engine.recover_files(
            device=fat_dev,
            entries=[by_name["Archive.zip"], by_name["Family_Video.mp4"]],
            destination_dir=restore_dir,
            session_id=session.session_id,
        )
        for o in outcomes:
            expected = self.artifacts[o.file_name]
            self.assertEqual(o.sha256, expected.sha256)
            with open(o.output_path, "rb") as fp:
                self.assertEqual(fp.read(), expected.payload)

    def test_05_exfat_deleted_entry_set_recovery(self) -> None:
        """Test exFAT parser on deleted File (0x05), Stream (0x40), and Name (0x41) entry sets."""
        exfat_dev = self.discovery.add_disk_image(self.paths["exfat"])
        self.assertEqual(exfat_dev.filesystem, "exFAT")

        session, entries = self.engine.run_scan(exfat_dev, scan_mode=ScanMode.QUICK_SCAN)
        by_name = {e.name: e for e in entries}
        self.assertIn("Voice_Note.wav", by_name)
        self.assertIn("Photo_001.png", by_name)

        restore_dir = os.path.join(self.temp_root, "restore_exfat")
        _, outcomes = self.engine.recover_files(
            device=exfat_dev,
            entries=[by_name["Voice_Note.wav"], by_name["Photo_001.png"]],
            destination_dir=restore_dir,
            session_id=session.session_id,
        )
        for o in outcomes:
            expected = self.artifacts[o.file_name]
            self.assertEqual(o.sha256, expected.sha256)

    def test_06_cancellation_and_large_chunked_scan(self) -> None:
        """Test scan cancellation mid-stream and verify clean stopping & session recording."""
        ntfs_dev = self.discovery.add_disk_image(self.paths["ntfs"])
        calls = 0

        def cancel_after_first() -> bool:
            nonlocal calls
            calls += 1
            return calls > 2

        session, _ = self.engine.run_scan(
            ntfs_dev,
            scan_mode=ScanMode.DEEP_SCAN,
            cancel_check=cancel_after_first,
        )
        self.assertEqual(session.status, "Cancelled")
        self.assertTrue(any("cancelled" in w.lower() for w in session.warnings))

    def test_07_same_device_protection_and_collision_resolution(self) -> None:
        """Verify same-device destination protection, filename collision handling, and write errors."""
        ntfs_dev = self.discovery.add_disk_image(self.paths["ntfs"])
        _, entries = self.engine.run_scan(ntfs_dev, scan_mode=ScanMode.QUICK_SCAN)
        txt_entry = next(e for e in entries if e.name == "Old_File.txt")

        same_vol_dev = DeviceInfo(
            id="win:C",
            name="Local Disk (C:)",
            path=self.paths["ntfs"],
            device_type=DeviceType.LOGICAL_VOLUME,
            filesystem="NTFS",
            mount_point=os.path.join(self.temp_root, "simulated_c_drive"),
        )
        os.makedirs(same_vol_dev.mount_point, exist_ok=True)
        with self.assertRaises(DestinationSameDeviceError):
            self.engine.recover_files(
                device=same_vol_dev,
                entries=[txt_entry],
                destination_dir=os.path.join(same_vol_dev.mount_point, "Recovered"),
                allow_same_device=False,
            )

        collision_dir = os.path.join(self.temp_root, "collision_test")
        _, out1 = self.engine.recover_files(ntfs_dev, [txt_entry], collision_dir, preserve_structure=False)
        _, out2 = self.engine.recover_files(ntfs_dev, [txt_entry], collision_dir, preserve_structure=False)
        self.assertNotEqual(out1[0].output_path, out2[0].output_path)
        self.assertIn("_recovered_1", out2[0].output_path)
        self.assertTrue(os.path.exists(out1[0].output_path))
        self.assertTrue(os.path.exists(out2[0].output_path))

    def test_08_deleted_only_mounted_scan_and_reports_clear(self) -> None:
        """
        Verify:
        1. Mounted volume live scan ONLY returns deleted/recycled files ($Recycle.Bin / .Trash)
           and NEVER returns existing active files in Desktop/Documents/Pictures.
        2. `ReportExporter.export_txt` and `db.clear_reports()` work properly.
        """
        sim_vol_dir = os.path.join(self.temp_root, "sim_live_vol")
        active_dir = os.path.join(sim_vol_dir, "Users", "TestUser", "Documents")
        recycle_dir = os.path.join(sim_vol_dir, "$Recycle.Bin", "S-1-5-21-1000")
        os.makedirs(active_dir, exist_ok=True)
        os.makedirs(recycle_dir, exist_ok=True)

        with open(os.path.join(active_dir, "Existing_Active_Work.docx"), "wb") as fp:
            fp.write(b"ACTIVE_FILE_CONTENT_DO_NOT_RECOVER")

        with open(os.path.join(recycle_dir, "$R123456.jpg"), "wb") as fp:
            fp.write(self.artifacts["Vacation_Photo.jpg"].payload)

        live_dev = DeviceInfo(
            id="win:Z",
            name="Simulated Volume (Z:)",
            path="\\\\.\\Z:",
            device_type=DeviceType.LOGICAL_VOLUME,
            filesystem="NTFS",
            mount_point=sim_vol_dir,
        )
        _, found = self.engine.run_scan(live_dev, scan_mode=ScanMode.QUICK_SCAN)
        found_names = {e.name for e in found}
        self.assertNotIn("Existing_Active_Work.docx", found_names)
        self.assertIn("$R123456.jpg", found_names)

        rep_dir = os.path.join(self.temp_root, "reports")
        logs = self.db.list_recovery_logs()
        self.assertGreaterEqual(len(logs), 1)
        txt_p = ReportExporter.export_txt(os.path.join(rep_dir, "report.txt"), None, found, logs)
        with open(txt_p, "r", encoding="utf-8") as fp:
            txt_content = fp.read()
        self.assertIn("SAVED DATA RECORDS (RECOVERED FILES HISTORY)", txt_content)
        self.assertNotIn("FOUND DATA RECORDS (DISCOVERED FILES)", txt_content)

        self.db.clear_reports()
        self.assertEqual(len(self.db.list_recovery_logs()), 0)

    def test_09_no_preshown_physical_disks_and_dynamic_peripheral_hotplug(self) -> None:
        """Verify that enumerate_all() does not pre-show Physical Disks or sample images until connected/added."""
        fresh_discovery = DriveDiscovery()
        initial_devs = fresh_discovery.enumerate_all(sample_images_dir=self.images_dir)
        for d in initial_devs:
            self.assertNotEqual(d.device_type, DeviceType.PHYSICAL_DISK)
            self.assertNotEqual(d.device_type, DeviceType.DISK_IMAGE)

        sig_before = fresh_discovery.get_connected_drive_signature()
        fresh_discovery.add_disk_image(self.paths["exfat"])
        sig_after = fresh_discovery.get_connected_drive_signature()
        self.assertNotEqual(sig_before, sig_after)

    def test_10_ui_clear_reports_no_text_log_and_rotating_orbit(self) -> None:
        """
        Verify:
        - `Clear Reports` button (`btn_clear_reports` & `clear_all_reports`) in `ReportsView`.
        - Text log box (`detail_box`) and Found Data removed from `ReportsView`.
        - 360-degree rotating 3D Neon Orbit animation (`_orbit_angle`, `_platter_angle_deg`, `orbit_hdd_clean.png`) in `ui/widgets.py`.
        """
        with open(ROOT_DIR / "ui" / "views.py", "r", encoding="utf-8") as vfp:
            v_src = vfp.read()
        with open(ROOT_DIR / "ui" / "widgets.py", "r", encoding="utf-8") as wfp:
            w_src = wfp.read()

        self.assertIn("btn_clear_reports", v_src)
        self.assertIn("def clear_all_reports", v_src)
        self.assertNotIn("self.detail_box", v_src)
        self.assertNotIn("lbl_kpi_found", v_src)
        self.assertIn("_orbit_angle", w_src)
        self.assertIn("_platter_angle_deg", w_src)
        self.assertTrue((ROOT_DIR / "assets" / "orbit_hdd_clean.png").exists())
        self.assertTrue((ROOT_DIR / "assets" / "orbit_tile_image.png").exists())
        self.assertTrue((ROOT_DIR / "assets" / "orbit_tile_doc.png").exists())
        self.assertTrue((ROOT_DIR / "assets" / "orbit_tile_video.png").exists())
        self.assertTrue((ROOT_DIR / "assets" / "orbit_tile_audio.png").exists())

    def test_11_ext4_parser_hover_styles_and_clean_startup_without_previous_records(self) -> None:
        """
        Verify:
        1. EXT4 deleted inode & extent tree recovery works on an EXT4 image.
        2. Enhanced button hover styles (`PrimaryStartScanBtn:hover`, `PrimaryActionBtn:hover`, `OutlinedActionBtn:hover`) are present.
        3. `clear_all_session_and_report_records()` clears all previous sessions, findings, and recovery logs on tool startup.
        """
        # 1. Build a disposable EXT4 image with a deleted inode (inode 12) pointing to Vacation_Photo.jpg
        ext4_path = os.path.join(self.temp_root, "android_userdata_ext4.img")
        block_size = 4096
        total_blocks = 64
        img_buf = bytearray(block_size * total_blocks)

        # Superblock at offset 1024
        sb_off = 1024
        struct.pack_into("<I", img_buf, sb_off + 0x00, 64)           # s_inodes_count
        struct.pack_into("<I", img_buf, sb_off + 0x04, total_blocks) # s_blocks_count_lo
        struct.pack_into("<I", img_buf, sb_off + 0x14, 0)            # s_first_data_block
        struct.pack_into("<I", img_buf, sb_off + 0x18, 2)            # s_log_block_size (4096)
        struct.pack_into("<I", img_buf, sb_off + 0x20, 64)           # s_blocks_per_group
        struct.pack_into("<I", img_buf, sb_off + 0x28, 64)           # s_inodes_per_group
        struct.pack_into("<H", img_buf, sb_off + 0x38, 0xEF53)       # s_magic (EXT4)
        struct.pack_into("<I", img_buf, sb_off + 0x4C, 1)            # s_rev_level = 1
        struct.pack_into("<H", img_buf, sb_off + 0x58, 256)          # s_inode_size = 256

        # Group Descriptor 0 at block 1 (offset 4096): bg_inode_table = block 2
        gdt_off = block_size * 1
        struct.pack_into("<I", img_buf, gdt_off + 0x08, 2)

        # Write payload of Vacation_Photo.jpg at block 10 (offset 40960)
        jpg_payload = self.artifacts["Vacation_Photo.jpg"].payload
        data_blk = 10
        num_blks = (len(jpg_payload) + block_size - 1) // block_size
        img_buf[data_blk * block_size : data_blk * block_size + len(jpg_payload)] = jpg_payload

        # Write deleted Inode 12 (index 11 in group 0) at block 2 + 11 * 256
        ino_off = block_size * 2 + 11 * 256
        struct.pack_into("<H", img_buf, ino_off + 0x00, 0x81A4)            # S_IFREG | 0644
        struct.pack_into("<I", img_buf, ino_off + 0x04, len(jpg_payload))  # i_size_lo
        struct.pack_into("<I", img_buf, ino_off + 0x10, 1700000000)        # i_mtime
        struct.pack_into("<I", img_buf, ino_off + 0x14, 1700000100)        # i_dtime > 0 (deleted)
        struct.pack_into("<H", img_buf, ino_off + 0x1A, 0)                 # i_links_count = 0
        struct.pack_into("<I", img_buf, ino_off + 0x20, 0x00080000)        # EXT4_EXTENTS_FL
        # Extent header (eh_magic=0xF30A, eh_entries=1, eh_max=4, eh_depth=0) + 1 extent
        struct.pack_into("<HHHH", img_buf, ino_off + 0x28, 0xF30A, 1, 4, 0)
        struct.pack_into("<IHHI", img_buf, ino_off + 0x28 + 12, 0, num_blks, 0, data_blk)

        with open(ext4_path, "wb") as fp:
            fp.write(img_buf)

        fs_name, is_enc, _ = detect_image_filesystem(ext4_path)
        self.assertEqual(fs_name, "EXT4")
        self.assertFalse(is_enc)

        ext4_dev = self.discovery.add_disk_image(ext4_path)
        session, ext4_entries = self.engine.run_scan(ext4_dev, scan_mode=ScanMode.QUICK_SCAN)
        self.assertEqual(session.status, "Completed")
        self.assertGreaterEqual(len(ext4_entries), 1)
        self.assertEqual(ext4_entries[0].recovery_method, RecoveryMethod.EXT4_INODE)
        self.assertEqual(ext4_entries[0].extension, "JPG")
        self.assertEqual(ext4_entries[0].size_bytes, len(jpg_payload))

        # 2. Verify enhanced button hover stylesheets
        for pal in (LIGHT_PALETTE, DARK_PALETTE):
            qss = ThemeManager.build_stylesheet(pal)
            self.assertIn("QPushButton#PrimaryStartScanBtn:hover", qss)
            self.assertIn("QPushButton#PrimaryStartScanBtn:pressed", qss)
            self.assertIn("QPushButton#PrimaryActionBtn:hover", qss)
            self.assertIn("QPushButton#OutlinedActionBtn:hover", qss)
            self.assertIn("QPushButton#StopScanBtn:hover", qss)

        # 3. Verify clean startup clears all previous sessions, findings, and recovery logs
        self.assertGreater(len(self.db.list_sessions()), 0)
        self.db.clear_all_session_and_report_records()
        self.assertEqual(len(self.db.list_sessions()), 0)
        self.assertEqual(len(self.db.list_recovery_logs()), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
