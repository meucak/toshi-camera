import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
import numpy as np
from PyQt6.QtWidgets import QApplication, QDialogButtonBox, QLabel, QPushButton
from toshi_camera.diagnostics import HardwareReport, VideoDevice
from toshi_camera.phone_bridge import PhoneBridgeServer
from toshi_camera.storage import MediaStorage
from toshi_camera.ui import CameraMainWindow, DiagnosticsDialog, PhoneConnectDialog

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


def test_phone_connect_dialog_hig_compliance_and_qr_rendering(tmp_path: Path):
    srv = PhoneBridgeServer(host="127.0.0.1", port=0, cert_dir=tmp_path)
    srv.start()
    try:
        dlg = PhoneConnectDialog(server=srv, ips=["127.0.0.1"])
        assert "#" not in dlg.styleSheet()
        assert "rgb(" not in dlg.styleSheet()
        assert len(dlg.findChildren(QDialogButtonBox)) == 1

        buttons = [b for b in dlg.findChildren(QPushButton) if b.text()]
        assert len(buttons) >= 3
        mnemonics: list[str] = []
        for btn in buttons:
            text = btn.text()
            assert "&" in text, f"Button missing mnemonic: {text}"
            mnemonics.append(text[text.index("&") + 1].lower())
        assert len(mnemonics) == len(set(mnemonics)), f"Duplicate mnemonics: {mnemonics}"

        for lbl in [l for l in dlg.findChildren(QLabel) if l.buddy() is not None]:
            assert not lbl.text().strip().endswith(":")

        pix = dlg.qr_label.pixmap()
        assert pix is not None and not pix.isNull()
        assert dlg.url_edit.text() == srv.build_url("127.0.0.1")
        dlg.close()
    finally:
        srv.stop()


def test_main_window_includes_phone_qr_source_and_receives_frames(tmp_path: Path):
    import asyncio
    import ssl
    import cv2
    import numpy as np
    import websockets

    storage = MediaStorage(tmp_path / "photos", tmp_path / "videos")
    srv = PhoneBridgeServer(host="127.0.0.1", port=0, cert_dir=tmp_path / "certs")
    win = CameraMainWindow(
        storage=storage,
        auto_start_capture=False,
        phone_bridge=srv,
    )
    try:
        idx = win.source_combo.findData("phone://qr")
        assert idx >= 0
        win.source_combo.setCurrentIndex(idx)
        srv.start()

        async def _send_green_frame():
            ctx = ssl._create_unverified_context()
            ws_url = f"wss://127.0.0.1:{srv.port}/ws?t={srv.token}"
            async with websockets.connect(ws_url, ssl=ctx) as ws:
                green = np.zeros((240, 320, 3), dtype=np.uint8)
                green[:, :] = (10, 230, 20)  # High green channel in BGR
                ok, buf = cv2.imencode(".jpg", green)
                assert ok is True
                await ws.send(buf.tobytes())
                await asyncio.sleep(0.15)

        asyncio.run(_send_green_frame())
        win._on_tick()
        assert win._last_frame is not None
        mean_bgr = win._last_frame.mean(axis=(0, 1))
        assert mean_bgr[1] > 180 and mean_bgr[0] < 60 and mean_bgr[2] < 60
    finally:
        win.close()


def test_main_window_portrait_landscape_presets_and_rotation(tmp_path: Path):
    storage = MediaStorage(tmp_path / "photos", tmp_path / "videos")
    win = CameraMainWindow(storage=storage, auto_start_capture=False)
    try:
        res_values = [win.resolution_combo.itemData(i) for i in range(win.resolution_combo.count())]
        assert (640, 480) in res_values
        assert (480, 640) in res_values
        assert (1280, 720) in res_values
        assert (720, 1280) in res_values

        # Switch to portrait 480x640 and 90-deg rotation
        portrait_idx = res_values.index((480, 640))
        win.resolution_combo.setCurrentIndex(portrait_idx)
        rot_idx = win.rotation_combo.findData(90)
        assert rot_idx >= 0
        win.rotation_combo.setCurrentIndex(rot_idx)
        assert win.current_frame_settings().rotation_deg == 90

        win._on_tick()
        assert win._last_frame is not None
        assert win._last_frame.shape == (640, 480, 3)

        win.reset_adjustments()
        assert win.current_frame_settings().rotation_deg == 0
    finally:
        win.close()


def test_phone_connect_dialog_has_auto_mic_option(tmp_path: Path):
    srv = PhoneBridgeServer(host="127.0.0.1", port=0, cert_dir=tmp_path)
    srv.start()
    try:
        dlg = PhoneConnectDialog(server=srv, ips=["127.0.0.1"])
        assert dlg.auto_mic_checkbox.isChecked() is True
        dlg.close()
    finally:
        srv.stop()


