from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import cv2
import numpy as np


@dataclass(frozen=True)
class FrameSettings:
    brightness: int = 0  # -100 .. +100
    contrast: int = 0    # -100 .. +100
    saturation: int = 0  # -100 .. +100
    mirror_horizontal: bool = False
    flip_vertical: bool = False
    rotation_deg: int = 0  # 0, 90, 180, 270


def apply_adjustments(frame: np.ndarray, settings: FrameSettings) -> np.ndarray:
    out = frame.copy()

    rot = settings.rotation_deg % 360
    if rot == 90:
        out = cv2.rotate(out, cv2.ROTATE_90_CLOCKWISE)
    elif rot == 180:
        out = cv2.rotate(out, cv2.ROTATE_180)
    elif rot == 270:
        out = cv2.rotate(out, cv2.ROTATE_90_COUNTERCLOCKWISE)

    if settings.mirror_horizontal and settings.flip_vertical:
        out = cv2.flip(out, -1)
    elif settings.mirror_horizontal:
        out = cv2.flip(out, 1)
    elif settings.flip_vertical:
        out = cv2.flip(out, 0)

    if settings.brightness != 0 or settings.contrast != 0:
        alpha = max(0.1, 1.0 + (settings.contrast / 100.0))
        beta = float(settings.brightness) * 1.5
        out = cv2.convertScaleAbs(out, alpha=alpha, beta=beta)

    if settings.saturation != 0 and out.ndim == 3 and out.shape[2] == 3:
        hsv = cv2.cvtColor(out, cv2.COLOR_BGR2HSV).astype(np.float32)
        sat_scale = max(0.0, 1.0 + (settings.saturation / 100.0))
        hsv[:, :, 1] = np.clip(hsv[:, :, 1] * sat_scale, 0, 255)
        out = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)

    return out


def generate_test_frame(
    width: int = 640,
    height: int = 480,
    frame_index: int = 0,
    label: str = "Toshi Kamera",
) -> np.ndarray:
    frame = np.zeros((height, width, 3), dtype=np.uint8)

    # Classic broadcast SMPTE-style color bars (BGR)
    bars_bgr = [
        (192, 192, 192),  # White/Gray
        (0, 192, 192),    # Yellow
        (192, 192, 0),    # Cyan
        (0, 192, 0),      # Green
        (192, 0, 192),    # Magenta
        (0, 0, 192),      # Red
        (192, 0, 0),      # Blue
    ]
    bar_h = int(height * 0.68)
    bar_w = max(1, width // len(bars_bgr))
    for idx, color in enumerate(bars_bgr):
        x0 = idx * bar_w
        x1 = width if idx == len(bars_bgr) - 1 else (idx + 1) * bar_w
        frame[0:bar_h, x0:x1] = color

    # Lower studio slate area
    frame[bar_h:height, :] = (28, 30, 34)

    # Moving scan/sync indicator bar to verify live framerate
    scan_x = int((frame_index * 8) % max(1, width - 40))
    scan_y0 = bar_h + 12
    scan_y1 = min(height - 12, bar_h + 26)
    frame[scan_y0:scan_y1, scan_x : scan_x + 40] = (80, 200, 120)

    # Timestamp & status overlay
    ts = datetime.now().strftime("%H:%M:%S")
    cv2.putText(
        frame,
        f"{label} | Canli Kalibrasyon | Kare #{frame_index}",
        (16, min(height - 44, bar_h + 56)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.58,
        (235, 235, 235),
        1,
        cv2.LINE_AA,
    )
    cv2.putText(
        frame,
        f"{width}x{height} | {ts}",
        (16, min(height - 16, bar_h + 86)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.52,
        (170, 185, 200),
        1,
        cv2.LINE_AA,
    )
    return frame
