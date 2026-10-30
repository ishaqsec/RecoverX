"""Drive, Partition, and Connected USB / Mobile Storage Discovery (64-bit Windows Safe)."""
from __future__ import annotations

import ctypes
import json
import logging
import os
import platform
import shutil
import struct
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger("recoverx.devices.discovery")

CREATE_NO_WINDOW = 0x08000000 if platform.system() == "Windows" else 0


def is_running_as_admin() -> bool:
    """Return True if the current process has Administrator (Windows) or root (POSIX) privileges."""
    if platform.system() == "Windows":
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False
    else:
        try:
            return os.geteuid() == 0
        except AttributeError:
            return False


def request_windows_uac_elevation(script_args: Optional[List[str]] = None) -> bool:
    if platform.system() != "Windows":
        return False
    try:
        args = script_args if script_args is not None else sys.argv
        params = " ".join(f'"{a}"' for a in args)
        shell32 = ctypes.windll.shell32
        shell32.ShellExecuteW.restype = ctypes.c_void_p
        rc = shell32.ShellExecuteW(
            None,
            "runas",
            sys.executable,
            params,
            os.getcwd(),
            1,
        )
        return int(rc or 0) > 32
    except Exception as exc:
        logger.warning("UAC elevation request failed: %s", exc)
        return False


def find_adb_executable() -> Optional[str]:
    """Locate `adb` executable on PATH or standard SDK directories."""
    on_path = shutil.which("adb")
    if on_path:
        return on_path
    if platform.system() == "Windows":
        local_app = os.environ.get("LOCALAPPDATA", "")
        user_prof = os.environ.get("USERPROFILE", "")
        candidates = [
            os.path.join(local_app, "Android", "Sdk", "platform-tools", "adb.exe"),
            os.path.join(user_prof, "AppData", "Local", "Android", "Sdk", "platform-tools", "adb.exe"),
            r"C:\platform-tools\adb.exe",
            r"C:\Android\platform-tools\adb.exe",
            r"C:\Program Files (x86)\Minimal ADB and Fastboot\adb.exe",
        ]
        for c in candidates:
            if c and os.path.isfile(c):
                return c
    return None


class DeviceType(str, Enum):
    LOGICAL_VOLUME = "Logical Volume"
    PHYSICAL_DISK = "Physical Disk"
    REMOVABLE_DRIVE = "Removable Drive"
    EXTERNAL_DRIVE = "External Drive"
    DISK_IMAGE = "Disk Image"


@dataclass
class DeviceInfo:
    id: str
    name: str
    path: str
    device_type: DeviceType
    filesystem: str = "Unknown"
    total_bytes: int = 0
    free_bytes: int = 0
    is_accessible: bool = True
    is_encrypted: bool = False
    is_read_only: bool = True
    requires_admin: bool = False
    serial_number: str = ""
    status_note: str = "Ready (Read-Only)"
    mount_point: str = ""
    is_peripheral: bool = False
    metadata: dict = field(default_factory=dict)

    @property
    def used_bytes(self) -> int:
        return max(0, self.total_bytes - self.free_bytes)

    @property
    def usage_ratio(self) -> float:
        if self.total_bytes <= 0:
            return 0.45
        return min(1.0, max(0.0, self.used_bytes / float(self.total_bytes)))

    @property
    def capacity_summary(self) -> str:
        if self.total_bytes <= 0:
            return "Size Unknown"
        free_str = format_capacity(self.free_bytes)
        total_str = format_capacity(self.total_bytes)
        return f"{free_str} free of {total_str}"


def format_capacity(num_bytes: int) -> str:
    if num_bytes < 1024:
        return f"{num_bytes} B"
    elif num_bytes < 1024 ** 2:
        return f"{num_bytes / 1024:.1f} KB"
    elif num_bytes < 1024 ** 3:
        return f"{num_bytes / (1024 ** 2):.1f} MB"
    else:
        gb = num_bytes / (1024 ** 3)
        if gb >= 10:
            return f"{int(round(gb))} GB"
        return f"{gb:.1f} GB"


