from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
from PyQt6.QtCore import Qt, QTimer, QUrl
from PyQt6.QtGui import (
    QAction,
    QDesktopServices,
    QFont,
    QIcon,
    QImage,
    QKeySequence,
    QPalette,
    QPixmap,
)
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSlider,
    QSplitter,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from toshi_camera.diagnostics import (
    HardwareReport,
    collect_live_hardware_report,
    discover_video_devices,
)
from toshi_camera.processing import (
    FrameSettings,
    apply_adjustments,
    generate_test_frame,
)
from toshi_camera.storage import MediaStorage
from toshi_camera.virtual_cam import VirtualCamBridge, validate_stream_url


class AspectRatioVideoLabel(QLabel):
    """Responsive video viewport using layout policies without fixed pixel geometry."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.setMinimumSize(320, 240)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setFrameShadow(QFrame.Shadow.Sunken)
        self.setAutoFillBackground(True)
        self.setBackgroundRole(QPalette.ColorRole.Base)
        self.setWordWrap(True)
        self._current_pixmap: Optional[QPixmap] = None

    def set_video_frame(self, bgr_frame: np.ndarray) -> None:
        rgb = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        bytes_per_line = ch * w
        qimg = QImage(
            rgb.data, w, h, bytes_per_line, QImage.Format.Format_RGB888
        ).copy()
        self._current_pixmap = QPixmap.fromImage(qimg)
        self._update_scaled()

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._update_scaled()

    def _update_scaled(self) -> None:
        if self._current_pixmap is None or self._current_pixmap.isNull():
            return
        scaled = self._current_pixmap.scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        super().setPixmap(scaled)


class DiagnosticsDialog(QDialog):
    """Hardware & ACPI/V4L2 diagnostics dialog compliant with Qt & HIG standards."""

    def __init__(
        self, report: HardwareReport, parent: Optional[QWidget] = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Donanım Tanılama — Toshi Kamera")
        self.setWindowIcon(
            QIcon.fromTheme(
                "dialog-information",
                self.style().standardIcon(
                    self.style().StandardPixmap.SP_MessageBoxInformation
                ),
            )
        )
        self._report = report

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(16, 16, 16, 16)
        root_layout.setSpacing(16)

        title_lbl = QLabel("Toshiba Satellite L735 Kamera ve Veri Yolu Durumu")
        title_font = QFont(title_lbl.font())
        title_font.setPointSize(title_font.pointSize() + 2)
        title_font.setBold(True)
        title_lbl.setFont(title_font)
        title_lbl.setWordWrap(True)
        root_layout.addWidget(title_lbl)

        status_group = QGroupBox("Anakart ve Sürücü Bulguları")
        form = QFormLayout(status_group)
        form.setContentsMargins(12, 12, 12, 12)
        form.setSpacing(8)

        ccde_text = (
            "0x0 (BIOS POST üzerinde dahili kamera algılanmadı)"
            if report.ccde_flag == 0
            else f"0x{report.ccde_flag:x}"
            if report.ccde_flag is not None
            else "Bilinmiyor"
        )
        usb_text = (
            "Bağlı (Aktif)"
            if report.usb_webcam_attached
            else "Bağlı değil (İç USB portlarında sinyal yok — state: not attached)"
        )
        loopback_text = (
            "Aktif (/dev/video0 — Toshi Virtual Camera)"
            if report.loopback_loaded
            else "Yüklü değil"
        )

        ccde_val_lbl = QLabel(ccde_text)
        ccde_val_lbl.setWordWrap(True)
        usb_val_lbl = QLabel(usb_text)
        usb_val_lbl.setWordWrap(True)
        loop_val_lbl = QLabel(loopback_text)
        loop_val_lbl.setWordWrap(True)

        form.addRow(QLabel("ACPI OGNS CCDE bayrağı"), ccde_val_lbl)
        form.addRow(QLabel("Fiziksel USB kamera hattı"), usb_val_lbl)
        form.addRow(QLabel("Sanal kamera köprüsü"), loop_val_lbl)
        root_layout.addWidget(status_group)

        dev_group = QGroupBox("Algılanan V4L2 Video Düğümleri")
        dev_layout = QVBoxLayout(dev_group)
        dev_layout.setContentsMargins(12, 12, 12, 12)
        dev_list = QListWidget()
        if report.devices:
            for d in report.devices:
                kind = "Sanal Köprü" if d.is_loopback else "Fiziksel Kamera"
                dev_list.addItem(f"{d.path} — {d.name} ({d.driver}, {kind})")
        else:
            dev_list.addItem("Algılanan V4L2 video düğümü yok")
        dev_layout.addWidget(dev_list)
        root_layout.addWidget(dev_group)

        summary_group = QGroupBox("Kök Neden ve Çözüm Özeti")
        summary_layout = QVBoxLayout(summary_group)
        summary_layout.setContentsMargins(12, 12, 12, 12)
        summary_lbl = QLabel(report.summary_tr)
        summary_lbl.setWordWrap(True)
        summary_layout.addWidget(summary_lbl)
        root_layout.addWidget(summary_group)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_btn = button_box.button(QDialogButtonBox.StandardButton.Close)
        if close_btn is not None:
            close_btn.setText("&Kapat")
            close_btn.setDefault(True)
        button_box.rejected.connect(self.reject)
        button_box.accepted.connect(self.accept)
        root_layout.addWidget(button_box)


class CameraMainWindow(QMainWindow):
    """Main camera application window adhering to Apple HIG and Qt QWidgets standards."""

    RESOLUTIONS = [
        ("640 × 480 (VGA)", 640, 480),
        ("1280 × 720 (HD)", 1280, 720),
        ("320 × 240 (QVGA)", 320, 240),
    ]
    TIMERS = [
        ("Kapalı (Anında)", 0),
        ("3 saniye", 3),
        ("5 saniye", 5),
        ("10 saniye", 10),
    ]

    def __init__(
        self,
        storage: Optional[MediaStorage] = None,
        auto_start_capture: bool = True,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Toshi Kamera")
        self.setWindowIcon(
            QIcon.fromTheme(
                "camera-web",
                self.style().standardIcon(
                    self.style().StandardPixmap.SP_ComputerIcon
                ),
            )
        )

        default_photo_dir = Path.home() / "Resimler" / "Kamera"
        default_video_dir = Path.home() / "Videolar" / "Kamera"
        self.storage = storage or MediaStorage(default_photo_dir, default_video_dir)
        self.virtual_bridge = VirtualCamBridge(target_device="/dev/video0")

        self._cap: Optional[cv2.VideoCapture] = None
        self._video_writer: Optional[cv2.VideoWriter] = None
        self._recording_path: Optional[Path] = None
        self._frame_index: int = 0
        self._last_frame: Optional[np.ndarray] = None
        self._countdown_remaining: int = 0

        self._build_ui()
        self._build_shortcuts()
        self.refresh_sources(auto_open=auto_start_capture)
        self.refresh_gallery()

        self._frame_timer = QTimer(self)
        self._frame_timer.setInterval(33)  # ~30 FPS
        self._frame_timer.timeout.connect(self._on_tick)
        if auto_start_capture:
            self._frame_timer.start()

        self._countdown_timer = QTimer(self)
        self._countdown_timer.setInterval(1000)
        self._countdown_timer.timeout.connect(self._on_countdown_tick)

    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        outer_layout = QVBoxLayout(central)
        outer_layout.setContentsMargins(16, 16, 16, 16)
        outer_layout.setSpacing(16)

        splitter = QSplitter(Qt.Orientation.Horizontal, central)
        splitter.setChildrenCollapsible(False)
        outer_layout.addWidget(splitter, stretch=1)

        # Left pane: Viewport + Primary Action Bar
        left_pane = QWidget(splitter)
        left_layout = QVBoxLayout(left_pane)
        left_layout.setContentsMargins(0, 0, 8, 0)
        left_layout.setSpacing(12)

        self.viewport = AspectRatioVideoLabel(left_pane)
        left_layout.addWidget(self.viewport, stretch=1)

        action_bar = QHBoxLayout()
        action_bar.setSpacing(8)

        self.photo_btn = QPushButton("&Fotoğraf Çek")
        self.photo_btn.setMinimumHeight(44)
        self.photo_btn.setIcon(QIcon.fromTheme("camera-photo"))
        self.photo_btn.setDefault(True)
        self.photo_btn.clicked.connect(self.trigger_photo_capture)

        self.video_btn = QPushButton("&Video Kaydet")
        self.video_btn.setMinimumHeight(44)
        self.video_btn.setCheckable(True)
        self.video_btn.setIcon(QIcon.fromTheme("media-record"))
        self.video_btn.clicked.connect(self.toggle_video_recording)

        self.diag_btn = QPushButton("&Donanım Tanılama")
        self.diag_btn.setMinimumHeight(44)
        self.diag_btn.setIcon(QIcon.fromTheme("dialog-information"))
        self.diag_btn.clicked.connect(self.open_diagnostics_dialog)

        action_bar.addWidget(self.photo_btn)
        action_bar.addWidget(self.video_btn)
        action_bar.addStretch(1)
        action_bar.addWidget(self.diag_btn)
        left_layout.addLayout(action_bar)

        # Right pane: Source selection, Image adjustments, Virtual Bridge, Gallery
        right_pane = QWidget(splitter)
        right_layout = QVBoxLayout(right_pane)
        right_layout.setContentsMargins(8, 0, 0, 0)
        right_layout.setSpacing(12)

        # 1. Source & Capture Settings Group
        source_group = QGroupBox("Kaynak ve Çekim Ayarları")
        source_form = QFormLayout(source_group)
        source_form.setContentsMargins(12, 12, 12, 12)
        source_form.setSpacing(8)

        self.source_combo = QComboBox()
        self.source_combo.setMinimumHeight(36)
        self.source_combo.currentIndexChanged.connect(self._on_source_changed)
        lbl_source = QLabel("Kamera &kaynağı")
        lbl_source.setBuddy(self.source_combo)

        self.stream_url_edit = QLineEdit()
        self.stream_url_edit.setPlaceholderText("http://192.168.1.50:8080/video")
        self.stream_url_edit.setMinimumHeight(36)
        self.stream_url_edit.returnPressed.connect(self._on_source_changed)
        lbl_stream = QLabel("Ağ &akış adresi")
        lbl_stream.setBuddy(self.stream_url_edit)

        self.resolution_combo = QComboBox()
        self.resolution_combo.setMinimumHeight(36)
        for title, w, h in self.RESOLUTIONS:
            self.resolution_combo.addItem(title, (w, h))
        self.resolution_combo.currentIndexChanged.connect(self._on_source_changed)
        lbl_res = QLabel("Ç&özünürlük")
        lbl_res.setBuddy(self.resolution_combo)

        self.timer_combo = QComboBox()
        self.timer_combo.setMinimumHeight(36)
        for title, sec in self.TIMERS:
            self.timer_combo.addItem(title, sec)
        lbl_timer = QLabel("&Zamanlayıcı")
        lbl_timer.setBuddy(self.timer_combo)

        source_form.addRow(lbl_source, self.source_combo)
        source_form.addRow(lbl_stream, self.stream_url_edit)
        source_form.addRow(lbl_res, self.resolution_combo)
        source_form.addRow(lbl_timer, self.timer_combo)

        source_btn_row = QHBoxLayout()
        self.refresh_btn = QPushButton("&Kaynakları Yenile")
        self.refresh_btn.setMinimumHeight(36)
        self.refresh_btn.setIcon(QIcon.fromTheme("view-refresh"))
        self.refresh_btn.clicked.connect(lambda: self.refresh_sources(auto_open=True))

        self.bridge_btn = QPushButton("&Sanal Köprüyü Başlat")
        self.bridge_btn.setMinimumHeight(36)
        self.bridge_btn.setCheckable(True)
        self.bridge_btn.setIcon(QIcon.fromTheme("network-transmit-receive"))
        self.bridge_btn.clicked.connect(self.toggle_virtual_bridge)

        source_btn_row.addWidget(self.refresh_btn)
        source_btn_row.addWidget(self.bridge_btn)
        source_form.addRow(source_btn_row)
        right_layout.addWidget(source_group)

        # 2. Image Adjustments Group
        adj_group = QGroupBox("Görüntü Kontrolleri")
        adj_form = QFormLayout(adj_group)
        adj_form.setContentsMargins(12, 12, 12, 12)
        adj_form.setSpacing(8)

        self.brightness_slider = QSlider(Qt.Orientation.Horizontal)
        self.brightness_slider.setRange(-100, 100)
        self.brightness_slider.setValue(0)
        lbl_bright = QLabel("&Parlaklık")
        lbl_bright.setBuddy(self.brightness_slider)

        self.contrast_slider = QSlider(Qt.Orientation.Horizontal)
        self.contrast_slider.setRange(-100, 100)
        self.contrast_slider.setValue(0)
        lbl_contrast = QLabel("K&ontrast")
        lbl_contrast.setBuddy(self.contrast_slider)

        self.saturation_slider = QSlider(Qt.Orientation.Horizontal)
        self.saturation_slider.setRange(-100, 100)
        self.saturation_slider.setValue(0)
        lbl_sat = QLabel("Do&ygunluk")
        lbl_sat.setBuddy(self.saturation_slider)

        self.mirror_checkbox = QCheckBox("Yatay ayna görüntüsü")
        self.flip_checkbox = QCheckBox("Dikey çevir")

        self.reset_adj_btn = QPushButton("&Ayarları Sıfırla")
        self.reset_adj_btn.setMinimumHeight(36)
        self.reset_adj_btn.setIcon(QIcon.fromTheme("edit-undo"))
        self.reset_adj_btn.clicked.connect(self.reset_adjustments)

        adj_form.addRow(lbl_bright, self.brightness_slider)
        adj_form.addRow(lbl_contrast, self.contrast_slider)
        adj_form.addRow(lbl_sat, self.saturation_slider)
        adj_form.addRow(self.mirror_checkbox)
        adj_form.addRow(self.flip_checkbox)
        adj_form.addRow(self.reset_adj_btn)
        right_layout.addWidget(adj_group)

        # 3. Gallery Group
        gallery_group = QGroupBox("Çekim Galerisi")
        gallery_layout = QVBoxLayout(gallery_group)
        gallery_layout.setContentsMargins(12, 12, 12, 12)
        gallery_layout.setSpacing(8)

        self.gallery_list = QListWidget()
        self.gallery_list.itemDoubleClicked.connect(self.open_selected_media)
        gallery_layout.addWidget(self.gallery_list, stretch=1)

        gallery_btn_row = QHBoxLayout()
        self.open_media_btn = QPushButton("S&eçiliyi Aç")
        self.open_media_btn.setMinimumHeight(36)
        self.open_media_btn.setIcon(QIcon.fromTheme("document-open"))
        self.open_media_btn.clicked.connect(self.open_selected_media)

        self.delete_media_btn = QPushButton("Seçiliyi S&il")
        self.delete_media_btn.setMinimumHeight(36)
        self.delete_media_btn.setIcon(QIcon.fromTheme("edit-delete"))
        self.delete_media_btn.clicked.connect(self.delete_selected_media)

        gallery_btn_row.addWidget(self.open_media_btn)
        gallery_btn_row.addWidget(self.delete_media_btn)
        gallery_layout.addLayout(gallery_btn_row)
        right_layout.addWidget(gallery_group, stretch=1)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        # Logical keyboard tab order
        self.setTabOrder(self.photo_btn, self.video_btn)
        self.setTabOrder(self.video_btn, self.diag_btn)
        self.setTabOrder(self.diag_btn, self.source_combo)
        self.setTabOrder(self.source_combo, self.stream_url_edit)
        self.setTabOrder(self.stream_url_edit, self.resolution_combo)
        self.setTabOrder(self.resolution_combo, self.timer_combo)
        self.setTabOrder(self.timer_combo, self.refresh_btn)
        self.setTabOrder(self.refresh_btn, self.bridge_btn)
        self.setTabOrder(self.bridge_btn, self.brightness_slider)
        self.setTabOrder(self.brightness_slider, self.contrast_slider)
        self.setTabOrder(self.contrast_slider, self.saturation_slider)
        self.setTabOrder(self.saturation_slider, self.mirror_checkbox)
        self.setTabOrder(self.mirror_checkbox, self.flip_checkbox)
        self.setTabOrder(self.flip_checkbox, self.reset_adj_btn)
        self.setTabOrder(self.reset_adj_btn, self.gallery_list)
        self.setTabOrder(self.gallery_list, self.open_media_btn)
        self.setTabOrder(self.open_media_btn, self.delete_media_btn)

        status = QStatusBar(self)
        self.setStatusBar(status)
        status.showMessage("Hazır — Toshi Kamera")

    def _build_shortcuts(self) -> None:
        act_capture = QAction("Fotoğraf Çek", self)
        act_capture.setShortcut(QKeySequence(Qt.Key.Key_Space))
        act_capture.triggered.connect(self.trigger_photo_capture)
        self.addAction(act_capture)

        act_record = QAction("Video Kaydet", self)
        act_record.setShortcut(QKeySequence("Ctrl+R"))
        act_record.triggered.connect(self.video_btn.click)
        self.addAction(act_record)

        act_diag = QAction("Donanım Tanılama", self)
        act_diag.setShortcut(QKeySequence("Ctrl+D"))
        act_diag.triggered.connect(self.open_diagnostics_dialog)
        self.addAction(act_diag)

        act_quit = QAction("Çıkış", self)
        act_quit.setShortcut(QKeySequence.StandardKey.Quit)
        act_quit.triggered.connect(self.close)
        self.addAction(act_quit)

    def current_frame_settings(self) -> FrameSettings:
        return FrameSettings(
            brightness=self.brightness_slider.value(),
            contrast=self.contrast_slider.value(),
            saturation=self.saturation_slider.value(),
            mirror_horizontal=self.mirror_checkbox.isChecked(),
            flip_vertical=self.flip_checkbox.isChecked(),
        )

    def reset_adjustments(self) -> None:
        self.brightness_slider.setValue(0)
        self.contrast_slider.setValue(0)
        self.saturation_slider.setValue(0)
        self.mirror_checkbox.setChecked(False)
        self.flip_checkbox.setChecked(False)
        if self.statusBar() is not None:
            self.statusBar().showMessage("Görüntü ayarları varsayılana sıfırlandı", 3000)

    def refresh_sources(self, auto_open: bool = True) -> None:
        self.source_combo.blockSignals(True)
        self.source_combo.clear()

        devices = discover_video_devices()
        for dev in devices:
            tag = "Sanal Köprü" if dev.is_loopback else "Yerel V4L2"
            self.source_combo.addItem(f"{dev.name} ({dev.path} — {tag})", dev.path)

        self.source_combo.addItem(
            "Canlı Kalibrasyon ve Test Sinyali (Dahili)", "test://calibration"
        )
        self.source_combo.addItem(
            "Ağ / Telefon Kamerası (HTTP MJPEG / RTSP)", "net://stream"
        )

        # Default to physical camera if present, otherwise calibration signal
        phys_idx = next(
            (i for i, d in enumerate(devices) if not d.is_loopback), None
        )
        if phys_idx is not None:
            self.source_combo.setCurrentIndex(phys_idx)
        else:
            cal_idx = self.source_combo.findData("test://calibration")
            if cal_idx >= 0:
                self.source_combo.setCurrentIndex(cal_idx)

        self.source_combo.blockSignals(False)
        if auto_open:
            self._on_source_changed()

    def _release_capture(self) -> None:
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None

    def _selected_resolution(self) -> tuple[int, int]:
        data = self.resolution_combo.currentData()
        if isinstance(data, tuple) and len(data) == 2:
            return int(data[0]), int(data[1])
        return 640, 480

    def _on_source_changed(self) -> None:
        self._release_capture()
        source_data = self.source_combo.currentData()
        w, h = self._selected_resolution()

        if isinstance(source_data, str) and source_data.startswith("/dev/video"):
            cap = cv2.VideoCapture(source_data, cv2.CAP_V4L2)
            if cap.isOpened():
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
                self._cap = cap
                if self.statusBar() is not None:
                    self.statusBar().showMessage(f"Aktif kaynak: {source_data} ({w}×{h})")
                return
            cap.release()
            if self.statusBar() is not None:
                self.statusBar().showMessage(
                    f"{source_data} üzerinde aktif akış yok; canlı kalibrasyon sinyali gösteriliyor"
                )
        elif source_data == "net://stream":
            url = self.stream_url_edit.text().strip()
            if validate_stream_url(url):
                cap = cv2.VideoCapture(url)
                if cap.isOpened():
                    self._cap = cap
                    if self.statusBar() is not None:
                        self.statusBar().showMessage(f"Ağ kamerası bağlandı: {url}")
                    return
                cap.release()
            if self.statusBar() is not None:
                self.statusBar().showMessage(
                    "Geçerli bir HTTP MJPEG veya RTSP akış adresi girin"
                )
        else:
            if self.statusBar() is not None:
                self.statusBar().showMessage(
                    f"Canlı kalibrasyon sinyali aktif ({w}×{h})"
                )

    def _on_tick(self) -> None:
        w, h = self._selected_resolution()
        frame: Optional[np.ndarray] = None

        if self._cap is not None and self._cap.isOpened():
            ok, raw = self._cap.read()
            if ok and raw is not None and raw.size > 0:
                frame = cv2.resize(raw, (w, h))

        if frame is None:
            frame = generate_test_frame(
                width=w,
                height=h,
                frame_index=self._frame_index,
                label="Toshi Kamera",
            )

        self._frame_index += 1
        processed = apply_adjustments(frame, self.current_frame_settings())

        if self._countdown_remaining > 0:
            overlay = processed.copy()
            cv2.putText(
                overlay,
                str(self._countdown_remaining),
                (w // 2 - 28, h // 2 + 24),
                cv2.FONT_HERSHEY_SIMPLEX,
                2.6,
                (255, 255, 255),
                4,
                cv2.LINE_AA,
            )
            self.viewport.set_video_frame(overlay)
        else:
            self.viewport.set_video_frame(processed)

        self._last_frame = processed

        if self._video_writer is not None:
            self._video_writer.write(processed)

    def trigger_photo_capture(self) -> None:
        delay_sec = int(self.timer_combo.currentData() or 0)
        if delay_sec <= 0:
            self.capture_photo_now()
        else:
            self._countdown_remaining = delay_sec
            self._countdown_timer.start()
            if self.statusBar() is not None:
                self.statusBar().showMessage(
                    f"Fotoğraf çekimi için geri sayım: {self._countdown_remaining} sn"
                )

    def _on_countdown_tick(self) -> None:
        self._countdown_remaining -= 1
        if self._countdown_remaining <= 0:
            self._countdown_timer.stop()
            self.capture_photo_now()
        elif self.statusBar() is not None:
            self.statusBar().showMessage(
                f"Fotoğraf çekimi için geri sayım: {self._countdown_remaining} sn"
            )

    def capture_photo_now(self) -> Optional[Path]:
        if self._last_frame is None:
            self._on_tick()
        if self._last_frame is None:
            return None
        saved = self.storage.save_photo(self._last_frame)
        self.refresh_gallery()
        if self.statusBar() is not None:
            self.statusBar().showMessage(f"Fotoğraf kaydedildi: {saved.name}", 4000)
        return saved

    def toggle_video_recording(self) -> None:
        if self._video_writer is not None:
            self._video_writer.release()
            self._video_writer = None
            saved = self._recording_path
            self._recording_path = None
            self.video_btn.setChecked(False)
            self.video_btn.setText("&Video Kaydet")
            self.refresh_gallery()
            if saved is not None and self.statusBar() is not None:
                self.statusBar().showMessage(
                    f"Video kaydı tamamlandı: {saved.name}", 4000
                )
            return

        w, h = self._selected_resolution()
        out_path = self.storage.allocate_video_path(prefix="VID", ext="avi")
        fourcc = cv2.VideoWriter_fourcc(*"MJPG")
        writer = cv2.VideoWriter(str(out_path), fourcc, 25.0, (w, h))
        if not writer.isOpened():
            self.video_btn.setChecked(False)
            if self.statusBar() is not None:
                self.statusBar().showMessage("Video kaydedici başlatılamadı", 4000)
            return

        self._video_writer = writer
        self._recording_path = out_path
        self.video_btn.setChecked(True)
        self.video_btn.setText("&Kaydı Durdur")
        if self.statusBar() is not None:
            self.statusBar().showMessage(f"Video kaydediliyor: {out_path.name}")

    def toggle_virtual_bridge(self) -> None:
        if self.virtual_bridge.is_running():
            self.virtual_bridge.stop()
            self.bridge_btn.setChecked(False)
            self.bridge_btn.setText("&Sanal Köprüyü Başlat")
            if self.statusBar() is not None:
                self.statusBar().showMessage(
                    "/dev/video0 sanal kamera köprüsü durduruldu", 4000
                )
            return

        w, h = self._selected_resolution()
        url_text = self.stream_url_edit.text().strip()
        source_url = url_text if validate_stream_url(url_text) else None
        try:
            self.virtual_bridge.start(source_url=source_url, width=w, height=h, fps=30)
            self.bridge_btn.setChecked(True)
            self.bridge_btn.setText("&Sanal Köprüyü Durdur")
            mode = source_url or "Canlı Kalibrasyon Akışı"
            if self.statusBar() is not None:
                self.statusBar().showMessage(
                    f"/dev/video0 sanal kamerasına akış veriliyor ({mode})", 5000
                )
        except Exception as exc:
            self.bridge_btn.setChecked(False)
            if self.statusBar() is not None:
                self.statusBar().showMessage(f"Sanal köprü hatası: {exc}", 5000)

    def refresh_gallery(self) -> None:
        self.gallery_list.clear()
        for item in self.storage.list_media(limit=50):
            badge = "Fotoğraf" if item.kind == "photo" else "Video"
            lw_item = QListWidgetItem(f"[{badge}] {item.path.name}")
            lw_item.setData(Qt.ItemDataRole.UserRole, str(item.path))
            self.gallery_list.addItem(lw_item)

    def open_selected_media(self) -> None:
        current = self.gallery_list.currentItem()
        if current is None:
            return
        raw_path = current.data(Qt.ItemDataRole.UserRole)
        if not raw_path:
            return
        path = Path(str(raw_path))
        if path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def delete_selected_media(self) -> None:
        current = self.gallery_list.currentItem()
        if current is None:
            return
        raw_path = current.data(Qt.ItemDataRole.UserRole)
        if not raw_path:
            return
        path = Path(str(raw_path))
        ans = QMessageBox.question(
            self,
            "Dosyayı Sil",
            f"'{path.name}' dosyasını kalıcı olarak silmek istiyor musunuz?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if ans == QMessageBox.StandardButton.Yes:
            if self.storage.delete_media_file(path):
                self.refresh_gallery()
                if self.statusBar() is not None:
                    self.statusBar().showMessage(f"Silindi: {path.name}", 3000)

    def open_diagnostics_dialog(self) -> None:
        report = collect_live_hardware_report()
        dlg = DiagnosticsDialog(report, self)
        dlg.exec()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self._frame_timer.stop()
        self._countdown_timer.stop()
        if self._video_writer is not None:
            self._video_writer.release()
            self._video_writer = None
        self._release_capture()
        self.virtual_bridge.stop()
        super().closeEvent(event)
