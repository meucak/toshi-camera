# Toshi Kamera (`toshi-camera`)

Toshiba Satellite L735 (Debian 13 LXQt) için **Apple HIG** ve **Qt/QWidgets Mimari Anayasası** standartlarına uygun olarak geliştirilmiş masaüstü kamera stüdyosu, sanal kamera köprüsü (`v4l2loopback`) ve donanım tanılama uygulaması.

## Özellikler

- **Uygulamasız Telefon Kamerası & Mikrofonu (QR Kod Köprüsü):** Aynı Wi-Fi ağındaki telefonun kamerasını ve mikrofonunu hiçbir telefon uygulaması kurmadan QR kod okutup tarayıcıdan (`HTTPS + WSS`) bağlar; görüntüyü `/dev/video0` (`Toshi Virtual Camera`), sesi ise PulseAudio `Toshi_Virtual_Mic` (`toshi_virtual_mic`) sanal mikrofonuna aktarır.
- **Yatay / Dikey (Portrait / Landscape) & Döndürme:** Hem telefon web arayüzünde hem de masaüstü stüdyosunda `Yatay`/`Dikey` çözünürlük ön ayarları ve `0° / 90° / 180° / 270°` döndürme kontrolleri sunar.
- **Canlı Kamera & Kalibrasyon Stüdyosu:** Takılı V4L2/UVC kameralardan (`/dev/video*`), QR telefon kamerasından, ağ/IP kamera akışlarından (`HTTP MJPEG`, `RTSP`, `UDP`) veya dahili 60 FPS kalibrasyon deseninden gerçek zamanlı görüntüleme.
- **Gerçek Zamanlı Görüntü İşleme:** Parlaklık (`-100..+100`), Kontrast (`0.5x..2.5x`), Doygunluk (`0.0x..2.5x`), Döndürme, Yatay Ayna ve Dikey Çevirme kontrolleri.
- **Fotoğraf (PNG) & Sesli Video (MP4/AVI) Kaydı:** Tüm kayıtlar `~/Kamera` dizininde saklanır; uygulama içi galeri önizleme, tek tıkla **Klasörü Aç** butonu, onaylı silme ve terminalden `kamera --saves` ile doğrudan kayıt klasörüne geçiş desteği sunar.
- **Sanal Kamera & Mikrofon Köprüsü (`v4l2loopback` + `PulseAudio`):** QR telefon kamerasını ve mikrofonunu tarayıcı (WebRTC), Zoom, OBS vb. tüm Linux uygulamalarında gerçek kamera ve mikrofon olarak kullanılabilir hale getirir.
- **ACPI & USB Donanım Tanılama:** Toshiba Satellite L735 dahili kamera hattını (`\CCDE` ACPI NVS bayrağı ve EHCI USB 2.0 hub portlarını) denetleyerek donanım durumunu raporlar.

## Kurulum ve Çalıştırma

### Gereksinimler (Debian / Ubuntu)
```bash
sudo apt install python3-pyqt6 python3-opencv python3-numpy python3-websockets pulseaudio-utils openssl ffmpeg v4l-utils v4l2loopback-dkms
```

### Çalıştırma
Terminalden doğrudan:
```bash
kamera
```
Kayıt klasörünü (`~/Kamera`) grafik dosya yöneticisinde açmak için:
```bash
kamera --saves
```
veya proje dizininden:
```bash
PYTHONPATH=src python3 -m toshi_camera.main
```

### Testleri Çalıştırma
```bash
PYTHONPATH=src pytest -v
```
