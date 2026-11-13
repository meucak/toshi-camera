import pytest
from toshi_camera.virtual_cam import (
    VirtualCamBridge,
    build_ffmpeg_loopback_cmd,
    build_ffmpeg_pipe_cmd,
    validate_stream_url,
)


def test_validate_stream_url():
    assert validate_stream_url("http://192.168.1.50:8080/video") is True
    assert validate_stream_url("https://192.168.1.50:8443/stream.mjpg") is True
    assert validate_stream_url("rtsp://192.168.1.50:8554/live") is True
    assert validate_stream_url("udp://127.0.0.1:5000") is True
    assert validate_stream_url("ftp://bad") is False
    assert validate_stream_url("") is False
    assert validate_stream_url("   ") is False


def test_build_ffmpeg_loopback_cmd_for_test_pattern_and_stream():
    cmd_test = build_ffmpeg_loopback_cmd(None, "/dev/video0", 640, 480, 30)
    assert "testsrc2=size=640x480:rate=30" in cmd_test
    assert "/dev/video0" in cmd_test

    cmd_net = build_ffmpeg_loopback_cmd(
        "http://192.168.1.50:8080/video", "/dev/video0", 640, 480, 30
    )
    assert "http://192.168.1.50:8080/video" in cmd_net
    assert "/dev/video0" in cmd_net

    with pytest.raises(ValueError):
        build_ffmpeg_loopback_cmd("invalid://url", "/dev/video0")


def test_virtual_cam_bridge_stop_when_not_started():
    bridge = VirtualCamBridge(target_device="/dev/video0")
    assert bridge.is_running() is False
    bridge.stop()
    assert bridge.is_running() is False


def test_build_ffmpeg_pipe_cmd():
    cmd = build_ffmpeg_pipe_cmd("/dev/video0", 1280, 720, 25)
    assert "rawvideo" in cmd
    assert "bgr24" in cmd
    assert "1280x720" in cmd
    assert "pipe:0" in cmd
    assert "v4l2" in cmd
    assert "/dev/video0" in cmd


def test_virtual_cam_bridge_pipe_mode_feeds_frames_and_stops(monkeypatch):
    import io
    import time
    import numpy as np

    class FakeStdin:
        def __init__(self):
            self.chunks = []
            self.closed = False

        def write(self, data: bytes) -> int:
            if not self.closed:
                self.chunks.append(len(data))
            return len(data)

        def flush(self) -> None:
            pass

        def close(self) -> None:
            self.closed = True

    class FakeProc:
        def __init__(self, cmd, **kwargs):
            self.cmd = cmd
            self.stdin = FakeStdin()
            self._terminated = False

        def poll(self):
            return 0 if self._terminated else None

        def terminate(self):
            self._terminated = True

        def kill(self):
            self._terminated = True

        def wait(self, timeout=None):
            self._terminated = True
            return 0

    fake_holder = {}

    def fake_popen(cmd, **kwargs):
        proc = FakeProc(cmd, **kwargs)
        fake_holder["proc"] = proc
        return proc

    monkeypatch.setattr("toshi_camera.virtual_cam.subprocess.Popen", fake_popen)

    bridge = VirtualCamBridge(target_device="/dev/video0")
    bridge.start_pipe(width=320, height=240, fps=30)
    assert bridge.is_running() is True
    assert bridge.is_pipe_mode() is True

    # Push a different-size frame; bridge must resize to 320x240x3 = 230400 bytes
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    bridge.push_frame(frame)
    time.sleep(0.12)
    bridge.stop()

    assert bridge.is_running() is False
    assert bridge.is_pipe_mode() is False
    proc = fake_holder["proc"]
    assert len(proc.stdin.chunks) >= 1
    assert all(size == 320 * 240 * 3 for size in proc.stdin.chunks)
