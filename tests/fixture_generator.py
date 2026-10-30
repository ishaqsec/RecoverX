"""
Deterministic Disposable Disk-Image Fixture Generator for RecoverX.
Creates real binary NTFS, FAT32, and exFAT disk images containing known files,
deleted records, fragmented runs, partially overwritten files, and invalid-signature traps.
"""
from __future__ import annotations

import hashlib
import io
import json
import struct
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Tuple

from PIL import Image, ImageDraw


@dataclass
class KnownTestArtifact:
    name: str
    extension: str
    payload: bytes
    sha256: str
    expect_complete: bool = True


def build_known_payloads() -> Dict[str, KnownTestArtifact]:
    """Generate real, valid binary files (JPG, PNG, PDF, DOCX, ZIP, MP4, WAV, TXT) with known SHA-256 hashes."""
    artifacts: Dict[str, KnownTestArtifact] = {}

    # 1. Valid JPEG Image
    img_jpg = Image.new("RGB", (160, 100), color=(24, 92, 185))
    draw = ImageDraw.Draw(img_jpg)
    draw.rectangle([20, 20, 140, 80], outline=(255, 255, 255), width=3)
    jpg_buf = io.BytesIO()
    img_jpg.save(jpg_buf, format="JPEG", quality=92)
    jpg_bytes = jpg_buf.getvalue()
    artifacts["Vacation_Photo.jpg"] = KnownTestArtifact(
        name="Vacation_Photo.jpg",
        extension="JPG",
        payload=jpg_bytes,
        sha256=hashlib.sha256(jpg_bytes).hexdigest(),
    )

    # 2. Valid PNG Image
    img_png = Image.new("RGBA", (120, 90), color=(16, 185, 129, 255))
    png_buf = io.BytesIO()
    img_png.save(png_buf, format="PNG")
    png_bytes = png_buf.getvalue()
    artifacts["Photo_001.png"] = KnownTestArtifact(
        name="Photo_001.png",
        extension="PNG",
        payload=png_bytes,
        sha256=hashlib.sha256(png_bytes).hexdigest(),
    )

    # 3. Valid PDF Document
    pdf_bytes = (
        b"%PDF-1.4\n"
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R >>\nendobj\n"
        b"4 0 obj\n<< /Length 55 >>\nstream\nBT /F1 18 Tf 72 712 Td (RecoverX Forensic Test PDF) Tj ET\nendstream\nendobj\n"
        b"xref\n0 5\n0000000000 65535 f \n"
        b"trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n260\n%%EOF\n"
    )
    artifacts["Project_Report.pdf"] = KnownTestArtifact(
        name="Project_Report.pdf",
        extension="PDF",
        payload=pdf_bytes,
        sha256=hashlib.sha256(pdf_bytes).hexdigest(),
    )

    # 4. Valid DOCX (Office OpenXML container)
    docx_buf = io.BytesIO()
    with zipfile.ZipFile(docx_buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"></Types>',
        )
        zf.writestr(
            "word/document.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:body><w:p><w:r><w:t>Confidential Forensics Case Report</w:t></w:r></w:p></w:body></w:document>",
        )
    docx_bytes = docx_buf.getvalue()
    artifacts["Document.docx"] = KnownTestArtifact(
        name="Document.docx",
        extension="DOCX",
        payload=docx_bytes,
        sha256=hashlib.sha256(docx_bytes).hexdigest(),
    )

    # 5. Valid ZIP Archive
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("evidence_notes.txt", "RecoverX test archive content verified.\n")
        zf.writestr("manifest.json", '{"case_id": "RX-2026-001", "verified": true}\n')
    zip_bytes = zip_buf.getvalue()
    artifacts["Archive.zip"] = KnownTestArtifact(
        name="Archive.zip",
        extension="ZIP",
        payload=zip_bytes,
        sha256=hashlib.sha256(zip_bytes).hexdigest(),
    )

    # 6. Valid MP4 ISO Base Media container
    ftyp_atom = struct.pack(">I4s4sI4s", 20, b"ftyp", b"isom", 512, b"isom")
    moov_payload = b"mvhd" + b"\x00" * 36
    moov_atom = struct.pack(">I4s", 8 + len(moov_payload), b"moov") + moov_payload
    mdat_payload = b"\x11\x22\x33\x44" * 64
    mdat_atom = struct.pack(">I4s", 8 + len(mdat_payload), b"mdat") + mdat_payload
    mp4_bytes = ftyp_atom + moov_atom + mdat_atom
    artifacts["Family_Video.mp4"] = KnownTestArtifact(
        name="Family_Video.mp4",
        extension="MP4",
        payload=mp4_bytes,
        sha256=hashlib.sha256(mp4_bytes).hexdigest(),
    )

    # 7. Valid WAV Audio RIFF container
    pcm_samples = b"\x00\x10\x20\x10\x00\xf0\xe0\xf0" * 32
    fmt_chunk = b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, 8000, 8000, 1, 8)
    data_chunk = b"data" + struct.pack("<I", len(pcm_samples)) + pcm_samples
    riff_body = b"WAVE" + fmt_chunk + data_chunk
    wav_bytes = b"RIFF" + struct.pack("<I", len(riff_body)) + riff_body
    artifacts["Voice_Note.wav"] = KnownTestArtifact(
        name="Voice_Note.wav",
        extension="WAV",
        payload=wav_bytes,
        sha256=hashlib.sha256(wav_bytes).hexdigest(),
    )

    # 8. Valid Plain Text File
    txt_bytes = (
        b"RecoverX Digital Forensics Test Note\n"
        b"Original Path: C:\\Recovered\\Notes\\Old_File.txt\n"
        b"Verification Token: RECOVERX-EXACT-MATCH-99481\n"
    )
    artifacts["Old_File.txt"] = KnownTestArtifact(
        name="Old_File.txt",
        extension="TXT",
        payload=txt_bytes,
        sha256=hashlib.sha256(txt_bytes).hexdigest(),
    )

    return artifacts


