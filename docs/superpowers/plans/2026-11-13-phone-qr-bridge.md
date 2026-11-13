# Telefon Kamerası QR Köprüsü Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an app-less, QR-code-paired HTTPS+WSS phone camera bridge to `toshi-camera` that displays phone video in the studio and streams processed frames to `/dev/video0` (`v4l2loopback`).

**Architecture:** `phone_bridge.py` manages LAN IP discovery, cached SAN self-signed TLS certs via `openssl`, QR matrix generation via `cv2.QRCodeEncoder`, and a single-port `websockets` HTTPS+WSS server in a background thread. `virtual_cam.py` gains raw-frame pipe feeding (`ffmpeg` stdin -> `/dev/video0`) while keeping existing `source_url` behavior intact. `ui.py` adds `PhoneConnectDialog` and `phone://qr` source handling compliant with Apple HIG and Qt/QWidgets rules.

**Tech Stack:** Python 3.13, PyQt6 6.9, OpenCV 4.10 (`QRCodeEncoder`, `imdecode`), NumPy, `websockets` 15.0, `openssl`, `ffmpeg`, `v4l2loopback`.

**Spec:** `docs/superpowers/specs/2026-11-13-phone-qr-bridge-design.md`

## Global Constraints
- Zero new third-party pip dependencies (must run on Toshi with existing `PyQt6`, `cv2`, `numpy`, `websockets`, `openssl`, `ffmpeg`).
- Zero hardcoded `#hex` or `rgb()` in Qt stylesheets; zero `setGeometry`.
- Unique `&` mnemonics on all `QPushButton` widgets; no trailing `:` on `QFormLayout` buddy labels.
- Existing 14 unit tests must keep passing without regressions.

## Review Focus
- Unauthorized access on LAN: `GET /` and `WSS /ws` without matching `?t=<token>` must return HTTP 403.
- Self-signed cert mismatch across multiple IPs: SAN must include selected/all discovered LAN IPs + `127.0.0.1` + `localhost` and regenerate if IPs change.
- Corrupted/non-JPEG binary frame on WebSocket: server must ignore invalid payloads without crashing or dropping valid frames.
- `ffmpeg` pipe stall or premature exit when feeding `/dev/video0`: `push_frame` must never block the Qt GUI thread and `stop()` must cleanly terminate feeder thread + subprocess.
- Phone disconnect while `phone://qr` is active: UI must stay responsive and show a clean waiting state instead of freezing or crashing.

---

### Task 1: Phone Bridge Core (`phone_bridge.py`) — IP Discovery, TLS Certs, QR Generation, Mobile HTML & Single-Port HTTPS+WSS Server

**Files:**
- Create: `src/toshi_camera/phone_bridge.py`
- Create: `tests/test_phone_bridge.py`

**Interfaces:**
- Produces:
  - `discover_lan_ips() -> list[str]`
  - `ensure_self_signed_cert(cert_dir: Path, ips: list[str]) -> tuple[Path, Path]`
  - `generate_qr_image(url: str, scale: int = 8, border: int = 4) -> np.ndarray`
  - `build_mobile_page_html() -> str`
  - `PhoneBridgeServer(host: str = "0.0.0.0", port: int = 8443, cert_dir: Optional[Path] = None)` with `.start()`, `.stop()`, `.is_running()`, `.port`, `.token`, `.build_url(ip: str) -> str`, `.regenerate_token() -> str`, `.get_latest_frame() -> Optional[tuple[np.ndarray, int]]`, `.is_client_connected() -> bool`, `.client_info() -> Optional[str]`, `.current_fps() -> float`.

- [ ] **Step 1: Write failing tests in `tests/test_phone_bridge.py`**
  - `test_discover_lan_ips_prioritizes_private_lan_and_filters_loopback`
  - `test_ensure_self_signed_cert_creates_and_caches_for_same_ips`
  - `test_generate_qr_image_roundtrips_with_cv2_qr_detector`
  - `test_phone_bridge_server_serves_http_and_rejects_bad_token`
  - `test_phone_bridge_server_receives_jpeg_frames_over_wss_and_ignores_garbage`
- [ ] **Step 2: Sync to Toshi and run `pytest tests/test_phone_bridge.py -v` — verify FAIL (module missing)**
- [ ] **Step 3: Implement `src/toshi_camera/phone_bridge.py`**
- [ ] **Step 4: Sync to Toshi and run `pytest tests/test_phone_bridge.py -v` — verify PASS**
- [ ] **Step 5: Commit**

---

### Task 2: Virtual Camera Pipe Mode (`virtual_cam.py`)

**Files:**
- Modify: `src/toshi_camera/virtual_cam.py`
- Modify: `tests/test_virtual_cam.py`

**Interfaces:**
- Produces:
  - `build_ffmpeg_pipe_cmd(target_device: str = "/dev/video0", width: int = 640, height: int = 480, fps: int = 30) -> list[str]`
  - `VirtualCamBridge.start_pipe(width: int = 640, height: int = 480, fps: int = 30) -> None`
  - `VirtualCamBridge.push_frame(frame: np.ndarray) -> None`
  - `VirtualCamBridge.is_pipe_mode() -> bool`

- [ ] **Step 1: Write failing tests in `tests/test_virtual_cam.py`**
  - `test_build_ffmpeg_pipe_cmd`
  - `test_virtual_cam_bridge_pipe_mode_writes_resized_bgr24_frames` (using a lightweight mock/cat subprocess or `MockPopen` / real `cat >/dev/null` to verify non-blocking frame feeding and clean `stop()`)
- [ ] **Step 2: Sync to Toshi and run `pytest tests/test_virtual_cam.py -v` — verify FAIL**
- [ ] **Step 3: Implement pipe mode in `src/toshi_camera/virtual_cam.py`**
- [ ] **Step 4: Sync to Toshi and run `pytest tests/test_virtual_cam.py -v` — verify PASS**
- [ ] **Step 5: Commit**

---

### Task 3: PyQt6 `PhoneConnectDialog` & `CameraMainWindow` Integration (`ui.py`)

**Files:**
- Modify: `src/toshi_camera/ui.py`
- Modify: `tests/test_ui.py`

**Interfaces:**
- Consumes: `PhoneBridgeServer`, `discover_lan_ips`, `generate_qr_image` from `toshi_camera.phone_bridge`, `VirtualCamBridge.start_pipe` / `push_frame` from `toshi_camera.virtual_cam`.
- Produces: `PhoneConnectDialog`, `CameraMainWindow` with `phone://qr` source, `phone_connect_btn`, `open_phone_connect_dialog()`, auto-bridge option.

- [ ] **Step 1: Write failing tests in `tests/test_ui.py`**
  - `test_phone_connect_dialog_hig_compliance_and_qr_rendering`
  - `test_main_window_includes_phone_qr_source_and_receives_frames`
- [ ] **Step 2: Sync to Toshi and run `pytest tests/test_ui.py -v` — verify FAIL**
- [ ] **Step 3: Implement `PhoneConnectDialog` and `CameraMainWindow` phone bridge integration in `src/toshi_camera/ui.py`**
- [ ] **Step 4: Sync to Toshi and run full `pytest -v` — verify ALL PASS**
- [ ] **Step 5: Live E2E verification on Toshi (`PhoneBridgeServer` + real HTTPS/WSS + `/dev/video0` `v4l2loopback` + `cv2.VideoCapture('/dev/video0')`), update `README.md`, commit.**
