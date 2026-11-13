# Toshi Kamera Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and deploy a native PyQt6 (`QWidgets`) desktop camera studio and hardware diagnostics suite (`toshi-camera`) with `v4l2loopback` virtual camera bridge on Toshi.

**Architecture:** Modular Python package (`toshi_camera`) separating hardware/V4L2/ACPI diagnostics (`diagnostics.py`), real-time frame transformations and calibration signal generation (`processing.py`), photo/video gallery persistence (`storage.py`), `v4l2loopback` stream feeder (`virtual_cam.py`), and an Apple HIG + Qt QWidgets compliant desktop UI (`ui.py`).

**Tech Stack:** Python 3.13, PyQt6 (`QtWidgets`, `QtCore`, `QtGui`), OpenCV (`cv2`), NumPy, `v4l2loopback`, FFmpeg, `pytest`.

**Spec:** `/home/kasa/toshi-camera/docs/superpowers/specs/2026-11-13-toshi-camera-design.md`

## Global Constraints
- Zero hardcoded colors (`#hex` or `rgb(...)` forbidden in stylesheets/widgets; use `QPalette` system roles only).
- Zero `setGeometry()` or fixed pixel layout calls; use `QVBoxLayout`, `QHBoxLayout`, `QGridLayout`, `QFormLayout`, `QSplitter`, and `QSizePolicy`.
- Dialogs must use `QDialogButtonBox` with safe defaults (`setDefault(True)` on non-destructive actions, `Escape` on cancel).
- Non-conflicting mnemonics (`&`) on all interactive buttons and form labels paired via `setBuddy()`, explicit `setTabOrder()`, and `QKeySequence` shortcuts.
- Title Case for buttons/menus, Sentence case for form labels/checkboxes without trailing colons (`:`).
- Vector freedesktop theme icons via `QIcon.fromTheme(..., fallback)`.

## Review Focus
1. Empty or missing `/dev/video*` directory when enumerating V4L2 devices — `discover_video_devices()` must return an empty list without raising `FileNotFoundError`.
2. Extreme brightness/contrast/saturation slider inputs (`-100` to `+100`) on `uint8` frames — `apply_adjustments()` must clip safely to `[0, 255]` with `dtype=uint8` without integer wrap-around.
3. Unreachable or invalid network stream URL in `VirtualCamBridge` — command builder and start/stop lifecycle must validate URLs and clean up subprocesses cleanly without zombie processes.
4. Deleting a gallery item that was already removed on disk — `delete_media_file()` must return `False` gracefully without raising an unhandled exception.
5. UI compliance with Qt & HIG rules — automated test must inspect all widgets in `CameraMainWindow` and `DiagnosticsDialog` to verify zero trailing colons in form labels, non-conflicting mnemonics, `QDialogButtonBox` presence, and zero hardcoded color stylesheets.

---

### Task 1: V4L2 & Toshi Hardware Diagnostics (`diagnostics.py`)

**Files:**
- Create: `src/toshi_camera/__init__.py`
- Create: `src/toshi_camera/diagnostics.py`
- Test: `tests/test_diagnostics.py`

**Interfaces:**
- Consumes: none
- Produces:
  - `VideoDevice(path: str, name: str, driver: str, is_loopback: bool)` (dataclass)
  - `HardwareReport(ccde_flag: Optional[int], usb_webcam_attached: bool, loopback_loaded: bool, devices: list[VideoDevice], summary_tr: str)` (dataclass)
  - `discover_video_devices(sys_class_path: Path = Path("/sys/class/video4linux")) -> list[VideoDevice]`
  - `build_hardware_report(sys_class_path: Path = Path("/sys/class/video4linux"), ccde_flag: Optional[int] = 0, lsusb_output: str = "", lsmod_output: str = "") -> HardwareReport`

