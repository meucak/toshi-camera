from __future__ import annotations

from collections import deque
import errno
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
from typing import Optional

import cv2
import numpy as np


DEFAULT_MIC_FIFO = Path.home() / ".cache" / "toshi-camera" / "toshi_virtual_mic.fifo"
DEFAULT_SOURCE_NAME = "toshi_virtual_mic"
DEFAULT_SAMPLE_RATE = 44100


def build_pactl_load_pipe_source_cmd(
    fifo_path: Path = DEFAULT_MIC_FIFO,
    source_name: str = DEFAULT_SOURCE_NAME,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    description: str = "Toshi_Virtual_Mic",
) -> list[str]:
    return [
        "pactl",
        "load-module",
        "module-pipe-source",
        f"source_name={source_name}",
        f"file={fifo_path}",
        "format=s16le",
        f"rate={sample_rate}",
        "channels=1",
        f"source_properties=device.description={description}",
    ]


class VirtualMicBridge:
    """PulseAudio module-pipe-source bridge exposing phone mic as a Linux audio source."""

    def __init__(
        self,
        fifo_path: Path = DEFAULT_MIC_FIFO,
        source_name: str = DEFAULT_SOURCE_NAME,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
    ) -> None:
        self.fifo_path = Path(fifo_path)
        self.source_name = source_name
        self.sample_rate = sample_rate
        self._module_id: Optional[str] = None
        self._running = False
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._pcm_queue: deque[bytes] = deque(maxlen=150)

    def is_running(self) -> bool:
        return self._running and self._thread is not None and self._thread.is_alive()

    def _unload_stale_modules(self) -> None:
        try:
            res = subprocess.run(
                ["pactl", "list", "short", "modules"],
                capture_output=True,
                text=True,
                timeout=3.0,
                check=False,
            )
        except Exception:
            return
        if res.returncode != 0:
            return
        for line in res.stdout.splitlines():
            if "module-pipe-source" in line and f"source_name={self.source_name}" in line:
                mod_id = line.split("\t", 1)[0].strip()
                if mod_id.isdigit():
                    subprocess.run(
                        ["pactl", "unload-module", mod_id],
                        capture_output=True,
                        text=True,
                        timeout=3.0,
                        check=False,
                    )

    def start(self) -> None:
        if self.is_running():
            return
        self.fifo_path.parent.mkdir(parents=True, exist_ok=True)
        self._unload_stale_modules()
        if self.fifo_path.exists():
            try:
                self.fifo_path.unlink()
            except OSError:
                pass

        cmd = build_pactl_load_pipe_source_cmd(
            fifo_path=self.fifo_path,
            source_name=self.source_name,
            sample_rate=self.sample_rate,
        )
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=4.0, check=False)
        if res.returncode != 0:
            raise RuntimeError(
                f"Sanal mikrofon modülü yüklenemedi: {res.stderr.strip() or res.stdout.strip()}"
            )
        self._module_id = res.stdout.strip()
        with self._lock:
            self._pcm_queue.clear()
        self._stop_event.clear()
        self._running = True
        self._thread = threading.Thread(target=self._writer_loop, daemon=True)
        self._thread.start()

    def push_pcm(self, pcm_s16le: bytes) -> None:
        if not self._running or not pcm_s16le:
            return
        with self._lock:
            self._pcm_queue.append(pcm_s16le)

    def _writer_loop(self) -> None:
        fd: Optional[int] = None
        silence = b"\x00" * int(self.sample_rate * 2 * 0.02)
        try:
            while not self._stop_event.is_set():
                if fd is None:
                    if not self.fifo_path.exists():
                        self._stop_event.wait(0.02)
                        continue
                    try:
                        fd = os.open(self.fifo_path, os.O_WRONLY | os.O_NONBLOCK)
                    except OSError as exc:
                        if exc.errno in (errno.ENXIO, errno.ENOENT):
                            self._stop_event.wait(0.02)
                            continue
                        break

                chunk: Optional[bytes] = None
                with self._lock:
                    if self._pcm_queue:
                        chunk = self._pcm_queue.popleft()

                payload = chunk if chunk is not None else silence
                try:
                    os.write(fd, payload)
                except BlockingIOError:
                    self._stop_event.wait(0.015)
                except OSError as exc:
                    if exc.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
                        self._stop_event.wait(0.015)
                    elif exc.errno == errno.EPIPE:
                        try:
                            os.close(fd)
                        except OSError:
                            pass
                        fd = None
                        self._stop_event.wait(0.02)
                    else:
                        break
                else:
                    if chunk is None:
                        self._stop_event.wait(0.02)
        finally:
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass

    def stop(self) -> None:
        self._running = False
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        if self._module_id:
            try:
                subprocess.run(
                    ["pactl", "unload-module", self._module_id],
                    capture_output=True,
                    text=True,
                    timeout=3.0,
                    check=False,
                )
            except Exception:
                pass
            self._module_id = None
        if self.fifo_path.exists():
            try:
                self.fifo_path.unlink()
            except OSError:
                pass


