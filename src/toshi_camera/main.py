from __future__ import annotations

import os
import sys
from typing import Optional

from toshi_camera import __version__
from toshi_camera.storage import get_default_saves_dir


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
        os.chdir(saves_dir)
        shell = os.environ.get("SHELL", "/bin/bash")
        os.execvp(shell, [shell])
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
