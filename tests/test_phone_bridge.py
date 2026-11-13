import asyncio
import ssl
import urllib.error
import urllib.request
from pathlib import Path

import cv2
import numpy as np
import pytest
import websockets

from toshi_camera.phone_bridge import (
    PhoneBridgeServer,
    build_mobile_page_html,
    decode_audio_packet,
    discover_lan_ips,
    encode_audio_packet,
    ensure_self_signed_cert,
    generate_qr_image,
    parse_ipv4_from_ip_addr_output,
    resample_pcm_s16le,
)


def test_parse_ipv4_from_ip_addr_output_prioritizes_lan_and_skips_loopback():
    sample = (
        "1: lo    inet 127.0.0.1/8 scope host lo\\       valid_lft forever preferred_lft forever\n"
        "5: tailscale0    inet 100.79.246.19/32 scope global tailscale0\\       valid_lft forever\n"
        "3: wlp8s0    inet 192.168.1.27/24 brd 192.168.1.255 scope global dynamic wlp8s0\n"
        "4: eth0    inet 10.0.0.15/24 scope global eth0\n"
    )
    ips = parse_ipv4_from_ip_addr_output(sample)
    assert "127.0.0.1" not in ips
    assert ips[0] == "192.168.1.27"
    assert "10.0.0.15" in ips
    assert ips[-1] == "100.79.246.19"
    assert isinstance(discover_lan_ips(), list)


def test_ensure_self_signed_cert_creates_and_caches(tmp_path: Path):
    cert_path, key_path = ensure_self_signed_cert(tmp_path, ["192.168.1.27"])
    assert cert_path.exists()
    assert key_path.exists()
    first_mtime = cert_path.stat().st_mtime_ns

    # Same IP list should reuse cached cert
    cert_path2, key_path2 = ensure_self_signed_cert(tmp_path, ["192.168.1.27"])
    assert cert_path2 == cert_path
    assert key_path2 == key_path
    assert cert_path2.stat().st_mtime_ns == first_mtime

    # Changed IP list should regenerate cert with updated SAN
    cert_path3, _ = ensure_self_signed_cert(tmp_path, ["192.168.1.27", "192.168.1.99"])
    assert cert_path3.exists()
    assert (tmp_path / ".san_ips").read_text(encoding="utf-8").strip() == "192.168.1.27,192.168.1.99"


def test_generate_qr_image_roundtrips_with_cv2_detector():
    url = "https://192.168.1.27:8443/?t=abc123XYZ"
    img = generate_qr_image(url, scale=8, border=4)
    assert img.ndim == 2
    assert img.dtype == np.uint8
    assert img.shape[0] == img.shape[1]
    detector = cv2.QRCodeDetector()
    decoded, _, _ = detector.detectAndDecode(img)
    assert decoded == url


def test_build_mobile_page_html_has_camera_and_ws_controls():
    html = build_mobile_page_html()
    assert "getUserMedia" in html
    assert "/ws" in html
    assert "facingMode" in html
    assert "AudioContext" in html
    assert "orientationSelect" in html


def test_audio_packet_roundtrip_and_resample():
    pcm = (np.sin(np.linspace(0, 2 * np.pi, 480)) * 12000).astype("<i2").tobytes()
    pkt = encode_audio_packet(48000, pcm)
    decoded = decode_audio_packet(pkt)
    assert decoded is not None
    rate, raw = decoded
    assert rate == 48000
    assert raw == pcm

    assert decode_audio_packet(b"JUNK") is None
    assert decode_audio_packet(b"AUD0\x00\x00") is None

    # Identity resample
    assert resample_pcm_s16le(pcm, 44100, 44100) == pcm
    # Downsample 48000 -> 44100
    resampled = resample_pcm_s16le(pcm, 48000, 44100)
    assert len(resampled) % 2 == 0
    assert 800 <= len(resampled) <= 920


def test_phone_bridge_server_receives_audio_packets_over_wss(tmp_path: Path):
    srv = PhoneBridgeServer(host="127.0.0.1", port=0, cert_dir=tmp_path)
    srv.start()
    try:
        ctx = ssl._create_unverified_context()
        pcm = (np.ones(1024, dtype="<i2") * 3000).tobytes()
        pkt = encode_audio_packet(44100, pcm)

        async def _send_audio():
            ws_url = f"wss://127.0.0.1:{srv.port}/ws?t={srv.token}"
            async with websockets.connect(ws_url, ssl=ctx) as ws:
                await ws.send(pkt)
                await asyncio.sleep(0.15)

        asyncio.run(_send_audio())
        chunks = srv.pop_audio_chunks()
        assert len(chunks) >= 1
        assert chunks[0] == pcm
        assert srv.is_audio_active() is True
        assert srv.audio_level() > 0.0
    finally:
        srv.stop()


def test_phone_bridge_server_http_auth_and_wss_frame_streaming(tmp_path: Path):
    srv = PhoneBridgeServer(host="127.0.0.1", port=0, cert_dir=tmp_path)
    srv.start()
    try:
        assert srv.is_running() is True
        assert srv.port > 0
        valid_url = srv.build_url("127.0.0.1")

        ctx = ssl._create_unverified_context()

        # Unauthorized GET / must fail with 403
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(f"https://127.0.0.1:{srv.port}/", context=ctx, timeout=3)
        assert exc_info.value.code == 403

        # Authorized GET /?t=... must return 200 HTML
        with urllib.request.urlopen(valid_url, context=ctx, timeout=3) as resp:
            assert resp.status == 200
            body = resp.read().decode("utf-8")
            assert "getUserMedia" in body

        # Connect over WSS, send garbage + valid JPEG frame, verify decode
        async def _ws_client():
            bad_ws_url = f"wss://127.0.0.1:{srv.port}/ws?t=wrong"
            with pytest.raises(Exception):
                async with websockets.connect(bad_ws_url, ssl=ctx):
                    pass

            good_ws_url = f"wss://127.0.0.1:{srv.port}/ws?t={srv.token}"
            async with websockets.connect(good_ws_url, ssl=ctx) as ws:
                # Garbage bytes must be ignored without closing connection
                await ws.send(b"not-a-valid-jpeg-payload")

                # Valid BGR image encoded as JPEG
                sample = np.zeros((120, 160, 3), dtype=np.uint8)
                sample[:, :] = (40, 180, 90)
                ok, buf = cv2.imencode(".jpg", sample)
                assert ok is True
                await ws.send(buf.tobytes())
                await asyncio.sleep(0.15)

        asyncio.run(_ws_client())
        latest = srv.get_latest_frame()
        assert latest is not None
        frame, seq = latest
        assert seq >= 1
        assert frame.shape == (120, 160, 3)
    finally:
        srv.stop()
        assert srv.is_running() is False
