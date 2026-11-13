from pathlib import Path
from toshi_camera.diagnostics import (
    VideoDevice,
    HardwareReport,
    discover_video_devices,
    build_hardware_report,
)


def test_discover_video_devices_handles_missing_dir(tmp_path: Path):
    assert discover_video_devices(tmp_path / "nonexistent") == []


def test_discover_video_devices_parses_sysfs_nodes(tmp_path: Path):
    v0 = tmp_path / "video0"
    v0.mkdir()
    (v0 / "name").write_text("Toshi Virtual Camera\n", encoding="utf-8")
    v1 = tmp_path / "video1"
    v1.mkdir()
    (v1 / "name").write_text("USB 2.0 UVC HD Webcam\n", encoding="utf-8")

    devices = discover_video_devices(tmp_path)
    assert len(devices) == 2
    assert devices[0] == VideoDevice(
        path="/dev/video0",
        name="Toshi Virtual Camera",
        driver="v4l2loopback",
        is_loopback=True,
    )
    assert devices[1] == VideoDevice(
        path="/dev/video1",
        name="USB 2.0 UVC HD Webcam",
        driver="uvcvideo",
        is_loopback=False,
    )


def test_build_hardware_report_detects_disconnected_internal_cam(tmp_path: Path):
    report = build_hardware_report(
        sys_class_path=tmp_path,
        ccde_flag=0,
        lsusb_output=(
            "Bus 001 Device 003: ID 0bda:0129 Realtek Semiconductor Corp. RTS5129 Card Reader Controller\n"
            "Bus 002 Device 004: ID 0930:0215 Toshiba Corp.\n"
        ),
        lsmod_output="v4l2loopback 49152 0\ntoshiba_acpi 73728 0\n",
    )
    assert report.ccde_flag == 0
    assert report.usb_webcam_attached is False
    assert report.loopback_loaded is True
    assert "CCDE=0" in report.summary_tr
    assert "fiziksel" in report.summary_tr.lower()


def test_build_hardware_report_detects_attached_usb_webcam(tmp_path: Path):
    v0 = tmp_path / "video0"
    v0.mkdir()
    (v0 / "name").write_text("Chicony USB 2.0 Camera\n", encoding="utf-8")
    report = build_hardware_report(
        sys_class_path=tmp_path,
        ccde_flag=1,
        lsusb_output="Bus 001 Device 005: ID 04f2:b217 Chicony Electronics Co., Ltd Toshiba Integrated Webcam\n",
        lsmod_output="uvcvideo 135168 0\n",
    )
    assert report.ccde_flag == 1
    assert report.usb_webcam_attached is True
    assert len(report.devices) == 1
    assert not report.devices[0].is_loopback