def test_main_window_open_saves_folder_button(tmp_path: Path, monkeypatch):
    from PyQt6.QtCore import QUrl

    opened_urls: list[QUrl] = []
    monkeypatch.setattr(
        "toshi_camera.ui.QDesktopServices.openUrl",
        lambda url: opened_urls.append(url) or True,
    )

    saves = tmp_path / "Kamera"
    storage = MediaStorage(saves, saves)
    win = CameraMainWindow(storage=storage, auto_start_capture=False)
    try:
        win.open_folder_btn.click()
        assert len(opened_urls) == 1
        assert Path(opened_urls[0].toLocalFile()) == saves
    finally:
        win.close()


def test_close_event_minimizes_when_stream_active_and_force_quit_closes(
    tmp_path: Path, monkeypatch
):
    storage = MediaStorage(tmp_path / "photos", tmp_path / "videos")
    srv = PhoneBridgeServer(host="127.0.0.1", port=0, cert_dir=tmp_path / "certs")
    srv.start()
    win = CameraMainWindow(
        storage=storage, auto_start_capture=False, phone_bridge=srv
    )
    try:
        # Simulate active phone client
        monkeypatch.setattr(srv, "is_client_connected", lambda: True)
        monkeypatch.setattr("toshi_camera.ui.QSystemTrayIcon.isSystemTrayAvailable", lambda: False)

        minimized = []
        monkeypatch.setattr(win, "showMinimized", lambda: minimized.append(True))

        # Regular close (clicking X) must minimize and keep phone bridge running
        closed = win.close()
        assert closed is False
        assert minimized == [True]
        assert srv.is_running() is True

        # Explicit quit (Ctrl+Q / tray exit) must stop bridge and close
        assert win.quit_application() is True
        assert srv.is_running() is False
    finally:
        srv.stop()


def test_close_event_hides_to_tray_when_tray_available(tmp_path: Path, monkeypatch):
    storage = MediaStorage(tmp_path / "photos", tmp_path / "videos")
    srv = PhoneBridgeServer(host="127.0.0.1", port=0, cert_dir=tmp_path / "certs")
    srv.start()
    win = CameraMainWindow(
        storage=storage, auto_start_capture=False, phone_bridge=srv
    )
    try:
        monkeypatch.setattr(srv, "is_client_connected", lambda: True)
        monkeypatch.setattr("toshi_camera.ui.QSystemTrayIcon.isSystemTrayAvailable", lambda: True)

        class FakeTray:
            def __init__(self):
                self.shown = False
                self.messages = []

            def show(self):
                self.shown = True

            def hide(self):
                self.shown = False

            def showMessage(self, title, msg, icon, msecs):
                self.messages.append((title, msg))

        fake_tray = FakeTray()
        win._tray_icon = fake_tray  # type: ignore[assignment]
        hidden = []
        monkeypatch.setattr(win, "hide", lambda: hidden.append(True))

        assert win.close() is False
        assert hidden == [True]
        assert fake_tray.shown is True
        assert len(fake_tray.messages) == 1
        assert srv.is_running() is True

        assert win.quit_application() is True
        assert srv.is_running() is False
        assert fake_tray.shown is False
    finally:
        srv.stop()


def test_on_tick_continues_virtual_bridge_push_when_minimized(tmp_path: Path, monkeypatch):
    storage = MediaStorage(tmp_path / "photos", tmp_path / "videos")
    srv = PhoneBridgeServer(host="127.0.0.1", port=0, cert_dir=tmp_path / "certs")
    win = CameraMainWindow(
        storage=storage, auto_start_capture=False, phone_bridge=srv
    )
    try:
        qr_idx = win.source_combo.findData("phone://qr")
        assert qr_idx >= 0
        win.source_combo.setCurrentIndex(qr_idx)

        fake_frame = np.zeros((120, 160, 3), dtype=np.uint8)
        monkeypatch.setattr(srv, "get_latest_frame", lambda: (fake_frame, 1.0))

        pushed = []
        viewport_calls = []
        monkeypatch.setattr(win, "isMinimized", lambda: True)
        monkeypatch.setattr(win.virtual_bridge, "is_pipe_mode", lambda: True)
        monkeypatch.setattr(win.virtual_bridge, "push_frame", lambda frame: pushed.append(frame.shape))
        monkeypatch.setattr(win.viewport, "set_video_frame", lambda frame: viewport_calls.append(True))

        win._on_tick()
        assert len(pushed) == 1
        assert viewport_calls == []
        assert win._last_frame is not None
    finally:
        win.quit_application()
