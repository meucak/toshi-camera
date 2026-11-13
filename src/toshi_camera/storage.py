from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import time
import cv2
import numpy as np


@dataclass(frozen=True)
class MediaItem:
    path: Path
    kind: str  # "photo" or "video"
    created_at: float


def get_default_saves_dir() -> Path:
    saves_dir = Path.home() / "Kamera"
    saves_dir.mkdir(parents=True, exist_ok=True)
    return saves_dir


class MediaStorage:
    PHOTO_EXTS = {".png", ".jpg", ".jpeg"}
    VIDEO_EXTS = {".avi", ".mp4", ".mkv"}

    def __init__(self, photo_dir: Path, video_dir: Path) -> None:
        self.photo_dir = Path(photo_dir)
        self.video_dir = Path(video_dir)
        self.photo_dir.mkdir(parents=True, exist_ok=True)
        self.video_dir.mkdir(parents=True, exist_ok=True)

    def _unique_path(self, directory: Path, prefix: str, ext: str) -> Path:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        clean_ext = ext.lstrip(".")
        candidate = directory / f"{prefix}_{stamp}.{clean_ext}"
        counter = 1
        while candidate.exists():
            candidate = directory / f"{prefix}_{stamp}_{counter}.{clean_ext}"
            counter += 1
        return candidate

    def save_photo(self, frame: np.ndarray, prefix: str = "IMG") -> Path:
        self.photo_dir.mkdir(parents=True, exist_ok=True)
        out_path = self._unique_path(self.photo_dir, prefix, "png")
        ok = cv2.imwrite(str(out_path), frame)
        if not ok:
            raise OSError(f"Fotoğraf kaydedilemedi: {out_path}")
        return out_path

    def allocate_video_path(self, prefix: str = "VID", ext: str = "avi") -> Path:
        self.video_dir.mkdir(parents=True, exist_ok=True)
        return self._unique_path(self.video_dir, prefix, ext)

    def list_media(self, limit: int = 50) -> list[MediaItem]:
        items: list[MediaItem] = []
        for directory in (self.photo_dir, self.video_dir):
            if not directory.exists():
                continue
            for p in directory.iterdir():
                if not p.is_file():
                    continue
                suffix = p.suffix.lower()
                if suffix in self.PHOTO_EXTS:
                    kind = "photo"
                elif suffix in self.VIDEO_EXTS:
                    kind = "video"
                else:
                    continue
                try:
                    mtime = p.stat().st_mtime
                except OSError:
                    mtime = time.time()
                items.append(MediaItem(path=p, kind=kind, created_at=mtime))

        items.sort(key=lambda item: item.created_at, reverse=True)
        return items[:limit]

    def delete_media_file(self, path: Path) -> bool:
        target = Path(path)
        if not target.exists() or not target.is_file():
            return False
        try:
            target.unlink()
            return True
        except OSError:
            return False
