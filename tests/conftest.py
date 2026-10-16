from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from inventoryiq import config as C
from inventoryiq.data_io import load_dataset
from inventoryiq.synthetic import generate


@pytest.fixture(scope="session")
def tiny_source(tmp_path_factory) -> Path:
    """A small synthetic M5-format dataset (3 items per department, 3 stores)."""
    out = tmp_path_factory.mktemp("synthetic_m5")
    generate(out, items_per_dept=3, seed=11)
    return out


@pytest.fixture(scope="session")
def tiny_ds(tiny_source):
    return load_dataset(tiny_source, "synthetic")


@pytest.fixture(scope="session")
def pipeline_run(tmp_path_factory):
    """Full pipeline on the standard synthetic dataset; app JSON goes to a temp dir."""
    from inventoryiq.pipeline import run

    app_dir = tmp_path_factory.mktemp("app_data")
    summary = run("synthetic", app_dir=app_dir)
    return {
        "summary": summary,
        "app_dir": app_dir,
        "reports": C.REPORTS_DIR / "synthetic",
        "processed": C.PROCESSED_DIR / "synthetic",
        "deliverables": C.DELIVERABLES_DIR / "synthetic",
    }


def load_json(path: Path):
    return json.loads(Path(path).read_text())


def m5_available() -> bool:
    return all((C.RAW_DIR / f).exists() for f in C.RAW_FILES)


requires_m5 = pytest.mark.skipif(
    not m5_available(), reason="licensed M5 files not present in data/raw"
)


def line(**kw) -> dict[str, np.ndarray]:
    """Single-line input dict for the policy engine with sensible defaults."""
    base = dict(
        mu=10.0,
        sigma=4.0,
        lt_mean=5.0,
        lt_sd=2.0,
        on_hand=100.0,
        on_order=30.0,
        backorders=0.0,
        moq=12.0,
        case_pack=12.0,
        unit_cost=2.0,
        unit_price=3.0,
        order_cost=6.0,
        intermittent=False,
    )
    base.update(kw)
    return {k: np.array([v]) for k, v in base.items()}


def lines(rows: list[dict]) -> dict[str, np.ndarray]:
    keys = rows[0].keys()
    return {k: np.array([r[k] for r in rows]) for k in keys}
