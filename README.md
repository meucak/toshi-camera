# Toshi Kamera (`toshi-camera`)

Toshiba Satellite L735 (Debian 13 LXQt) için **Apple HIG** ve **Qt/QWidgets Mimari Anayasası** standartlarına uygun olarak geliştirilmiş masaüstü kamera stüdyosu, sanal kamera köprüsü (`v4l2loopback`) ve donanım tanılama uygulaması.

## Özellikler

- **Canlı Kamera & Kalibrasyon Stüdyosu:** Takılı V4L2/UVC kameralardan (`/dev/video*`), ağ/IP kamera akışlarından (`HTTP MJPEG`, `RTSP`, `UDP`) veya dahili 60 FPS kalibrasyon deseninden gerçek zamanlı görüntüleme.
- **Gerçek Zamanlı Görüntü İşleme:** Parlaklık (`-100..+100`), Kontrast (`0.5x..2.5x`), Doygunluk (`0.0x..2.5x`), Yatay Ayna ve Dikey Çevirme kontrolleri.
- **Fotoğraf (PNG) & Video (MP4) Kaydı:** `~/Pictures/ToshiCamera` ve `~/Videos/ToshiCamera` dizinlerine zaman damgalı kayıt, uygulama içi galeri önizleme ve onaylı silme.
- **Sanal Kamera Köprüsü (`v4l2loopback`):** Telefon kamerası (DroidCam / IP Webcam) veya kalibrasyon akışını FFmpeg aracılığıyla `/dev/video0` (`Toshi Virtual Camera`) aygıtına aktararak tarayıcı (WebRTC), Zoom, OBS vb. tüm Linux uygulamalarında kamera olarak kullanılmasını sağlar.
- **ACPI & USB Donanım Tanılama:** Toshiba Satellite L735 dahili kamera hattını (`\CCDE` ACPI NVS bayrağı ve EHCI USB 2.0 hub portlarını) denetleyerek donanım durumunu raporlar.

## Kurulum ve Çalıştırma

### Gereksinimler (Debian / Ubuntu)
```bash
sudo apt install python3-pyqt6 python3-opencv python3-numpy ffmpeg v4l-utils v4l2loopback-dkms
```

### Çalıştırma
```bash
PYTHONPATH=src python3 -m toshi_camera.main
```

### Testleri Çalıştırma
```bash
PYTHONPATH=src pytest -v
```
