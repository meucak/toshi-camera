from __future__ import annotations

import subprocess
from typing import Optional
from urllib.parse import urlparse


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


class VirtualCamBridge:
    def __init__(self, target_device: str = "/dev/video0") -> None:
        self.target_device = target_device
        self._proc: Optional[subprocess.Popen[bytes]] = None

    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

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
        self._proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )

    def stop(self) -> None:
        if self._proc is None:
            return
        if self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait(timeout=1.0)
        self._proc = None
