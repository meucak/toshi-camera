from __future__ import annotations

import asyncio
from collections import deque
import hmac
import ipaddress
from pathlib import Path
import re
import secrets
import socket
import ssl
import struct
import subprocess
import threading
import time
from typing import Callable, Optional
from urllib.parse import parse_qs, urlsplit

import cv2
import numpy as np
from websockets.asyncio.server import Server, ServerConnection, serve
from websockets.datastructures import Headers
from websockets.http11 import Request, Response


_INET_RE = re.compile(r"\binet\s+(\d{1,3}(?:\.\d{1,3}){3})/\d+")
_TAILSCALE_NET = ipaddress.IPv4Network("100.64.0.0/10")
AUDIO_MAGIC = b"AUD0"
TARGET_AUDIO_RATE = 44100


def encode_audio_packet(sample_rate: int, pcm_s16le: bytes) -> bytes:
    return AUDIO_MAGIC + struct.pack("<I", int(sample_rate)) + pcm_s16le


def decode_audio_packet(payload: bytes) -> Optional[tuple[int, bytes]]:
    if len(payload) < 8 or payload[:4] != AUDIO_MAGIC:
        return None
    (sample_rate,) = struct.unpack("<I", payload[4:8])
    pcm = payload[8:]
    if sample_rate < 8000 or sample_rate > 192000 or len(pcm) < 2 or (len(pcm) % 2) != 0:
        return None
    return int(sample_rate), bytes(pcm)


def resample_pcm_s16le(
    pcm_bytes: bytes, src_rate: int, dst_rate: int = TARGET_AUDIO_RATE
) -> bytes:
    if not pcm_bytes or src_rate == dst_rate or src_rate <= 0 or dst_rate <= 0:
        return pcm_bytes
    samples = np.frombuffer(pcm_bytes, dtype="<i2")
    if samples.size < 2:
        return pcm_bytes
    dst_len = max(1, int(round(samples.size * (dst_rate / float(src_rate)))))
    x_old = np.linspace(0.0, 1.0, num=samples.size, endpoint=False)
    x_new = np.linspace(0.0, 1.0, num=dst_len, endpoint=False)
    interp = np.interp(x_new, x_old, samples.astype(np.float32))
    clipped = np.clip(np.rint(interp), -32768, 32767).astype("<i2")
    return clipped.tobytes()


def _ip_sort_key(ip: str) -> tuple[int, str]:
    addr = ipaddress.IPv4Address(ip)
    if ip.startswith("192.168."):
        return (0, ip)
    if ip.startswith("10."):
        return (1, ip)
    if addr.is_private and addr not in _TAILSCALE_NET:
        return (2, ip)
    if addr in _TAILSCALE_NET:
        return (4, ip)
    return (3, ip)


