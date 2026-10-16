"""Every relative link and image in the repository's Markdown documents must resolve."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCS = [
    ROOT / "README.md",
    *(ROOT / "docs").glob("*.md"),
    ROOT / "sql" / "README.md",
    ROOT / "excel" / "power_query" / "README.md",
    *(ROOT / "notion-portfolio-package").glob("*.md"),
    ROOT / "demo-video" / "recording_plan.md",
]
LINK = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)\)")


def _links(md: Path):
    text = re.sub(r"```.*?```", "", md.read_text(encoding="utf-8"), flags=re.S)  # code blocks
    text = re.sub(r"`[^`]*`", "", text)  # inline code is an example, not a link
    for target in LINK.findall(text):
        if target.startswith(("http://", "https://", "mailto:", "#", "{{", "<")):
            continue
        yield target.split("#")[0]


@pytest.mark.parametrize(
    "md", [d for d in DOCS if d.exists()], ids=lambda p: str(p.relative_to(ROOT))
)
def test_relative_links_resolve(md):
    missing = [t for t in _links(md) if t and not (md.parent / t).exists()]
    assert not missing, f"{md.name}: broken links {missing}"


@pytest.mark.parametrize(
    "md", [d for d in DOCS if d.exists()], ids=lambda p: str(p.relative_to(ROOT))
)
def test_links_point_to_published_files(md):
    """A link to a git-ignored file would be dead in the public repository."""
    import shutil
    import subprocess

    if shutil.which("git") is None or not (ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    targets = [
        str((md.parent / t).resolve().relative_to(ROOT))
        for t in _links(md)
        if t and (md.parent / t).exists()
    ]
    if not targets:
        return
    res = subprocess.run(
        ["git", "check-ignore", *targets], cwd=ROOT, capture_output=True, text=True
    )
    ignored = [t for t in res.stdout.splitlines() if t]
    assert not ignored, f"{md.name} links to files excluded from publication: {ignored}"
