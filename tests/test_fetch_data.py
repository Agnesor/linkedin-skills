import hashlib
from pathlib import Path

import pytest

from scripts.fetch_data import fetch, main, read_checksums


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def mirror(tmp_path: Path) -> tuple[str, dict[str, str]]:
    source = tmp_path / "mirror"
    source.mkdir()
    files = {"a.parquet": b"alpha", "b.parquet": b"beta"}
    for name, data in files.items():
        (source / name).write_bytes(data)
    return source.as_uri(), {name: digest(data) for name, data in files.items()}


def test_read_checksums_parses_sha256sum_output(tmp_path):
    path = tmp_path / "data.sha256"
    path.write_text("abc  a.parquet\ndef *b.parquet\n\n")
    assert read_checksums(path) == {"a.parquet": "abc", "b.parquet": "def"}


def test_fetch_downloads_and_verifies(mirror, tmp_path):
    base_url, checksums = mirror
    dest = tmp_path / "data"
    fetch(base_url, dest, checksums)
    assert (dest / "a.parquet").read_bytes() == b"alpha"
    assert not list(dest.glob("*.part"))


def test_fetch_rejects_mismatch_and_leaves_nothing(mirror, tmp_path):
    base_url, checksums = mirror
    checksums["a.parquet"] = digest(b"something else")
    dest = tmp_path / "data"
    with pytest.raises(ValueError, match="sha256 mismatch"):
        fetch(base_url, dest, checksums)
    assert not (dest / "a.parquet").exists()
    assert not list(dest.glob("*.part"))


def test_main_returns_1_on_missing_file(mirror, tmp_path, capsys):
    base_url, _ = mirror
    sums = tmp_path / "data.sha256"
    sums.write_text(f"{digest(b'x')}  missing.parquet\n")
    code = main(["--base-url", base_url, "--dest", str(tmp_path / "d"), "--checksums", str(sums)])
    assert code == 1
    assert "error" in capsys.readouterr().err
