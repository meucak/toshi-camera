# Mikrofon, Yön (Portrait/Landscape) ve `kamera --saves` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add phone microphone capture & PulseAudio virtual microphone (`Toshi Virtual Mic`), portrait/landscape orientation & rotation controls, and `kamera --saves` terminal directory navigation.

**Architecture:**
- `phone_bridge.py` multiplexes `AUD0` PCM audio packets alongside JPEG video frames over the existing single-port `WSS /ws`, resamples PCM to 44100 Hz via NumPy, and adds mic + orientation controls to the mobile page.
- `audio_bridge.py` manages a PulseAudio `module-pipe-source` (`toshi_virtual_mic`) FIFO writer thread so Linux apps see the phone mic as a real microphone.
- `processing.py` adds `rotation_deg` (0/90/180/270) to `FrameSettings`; `ui.py` adds Portrait/Landscape resolution presets, rotation selector, auto virtual mic start, and audio+video `.mp4` recording via `ffmpeg`.
- `storage.py` & `main.py` unify saves into `~/Kamera` (`get_default_saves_dir()`) and implement `--saves-path` / `--saves` CLI support paired with Toshi launcher + `~/.bashrc` `kamera()` function.

**Tech Stack:** Python 3.13, PyQt6 6.9, OpenCV 4.10, NumPy, `websockets` 15.0, PulseAudio (`pactl` `module-pipe-source`), `ffmpeg`.

---

### Task 1: Audio Packet Protocol, Resampling & Phone Bridge Mic Support (`phone_bridge.py`)
- Files: `src/toshi_camera/phone_bridge.py`, `tests/test_phone_bridge.py`
- TDD: test `encode_audio_packet` / `decode_audio_packet`, `resample_pcm_s16le`, `PhoneBridgeServer` receiving `AUD0` packets over WSS, and mobile HTML containing audio capture & orientation controls.

### Task 2: PulseAudio Virtual Microphone (`audio_bridge.py`)
- Files: `src/toshi_camera/audio_bridge.py`, `tests/test_audio_bridge.py`
- TDD: test `build_pactl_load_pipe_source_cmd`, `VirtualMicBridge` lifecycle (mocked `subprocess.run` and real FIFO write), `push_pcm`, `stop()` unloading module.

### Task 3: Rotation (`processing.py`), Unified Saves & `--saves` CLI (`storage.py`, `main.py`)
- Files: `src/toshi_camera/processing.py`, `src/toshi_camera/storage.py`, `src/toshi_camera/main.py`, `tests/test_processing.py`, `tests/test_storage.py`, `tests/test_cli.py`
- TDD: test 90/180/270 rotation in `apply_adjustments`, `get_default_saves_dir()`, `--saves-path` and `--version` CLI flags.

### Task 4: UI Integration — Portrait/Landscape Presets, Rotation Combo, Virtual Mic Bridge & Audio+Video Recording (`ui.py`)
- Files: `src/toshi_camera/ui.py`, `tests/test_ui.py`
- TDD: test portrait/landscape resolution presets, rotation combo updating `FrameSettings`, and `PhoneConnectDialog` mic checkbox.
- Final Verification: Run full `pytest -v` on Toshi, verify live `Toshi Virtual Mic` PulseAudio source + `/dev/video0` + `kamera --saves` in bash on Toshi.
