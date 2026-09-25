"""Download the prebuilt Parquet files and verify them against the checksums in the repo.

The checksums live in ``data.sha256`` next to the code, not in the release, so a replaced
or corrupted release asset fails the check instead of being trusted.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.request
from pathlib import Path

DEFAULT_BASE_URL = "https://github.com/Agnesor/linkedin-skills/releases/download/data-v1"
TIMEOUT_SECONDS = 120


def read_checksums(path: Path) -> dict[str, str]:
    """Parse ``sha256sum`` output: ``<hex>  <file name>`` per line."""
    checksums = {}
    for line in path.read_text().splitlines():
        if line.strip():
            digest, name = line.split(maxsplit=1)
            checksums[name.strip().lstrip("*")] = digest
    return checksums


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch(base_url: str, dest: Path, checksums: dict[str, str]) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for name, expected in checksums.items():
        target = dest / name
        if target.is_file() and sha256(target) == expected:
            print(f"{name}: already present")
            continue
        url = f"{base_url.rstrip('/')}/{name}"
        print(f"{name}: downloading {url}")
        partial = target.with_suffix(target.suffix + ".part")
        with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as response:
            partial.write_bytes(response.read())
        actual = sha256(partial)
        if actual != expected:
            partial.unlink()
            raise ValueError(f"{name}: sha256 mismatch (expected {expected}, got {actual})")
        partial.replace(target)
        print(f"{name}: ok")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--dest", type=Path, default=Path("data"))
    parser.add_argument("--checksums", type=Path, default=Path("data.sha256"))
    args = parser.parse_args(argv)
    try:
        fetch(args.base_url, args.dest, read_checksums(args.checksums))
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
