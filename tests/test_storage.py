from pathlib import Path
import numpy as np
from toshi_camera.storage import MediaStorage, get_default_saves_dir


def test_save_photo_and_list_and_delete(tmp_path: Path):
    storage = MediaStorage(tmp_path / "photos", tmp_path / "videos")
    frame = np.zeros((64, 64, 3), dtype=np.uint8)
    saved = storage.save_photo(frame)
    assert saved.exists()
    assert saved.suffix == ".png"

    vid_path = storage.allocate_video_path()
    vid_path.write_bytes(b"RIFF0000AVI ")

    items = storage.list_media()
    assert len(items) == 2
    kinds = {it.kind for it in items}
    assert kinds == {"photo", "video"}

    assert storage.delete_media_file(saved) is True
    assert not saved.exists()
    # Review Focus #4: deleting an already-deleted file returns False gracefully
    assert storage.delete_media_file(saved) is False


def test_get_default_saves_dir(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    saves_dir = get_default_saves_dir()
    assert saves_dir == tmp_path / "Kamera"
    assert saves_dir.exists()
