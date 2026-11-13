import os
import threading
import time
from pathlib import Path

from toshi_camera.audio_bridge import (
    VirtualMicBridge,
    build_pactl_load_pipe_source_cmd,
)


def test_build_pactl_load_pipe_source_cmd(tmp_path: Path):
    fifo = tmp_path / "mic.fifo"
    cmd = build_pactl_load_pipe_source_cmd(
        fifo_path=fifo,
        source_name="toshi_virtual_mic",
        sample_rate=44100,
    )
    assert cmd[:3] == ["pactl", "load-module", "module-pipe-source"]
    assert "source_name=toshi_virtual_mic" in cmd
    assert f"file={fifo}" in cmd
    assert "format=s16le" in cmd
    assert "rate=44100" in cmd
    assert "channels=1" in cmd


def test_virtual_mic_bridge_lifecycle_and_fifo_write(tmp_path: Path, monkeypatch):
    fifo = tmp_path / "toshi_mic.fifo"
    calls = []

    class FakeResult:
        def __init__(self, returncode=0, stdout="", stderr=""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[:3] == ["pactl", "list", "short"]:
            return FakeResult(0, "")
        if cmd[:3] == ["pactl", "load-module", "module-pipe-source"]:
            os.mkfifo(fifo)
            return FakeResult(0, "42\n")
        if cmd[:2] == ["pactl", "unload-module"]:
            return FakeResult(0, "")
        return FakeResult(0, "")

    monkeypatch.setattr("toshi_camera.audio_bridge.subprocess.run", fake_run)

    bridge = VirtualMicBridge(fifo_path=fifo)
    received = bytearray()
    reader_ready = threading.Event()
    stop_reader = threading.Event()

    def reader():
        # Wait until FIFO exists
        for _ in range(50):
            if fifo.exists():
                break
            time.sleep(0.02)
        fd = os.open(fifo, os.O_RDONLY | os.O_NONBLOCK)
        reader_ready.set()
        try:
            while not stop_reader.is_set():
                try:
                    chunk = os.read(fd, 4096)
                    if chunk:
                        received.extend(chunk)
                    else:
                        time.sleep(0.01)
                except BlockingIOError:
                    time.sleep(0.01)
        finally:
            os.close(fd)

    rt = threading.Thread(target=reader, daemon=True)
    rt.start()

    bridge.start()
    assert bridge.is_running() is True
    assert reader_ready.wait(timeout=2.0)

    bridge.push_pcm(b"\x11\x22" * 512)
    time.sleep(0.12)
    stop_reader.set()
    rt.join(timeout=2.0)
    bridge.stop()

    assert bridge.is_running() is False
    assert b"\x11\x22" in bytes(received)
    assert ["pactl", "unload-module", "42"] in calls