def detect_image_filesystem(path: str) -> Tuple[str, bool, str]:
    """Inspect the first sectors of a disk image or volume to identify its filesystem."""
    try:
        with open(path, "rb") as fp:
            header = fp.read(4096)
        if len(header) < 512:
            return ("RAW / Unformatted", False, "Small image (<512 B)")
        if header[3:11] == b"-FVE-FS-":
            return ("BitLocker Encrypted", True, "Encrypted volume (BitLocker)")
        if header[:6] == b"LUKS\xba\xbe":
            return ("LUKS Encrypted", True, "Encrypted volume (LUKS)")
        if header[3:11] == b"NTFS    ":
            return ("NTFS", False, "Healthy NTFS volume")
        if header[3:11] == b"EXFAT   ":
            return ("exFAT", False, "Healthy exFAT volume")
        if header[82:90] == b"FAT32   ":
            return ("FAT32", False, "Healthy FAT32 volume")
        if header[54:62] in (b"FAT16   ", b"FAT12   ", b"FAT     "):
            return (header[54:62].decode("ascii", errors="ignore").strip(), False, "FAT volume")
        if len(header) >= 1082 and struct.unpack_from("<H", header, 1080)[0] == 0xEF53:
            return ("EXT4", False, "Healthy EXT4 volume")
        if header[510:512] == b"\x55\xaa":
            part_entry = header[446:462]
            lba_start = struct.unpack("<I", part_entry[8:12])[0]
            if 0 < lba_start < 65536:
                try:
                    with open(path, "rb") as fp:
                        fp.seek(lba_start * 512)
                        pboot = fp.read(2048)
                    if pboot[3:11] == b"NTFS    ":
                        return ("NTFS", False, f"NTFS partition at LBA {lba_start}")
                    if pboot[3:11] == b"EXFAT   ":
                        return ("exFAT", False, f"exFAT partition at LBA {lba_start}")
                    if pboot[82:90] == b"FAT32   ":
                        return ("FAT32", False, f"FAT32 partition at LBA {lba_start}")
                    if len(pboot) >= 1082 and struct.unpack_from("<H", pboot, 1080)[0] == 0xEF53:
                        return ("EXT4", False, f"EXT4 partition at LBA {lba_start}")
                except OSError:
                    pass
        return ("RAW / Carving", False, "Unformatted or unknown filesystem (Carving ready)")
    except PermissionError:
        return ("Inaccessible", False, "Administrator permissions required")
    except OSError as exc:
        return ("Inaccessible", False, f"Cannot read header: {exc}")


def _is_windows_usb_bus(raw_volume_path: str) -> bool:
    """
    64-bit safe check whether a Windows raw volume resides on a USB/SD/MMC bus
    using explicitly typed Win32 `CreateFileW`, `DeviceIoControl`, and `CloseHandle`.
    """
    if platform.system() != "Windows":
        return False
    try:
        import ctypes.wintypes as wt
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        CreateFileW = kernel32.CreateFileW
        CreateFileW.argtypes = [
            wt.LPCWSTR,
            wt.DWORD,
            wt.DWORD,
            ctypes.c_void_p,
            wt.DWORD,
            wt.DWORD,
            ctypes.c_void_p,
        ]
        CreateFileW.restype = ctypes.c_void_p

        DeviceIoControl = kernel32.DeviceIoControl
        DeviceIoControl.argtypes = [
            ctypes.c_void_p,
            wt.DWORD,
            ctypes.c_void_p,
            wt.DWORD,
            ctypes.c_void_p,
            wt.DWORD,
            ctypes.POINTER(wt.DWORD),
            ctypes.c_void_p,
        ]
        DeviceIoControl.restype = wt.BOOL

        CloseHandle = kernel32.CloseHandle
        CloseHandle.argtypes = [ctypes.c_void_p]
        CloseHandle.restype = wt.BOOL

        invalid_handle = ctypes.c_void_p(-1).value
        handle = CreateFileW(raw_volume_path, 0, 3, None, 3, 0, None)
        if not handle or handle == invalid_handle:
            return False
        try:
            query_buf = ctypes.create_string_buffer(struct.pack("<III", 0, 0, 0))
            out_buf = ctypes.create_string_buffer(512)
            bytes_ret = wt.DWORD(0)
            ok = DeviceIoControl(
                handle,
                0x002D1400,  # IOCTL_STORAGE_QUERY_PROPERTY
                ctypes.byref(query_buf),
                12,
                ctypes.byref(out_buf),
                512,
                ctypes.byref(bytes_ret),
                None,
            )
            if ok and bytes_ret.value >= 32:
                bus_type = out_buf.raw[28]
                return bus_type in (7, 12, 13)
        finally:
            CloseHandle(handle)
    except Exception:
        pass
    return False


