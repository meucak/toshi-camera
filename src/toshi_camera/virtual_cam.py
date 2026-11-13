from __future__ import annotations

import subprocess
import threading
import time
from typing import Optional
from urllib.parse import urlparse

import cv2
import numpy as np


ALLOWED_SCHEMES = {"http", "https", "rtsp", "rtsps", "udp", "tcp"}


def validate_stream_url(url: str) -> bool:
    cleaned = (url or "").strip()
    if not cleaned:
        return False
    parsed = urlparse(cleaned)
    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        return False
    return bool(parsed.netloc)


def build_ffmpeg_loopback_cmd(
    source_url: Optional[str],
    target_device: str = "/dev/video0",
    width: int = 640,
    height: int = 480,
    fps: int = 30,
) -> list[str]:
    if source_url is None:
        return [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-re",
            "-f",
            "lavfi",
            "-i",
            f"testsrc2=size={width}x{height}:rate={fps}",
            "-pix_fmt",
            "yuv420p",
            "-f",
            "v4l2",
            target_device,
        ]

    if not validate_stream_url(source_url):
        raise ValueError(f"Geçersiz akış adresi: {source_url}")

    return [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        source_url.strip(),
        "-vf",
        f"scale={width}:{height},fps={fps}",
        "-pix_fmt",
        "yuv420p",
        "-f",
        "v4l2",
        target_device,
    ]


def build_ffmpeg_pipe_cmd(
    target_device: str = "/dev/video0",
    width: int = 640,
    height: int = 480,
    fps: int = 30,
) -> list[str]:
    return [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "bgr24",
        "-s",
        f"{width}x{height}",
        "-r",
        str(fps),
        "-i",
        "pipe:0",
        "-pix_fmt",
        "yuv420p",
        "-f",
        "v4l2",
        target_device,
    ]


class VirtualCamBridge:
    def __init__(self, target_device: str = "/dev/video0") -> None:
        self.target_device = target_device
        self._proc: Optional[subprocess.Popen[bytes]] = None
        self._pipe_mode: bool = False
        self._pipe_size: tuple[int, int] = (640, 480)
        self._pipe_fps: int = 30
        self._frame_lock = threading.Lock()
        self._latest_frame_bytes: Optional[bytes] = None
        self._pipe_stop = threading.Event()
        self._feeder_thread: Optional[threading.Thread] = None

    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def is_pipe_mode(self) -> bool:
        return self._pipe_mode and self.is_running()

    def start(
        self,
        source_url: Optional[str] = None,
        width: int = 640,
        height: int = 480,
        fps: int = 30,
    ) -> None:
        self.stop()
        cmd = build_ffmpeg_loopback_cmd(
            source_url=source_url,
            target_device=self.target_device,
            width=width,
            height=height,
            fps=fps,
        )
        self._pipe_mode = False
        self._proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )

    def start_pipe(
        self,
        width: int = 640,
        height: int = 480,
        fps: int = 30,
    ) -> None:
        self.stop()
        cmd = build_ffmpeg_pipe_cmd(
            target_device=self.target_device,
            width=width,
            height=height,
            fps=fps,
        )
        self._pipe_size = (width, height)
        self._pipe_fps = max(1, fps)
        self._pipe_mode = True
        with self._frame_lock:
            self._latest_frame_bytes = np.zeros((height, width, 3), dtype=np.uint8).tobytes()
        self._pipe_stop.clear()
        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        self._feeder_thread = threading.Thread(target=self._feed_loop, daemon=True)
        self._feeder_thread.start()

    def push_frame(self, frame: np.ndarray) -> None:
        if not self._pipe_mode or frame is None or frame.size == 0:
            return
        w, h = self._pipe_size
        if frame.shape[1] != w or frame.shape[0] != h:
            resized = cv2.resize(frame, (w, h))
        else:
            resized = frame
        if resized.ndim == 2:
            resized = cv2.cvtColor(resized, cv2.COLOR_GRAY2BGR)
        payload = np.ascontiguousarray(resized, dtype=np.uint8).tobytes()
        with self._frame_lock:
            self._latest_frame_bytes = payload

    def _feed_loop(self) -> None:
        interval = 1.0 / self._pipe_fps
        next_tick = time.monotonic()
        while not self._pipe_stop.is_set():
            proc = self._proc
            if proc is None or proc.poll() is not None or proc.stdin is None:
                break
            with self._frame_lock:
                payload = self._latest_frame_bytes
            if payload:
                try:
                    proc.stdin.write(payload)
                    proc.stdin.flush()
                except (BrokenPipeError, OSError, ValueError):
                    break
            next_tick += interval
            delay = next_tick - time.monotonic()
            if delay > 0:
                self._pipe_stop.wait(delay)
            else:
                next_tick = time.monotonic()

    def stop(self) -> None:
        self._pipe_stop.set()
        self._pipe_mode = False
        if self._feeder_thread is not None:
            self._feeder_thread.join(timeout=1.5)
            self._feeder_thread = None

        if self._proc is None:
            return
        if self._proc.stdin is not None:
            try:
                self._proc.stdin.close()
            except OSError:
                pass
        if self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait(timeout=1.0)
        self._proc = None
