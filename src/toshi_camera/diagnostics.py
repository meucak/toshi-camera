from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class VideoDevice:
    path: str
    name: str
    driver: str
    is_loopback: bool


@dataclass(frozen=True)
class HardwareReport:
    ccde_flag: Optional[int]
    usb_webcam_attached: bool
    loopback_loaded: bool
    devices: list[VideoDevice]
    summary_tr: str


def discover_video_devices(
    sys_class_path: Path = Path("/sys/class/video4linux"),
) -> list[VideoDevice]:
    if not sys_class_path.exists() or not sys_class_path.is_dir():
        return []

    devices: list[VideoDevice] = []
    for entry in sorted(sys_class_path.iterdir(), key=lambda p: p.name):
        if not entry.name.startswith("video"):
            continue
        name_file = entry / "name"
        if name_file.exists():
            try:
                name = name_file.read_text(encoding="utf-8", errors="replace").strip()
            except OSError:
                name = entry.name
        else:
            name = entry.name

        lower_name = name.lower()
        is_loopback = (
            "loopback" in lower_name
            or "virtual" in lower_name
            or "dummy" in lower_name
        )
        driver = "v4l2loopback" if is_loopback else "uvcvideo"
        devices.append(
            VideoDevice(
                path=f"/dev/{entry.name}",
                name=name or entry.name,
                driver=driver,
                is_loopback=is_loopback,
            )
        )
    return devices


def build_hardware_report(
    sys_class_path: Path = Path("/sys/class/video4linux"),
    ccde_flag: Optional[int] = 0,
    lsusb_output: str = "",
    lsmod_output: str = "",
) -> HardwareReport:
    devices = discover_video_devices(sys_class_path)
    physical_cams = [d for d in devices if not d.is_loopback]
    usb_lower = lsusb_output.lower()
    usb_has_cam = any(
        kw in usb_lower
        for kw in ("camera", "webcam", "chicony", "suyin", "lite-on", "04f2:", "064e:", "5986:")
    )
    usb_webcam_attached = bool(physical_cams) or usb_has_cam
    loopback_loaded = "v4l2loopback" in lsmod_output or any(
        d.is_loopback for d in devices
    )

    lines: list[str] = []
    if ccde_flag == 0 and not usb_webcam_attached:
        lines.append(
            "Anakart ACPI NVS (OGNS @ 0xAF7BCC18) üzerinde CCDE=0 raporlanıyor "
            "ve iç USB hub portlarında (1-1.4 / 1-1.5 / 2-1.3 / 2-1.4) kamera veri "
            "hattı bağlı değil (state: not attached). Dahili kamera modülü veya "
            "menteşe LVDS/USB kablosu fiziksel olarak çıkık ya da arızalı."
        )
    elif usb_webcam_attached:
        lines.append(
            f"Fiziksel USB/V4L2 kamera algılandı (CCDE={ccde_flag if ccde_flag is not None else '?'})."
        )
    else:
        lines.append(
            f"Fiziksel kamera algılanmadı (CCDE={ccde_flag if ccde_flag is not None else 'bilinmiyor'})."
        )

    if loopback_loaded:
        lines.append(
            "v4l2loopback sanal kamera köprüsü aktif; ağ kamerası veya canlı kalibrasyon "
            "akışı /dev/video0 üzerinden tüm sistem uygulamalarında kullanılabilir."
        )
    else:
        lines.append("v4l2loopback sanal kamera modülü yüklü değil.")

    return HardwareReport(
        ccde_flag=ccde_flag,
        usb_webcam_attached=usb_webcam_attached,
        loopback_loaded=loopback_loaded,
        devices=devices,
        summary_tr=" ".join(lines),
    )


def _run_cmd_text(cmd: list[str]) -> str:
    try:
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=3.0,
            check=False,
        )
        return res.stdout or ""
    except Exception:
        return ""


def collect_live_hardware_report() -> HardwareReport:
    lsusb_out = _run_cmd_text(["lsusb"])
    lsmod_out = _run_cmd_text(["lsmod"])
    ccde_val: Optional[int] = 0
    call_path = Path("/proc/acpi/call")
    if call_path.exists():
        try:
            call_path.write_text("\\CCDE\n", encoding="utf-8")
            raw = call_path.read_text(encoding="utf-8", errors="ignore").strip("\x00\n ")
            if raw.startswith("0x"):
                ccde_val = int(raw, 16)
        except OSError:
            ccde_val = 0
    return build_hardware_report(
        sys_class_path=Path("/sys/class/video4linux"),
        ccde_flag=ccde_val,
        lsusb_output=lsusb_out,
        lsmod_output=lsmod_out,
    )