def _apply_ntfs_usa_to_record(rec_buf: bytearray) -> bytes:
    usa_off = 42
    usa_count = 3
    usn = b"\x01\x00"
    orig_sec0 = bytes(rec_buf[510:512])
    orig_sec1 = bytes(rec_buf[1022:1024])
    struct.pack_into("<HH", rec_buf, 4, usa_off, usa_count)
    rec_buf[usa_off : usa_off + 2] = usn
    rec_buf[usa_off + 2 : usa_off + 4] = orig_sec0
    rec_buf[usa_off + 4 : usa_off + 6] = orig_sec1
    rec_buf[510:512] = usn
    rec_buf[1022:1024] = usn
    return bytes(rec_buf)


def _make_ntfs_mft_record(
    record_num: int,
    flags: int,
    filename: str,
    parent_ref: int,
    resident_payload: bytes | None = None,
    runlist_bytes: bytes | None = None,
    real_size: int = 0,
) -> bytes:
    rec = bytearray(1024)
    rec[0:4] = b"FILE"
    attr_offset = 56
    struct.pack_into("<H", rec, 20, attr_offset)
    struct.pack_into("<H", rec, 22, flags)
    struct.pack_into("<I", rec, 44, record_num)

    pos = attr_offset

    ft_now = 133900000000000000
    si_val = struct.pack("<QQQQ", ft_now, ft_now, ft_now, ft_now) + b"\x00" * 16
    si_len = 24 + len(si_val)
    struct.pack_into("<IIBBHHHIHH", rec, pos, 0x10, si_len, 0, 0, 0, 0, 1, len(si_val), 24, 0)
    rec[pos + 24 : pos + 24 + len(si_val)] = si_val
    pos += si_len

    fn_utf16 = filename.encode("utf-16le")
    fn_val_hdr = struct.pack(
        "<QQQQQQQIIBB",
        parent_ref,
        ft_now,
        ft_now,
        ft_now,
        ft_now,
        real_size,
        real_size,
        0,
        0,
        len(filename),
        1,
    )
    fn_val = fn_val_hdr + fn_utf16
    fn_len = ((24 + len(fn_val) + 7) // 8) * 8
    struct.pack_into("<IIBBHHHIHH", rec, pos, 0x30, fn_len, 0, 0, 0, 0, 2, len(fn_val), 24, 0)
    rec[pos + 24 : pos + 24 + len(fn_val)] = fn_val
    pos += fn_len

    if resident_payload is not None:
        d_len = ((24 + len(resident_payload) + 7) // 8) * 8
        struct.pack_into("<IIBBHHHIHH", rec, pos, 0x80, d_len, 0, 0, 0, 0, 3, len(resident_payload), 24, 0)
        rec[pos + 24 : pos + 24 + len(resident_payload)] = resident_payload
        pos += d_len
    elif runlist_bytes is not None:
        rl_off = 64
        d_len = ((rl_off + len(runlist_bytes) + 7) // 8) * 8
        struct.pack_into("<IIBBHHH", rec, pos, 0x80, d_len, 1, 0, 0, 0, 3)
        alloc_sz = ((real_size + 4095) // 4096) * 4096
        struct.pack_into("<QQHHIQQQ", rec, pos + 16, 0, max(0, (alloc_sz // 4096) - 1), rl_off, 0, 0, alloc_sz, real_size, real_size)
        rec[pos + rl_off : pos + rl_off + len(runlist_bytes)] = runlist_bytes
        pos += d_len

    struct.pack_into("<I", rec, pos, 0xFFFFFFFF)
    struct.pack_into("<I", rec, 24, pos + 8)
    struct.pack_into("<I", rec, 28, 1024)
    return _apply_ntfs_usa_to_record(rec)


def create_ntfs_test_image(image_path: str, artifacts: Dict[str, KnownTestArtifact]) -> None:
    total_size = 2 * 1024 * 1024
    img = bytearray(total_size)

    boot = bytearray(512)
    boot[0:3] = b"\xeb\x52\x90"
    boot[3:11] = b"NTFS    "
    struct.pack_into("<HB", boot, 11, 512, 8)
    struct.pack_into("<Q", boot, 40, total_size // 512)
    struct.pack_into("<Q", boot, 48, 4)
    struct.pack_into("<b", boot, 64, -10)
    boot[510:512] = b"\x55\xaa"
    img[0:512] = boot

    mft_base = 4 * 4096

    rec0 = _make_ntfs_mft_record(0, 0x0001, "$MFT", 5, runlist_bytes=b"\x11\x08\x04\x00", real_size=32 * 1024)
    img[mft_base : mft_base + 1024] = rec0

    rec5 = _make_ntfs_mft_record(5, 0x0003, "", 5)
    img[mft_base + 5 * 1024 : mft_base + 6 * 1024] = rec5

    rec16 = _make_ntfs_mft_record(16, 0x0003, "Photos", 5)
    img[mft_base + 16 * 1024 : mft_base + 17 * 1024] = rec16

    txt_art = artifacts["Old_File.txt"]
    rec17 = _make_ntfs_mft_record(
        17, 0x0000, txt_art.name, 5, resident_payload=txt_art.payload, real_size=len(txt_art.payload)
    )
    img[mft_base + 17 * 1024 : mft_base + 18 * 1024] = rec17

    jpg_art = artifacts["Vacation_Photo.jpg"]
    jpg_lcn = 40
    jpg_clusters = (len(jpg_art.payload) + 4095) // 4096
    rl_jpg = bytes([0x11, jpg_clusters, jpg_lcn, 0x00])
    rec18 = _make_ntfs_mft_record(
        18, 0x0000, jpg_art.name, 16, runlist_bytes=rl_jpg, real_size=len(jpg_art.payload)
    )
    img[mft_base + 18 * 1024 : mft_base + 19 * 1024] = rec18
    img[jpg_lcn * 4096 : jpg_lcn * 4096 + len(jpg_art.payload)] = jpg_art.payload

    pdf_payload = artifacts["Project_Report.pdf"].payload
    rl_pdf = bytes([0x11, 0x01, 50, 0x00])
    rec19 = _make_ntfs_mft_record(
        19, 0x0000, "Project_Report.pdf", 5, runlist_bytes=rl_pdf, real_size=len(pdf_payload)
    )
    img[mft_base + 19 * 1024 : mft_base + 20 * 1024] = rec19
    img[50 * 4096 : 50 * 4096 + len(pdf_payload)] = pdf_payload

    docx_payload = artifacts["Document.docx"].payload
    rl_partial = bytes([0x11, 0x01, 60, 0x00])
    rec20 = _make_ntfs_mft_record(
        20, 0x0000, "Document.docx", 5, runlist_bytes=rl_partial, real_size=8192
    )
    img[mft_base + 20 * 1024 : mft_base + 21 * 1024] = rec20
    img[60 * 4096 : 60 * 4096 + len(docx_payload)] = docx_payload

    png_payload = artifacts["Photo_001.png"].payload
    carve_off = 0x00060000
    img[carve_off : carve_off + len(png_payload)] = png_payload

    img[0x00070000 : 0x00070012] = b"\xff\xd8\xff\x00FALSE_POSITIVE"

    Path(image_path).parent.mkdir(parents=True, exist_ok=True)
    with open(image_path, "wb") as fp:
        fp.write(img)


def _lfn_checksum(short_11: bytes) -> int:
    s = 0
    for b in short_11:
        s = (((s & 1) << 7) + (s >> 1) + b) & 0xFF
    return s


def _make_fat32_lfn_and_sfn(
    long_name: str,
    short_11: bytes,
    first_cluster: int,
    file_size: int,
    deleted: bool = True,
) -> bytes:
    chk = _lfn_checksum(short_11)
    utf16_chars = [ord(c) for c in long_name] + [0x0000]
    while len(utf16_chars) % 13 != 0:
        utf16_chars.append(0xFFFF)

    num_lfn = len(utf16_chars) // 13
    entries = []
    for seq in range(num_lfn, 0, -1):
        chunk = utf16_chars[(seq - 1) * 13 : seq * 13]
        raw_u16 = b"".join(struct.pack("<H", c) for c in chunk)
        lfn = bytearray(32)
        lfn[0] = 0xE5 if deleted else (seq | (0x40 if seq == num_lfn else 0x00))
        lfn[1:11] = raw_u16[0:10]
        lfn[11] = 0x0F
        lfn[12] = 0x00
        lfn[13] = chk
        lfn[14:26] = raw_u16[10:22]
        lfn[26:28] = b"\x00\x00"
        lfn[28:32] = raw_u16[22:26]
        entries.append(bytes(lfn))

    sfn = bytearray(32)
    sfn[0:11] = short_11
    if deleted:
        sfn[0] = 0xE5
    sfn[11] = 0x20
    dos_date = ((2025 - 1980) << 9) | (5 << 5) | 12
    dos_time = (14 << 11) | (23 << 5) | 0
    struct.pack_into("<HH", sfn, 14, dos_time, dos_date)
    struct.pack_into("<H", sfn, 20, (first_cluster >> 16) & 0xFFFF)
    struct.pack_into("<HH", sfn, 22, dos_time, dos_date)
    struct.pack_into("<H", sfn, 26, first_cluster & 0xFFFF)
    struct.pack_into("<I", sfn, 28, file_size)
    entries.append(bytes(sfn))
    return b"".join(entries)


def create_fat32_test_image(image_path: str, artifacts: Dict[str, KnownTestArtifact]) -> None:
    total_size = 1024 * 1024
    img = bytearray(total_size)

    boot = bytearray(512)
    boot[0:3] = b"\xeb\x58\x90"
    boot[3:11] = b"MSDOS5.0"
    struct.pack_into("<HBHB", boot, 11, 512, 8, 32, 2)
    struct.pack_into("<I", boot, 32, total_size // 512)
    struct.pack_into("<I", boot, 36, 16)
    struct.pack_into("<I", boot, 44, 2)
    boot[82:90] = b"FAT32   "
    boot[510:512] = b"\x55\xaa"
    img[0:512] = boot

    fat_offset = 32 * 512
    struct.pack_into("<III", img, fat_offset, 0x0FFFFFF8, 0x0FFFFFFF, 0x0FFFFFFF)

    data_heap = (32 + 2 * 16) * 512

    zip_art = artifacts["Archive.zip"]
    mp4_art = artifacts["Family_Video.mp4"]

    dir_entries = bytearray()
    dir_entries.extend(_make_fat32_lfn_and_sfn("Archive.zip", b"ARCHIVE ZIP", 5, len(zip_art.payload), deleted=True))
    dir_entries.extend(_make_fat32_lfn_and_sfn("Family_Video.mp4", b"FAMILY~1MP4", 10, len(mp4_art.payload), deleted=True))
    img[data_heap : data_heap + len(dir_entries)] = dir_entries

    clus5_off = data_heap + (5 - 2) * 4096
    img[clus5_off : clus5_off + len(zip_art.payload)] = zip_art.payload

    clus10_off = data_heap + (10 - 2) * 4096
    img[clus10_off : clus10_off + len(mp4_art.payload)] = mp4_art.payload

    with open(image_path, "wb") as fp:
        fp.write(img)


def create_exfat_test_image(image_path: str, artifacts: Dict[str, KnownTestArtifact]) -> None:
    total_size = 1024 * 1024
    img = bytearray(total_size)

    boot = bytearray(512)
    boot[0:3] = b"\xeb\x76\x90"
    boot[3:11] = b"EXFAT   "
    struct.pack_into("<IIII", boot, 80, 32, 16, 64, 200)
    struct.pack_into("<I", boot, 96, 2)
    boot[108] = 9
    boot[109] = 3
    boot[510:512] = b"\x55\xaa"
    img[0:512] = boot

    heap_offset = 64 * 512

    def _build_exfat_deleted_set(name: str, first_clus: int, size: int) -> bytes:
        e_file = bytearray(32)
        e_file[0] = 0x05
        e_file[1] = 2
        dos_date = ((2025 - 1980) << 9) | (5 << 5) | 10
        dos_time = (9 << 11) | (15 << 5) | 0
        ts = (dos_date << 16) | dos_time
        struct.pack_into("<II", e_file, 8, ts, ts)

        e_stream = bytearray(32)
        e_stream[0] = 0x40
        e_stream[1] = 0x03
        e_stream[3] = len(name)
        struct.pack_into("<Q", e_stream, 8, size)
        struct.pack_into("<I", e_stream, 20, first_clus)
        struct.pack_into("<Q", e_stream, 24, size)

        e_name = bytearray(32)
        e_name[0] = 0x41
        u16 = name.encode("utf-16le")[:30]
        e_name[2 : 2 + len(u16)] = u16
        return bytes(e_file + e_stream + e_name)

    wav_art = artifacts["Voice_Note.wav"]
    png_art = artifacts["Photo_001.png"]

    root_dir = bytearray()
    root_dir.extend(_build_exfat_deleted_set("Voice_Note.wav", 4, len(wav_art.payload)))
    root_dir.extend(_build_exfat_deleted_set("Photo_001.png", 8, len(png_art.payload)))
    img[heap_offset : heap_offset + len(root_dir)] = root_dir

    clus4_off = heap_offset + (4 - 2) * 4096
    img[clus4_off : clus4_off + len(wav_art.payload)] = wav_art.payload

    clus8_off = heap_offset + (8 - 2) * 4096
    img[clus8_off : clus8_off + len(png_art.payload)] = png_art.payload

    with open(image_path, "wb") as fp:
        fp.write(img)


def generate_all_sample_images(output_dir: str) -> Tuple[Dict[str, str], Dict[str, KnownTestArtifact]]:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    artifacts = build_known_payloads()

    paths = {
        "ntfs": str(out / "Local_Disk_C_NTFS.img"),
        "fat32": str(out / "Data_Volume_D_FAT32.img"),
        "exfat": str(out / "USB_Drive_E_exFAT.img"),
    }
    create_ntfs_test_image(paths["ntfs"], artifacts)
    create_fat32_test_image(paths["fat32"], artifacts)
    create_exfat_test_image(paths["exfat"], artifacts)

    manifest = {
        k: {"name": v.name, "extension": v.extension, "size": len(v.payload), "sha256": v.sha256}
        for k, v in artifacts.items()
    }
    with open(out / "FIXTURE_HASHES.json", "w", encoding="utf-8") as fp:
        json.dump(manifest, fp, indent=2)

    return (paths, artifacts)


if __name__ == "__main__":
    sample_dir = Path(__file__).resolve().parent.parent / "sample_images"
    paths, arts = generate_all_sample_images(str(sample_dir))
    print("Generated sample disposable disk images:", paths)