def parse_ipv4_from_ip_addr_output(output: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for match in _INET_RE.finditer(output or ""):
        ip = match.group(1)
        try:
            addr = ipaddress.IPv4Address(ip)
        except ipaddress.AddressValueError:
            continue
        if addr.is_loopback or addr.is_link_local or addr.is_unspecified:
            continue
        if ip not in seen:
            seen.add(ip)
            found.append(ip)
    found.sort(key=_ip_sort_key)
    return found


def discover_lan_ips() -> list[str]:
    ips: list[str] = []
    try:
        res = subprocess.run(
            ["ip", "-4", "-o", "addr", "show"],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
        if res.returncode == 0:
            ips = parse_ipv4_from_ip_addr_output(res.stdout)
    except Exception:
        ips = []

    if not ips:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("192.168.1.1", 80))
                local_ip = s.getsockname()[0]
                if local_ip and not local_ip.startswith("127."):
                    ips = [local_ip]
        except OSError:
            pass

    return ips or ["127.0.0.1"]


def ensure_self_signed_cert(cert_dir: Path, ips: list[str]) -> tuple[Path, Path]:
    cert_dir.mkdir(parents=True, exist_ok=True)
    cert_path = cert_dir / "cert.pem"
    key_path = cert_dir / "key.pem"
    marker_path = cert_dir / ".san_ips"

    clean_ips = sorted({ip.strip() for ip in ips if ip.strip()})
    marker_val = ",".join(clean_ips)

    if (
        cert_path.exists()
        and key_path.exists()
        and marker_path.exists()
        and marker_path.read_text(encoding="utf-8", errors="ignore").strip() == marker_val
    ):
        return cert_path, key_path

    san_entries = ["DNS:localhost", "IP:127.0.0.1"]
    for ip in clean_ips:
        if ip != "127.0.0.1":
            san_entries.append(f"IP:{ip}")
    san_ext = f"subjectAltName={','.join(san_entries)}"

    cmd = [
        "openssl",
        "req",
        "-x509",
        "-newkey",
        "rsa:2048",
        "-nodes",
        "-sha256",
        "-days",
        "365",
        "-keyout",
        str(key_path),
        "-out",
        str(cert_path),
        "-subj",
        "/CN=Toshi Kamera",
        "-addext",
        san_ext,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=15.0, check=False)
    if res.returncode != 0 or not cert_path.exists() or not key_path.exists():
        raise RuntimeError(f"TLS sertifikası oluşturulamadı: {res.stderr.strip()}")

    marker_path.write_text(marker_val, encoding="utf-8")
    return cert_path, key_path


def generate_qr_image(url: str, scale: int = 8, border: int = 4) -> np.ndarray:
    encoder = cv2.QRCodeEncoder.create()
    matrix = encoder.encode(url)
    if border > 0:
        matrix = cv2.copyMakeBorder(
            matrix,
            border,
            border,
            border,
            border,
            cv2.BORDER_CONSTANT,
            value=255,
        )
    if scale > 1:
        h, w = matrix.shape[:2]
        matrix = cv2.resize(
            matrix, (w * scale, h * scale), interpolation=cv2.INTER_NEAREST
        )
    return matrix


def build_mobile_page_html() -> str:
    return """<!DOCTYPE html>
<html lang="tr">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no" />
  <title>Toshi Kamera — Telefon Köprüsü</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #0c0d10;
      --surface: rgba(24, 26, 32, 0.86);
      --border: rgba(255, 255, 255, 0.14);
      --text: #f4f5f7;
      --muted: #a1a7b3;
      --accent: #0a84ff;
      --ok: #30d158;
      --warn: #ff9f0a;
      --err: #ff453a;
    }
    * { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
    html, body {
      margin: 0; padding: 0; width: 100%; height: 100%;
      background: var(--bg); color: var(--text);
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      overflow: hidden;
    }
    .app {
      position: relative; width: 100%; height: 100%;
      display: flex; flex-direction: column; justify-content: space-between;
    }
    video {
      position: absolute; inset: 0; width: 100%; height: 100%;
      object-fit: cover; background: #000;
    }
    .topbar, .bottombar {
      position: relative; z-index: 2;
      margin: 12px; padding: 12px 14px;
      background: var(--surface);
      backdrop-filter: blur(14px); -webkit-backdrop-filter: blur(14px);
      border: 1px solid var(--border); border-radius: 16px;
    }
    .topbar {
      display: flex; align-items: center; justify-content: space-between; gap: 10px;
    }
    .status {
      display: flex; align-items: center; gap: 8px; font-size: 14px; font-weight: 600;
    }
    .dot {
      width: 10px; height: 10px; border-radius: 50%; background: var(--warn);
      flex-shrink: 0;
    }
    .dot.ok { background: var(--ok); }
    .dot.err { background: var(--err); }
    .metrics { font-size: 13px; color: var(--muted); font-variant-numeric: tabular-nums; }
    .controls {
      display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px;
    }
    button, select {
      min-height: 46px; border-radius: 12px; border: 1px solid var(--border);
      background: rgba(255, 255, 255, 0.08); color: var(--text);
      font-size: 15px; font-weight: 600; padding: 0 12px; cursor: pointer;
    }
    button.primary { background: var(--accent); border-color: transparent; }
    button:disabled { opacity: 0.45; cursor: not-allowed; }
    .banner {
      position: relative; z-index: 3; margin: 0 12px; padding: 12px 14px;
      background: rgba(255, 69, 58, 0.92); color: #fff;
      border-radius: 12px; font-size: 14px; display: none;
    }
  </style>
</head>
<body>
  <div class="app">
    <video id="preview" autoplay playsinline muted></video>
    <div class="topbar">
      <div class="status">
        <span class="dot" id="dot"></span>
        <span id="statusText">Kamera başlatılıyor…</span>
      </div>
      <div class="metrics" id="metrics">0 FPS</div>
    </div>
    <div class="banner" id="errorBanner"></div>
    <div class="bottombar">
      <div class="controls">
        <button id="switchBtn" type="button">Ön / Arka Kamera</button>
        <button id="pauseBtn" type="button" class="primary">Yayını Duraklat</button>
        <button id="micBtn" type="button">Mikrofon Açık</button>
        <button id="torchBtn" type="button" disabled>Flaş Kapalı</button>
        <select id="resSelect" aria-label="Çözünürlük">
          <option value="640x480">640 × 480 (Hızlı)</option>
          <option value="1280x720" selected>1280 × 720 (HD)</option>
        </select>
        <select id="orientationSelect" aria-label="Yön">
          <option value="auto" selected>Yön: Otomatik</option>
          <option value="landscape">Yön: Yatay (Landscape)</option>
          <option value="portrait">Yön: Dikey (Portrait)</option>
        </select>
      </div>
    </div>
  </div>
  <canvas id="capCanvas" style="display:none;"></canvas>

  <script>
    (() => {
      const params = new URLSearchParams(window.location.search);
      const token = params.get("t") || "";
      const videoEl = document.getElementById("preview");
      const canvas = document.getElementById("capCanvas");
      const ctx = canvas.getContext("2d");
      const dot = document.getElementById("dot");
      const statusText = document.getElementById("statusText");
      const metricsEl = document.getElementById("metrics");
      const errorBanner = document.getElementById("errorBanner");
      const switchBtn = document.getElementById("switchBtn");
      const pauseBtn = document.getElementById("pauseBtn");
      const micBtn = document.getElementById("micBtn");
      const resSelect = document.getElementById("resSelect");
      const orientationSelect = document.getElementById("orientationSelect");
      const torchBtn = document.getElementById("torchBtn");

      let facingMode = "environment";
      let paused = false;
      let micEnabled = true;
      let stream = null;
      let audioCtx = null;
      let audioProc = null;
      let audioSource = null;
      let ws = null;
      let encoding = false;
      let sentFrames = 0;
      let fpsWindowStart = performance.now();
      let torchOn = false;
      let reconnectTimer = null;

      function setStatus(text, state) {
        statusText.textContent = text;
        dot.className = "dot" + (state ? " " + state : "");
      }

      function showError(msg) {
        errorBanner.textContent = msg;
        errorBanner.style.display = "block";
      }

      function hideError() {
        errorBanner.style.display = "none";
      }

      function parseRes() {
        const [rawW, rawH] = resSelect.value.split("x").map(Number);
        const w = rawW || 640;
        const h = rawH || 480;
        const orient = orientationSelect.value;
        if (orient === "portrait") {
          return { w: Math.min(w, h), h: Math.max(w, h) };
        }
        if (orient === "landscape") {
          return { w: Math.max(w, h), h: Math.min(w, h) };
        }
        return { w, h };
      }

      function stopAudioPipeline() {
        if (audioProc) {
          try { audioProc.disconnect(); } catch (_) {}
          audioProc.onaudioprocess = null;
          audioProc = null;
        }
        if (audioSource) {
          try { audioSource.disconnect(); } catch (_) {}
          audioSource = null;
        }
      }

      function setupAudioPipeline(mediaStream) {
        stopAudioPipeline();
        const audioTracks = mediaStream.getAudioTracks();
        if (!audioTracks || audioTracks.length === 0) {
          micEnabled = false;
          micBtn.textContent = "Mikrofon Yok";
          micBtn.disabled = true;
          return;
        }
        micBtn.disabled = false;
        const AudioCtx = window.AudioContext || window.webkitAudioContext;
        if (!AudioCtx) {
          micBtn.disabled = true;
          return;
        }
        if (!audioCtx) {
          audioCtx = new AudioCtx();
        }
        if (audioCtx.state === "suspended") {
          audioCtx.resume().catch(() => {});
        }
        audioSource = audioCtx.createMediaStreamSource(new MediaStream(audioTracks));
        audioProc = audioCtx.createScriptProcessor(2048, 1, 1);
        const silentGain = audioCtx.createGain();
        silentGain.gain.value = 0;

        audioProc.onaudioprocess = (ev) => {
          if (paused || !micEnabled || !ws || ws.readyState !== WebSocket.OPEN) {
            return;
          }
          if (ws.bufferedAmount > 262144) {
            return;
          }
          const input = ev.inputBuffer.getChannelData(0);
          const out = new ArrayBuffer(8 + input.length * 2);
          const view = new DataView(out);
          view.setUint8(0, 65); // 'A'
          view.setUint8(1, 85); // 'U'
          view.setUint8(2, 68); // 'D'
          view.setUint8(3, 48); // '0'
          view.setUint32(4, audioCtx.sampleRate || 44100, true);
          for (let i = 0; i < input.length; i++) {
            const s = Math.max(-1, Math.min(1, input[i]));
            view.setInt16(8 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
          }
          ws.send(out);
        };

        audioSource.connect(audioProc);
        audioProc.connect(silentGain);
        silentGain.connect(audioCtx.destination);
      }

      async function startCamera() {
        hideError();
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
          setStatus("Güvenli bağlam (HTTPS) gerekli", "err");
          showError("Tarayıcı kamera API'sine erişemedi. HTTPS sertifika uyarısını onayladığınızdan emin olun.");
          return;
        }
        stopAudioPipeline();
        if (stream) {
          stream.getTracks().forEach(t => t.stop());
          stream = null;
        }
        const { w, h } = parseRes();
        const videoConstraints = {
          facingMode: { ideal: facingMode },
          width: { ideal: w },
          height: { ideal: h },
          frameRate: { ideal: 30, max: 30 }
        };
        try {
          try {
            stream = await navigator.mediaDevices.getUserMedia({
              audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
              video: videoConstraints
            });
          } catch (_) {
            stream = await navigator.mediaDevices.getUserMedia({
              audio: false,
              video: videoConstraints
            });
          }
          videoEl.srcObject = stream;
          await videoEl.play();
          setupAudioPipeline(stream);
          torchOn = false;
          const track = stream.getVideoTracks()[0];
          const caps = track && track.getCapabilities ? track.getCapabilities() : {};
          torchBtn.disabled = !caps.torch;
          torchBtn.textContent = "Flaş Kapalı";
          connectWs();
        } catch (err) {
          setStatus("Kamera izni alınamadı", "err");
          showError("Kamera başlatılamadı: " + (err && err.message ? err.message : err));
        }
      }

      function connectWs() {
        if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
          return;
        }
        const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
        const wsUrl = proto + "//" + window.location.host + "/ws?t=" + encodeURIComponent(token);
        setStatus("Toshi'ye bağlanılıyor…", "");
        ws = new WebSocket(wsUrl);
        ws.binaryType = "arraybuffer";

        ws.onopen = () => {
          setStatus(paused ? "Duraklatıldı" : "Canlı Yayın Aktif", paused ? "" : "ok");
        };
        ws.onclose = () => {
          setStatus("Bağlantı kesildi, yeniden deneniyor…", "err");
          clearTimeout(reconnectTimer);
          reconnectTimer = setTimeout(connectWs, 1500);
        };
        ws.onerror = () => {
          setStatus("WebSocket bağlantı hatası", "err");
        };
      }

      function tickFrame() {
        const now = performance.now();
        if (
          !paused &&
          !encoding &&
          stream &&
          videoEl.readyState >= 2 &&
          ws &&
          ws.readyState === WebSocket.OPEN &&
          ws.bufferedAmount < 262144
        ) {
          const vw = videoEl.videoWidth || 640;
          const vh = videoEl.videoHeight || 480;
          const { w: maxW, h: maxH } = parseRes();
          const scale = Math.min(1, maxW / vw, maxH / vh);
          const cw = Math.max(2, Math.round(vw * scale));
          const ch = Math.max(2, Math.round(vh * scale));
          if (canvas.width !== cw || canvas.height !== ch) {
            canvas.width = cw;
            canvas.height = ch;
          }
          ctx.drawImage(videoEl, 0, 0, cw, ch);
          encoding = true;
          canvas.toBlob((blob) => {
            encoding = false;
            if (blob && ws && ws.readyState === WebSocket.OPEN && !paused) {
              ws.send(blob);
              sentFrames += 1;
            }
          }, "image/jpeg", 0.80);
        }

        if (now - fpsWindowStart >= 1000) {
          const fps = (sentFrames * 1000) / (now - fpsWindowStart);
          const cw = canvas.width || 0;
          const ch = canvas.height || 0;
          metricsEl.textContent = fps.toFixed(1) + " FPS" + (cw ? " • " + cw + "×" + ch : "");
          sentFrames = 0;
          fpsWindowStart = now;
        }
        setTimeout(tickFrame, 33);
      }

      switchBtn.addEventListener("click", () => {
        facingMode = facingMode === "environment" ? "user" : "environment";
        startCamera();
      });

      pauseBtn.addEventListener("click", () => {
        paused = !paused;
        pauseBtn.textContent = paused ? "Yayını Sürdür" : "Yayını Duraklat";
        if (ws && ws.readyState === WebSocket.OPEN) {
          setStatus(paused ? "Duraklatıldı" : "Canlı Yayın Aktif", paused ? "" : "ok");
        }
      });

      resSelect.addEventListener("change", () => {
        startCamera();
      });

      orientationSelect.addEventListener("change", () => {
        startCamera();
      });

      micBtn.addEventListener("click", () => {
        if (audioCtx && audioCtx.state === "suspended") {
          audioCtx.resume().catch(() => {});
        }
        micEnabled = !micEnabled;
        micBtn.textContent = micEnabled ? "Mikrofon Açık" : "Mikrofon Kapalı";
      });

      torchBtn.addEventListener("click", async () => {
        if (!stream) return;
        const track = stream.getVideoTracks()[0];
        if (!track || !track.applyConstraints) return;
        torchOn = !torchOn;
        try {
          await track.applyConstraints({ advanced: [{ torch: torchOn }] });
          torchBtn.textContent = torchOn ? "Flaş Açık" : "Flaş Kapalı";
        } catch (_) {
          torchOn = false;
          torchBtn.disabled = true;
        }
      });

      startCamera();
      tickFrame();
    })();
  </script>
</body>
</html>
"""


class PhoneBridgeServer:
    """Single-port HTTPS + WSS server streaming phone camera frames to OpenCV."""

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8443,
        cert_dir: Optional[Path] = None,
        cert_ips: Optional[list[str]] = None,
    ) -> None:
        self.host = host
        self.requested_port = port
        self.cert_dir = cert_dir or (Path.home() / ".config" / "toshi-camera" / "certs")
        self._cert_ips = cert_ips
        self.token = secrets.token_urlsafe(16)

        self._lock = threading.Lock()
        self._latest_frame: Optional[np.ndarray] = None
        self._frame_seq: int = 0
        self._frame_times: deque[float] = deque(maxlen=60)
        self._audio_chunks: deque[bytes] = deque(maxlen=120)
        self._audio_callback: Optional[Callable[[bytes], None]] = None
        self._last_audio_time: float = 0.0
        self._audio_level: float = 0.0
        self._active_clients: int = 0
        self._client_addr: Optional[str] = None

        self._bound_port: int = 0
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._stop_event_async: Optional[asyncio.Event] = None
        self._ready_event = threading.Event()
        self._start_error: Optional[BaseException] = None
        self._running = False
        self._html_bytes = build_mobile_page_html().encode("utf-8")

    @property
    def port(self) -> int:
        return self._bound_port

    def is_running(self) -> bool:
        return self._running and self._thread is not None and self._thread.is_alive()

    def build_url(self, ip: str) -> str:
        return f"https://{ip}:{self._bound_port}/?t={self.token}"

    def regenerate_token(self) -> str:
        with self._lock:
            self.token = secrets.token_urlsafe(16)
            return self.token

    def get_latest_frame(self) -> Optional[tuple[np.ndarray, int]]:
        with self._lock:
            if self._latest_frame is None:
                return None
            return self._latest_frame.copy(), self._frame_seq

    def set_audio_callback(self, cb: Optional[Callable[[bytes], None]]) -> None:
        with self._lock:
            self._audio_callback = cb

    def pop_audio_chunks(self) -> list[bytes]:
        with self._lock:
            chunks = list(self._audio_chunks)
            self._audio_chunks.clear()
            return chunks

    def is_audio_active(self) -> bool:
        now = time.monotonic()
        with self._lock:
            return self._last_audio_time > 0.0 and (now - self._last_audio_time) <= 2.0

    def audio_level(self) -> float:
        if not self.is_audio_active():
            return 0.0
        with self._lock:
            return self._audio_level

    def is_client_connected(self) -> bool:
        with self._lock:
            return self._active_clients > 0

    def client_info(self) -> Optional[str]:
        with self._lock:
            if self._active_clients <= 0:
                return None
            return self._client_addr

    def current_fps(self) -> float:
        now = time.monotonic()
        with self._lock:
            recent = [t for t in self._frame_times if now - t <= 2.0]
        if len(recent) < 2:
            return 0.0
        span = recent[-1] - recent[0]
        if span <= 0:
            return 0.0
        return (len(recent) - 1) / span

    def start(self) -> None:
        if self.is_running():
            return
        ips = self._cert_ips if self._cert_ips is not None else discover_lan_ips()
        cert_path, key_path = ensure_self_signed_cert(self.cert_dir, ips)

        ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ssl_ctx.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))

        self._ready_event.clear()
        self._start_error = None
        self._thread = threading.Thread(
            target=self._run_loop, args=(ssl_ctx,), daemon=True
        )
        self._thread.start()
        self._ready_event.wait(timeout=5.0)
        if self._start_error is not None:
            raise RuntimeError(f"Telefon köprüsü başlatılamadı: {self._start_error}")
        if not self._running:
            raise RuntimeError("Telefon köprüsü zaman aşımına uğradı")

    def stop(self) -> None:
        loop = self._loop
        stop_ev = self._stop_event_async
        if loop is not None and stop_ev is not None and not loop.is_closed():
            loop.call_soon_threadsafe(stop_ev.set)
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            self._thread = None
        self._running = False
        with self._lock:
            self._active_clients = 0
            self._client_addr = None

    def _token_valid(self, query: str) -> bool:
        params = parse_qs(query, keep_blank_values=False)
        supplied = params.get("t", [""])[0]
        with self._lock:
            expected = self.token
        return bool(supplied) and hmac.compare_digest(supplied, expected)

    def _process_request(
        self, connection: ServerConnection, request: Request
    ) -> Optional[Response]:
        parsed = urlsplit(request.path)
        if parsed.path in ("/", "/index.html"):
            if not self._token_valid(parsed.query):
                return Response(
                    403,
                    "Forbidden",
                    Headers([("Content-Type", "text/plain; charset=utf-8")]),
                    "Yetkisiz erisim: gecersiz oturum anahtari.".encode("utf-8"),
                )
            return Response(
                200,
                "OK",
                Headers(
                    [
                        ("Content-Type", "text/html; charset=utf-8"),
                        ("Cache-Control", "no-store"),
                    ]
                ),
                self._html_bytes,
            )

        if parsed.path == "/ws":
            if not self._token_valid(parsed.query):
                return Response(
                    403,
                    "Forbidden",
                    Headers([("Content-Type", "text/plain; charset=utf-8")]),
                    b"Unauthorized WebSocket token",
                )
            return None

        return Response(
            404,
            "Not Found",
            Headers([("Content-Type", "text/plain; charset=utf-8")]),
            b"Not Found",
        )

    async def _ws_handler(self, ws: ServerConnection) -> None:
        remote = ws.remote_address
        addr_str = f"{remote[0]}" if isinstance(remote, tuple) and remote else "telefon"
        with self._lock:
            self._active_clients += 1
            self._client_addr = addr_str
        try:
            async for message in ws:
                if not isinstance(message, (bytes, bytearray)) or not message:
                    continue
                raw_bytes = bytes(message)
                if raw_bytes[:4] == AUDIO_MAGIC:
                    parsed_audio = decode_audio_packet(raw_bytes)
                    if parsed_audio is None:
                        continue
                    src_rate, pcm = parsed_audio
                    pcm_44k = resample_pcm_s16le(pcm, src_rate, TARGET_AUDIO_RATE)
                    samples = np.frombuffer(pcm_44k, dtype="<i2")
                    rms = (
                        float(np.sqrt(np.mean(samples.astype(np.float32) ** 2)) / 32768.0)
                        if samples.size > 0
                        else 0.0
                    )
                    now = time.monotonic()
                    cb: Optional[Callable[[bytes], None]] = None
                    with self._lock:
                        self._audio_chunks.append(pcm_44k)
                        self._last_audio_time = now
                        self._audio_level = min(1.0, rms)
                        cb = self._audio_callback
                    if cb is not None:
                        try:
                            cb(pcm_44k)
                        except Exception:
                            pass
                    continue

                arr = np.frombuffer(raw_bytes, dtype=np.uint8)
                decoded = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                if decoded is None or decoded.size == 0:
                    continue
                now = time.monotonic()
                with self._lock:
                    self._latest_frame = decoded
                    self._frame_seq += 1
                    self._frame_times.append(now)
        finally:
            with self._lock:
                self._active_clients = max(0, self._active_clients - 1)
                if self._active_clients == 0:
                    self._client_addr = None

    async def _serve_async(self, ssl_ctx: ssl.SSLContext) -> None:
        self._stop_event_async = asyncio.Event()
        candidate_ports = (
            [0]
            if self.requested_port == 0
            else list(range(self.requested_port, self.requested_port + 10)) + [0]
        )

        server: Optional[Server] = None
        last_err: Optional[OSError] = None
        for p in candidate_ports:
            try:
                server = await serve(
                    self._ws_handler,
                    self.host,
                    p,
                    ssl=ssl_ctx,
                    process_request=self._process_request,
                    max_size=4 * 1024 * 1024,
                    ping_interval=15,
                    ping_timeout=15,
                )
                break
            except OSError as exc:
                last_err = exc

        if server is None:
            raise last_err or OSError("Uygun port bulunamadı")

        async with server:
            sock = server.sockets[0]
            self._bound_port = int(sock.getsockname()[1])
            self._running = True
            self._ready_event.set()
            await self._stop_event_async.wait()

    def _run_loop(self, ssl_ctx: ssl.SSLContext) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._serve_async(ssl_ctx))
        except BaseException as exc:
            self._start_error = exc
            self._running = False
            self._ready_event.set()
        finally:
            self._running = False
            loop.close()
