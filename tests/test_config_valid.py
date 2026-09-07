"""L1 config gate: every config must resolve, have required fields, and point
to an existing dataset path. Run before any GPU job (DISCIPLINE.md 三层门禁).

    python tests/test_config_valid.py
"""

from __future__ import annotations

import glob
import os
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dynamic_3dgs.config import load_config  # noqa: E402

REQUIRED_CALIB = ["fx", "fy", "cx", "cy", "width", "height"]


def check_config(path: str) -> list:
    errs = []
    try:
        cfg = load_config(path)
    except Exception as e:
        return [f"{path}: failed to load/merge: {e}"]
    if cfg.get("abstract"):
        return []  # template config, no dataset expected
    ds = cfg.get("dataset", {})
    calib = ds.get("calibration", {})
    for k in REQUIRED_CALIB:
        if k not in calib:
            errs.append(f"{path}: calibration missing '{k}'")
    p = ds.get("path", "")
    if not p or "PLACEHOLDER" in p:
        errs.append(f"{path}: dataset.path unset/placeholder")
    elif not os.path.isdir(p):
        errs.append(f"{path}: dataset.path does not exist: {p}")
    if int(cfg.get("steps", 0)) <= 0:
        errs.append(f"{path}: steps must be > 0")
    return errs


def main():
    errs = []
    for path in sorted(glob.glob("configs/**/*.yaml", recursive=True)):
        errs += check_config(path)
    if errs:
        print("L1 FAIL")
        for e in errs:
            print(" -", e)
        sys.exit(1)
    print("L1 PASS: all configs valid")


if __name__ == "__main__":
    main()