- [ ] **Step 1: Write the failing test in `tests/test_diagnostics.py`**
```python
from pathlib import Path
from toshi_camera.diagnostics import discover_video_devices, build_hardware_report

def test_discover_video_devices_handles_missing_dir(tmp_path: Path):
    assert discover_video_devices(tmp_path / "nonexistent") == []

def test_discover_video_devices_parses_sysfs_nodes(tmp_path: Path):
    v0 = tmp_path / "video0"
    v0.mkdir()
    (v0 / "name").write_text("Toshi Virtual Camera\n", encoding="utf-8")
    devices = discover_video_devices(tmp_path)
    assert len(devices) == 1
    assert devices[0].path == "/dev/video0"
    assert devices[0].name == "Toshi Virtual Camera"
    assert devices[0].is_loopback is True

def test_build_hardware_report_detects_disconnected_internal_cam(tmp_path: Path):
    report = build_hardware_report(
        sys_class_path=tmp_path,
        ccde_flag=0,
        lsusb_output="Bus 002 Device 004: ID 0930:0215 Toshiba Corp.",
        lsmod_output="v4l2loopback 49152 0\n",
    )
    assert report.ccde_flag == 0
    assert report.usb_webcam_attached is False
    assert report.loopback_loaded is True
    assert "CCDE=0" in report.summary_tr
```

- [ ] **Step 2: Run test to verify it fails**
Run: `PYTHONPATH=src pytest tests/test_diagnostics.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'toshi_camera.diagnostics'`

- [ ] **Step 3: Implement `src/toshi_camera/diagnostics.py`**
Implement `VideoDevice`, `HardwareReport`, `discover_video_devices()`, `build_hardware_report()`, and `collect_live_hardware_report()`.

- [ ] **Step 4: Run test to verify it passes**
Run: `PYTHONPATH=src pytest tests/test_diagnostics.py -v`
Expected: PASS

- [ ] **Step 5: Commit**
```bash
git add src/toshi_camera/__init__.py src/toshi_camera/diagnostics.py tests/test_diagnostics.py
git commit -m "feat(diagnostics): add V4L2 and ACPI CCDE hardware diagnostics"
```

---

### Task 2: Frame Processing & Calibration Signal Generator (`processing.py`)

**Files:**
- Create: `src/toshi_camera/processing.py`
- Test: `tests/test_processing.py`

**Interfaces:**
- Consumes: `numpy`, `cv2`
- Produces:
  - `FrameSettings(brightness: int = 0, contrast: int = 0, saturation: int = 0, mirror_horizontal: bool = False, flip_vertical: bool = False)` (dataclass)
  - `apply_adjustments(frame: np.ndarray, settings: FrameSettings) -> np.ndarray`
  - `generate_test_frame(width: int, height: int, frame_index: int, label: str = "Toshi Kamera") -> np.ndarray`

- [ ] **Step 1: Write the failing test in `tests/test_processing.py`**
```python
import numpy as np
from toshi_camera.processing import FrameSettings, apply_adjustments, generate_test_frame

def test_apply_adjustments_clips_extreme_values_without_wrap():
    frame = np.full((16, 16, 3), 200, dtype=np.uint8)
    bright = apply_adjustments(frame, FrameSettings(brightness=100, contrast=50, saturation=50))
    assert bright.dtype == np.uint8
    assert bright.shape == (16, 16, 3)
    assert int(bright.min()) >= 200

def test_apply_adjustments_mirror_and_flip():
    frame = np.zeros((4, 4, 3), dtype=np.uint8)
    frame[0, 0] = [255, 0, 0]
    out = apply_adjustments(frame, FrameSettings(mirror_horizontal=True, flip_vertical=True))
    assert tuple(out[3, 3]) == (255, 0, 0)

def test_generate_test_frame_dimensions_and_animation():
    f1 = generate_test_frame(640, 480, 0)
    f2 = generate_test_frame(640, 480, 15)
    assert f1.shape == (480, 640, 3)
    assert f1.dtype == np.uint8
    assert not np.array_equal(f1, f2)
```

- [ ] **Step 2: Run test to verify it fails**
Run: `PYTHONPATH=src pytest tests/test_processing.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'toshi_camera.processing'`

- [ ] **Step 3: Implement `src/toshi_camera/processing.py`**
Implement `FrameSettings`, `apply_adjustments()`, and `generate_test_frame()`.

