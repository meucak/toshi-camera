from pathlib import Path
from toshi_camera.main import main


def test_cli_saves_path_creates_and_prints_dir(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    rc = main(["--saves-path"])
    assert rc == 0
    out = capsys.readouterr().out.strip()
    assert Path(out) == tmp_path / "Kamera"
    assert Path(out).is_dir()


def test_cli_version(capsys):
    rc = main(["--version"])
    assert rc == 0
    assert "Toshi Kamera" in capsys.readouterr().out