class FfmpegAudioVideoRecorder:
    """Muxes live BGR24 video frames and s16le mono PCM audio into MP4 via FFmpeg."""

    def __init__(
        self,
        out_path: Path,
        width: int,
        height: int,
        fps: int = 25,
        sample_rate: int = DEFAULT_SAMPLE_RATE,
    ) -> None:
        self.out_path = Path(out_path)
        self.width = int(width)
        self.height = int(height)
        self.fps = max(1, int(fps))
        self.sample_rate = int(sample_rate)

        self._tmp_dir = tempfile.TemporaryDirectory(prefix="toshi_rec_")
        self._audio_fifo = Path(self._tmp_dir.name) / "audio.fifo"
        os.mkfifo(self._audio_fifo)

        self._stop_event = threading.Event()
        self._frame_lock = threading.Lock()
        self._latest_frame: bytes = np.zeros((self.height, self.width, 3), dtype=np.uint8).tobytes()
        self._audio_lock = threading.Lock()
        self._audio_queue: deque[bytes] = deque(maxlen=200)

        cmd = [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "bgr24",
            "-s",
            f"{self.width}x{self.height}",
            "-r",
            str(self.fps),
            "-i",
            "pipe:0",
            "-f",
            "s16le",
            "-ar",
            str(self.sample_rate),
            "-ac",
            "1",
            "-i",
            str(self._audio_fifo),
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(self.out_path),
        ]
        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        self._video_thread = threading.Thread(target=self._video_loop, daemon=True)
        self._audio_thread = threading.Thread(target=self._audio_loop, daemon=True)
        self._video_thread.start()
        self._audio_thread.start()

    def write(self, frame: np.ndarray) -> None:
        if self._stop_event.is_set() or frame is None or frame.size == 0:
            return
        if frame.shape[1] != self.width or frame.shape[0] != self.height:
            frame = cv2.resize(frame, (self.width, self.height))
        payload = np.ascontiguousarray(frame, dtype=np.uint8).tobytes()
        with self._frame_lock:
            self._latest_frame = payload

    def push_pcm(self, pcm_s16le: bytes) -> None:
        if self._stop_event.is_set() or not pcm_s16le:
            return
        with self._audio_lock:
            self._audio_queue.append(pcm_s16le)

    def _video_loop(self) -> None:
        interval = 1.0 / self.fps
        next_tick = time.monotonic()
        while not self._stop_event.is_set():
            if self._proc.poll() is not None or self._proc.stdin is None:
                break
            with self._frame_lock:
                payload = self._latest_frame
            try:
                self._proc.stdin.write(payload)
                self._proc.stdin.flush()
            except (BrokenPipeError, OSError, ValueError):
                break
            next_tick += interval
            delay = next_tick - time.monotonic()
            if delay > 0:
                self._stop_event.wait(delay)
            else:
                next_tick = time.monotonic()

    def _audio_loop(self) -> None:
        fd: Optional[int] = None
        silence = b"\x00" * int(self.sample_rate * 2 * 0.02)
        try:
            while not self._stop_event.is_set():
                if fd is None:
                    try:
                        fd = os.open(self._audio_fifo, os.O_WRONLY | os.O_NONBLOCK)
                    except OSError as exc:
                        if exc.errno in (errno.ENXIO, errno.ENOENT):
                            self._stop_event.wait(0.02)
                            continue
                        break
                chunk: Optional[bytes] = None
                with self._audio_lock:
                    if self._audio_queue:
                        chunk = self._audio_queue.popleft()
                payload = chunk if chunk is not None else silence
                try:
                    os.write(fd, payload)
                except BlockingIOError:
                    self._stop_event.wait(0.015)
                except OSError as exc:
                    if exc.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
                        self._stop_event.wait(0.015)
                    else:
                        break
                else:
                    if chunk is None:
                        self._stop_event.wait(0.02)
        finally:
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass

    def release(self) -> None:
        self._stop_event.set()
        if self._proc.stdin is not None:
            try:
                self._proc.stdin.close()
            except OSError:
                pass
        self._video_thread.join(timeout=2.0)
        self._audio_thread.join(timeout=2.0)
        if self._proc.poll() is None:
            try:
                self._proc.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                self._proc.terminate()
                self._proc.wait(timeout=1.5)
        self._tmp_dir.cleanup()
