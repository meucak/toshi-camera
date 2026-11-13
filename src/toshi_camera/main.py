from __future__ import annotations

import sys
from PyQt6.QtWidgets import QApplication
from toshi_camera.ui import CameraMainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Toshi Kamera")
    app.setOrganizationName("Toshi")
    win = CameraMainWindow()
    win.resize(980, 640)
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