class DriveDiscovery:
    """
    Discovers mounted logical volumes, connected USB/MTP/ADB storage devices,
    and local mobile backup containers with background caching so UI hotplug polling never blocks.
    """

    def __init__(self, extra_image_paths: Optional[List[str]] = None):
        self.extra_image_paths: List[str] = list(extra_image_paths or [])
        self._wpd_cache: List[DeviceInfo] = []
        self._wpd_last_refresh: float = 0.0
        self._wpd_lock = threading.Lock()
        self._wpd_refreshing: bool = False

    def add_disk_image(self, image_path: str) -> DeviceInfo:
        p = Path(image_path).resolve()
        if str(p) not in self.extra_image_paths:
            self.extra_image_paths.append(str(p))
        return self._inspect_image_file(str(p))

    def _inspect_image_file(self, image_path: str) -> DeviceInfo:
        p = Path(image_path)
        if not p.exists():
            return DeviceInfo(
                id=f"img:{p.name}",
                name=f"Image ({p.name})",
                path=str(p),
                device_type=DeviceType.DISK_IMAGE,
                filesystem="Missing",
                total_bytes=0,
                free_bytes=0,
                is_accessible=False,
                status_note="Disk image file not found",
            )
        size = p.stat().st_size
        fs_type, is_enc, note = detect_image_filesystem(str(p))
        free_est = int(size * 0.35)
        return DeviceInfo(
            id=f"img:{p.name}",
            name=f"{p.name}",
            path=str(p),
            device_type=DeviceType.DISK_IMAGE,
            filesystem=fs_type,
            total_bytes=size,
            free_bytes=free_est,
            is_accessible=not is_enc,
            is_encrypted=is_enc,
            is_read_only=True,
            status_note=note,
            mount_point=str(p.parent),
        )

    def _enumerate_adb_storage(self) -> List[DeviceInfo]:
        """Discover internal storage of USB-connected devices accessible via ADB bridge."""
        adb_exe = find_adb_executable()
        if not adb_exe:
            return []
        found: List[DeviceInfo] = []
        try:
            proc = subprocess.run(
                [adb_exe, "devices", "-l"],
                capture_output=True,
                text=True,
                timeout=1.2,
                creationflags=CREATE_NO_WINDOW,
            )
            if proc.returncode != 0:
                return []
            for line in proc.stdout.splitlines()[1:]:
                line = line.strip()
                if not line or "offline" in line or "unauthorized" in line:
                    continue
                parts = line.split()
                if len(parts) >= 2 and parts[1] == "device":
                    serial = parts[0]
                    model_name = serial
                    for token in parts[2:]:
                        if token.startswith("model:"):
                            model_name = token.split(":", 1)[1].replace("_", " ")
                            break

                    total_b = 64 * (1024 ** 3)
                    free_b = 20 * (1024 ** 3)
                    try:
                        df_proc = subprocess.run(
                            [adb_exe, "-s", serial, "shell", "df", "-k", "/storage/emulated/0"],
                            capture_output=True,
                            text=True,
                            timeout=1.0,
                            creationflags=CREATE_NO_WINDOW,
                        )
                        if df_proc.returncode == 0:
                            df_lines = [ln.strip() for ln in df_proc.stdout.splitlines() if ln.strip()]
                            if len(df_lines) >= 2:
                                cols = df_lines[-1].split()
                                if len(cols) >= 4 and cols[1].isdigit() and cols[3].isdigit():
                                    total_b = int(cols[1]) * 1024
                                    free_b = int(cols[3]) * 1024
                    except Exception:
                        pass

                    found.append(
                        DeviceInfo(
                            id=f"adb:{serial}",
                            name=f"{model_name} (USB)",
                            path=f"adb://{serial}/storage/emulated/0",
                            device_type=DeviceType.REMOVABLE_DRIVE,
                            filesystem="Internal Storage",
                            total_bytes=total_b,
                            free_bytes=free_b,
                            is_accessible=True,
                            is_read_only=True,
                            mount_point="/storage/emulated/0",
                            is_peripheral=True,
                            metadata={"adb_serial": serial, "adb_exe": adb_exe},
                        )
                    )
        except Exception:
            pass
        return found

    def _query_wpd_com_worker(self) -> List[DeviceInfo]:
        """Run Windows Shell.Application COM WPD discovery with strict timeout protection."""
        if platform.system() != "Windows":
            return []
        found: List[DeviceInfo] = []
        ps_script = (
            "$ErrorActionPreference='SilentlyContinue'; "
            "$sh=New-Object -ComObject Shell.Application; "
            "$ns=$sh.NameSpace(17); "
            "$out=@(); "
            "foreach($it in $ns.Items()){ "
            "  if(-not $it.IsFileSystem -and $it.IsFolder){ "
            "    $sub=$it.GetFolder(); "
            "    if($sub){ "
            "      foreach($ch in $sub.Items()){ "
            "        if($ch.IsFolder -and ($ch.Name -match 'Internal|Storage|Phone|Memory|Shared|DCIM|Card')){ "
            "          $out += [PSCustomObject]@{Name=$it.Name; SubName=$ch.Name; Path=$it.Path; SubPath=$ch.Path}; "
            "          break "
            "        } "
            "      } "
            "    } "
            "  } "
            "} "
            "$out | ConvertTo-Json -Compress"
        )
        try:
            proc = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
                capture_output=True,
                text=True,
                timeout=2.0,
                creationflags=CREATE_NO_WINDOW,
            )
            raw_json = (proc.stdout or "").strip()
            if not raw_json:
                return []
            parsed = json.loads(raw_json)
            if isinstance(parsed, dict):
                parsed = [parsed]
            for item in parsed:
                dev_name = str(item.get("Name") or "").strip()
                sub_name = str(item.get("SubName") or "Internal Storage").strip()
                dev_path = str(item.get("Path") or "").strip()
                sub_path = str(item.get("SubPath") or dev_path).strip()
                if not dev_name:
                    continue
                found.append(
                    DeviceInfo(
                        id=f"wpd:{dev_name}",
                        name=f"{dev_name} ({sub_name})",
                        path=f"wpd://{dev_name}",
                        device_type=DeviceType.REMOVABLE_DRIVE,
                        filesystem="Internal Storage",
                        total_bytes=64 * (1024 ** 3),
                        free_bytes=22 * (1024 ** 3),
                        is_accessible=True,
                        is_read_only=True,
                        mount_point=sub_path,
                        is_peripheral=True,
                        metadata={
                            "wpd_device_name": dev_name,
                            "wpd_sub_name": sub_name,
                            "wpd_device_path": dev_path,
                            "wpd_sub_path": sub_path,
                        },
                    )
                )
        except Exception:
            pass
        return found

    def _enumerate_windows_wpd_storage(self, existing_names: set) -> List[DeviceInfo]:
        """
        Non-blocking WPD/MTP device enumeration: always runs COM discovery on a background
        daemon thread so the UI window opens instantaneously and never stalls.
        """
        if platform.system() != "Windows":
            return []
        now = time.monotonic()
        if (self._wpd_last_refresh == 0.0 or (now - self._wpd_last_refresh) > 6.0) and not self._wpd_refreshing:
            self._wpd_refreshing = True

            def _bg_refresh() -> None:
                try:
                    fresh_list = self._query_wpd_com_worker()
                    with self._wpd_lock:
                        self._wpd_cache = fresh_list
                        self._wpd_last_refresh = time.monotonic()
                finally:
                    self._wpd_refreshing = False

            threading.Thread(target=_bg_refresh, daemon=True).start()

        with self._wpd_lock:
            cached = list(self._wpd_cache)
        return [
            d for d in cached
            if not any(d.metadata.get("wpd_device_name", "").lower() in ex.lower() for ex in existing_names)
        ]

    def _enumerate_ios_backups(self) -> List[DeviceInfo]:
        """Discover local unencrypted iOS MobileSync backups containing `Manifest.db`."""
        candidates: List[Path] = []
        if platform.system() == "Windows":
            appdata = os.environ.get("APPDATA", "")
            userprof = os.environ.get("USERPROFILE", "")
            if appdata:
                candidates.append(Path(appdata) / "Apple Computer" / "MobileSync" / "Backup")
            if userprof:
                candidates.append(Path(userprof) / "Apple" / "MobileSync" / "Backup")
        else:
            home = Path.home()
            candidates.append(home / "Library" / "Application Support" / "MobileSync" / "Backup")
            candidates.append(home / ".local" / "share" / "ignan" / "backups")

        found: List[DeviceInfo] = []
        for root in candidates:
            if not (root.exists() and root.is_dir()):
                continue
            try:
                for sub in root.iterdir():
                    manifest_db = sub / "Manifest.db"
                    if sub.is_dir() and manifest_db.is_file():
                        short_id = sub.name[:8]
                        sz = manifest_db.stat().st_size
                        found.append(
                            DeviceInfo(
                                id=f"iosbackup:{sub.name}",
                                name=f"Mobile Backup ({short_id})",
                                path=f"iosbackup://{sub}",
                                device_type=DeviceType.REMOVABLE_DRIVE,
                                filesystem="Internal Storage",
                                total_bytes=max(16 * (1024 ** 3), sz * 64),
                                free_bytes=4 * (1024 ** 3),
                                is_accessible=True,
                                is_read_only=True,
                                mount_point=str(sub),
                                is_peripheral=True,
                                metadata={"backup_dir": str(sub), "manifest_db": str(manifest_db)},
                            )
                        )
            except OSError:
                pass
        return found

    def get_connected_drive_signature(self) -> str:
        """Lightweight fingerprint of currently connected volumes & USB devices for live hotplug detection."""
        adb_sig = ""
        adb_exe = find_adb_executable()
        if adb_exe:
            try:
                proc = subprocess.run(
                    [adb_exe, "devices"],
                    capture_output=True,
                    text=True,
                    timeout=0.5,
                    creationflags=CREATE_NO_WINDOW,
                )
                if proc.returncode == 0:
                    adb_sig = "|".join(
                        ln.split()[0]
                        for ln in proc.stdout.splitlines()[1:]
                        if len(ln.split()) >= 2 and ln.split()[1] == "device"
                    )
            except Exception:
                pass

        if platform.system() == "Windows":
            try:
                bitmask = ctypes.windll.kernel32.GetLogicalDrives()
                with self._wpd_lock:
                    wpd_cnt = len(self._wpd_cache)
                return f"win:{bitmask:08X}:adb:{adb_sig}:wpd:{wpd_cnt}:imgs:{len(self.extra_image_paths)}"
            except Exception:
                return f"win:0:adb:{adb_sig}:imgs:{len(self.extra_image_paths)}"
        else:
            try:
                gvfs_entries = []
                uid = os.getuid() if hasattr(os, "getuid") else 1000
                gvfs_dir = Path(f"/run/user/{uid}/gvfs")
                if gvfs_dir.exists():
                    gvfs_entries = sorted(p.name for p in gvfs_dir.iterdir())
                if os.path.exists("/proc/mounts"):
                    with open("/proc/mounts", "r", encoding="utf-8", errors="ignore") as fp:
                        lines = [line.split()[1] for line in fp if len(line.split()) >= 2]
                    return f"posix:{'|'.join(sorted(lines))}:gvfs:{'|'.join(gvfs_entries)}:adb:{adb_sig}:imgs:{len(self.extra_image_paths)}"
            except Exception:
                pass
            return f"posix:adb:{adb_sig}:imgs:{len(self.extra_image_paths)}"

    def enumerate_all(self, sample_images_dir: Optional[str] = None) -> List[DeviceInfo]:
        devices: List[DeviceInfo] = []
        sys_name = platform.system()

        if sys_name == "Windows":
            devices.extend(self._enumerate_windows())
        else:
            devices.extend(self._enumerate_posix())

        adb_devs = self._enumerate_adb_storage()
        devices.extend(adb_devs)

        if sys_name == "Windows":
            existing_names = {d.name for d in devices}
            wpd_devs = self._enumerate_windows_wpd_storage(existing_names)
            devices.extend(wpd_devs)

        ios_devs = self._enumerate_ios_backups()
        devices.extend(ios_devs)

        seen_paths = {d.path for d in devices}
        for img_path in self.extra_image_paths:
            if img_path not in seen_paths and os.path.exists(img_path):
                devices.append(self._inspect_image_file(img_path))
                seen_paths.add(img_path)

        return devices

    def _enumerate_windows(self) -> List[DeviceInfo]:
        """64-bit safe Windows volume enumeration with explicit Win32 argtypes and WCHAR buffer lengths."""
        results: List[DeviceInfo] = []
        admin = is_running_as_admin()
        try:
            import ctypes.wintypes as wt
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

            GetLogicalDrives = kernel32.GetLogicalDrives
            GetLogicalDrives.argtypes = []
            GetLogicalDrives.restype = wt.DWORD

            GetDriveTypeW = kernel32.GetDriveTypeW
            GetDriveTypeW.argtypes = [wt.LPCWSTR]
            GetDriveTypeW.restype = wt.UINT

            GetVolumeInformationW = kernel32.GetVolumeInformationW
            GetVolumeInformationW.argtypes = [
                wt.LPCWSTR,
                wt.LPWSTR,
                wt.DWORD,
                ctypes.POINTER(wt.DWORD),
                ctypes.POINTER(wt.DWORD),
                ctypes.POINTER(wt.DWORD),
                wt.LPWSTR,
                wt.DWORD,
            ]
            GetVolumeInformationW.restype = wt.BOOL

            GetDiskFreeSpaceExW = kernel32.GetDiskFreeSpaceExW
            GetDiskFreeSpaceExW.argtypes = [
                wt.LPCWSTR,
                ctypes.POINTER(ctypes.c_ulonglong),
                ctypes.POINTER(ctypes.c_ulonglong),
                ctypes.POINTER(ctypes.c_ulonglong),
            ]
            GetDiskFreeSpaceExW.restype = wt.BOOL

            bitmask = GetLogicalDrives()
            for i in range(26):
                if not (bitmask & (1 << i)):
                    continue
                letter = chr(ord("A") + i)
                root_path = f"{letter}:\\"
                raw_path = f"\\\\.\\{letter}:"
                drive_type_code = GetDriveTypeW(root_path)

                if drive_type_code in (0, 1):
                    continue

                is_usb_bus = _is_windows_usb_bus(raw_path)
                is_peripheral = False
                if drive_type_code == 2:
                    dtype = DeviceType.REMOVABLE_DRIVE
                    is_peripheral = True
                elif drive_type_code == 3 and is_usb_bus:
                    dtype = DeviceType.EXTERNAL_DRIVE
                    is_peripheral = True
                elif drive_type_code == 3:
                    dtype = DeviceType.LOGICAL_VOLUME
                else:
                    dtype = DeviceType.EXTERNAL_DRIVE
                    is_peripheral = True

                vol_name_buf = ctypes.create_unicode_buffer(261)
                fs_name_buf = ctypes.create_unicode_buffer(261)
                serial_num = wt.DWORD(0)
                max_comp_len = wt.DWORD(0)
                fs_flags = wt.DWORD(0)

                # IMPORTANT: Pass len(vol_name_buf) in WCHARs (261), NEVER ctypes.sizeof() in bytes!
                ok = GetVolumeInformationW(
                    root_path,
                    vol_name_buf,
                    len(vol_name_buf),
                    ctypes.byref(serial_num),
                    ctypes.byref(max_comp_len),
                    ctypes.byref(fs_flags),
                    fs_name_buf,
                    len(fs_name_buf),
                )

                free_bytes = ctypes.c_ulonglong(0)
                total_bytes = ctypes.c_ulonglong(0)
                total_free = ctypes.c_ulonglong(0)
                GetDiskFreeSpaceExW(
                    root_path,
                    ctypes.byref(free_bytes),
                    ctypes.byref(total_bytes),
                    ctypes.byref(total_free),
                )

                if not ok and total_bytes.value == 0:
                    continue

                label = vol_name_buf.value.strip() if ok else ""
                fs_name = fs_name_buf.value.strip() if ok else "RAW"
                if not label:
                    if dtype == DeviceType.REMOVABLE_DRIVE:
                        label = "USB Drive"
                    elif dtype == DeviceType.EXTERNAL_DRIVE:
                        label = "External"
                    elif letter == "C":
                        label = "Local Disk"
                    else:
                        label = "Data"

                display_name = f"{label} ({letter}:)"
                results.append(
                    DeviceInfo(
                        id=f"win:{letter}",
                        name=display_name,
                        path=raw_path,
                        device_type=dtype,
                        filesystem=fs_name or "RAW",
                        total_bytes=total_bytes.value,
                        free_bytes=free_bytes.value,
                        is_accessible=bool(ok or total_bytes.value > 0),
                        requires_admin=not admin,
                        serial_number=f"{serial_num.value:08X}",
                        mount_point=root_path,
                        is_peripheral=is_peripheral,
                        status_note="Connected Peripheral (Read-Only)" if is_peripheral else "Accessible Volume (Read-Only)",
                    )
                )
        except Exception as exc:
            logger.warning("Windows drive enumeration error: %s", exc)
        return results

    def _enumerate_posix(self) -> List[DeviceInfo]:
        results: List[DeviceInfo] = []
        try:
            mounts = []
            if os.path.exists("/proc/mounts"):
                with open("/proc/mounts", "r", encoding="utf-8", errors="ignore") as fp:
                    for line in fp:
                        parts = line.split()
                        if len(parts) >= 3:
                            dev, mnt, fstype = parts[0], parts[1], parts[2]
                            if fstype in (
                                "proc", "sysfs", "devtmpfs", "devpts", "tmpfs",
                                "cgroup", "cgroup2", "mqueue", "overlay", "squashfs",
                                "autofs", "fuse.portal", "tracefs", "securityfs", "pstore",
                            ):
                                continue
                            if mnt.startswith(("/proc", "/sys", "/dev", "/run/lock", "/var/lib/docker")):
                                continue
                            mounts.append((dev, mnt, fstype))

            uid = os.getuid() if hasattr(os, "getuid") else 1000
            gvfs_root = Path(f"/run/user/{uid}/gvfs")
            if gvfs_root.exists() and gvfs_root.is_dir():
                for child in gvfs_root.iterdir():
                    if child.is_dir():
                        mounts.append((str(child), str(child), "Internal Storage"))

            seen_mnts = set()
            for dev, mnt, fstype in mounts:
                if mnt in seen_mnts or not os.path.exists(mnt):
                    continue
                seen_mnts.add(mnt)
                try:
                    usage = shutil.disk_usage(mnt)
                    total_b = usage.total if usage.total > 0 else 64 * (1024 ** 3)
                    free_b = usage.free if usage.total > 0 else 20 * (1024 ** 3)
                    is_rem = mnt.startswith(("/media", "/run/media", "/mnt", "/run/user"))
                    dtype = DeviceType.REMOVABLE_DRIVE if is_rem else DeviceType.LOGICAL_VOLUME
                    if mnt == "/":
                        display_name = "Local Disk (/)"
                    elif is_rem:
                        display_name = f"USB Storage ({Path(mnt).name})"
                    else:
                        display_name = f"Volume ({Path(mnt).name or mnt})"

                    results.append(
                        DeviceInfo(
                            id=f"posix:{mnt}",
                            name=display_name,
                            path=dev if os.path.exists(dev) else mnt,
                            device_type=dtype,
                            filesystem=fstype.upper() if fstype != "Internal Storage" else fstype,
                            total_bytes=total_b,
                            free_bytes=free_b,
                            is_accessible=os.access(mnt, os.R_OK),
                            mount_point=mnt,
                            is_peripheral=is_rem,
                        )
                    )
                except OSError:
                    continue
        except Exception as exc:
            logger.warning("POSIX mount enumeration error: %s", exc)
        return results
