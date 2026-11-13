import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
from PyQt6.QtWidgets import QApplication, QDialogButtonBox, QLabel, QPushButton
from toshi_camera.diagnostics import HardwareReport, VideoDevice
from toshi_camera.storage import MediaStorage
from toshi_camera.ui import CameraMainWindow, DiagnosticsDialog

app = QApplication.instance() or QApplication([])


def test_diagnostics_dialog_uses_dialog_button_box():
    report = HardwareReport(
        ccde_flag=0,
        usb_webcam_attached=False,
        loopback_loaded=True,
        devices=[
            VideoDevice(
                path="/dev/video0",
                name="Toshi Virtual Camera",
                driver="v4l2loopback",
                is_loopback=True,
            )
        ],
        summary_tr="CCDE=0 ve fiziksel kamera bağlı değil.",
    )
    dlg = DiagnosticsDialog(report)
    boxes = dlg.findChildren(QDialogButtonBox)
    assert len(boxes) == 1
    assert "#" not in dlg.styleSheet()
    assert "rgb(" not in dlg.styleSheet()


def test_main_window_hig_and_qt_compliance(tmp_path: Path):
    storage = MediaStorage(tmp_path / "photos", tmp_path / "videos")
    win = CameraMainWindow(storage=storage, auto_start_capture=False)

    assert "#" not in win.styleSheet()
    assert "rgb(" not in win.styleSheet()

    buttons = [b for b in win.findChildren(QPushButton) if b.text()]
    assert len(buttons) >= 6
    mnemonics: list[str] = []
    for btn in buttons:
        text = btn.text()
        assert "&" in text, f"Button missing mnemonic: {text}"
        idx = text.index("&")
        assert idx + 1 < len(text)
        mnemonics.append(text[idx + 1].lower())
    assert len(mnemonics) == len(set(mnemonics)), f"Duplicate mnemonics: {mnemonics}"

    buddy_labels = [lbl for lbl in win.findChildren(QLabel) if lbl.buddy() is not None]
    assert len(buddy_labels) >= 5
    for lbl in buddy_labels:
        assert not lbl.text().strip().endswith(":"), (
            f"Form label ends with colon: {lbl.text()}"
        )


def test_main_window_photo_capture_and_reset_adjustments(tmp_path: Path):
    storage = MediaStorage(tmp_path / "photos", tmp_path / "videos")
    win = CameraMainWindow(storage=storage, auto_start_capture=False)

    win.brightness_slider.setValue(35)
    win.contrast_slider.setValue(-20)
    win.saturation_slider.setValue(40)
    win.mirror_checkbox.setChecked(True)
    win.reset_adjustments()
    assert win.brightness_slider.value() == 0
    assert win.contrast_slider.value() == 0
    assert win.saturation_slider.value() == 0
    assert win.mirror_checkbox.isChecked() is False

    win._on_tick()
    saved_path = win.capture_photo_now()
    assert saved_path is not None
    assert saved_path.exists()
    assert win.gallery_list.count() == 1
