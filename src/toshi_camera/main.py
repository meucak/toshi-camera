from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from toshi_camera import __version__
from toshi_camera.storage import get_default_saves_dir


def open_saves_directory(saves_dir: Path) -> bool:
    for tool in ("xdg-open", "pcmanfm-qt", "gio"):
        exe = shutil.which(tool)
        if not exe:
            continue
        cmd = [exe, "open", str(saves_dir)] if tool == "gio" else [exe, str(saves_dir)]
        subprocess.Popen(
            cmd,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    return False


def main(argv: Optional[list[str]] = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if "--version" in args or "-V" in args:
        print(f"Toshi Kamera v{__version__}")
        return 0

    if "--saves-path" in args:
        print(get_default_saves_dir())
        return 0

    if "--saves" in args:
        saves_dir = get_default_saves_dir()
        print(saves_dir)
        if not open_saves_directory(saves_dir):
            print("Dosya yöneticisi (xdg-open / pcmanfm-qt) bulunamadı.", file=sys.stderr)
            return 1
        return 0

    from PyQt6.QtWidgets import QApplication
    from toshi_camera.ui import CameraMainWindow

    app = QApplication([sys.argv[0], *args])
    app.setApplicationName("Toshi Kamera")
    app.setOrganizationName("Toshi")
    win = CameraMainWindow()
    win.resize(980, 640)
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
