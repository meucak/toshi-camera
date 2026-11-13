from __future__ import annotations

import sys
from PyQt6.QtWidgets import QApplication
from toshi_camera import __version__
from toshi_camera.ui import CameraMainWindow


def main() -> int:
    if "--version" in sys.argv or "-V" in sys.argv:
        print(f"Toshi Kamera v{__version__}")
        return 0
    app = QApplication(sys.argv)
    app.setApplicationName("Toshi Kamera")
    app.setOrganizationName("Toshi")
    win = CameraMainWindow()
    win.resize(980, 640)
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

