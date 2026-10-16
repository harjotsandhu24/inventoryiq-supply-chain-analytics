"""Serialisation helpers that never emit NaN or Infinity."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


def clean(obj):
    """Recursively convert NumPy types and replace NaN/inf with None."""
    if isinstance(obj, dict):
        return {str(k): clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, np.ndarray)):
        return [clean(v) for v in obj]
    if isinstance(obj, (bool, np.bool_)):
        return bool(obj)
    if isinstance(obj, (int, np.integer)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        return float(obj) if np.isfinite(obj) else None
    if obj is pd.NA or obj is pd.NaT:
        return None
    return obj


def write_json(path: Path, obj, indent: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            clean(obj), indent=indent, separators=None if indent else (",", ":"), allow_nan=False
        )
    )


def records(df: pd.DataFrame) -> list[dict]:
    return clean(df.to_dict("records"))