- [ ] **Step 4: Run test to verify it passes**
Run: `PYTHONPATH=src pytest tests/test_processing.py -v`
Expected: PASS

- [ ] **Step 5: Commit**
```bash
git add src/toshi_camera/processing.py tests/test_processing.py
git commit -m "feat(processing): add real-time frame adjustments and test signal generator"
```

---

### Task 3: Media Storage & Gallery Manager (`storage.py`)

**Files:**
- Create: `src/toshi_camera/storage.py`
- Test: `tests/test_storage.py`

**Interfaces:**
- Consumes: `numpy`, `cv2`, `pathlib.Path`
- Produces:
  - `MediaItem(path: Path, kind: str, created_at: float)` (dataclass)
  - `MediaStorage(photo_dir: Path, video_dir: Path)`
    - `.save_photo(frame: np.ndarray, prefix: str = "IMG") -> Path`
    - `.allocate_video_path(prefix: str = "VID", ext: str = "avi") -> Path`
    - `.list_media(limit: int = 50) -> list[MediaItem]`
    - `.delete_media_file(path: Path) -> bool`

- [ ] **Step 1: Write the failing test in `tests/test_storage.py`**
```python
from pathlib import Path
import numpy as np
from toshi_camera.storage import MediaStorage

def test_save_photo_and_list_and_delete(tmp_path: Path):
    storage = MediaStorage(tmp_path / "photos", tmp_path / "videos")
    frame = np.zeros((64, 64, 3), dtype=np.uint8)
    saved = storage.save_photo(frame)
    assert saved.exists()
    items = storage.list_media()
    assert len(items) == 1
    assert items[0].path == saved
    assert items[0].kind == "photo"
    assert storage.delete_media_file(saved) is True
    assert storage.delete_media_file(saved) is False
```

- [ ] **Step 2: Run test to verify it fails**
Run: `PYTHONPATH=src pytest tests/test_storage.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'toshi_camera.storage'`

- [ ] **Step 3: Implement `src/toshi_camera/storage.py`**
Implement `MediaItem` and `MediaStorage`.

- [ ] **Step 4: Run test to verify it passes**
Run: `PYTHONPATH=src pytest tests/test_storage.py -v`
Expected: PASS

- [ ] **Step 5: Commit**
```bash
git add src/toshi_camera/storage.py tests/test_storage.py
git commit -m "feat(storage): add photo/video storage and gallery management"
```

---

### Task 4: `v4l2loopback` Virtual Camera Feeder (`virtual_cam.py`)

**Files:**
- Create: `src/toshi_camera/virtual_cam.py`
- Test: `tests/test_virtual_cam.py`

**Interfaces:**
- Consumes: `subprocess`
- Produces:
  - `build_ffmpeg_loopback_cmd(source_url: Optional[str], target_device: str = "/dev/video0", width: int = 640, height: int = 480, fps: int = 30) -> list[str]`
  - `validate_stream_url(url: str) -> bool`
  - `VirtualCamBridge` (manages background `ffmpeg` feeder process to `/dev/video0`)

- [ ] **Step 1: Write the failing test in `tests/test_virtual_cam.py`**
```python
import pytest
from toshi_camera.virtual_cam import build_ffmpeg_loopback_cmd, validate_stream_url

def test_validate_stream_url():
    assert validate_stream_url("http://192.168.1.50:8080/video") is True
    assert validate_stream_url("rtsp://192.168.1.50:8554/live") is True
    assert validate_stream_url("ftp://bad") is False
    assert validate_stream_url("") is False

def test_build_ffmpeg_loopback_cmd_for_test_pattern_and_stream():
    cmd_test = build_ffmpeg_loopback_cmd(None, "/dev/video0", 640, 480, 30)
    assert "testsrc2=size=640x480:rate=30" in cmd_test
    assert "/dev/video0" in cmd_test

    cmd_net = build_ffmpeg_loopback_cmd("http://192.168.1.50:8080/video", "/dev/video0", 640, 480, 30)
    assert "http://192.168.1.50:8080/video" in cmd_net
    assert "/dev/video0" in cmd_net

    with pytest.raises(ValueError):
        build_ffmpeg_loopback_cmd("invalid://url", "/dev/video0")
```

