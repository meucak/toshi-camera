import numpy as np
from toshi_camera.processing import FrameSettings, apply_adjustments, generate_test_frame


def test_apply_adjustments_clips_extreme_values_without_wrap():
    frame = np.full((16, 16, 3), 200, dtype=np.uint8)
    bright = apply_adjustments(
        frame, FrameSettings(brightness=100, contrast=50, saturation=50)
    )
    assert bright.dtype == np.uint8
    assert bright.shape == (16, 16, 3)
    assert int(bright.min()) >= 200

    dark = apply_adjustments(
        frame, FrameSettings(brightness=-100, contrast=-50, saturation=-100)
    )
    assert dark.dtype == np.uint8
    assert int(dark.max()) <= 150


def test_apply_adjustments_mirror_and_flip():
    frame = np.zeros((4, 4, 3), dtype=np.uint8)
    frame[0, 0] = [255, 10, 20]
    out = apply_adjustments(
        frame, FrameSettings(mirror_horizontal=True, flip_vertical=True)
    )
    assert tuple(out[3, 3]) == (255, 10, 20)


def test_generate_test_frame_dimensions_and_animation():
    f1 = generate_test_frame(640, 480, 0, label="Toshi Kamera")
    f2 = generate_test_frame(640, 480, 15, label="Toshi Kamera")
    assert f1.shape == (480, 640, 3)
    assert f1.dtype == np.uint8
    assert not np.array_equal(f1, f2)
