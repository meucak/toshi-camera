# Telefon Kamerası QR Köprüsü (Uygulamasız LAN WebRTC/WSS Akışı) — Tasarım Spesifikasyonu

## 1. Amaç
Toshiba Satellite L735 (`Toshi`) üzerinde dahili kamera donanımının bulunmaması nedeniyle, kullanıcının aynı yerel ağdaki (Wi-Fi LAN) telefonunun kamerasını **telefona hiçbir uygulama kurmadan**, yalnızca `toshi-camera` içinden taranan bir **QR kod** aracılığıyla PC kamerası gibi (`/dev/video0` — `Toshi Virtual Camera` + uygulama içi stüdyo) kullanabilmesini sağlamak.

## 2. Mimari Tasarım
- **Tek Port HTTPS + WSS Sunucusu (`src/toshi_camera/phone_bridge.py`):**
  - Mobil tarayıcılarda `navigator.mediaDevices.getUserMedia` API'si güvenli bağlam (HTTPS) gerektirdiği için `openssl` ile yerel IP SAN'larını (`192.168.x.x` vb. + `localhost`) içeren kendinden imzalı TLS sertifikası `~/.config/toshi-camera/certs/` dizininde otomatik üretilir ve önbelleklenir.
  - `websockets.asyncio.server.serve` kullanılarak **aynı port** (varsayılan `8443`, doluysa otomatik boş port) üzerinden hem HTTP (`GET /?t=<token>`) hem de WebSocket (`WSS /ws?t=<token>`) sunulur. Böylece telefonda HTTPS sertifika uyarısı tek sefer onaylandığında WebSocket bağlantısı da kesintisiz çalışır.
  - Oturum başına rastgele URL-safe token (`secrets.token_urlsafe(16)`) ile aynı ağdaki yetkisiz erişimler `403` ile engellenir.
  - Telefondaki tarayıcı (Android Chrome/Firefox, iOS Safari) kamera karelerini `<canvas>` üzerinden JPEG (`0.82` kalite, `bufferedAmount` geri basınç kontrollü) olarak ikili (binary) WebSocket mesajlarıyla gönderir; sunucu `cv2.imdecode` ile BGR `np.ndarray` kareye dönüştürüp iş parçacığı güvenli (`threading.Lock`) tamponda tutar.
- **QR Kod Üretimi (`generate_qr_image`):**
  - Harici Python bağımlılığı gerektirmeden OpenCV `cv2.QRCodeEncoder` ile piksel keskinliğinde (`INTER_NEAREST`) QR kod görseli üretilir.
- **Canlı Kare Boru Hattı ile Sanal Kamera Köprüsü (`src/toshi_camera/virtual_cam.py`):**
  - Mevcut `VirtualCamBridge.start(source_url=...)` arayüzü korunur; ek olarak `start_pipe(width, height, fps)` ve `push_frame(frame)` eklenir.
  - `ffmpeg` `-f rawvideo -pix_fmt bgr24 -s WxH -r FPS -i pipe:0 -pix_fmt yuv420p -f v4l2 /dev/video0` komutuyla işlenmiş kareleri (ayna, çevirme, parlaklık/kontrast/doygunluk dahil) arka plan besleyici iş parçacığı üzerinden sabit FPS'te `/dev/video0` aygıtına basar.
- **PyQt6 Arayüz Entegrasyonu (`src/toshi_camera/ui.py`):**
  - Kural 2 (Apple HIG) ve Kural 5 (Qt/QWidgets Anayasası: sıfır hardcoded `#hex`/`rgb()`, sıfır `setGeometry`, `QDialogButtonBox`, benzersiz `&` mnemonic, `setBuddy`, `QIcon.fromTheme`) tam uygulanır.
  - Ana pencerede `"Telefon Kamerası (QR Kod)"` (`phone://qr`) kaynağı, `"&Telefon Bağla (QR)"` butonu ve `Ctrl+T` kısayolu eklenir.
  - `PhoneConnectDialog` içinde: QR kod önizlemesi, yerel ağ arayüzü/IP seçici, kopyalanabilir bağlantı adresi, canlı bağlantı/FPS durumu, `"Telefon bağlanınca /dev/video0 sanal kamerasını otomatik başlat"` onay kutusu (varsayılan açık) ve kısa HTTPS onay rehberi yer alır.

## 3. Kapsam Dışı
- İnternet üzerinden (WAN/NAT aşımı) akış veya bulut sunucusu kullanımı.
- Telefona özel APK/iOS uygulaması geliştirme.
