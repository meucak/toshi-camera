import pytest
from toshi_camera.virtual_cam import (
    VirtualCamBridge,
    build_ffmpeg_loopback_cmd,
    validate_stream_url,
)


def test_validate_stream_url():
    assert validate_stream_url("http://192.168.1.50:8080/video") is True
    assert validate_stream_url("https://192.168.1.50:8443/stream.mjpg") is True
    assert validate_stream_url("rtsp://192.168.1.50:8554/live") is True
    assert validate_stream_url("udp://127.0.0.1:5000") is True
    assert validate_stream_url("ftp://bad") is False
    assert validate_stream_url("") is False
    assert validate_stream_url("   ") is False


def test_build_ffmpeg_loopback_cmd_for_test_pattern_and_stream():
    cmd_test = build_ffmpeg_loopback_cmd(None, "/dev/video0", 640, 480, 30)
    assert "testsrc2=size=640x480:rate=30" in cmd_test
    assert "/dev/video0" in cmd_test

    cmd_net = build_ffmpeg_loopback_cmd(
        "http://192.168.1.50:8080/video", "/dev/video0", 640, 480, 30
    )
    assert "http://192.168.1.50:8080/video" in cmd_net
    assert "/dev/video0" in cmd_net

    with pytest.raises(ValueError):
        build_ffmpeg_loopback_cmd("invalid://url", "/dev/video0")


def test_virtual_cam_bridge_stop_when_not_started():
    bridge = VirtualCamBridge(target_device="/dev/video0")
    assert bridge.is_running() is False
    bridge.stop()
    assert bridge.is_running() is False
