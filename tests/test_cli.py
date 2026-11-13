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


def test_cli_saves_opens_folder_with_file_manager(tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    launched: list[list[str]] = []

    class FakeProc:
        pass

    monkeypatch.setattr(
        "toshi_camera.main.shutil.which",
        lambda name: "/usr/bin/xdg-open" if name == "xdg-open" else None,
    )
    monkeypatch.setattr(
        "toshi_camera.main.subprocess.Popen",
        lambda cmd, **kwargs: launched.append(list(cmd)) or FakeProc(),
    )

    rc = main(["--saves"])
    assert rc == 0
    expected = tmp_path / "Kamera"
    assert expected.is_dir()
    assert str(expected) in capsys.readouterr().out
    assert launched == [["/usr/bin/xdg-open", str(expected)]]
