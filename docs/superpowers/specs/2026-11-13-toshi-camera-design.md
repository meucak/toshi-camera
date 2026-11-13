# Toshi Kamera (Toshi Camera Studio & Hardware Diagnostics) — Design Specification

## 1. Intent and Why
Toshi (Toshiba Satellite L735, Debian 13 LXQt) dahili kamerasının neden çalışmadığını teşhis etmek, sanal/ağ/USB kamera kaynaklarıyla kesintisiz çalışan yerel bir masaüstü kamera uygulaması sunmak ve donanım tanılama + `v4l2loopback` sanal kamera köprüsünü tek bir yerel arayüzde birleştirmek.

### Kök Neden Özeti (Toshiba Satellite L735)
- Anakart ACPI NVS (`OGNS` @ `0xAF7BCC18`) tablosunda `\WLA1 = 0x1` (Wi-Fi), `\CBT1 = 0x1` (Bluetooth `2-1.6`) ve `\ENSR = 0x2` (3D sensör) POST sırasında algılanırken `\CCDE = 0x0` (CCD Camera) olarak raporlanmaktadır.
- Toshiba WMI SMM metodları (`\_SB.QWMI.RS14`, `RS17`, `RS18`, `RS19` -> `OSMI`) tetiklense dahi iç USB hub portlarında (`8087:0024` port `1-1.4`, `1-1.5`, `2-1.3`, `2-1.4`) tüm 5V port güçleri açık (`Port Status: 0000.0100 power`) olmasına rağmen veri hatlarında (`D+`/`D-`) pull-up direnci görülmemektedir (`state: not attached`).
- Bu durum dahili kamera modülünün veya ekran menteşesinden geçen LVDS/USB kamera kablosunun fiziksel olarak çıkık/kopuk veya modülün arızalı olduğunu kanıtlamaktadır.

## 2. Goals, Non-Goals, and Anti-Goals
- **Goals:**
  1. **Çoklu Kamera Kaynağı Desteği:** Yerel V4L2 kameralar (`/dev/video*`), Ağ/IP/Telefon kamerası akışları (`HTTP MJPEG`, `RTSP`, `UDP`) ve yerleşik Canlı Test/Kalibrasyon Sinyali (hareketli SMPTE + zaman damgası + FPS).
  2. **`v4l2loopback` Sanal Kamera Köprüsü (`/dev/video0`):** Ağ kamerası veya test kaynağını `/dev/video0` (`Toshi Virtual Camera`) düğümüne besleyerek Firefox, Discord, Google Meet gibi üçüncü parti uygulamaların da Toshi'de kamera kullanabilmesini sağlamak.
  3. **Tam Donanımlı Fotoğraf & Video Çekimi:** Çözünürlük/FPS seçimi, 3s/5s/10s geri sayım sayacı, yatay/dikey ayna (mirror/flip), parlaklık/kontrast/doygunluk/pozlama ayarı, fotoğraf (`~/Resimler/Kamera`) ve MP4/AVI video (`~/Videolar/Kamera`) kaydı, uygulama içi galeri şeridi.
  4. **Canlı Donanım Tanılama Diyaloğu:** ACPI `\CCDE` durumu, USB hub iç portları, `v4l2loopback` çekirdek modülü ve `/dev/video*` düğümlerini canlı denetleyen ve raporlayan tanılama aracı.
  5. **Apple HIG (Kural 2) & Qt/QWidgets Mimari Anayasası (Kural 5):**
     - Sıfır hardcoded renk (`#hex` / `rgb()` yasak; yalnızca `QPalette` sistem rolleri).
     - Sıfır `setGeometry` / sabit piksel boyutlandırma (`QVBoxLayout`, `QHBoxLayout`, `QGridLayout`, `QFormLayout`, `QSplitter`, `QSizePolicy`).
     - Standart diyaloglarda `QDialogButtonBox`, tüm buton ve etiketlerde çakışmasız mnemonics (`&Fotoğraf Çek`, `&Video Kaydet`, `setBuddy()`), `setTabOrder()`, `QKeySequence` kısayolları.
     - Title Case butonlar, Sentence case form etiketleri (sonunda iki nokta üst üste olmadan), `QIcon.fromTheme()` freedesktop ikonları.
- **Non-Goals:** Bulut senkronizasyonu, yüz tanıma/AI filtreleri.
- **Anti-Goals:** Jenerik AI karanlık tema klişeleri (`blur-3xl`, mor/indigo radyal efektler), hardcoded CSS renkleri, mutlak piksel koordinatları.

## 3. Approaches Considered
1. **Yaklaşım A (Seçilen): PyQt6 (`QWidgets`) + OpenCV/NumPy + `v4l2loopback` + FFmpeg Köprüsü**
   - Yerel LXQt masaüstüyle %100 `QPalette`/`QStyle` uyumu, düşük bellek tüketimi, doğrudan V4L2/RTSP/MJPEG okuma ve `v4l2loopback` besleme yeteneği.
2. **Yaklaşım B: Web Tabanlı (Docker) Kamera Uygulaması**
   - Kural 2/5 masaüstü entegrasyonu ve düşük gecikmeli `/dev/video*` donanım erişimi açısından yerel masaüstü uygulaması kadar doğrudan değil.
3. **Yaklaşım C: Salt GStreamer CLI Sarmalayıcı**
   - Görüntü işleme kontrolleri (parlaklık, kontrast, doygunluk, ayna, test sinyali) ve galeri yönetimi kısıtlı.

## 4. Architecture & Modules
- `src/toshi_camera/diagnostics.py`: Toshi USB hub, V4L2 cihaz listesi, `v4l2loopback` durumu ve ACPI `\CCDE` durumunu sorgulayan saf (test edilebilir) tanılama modülü.
- `src/toshi_camera/processing.py`: Görüntü kareleri (NumPy `ndarray`) üzerinde parlaklık, kontrast, doygunluk, yatay/dikey çevirme (mirror/flip) ve canlı kalibrasyon/test karesi üretimi yapan modül.
- `src/toshi_camera/storage.py`: Fotoğraf (`.png`/`.jpg`) ve video (`.mp4`/`.avi`) dosya adlandırma, kaydetme, galeri listeleme ve güvenli silme işlemlerini yöneten modül.
- `src/toshi_camera/virtual_cam.py`: Seçili akışı veya test sinyalini FFmpeg / V4L2 üzerinden `/dev/video0` (`v4l2loopback`) sanal kamerasına aktaran yönetici.
- `src/toshi_camera/ui.py`: Kural 2 ve Kural 5'e tam uyumlu PyQt6 `QMainWindow`, `DiagnosticsDialog` ve `NetworkStreamDialog` sınıfları.