- [ ] **Step 2: Run test to verify it fails**
Run: `PYTHONPATH=src pytest tests/test_virtual_cam.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'toshi_camera.virtual_cam'`

- [ ] **Step 3: Implement `src/toshi_camera/virtual_cam.py`**
Implement `validate_stream_url()`, `build_ffmpeg_loopback_cmd()`, and `VirtualCamBridge`.

- [ ] **Step 4: Run test to verify it passes**
Run: `PYTHONPATH=src pytest tests/test_virtual_cam.py -v`
Expected: PASS

- [ ] **Step 5: Commit**
```bash
git add src/toshi_camera/virtual_cam.py tests/test_virtual_cam.py
git commit -m "feat(virtual-cam): add v4l2loopback FFmpeg bridge and stream validation"
```

---

### Task 5: PyQt6 Desktop UI & Toshi Deployment (`ui.py`, `main.py`)

**Files:**
- Create: `src/toshi_camera/ui.py`
- Create: `src/toshi_camera/main.py`
- Test: `tests/test_ui.py`

**Interfaces:**
- Consumes: `diagnostics.py`, `processing.py`, `storage.py`, `virtual_cam.py`, `PyQt6.QtWidgets`
- Produces:
  - `DiagnosticsDialog(report: HardwareReport, parent: Optional[QWidget] = None)`
  - `CameraMainWindow(storage: MediaStorage, parent: Optional[QWidget] = None)`
  - `main()` entry point

- [ ] **Step 1: Write the failing test in `tests/test_ui.py`**
```python
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
from PyQt6.QtWidgets import QApplication, QDialogButtonBox, QLabel, QPushButton
from toshi_camera.diagnostics import HardwareReport
from toshi_camera.storage import MediaStorage
from toshi_camera.ui import CameraMainWindow, DiagnosticsDialog

app = QApplication.instance() or QApplication([])

def test_diagnostics_dialog_uses_dialog_button_box():
    report = HardwareReport(0, False, True, [], "Test özet")
    dlg = DiagnosticsDialog(report)
    boxes = dlg.findChildren(QDialogButtonBox)
    assert len(boxes) == 1

def test_main_window_hig_and_qt_compliance(tmp_path: Path):
    storage = MediaStorage(tmp_path / "p", tmp_path / "v")
    win = CameraMainWindow(storage=storage, auto_start_capture=False)
    assert "#" not in win.styleSheet()
    assert "rgb(" not in win.styleSheet()
    buttons = [b for b in win.findChildren(QPushButton) if b.text()]
    mnemonics = []
    for b in buttons:
        text = b.text()
        assert "&" in text, f"Button missing mnemonic: {text}"
        idx = text.index("&")
        mnemonics.append(text[idx + 1].lower())
    assert len(mnemonics) == len(set(mnemonics)), f"Duplicate mnemonics: {mnemonics}"
    for lbl in win.findChildren(QLabel):
        if lbl.buddy() is not None:
            assert not lbl.text().strip().endswith(":"), f"Label ends with colon: {lbl.text()}"
```

- [ ] **Step 2: Run test to verify it fails**
Run: `PYTHONPATH=src pytest tests/test_ui.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'toshi_camera.ui'`

- [ ] **Step 3: Implement `src/toshi_camera/ui.py` and `src/toshi_camera/main.py`**
Implement `DiagnosticsDialog`, `CameraMainWindow`, and `main()`.

- [ ] **Step 4: Run full test suite to verify it passes**
Run: `PYTHONPATH=src pytest -v`
Expected: PASS (all tests across all 5 test files green)

- [ ] **Step 5: Commit and deploy to Toshi**
Commit all files, install `/home/toshi/.local/bin/toshi-camera` and `/home/toshi/.local/share/applications/toshi-camera.desktop` on Toshi, configure persistent `v4l2loopback` autoload (`/etc/modules-load.d/v4l2loopback.conf` and `/etc/modprobe.d/v4l2loopback.conf`), and verify the test suite and application directly on Toshi.
