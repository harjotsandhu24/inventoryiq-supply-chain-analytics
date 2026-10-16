"""Public screenshots and media: exist, are sharp, and are verified captures of the SYNTHETIC demo data."""

from __future__ import annotations

import hashlib
import json
import re
import struct
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs" / "screenshots" / "screenshots.manifest.json"
PUBLIC_DOCS = [ROOT / "README.md", *(ROOT / "notion-portfolio-package").glob("*.md")]
IMG = re.compile(r"!\[[^\]]*\]\(([^)\s]+\.png)\)")


def _png_size(p: Path) -> tuple[int, int]:
    head = p.read_bytes()[:24]
    assert head[:8] == b"\x89PNG\r\n\x1a\n", f"{p} is not a PNG"
    return struct.unpack(">II", head[16:24])


def _synthetic_hashes() -> set[str]:
    d = json.loads(MANIFEST.read_text())
    assert d["dataSource"] == "synthetic"
    return set(d["files"].values())


def _referenced_images():
    for doc in PUBLIC_DOCS:
        text = re.sub(r"```.*?```", "", doc.read_text(encoding="utf-8"), flags=re.S)
        for rel in IMG.findall(text):
            yield doc, (doc.parent / rel).resolve()


def test_manifest_declares_synthetic_source():
    assert MANIFEST.exists(), "run app/scripts/capture-screenshots.mjs on synthetic data"
    d = json.loads(MANIFEST.read_text())
    assert d["dataSource"] == "synthetic" and "not Walmart" in d["sourceLabel"]
    for name, digest in d["files"].items():
        assert hashlib.sha256((MANIFEST.parent / name).read_bytes()).hexdigest() == digest, name


@pytest.mark.parametrize("doc,img", list(_referenced_images()), ids=lambda x: Path(x).name)
def test_referenced_screenshots_are_verified_synthetic_and_sharp(doc, img):
    assert img.exists(), f"{doc.name} references missing {img}"
    assert hashlib.sha256(img.read_bytes()).hexdigest() in _synthetic_hashes(), (
        f"{img} is not a verified synthetic capture"
    )
    w, h = _png_size(img)
    assert w >= 2000 and h >= 1200, f"{img} is too small ({w}x{h})"


def test_every_public_media_file_is_verified_synthetic():
    hashes = _synthetic_hashes()
    video_manifest = ROOT / "demo-video" / "inventoryiq_demo_synthetic.webm.manifest.json"
    if video_manifest.exists():
        hashes.add(json.loads(video_manifest.read_text())["sha256"])
    media = [
        *(ROOT / "docs" / "screenshots").glob("*.png"),
        *(ROOT / "notion-portfolio-package" / "screenshots").glob("*.png"),
        ROOT / "demo-video" / "thumbnail.png",
    ]
    unverified = [
        str(m.relative_to(ROOT))
        for m in media
        if m.exists() and hashlib.sha256(m.read_bytes()).hexdigest() not in hashes
    ]
    assert not unverified, unverified
