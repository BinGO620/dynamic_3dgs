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

# dataset-family vs nominal intrinsics (monogs-ours incident audit 2026-09-09:
# Bonn intrinsics on a TUM sequence is a silent quality killer; all 640x480
# RGB-D families here share the resolution, so only fx catches the mixup)
EXPECTED_FX = {
    "tum/fr1": 517.31,
    "tum/fr2": 520.91,
    "tum/fr3": 535.40,
    "bonn": 542.82,
}
FX_TOL = 1.0


def _dataset_family(path: str) -> str | None:
    p = path.lower()
    if "bonn" in p:
        return "bonn"
    if "freiburg1" in p or "/fr1" in p:
        return "tum/fr1"
    if "freiburg2" in p or "/fr2" in p:
        return "tum/fr2"
    if "freiburg3" in p or "/fr3" in p:
        return "tum/fr3"
    return None


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
    else:
        if not os.path.isdir(p):
            errs.append(f"{path}: dataset.path does not exist: {p}")
        # intrinsic-vs-dataset cross-check (Bonn/TUM intrinsics are NOT
        # interchangeable; TUM fr1/fr2/fr3 each differ)
        fam = _dataset_family(p)
        if fam in EXPECTED_FX and "fx" in calib:
            fx = float(calib["fx"])
            exp = EXPECTED_FX[fam]
            if abs(fx - exp) > FX_TOL:
                errs.append(
                    f"{path}: intrinsics look wrong for {fam}: fx={fx} "
                    f"but {fam} nominal fx={exp} (wrong-family calibration?)"
                )
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
