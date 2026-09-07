"""G0.3 transition-sensitivity analysis (preregistered, ROADMAP.md §3.2).

Reads per_frame_eval.csv from a baseline run and reports the largest
PSNR dip relative to the sequence median, its timestamp location, and the
depth-jump events (median |Δdepth| between consecutive eval frames) as a
schedule-free event detector. A dip is "identifiable" if:
    max_dip >= 2.0 dB below sequence median PSNR
(consistency across sequences is judged by the caller / verdict).

    python scripts/analyze_transition.py results/baseline_vanilla/<seq>/seed_0
"""

from __future__ import annotations

import csv
import json
import os
import sys

import numpy as np


def load_rows(run_dir: str) -> list:
    path = os.path.join(run_dir, "per_frame_eval.csv")
    with open(path) as f:
        return list(csv.DictReader(f))


def analyze(run_dir: str, dip_db: float = 2.0, report=True) -> dict:
    rows = load_rows(run_dir)
    psnr = np.array([float(r["psnr"]) for r in rows])
    t = np.array([float(r["t"]) for r in rows])
    depth = np.array(
        [float(r["depth_l1_cm"]) if r["depth_l1_cm"] else np.nan for r in rows]
    )
    med = float(np.median(psnr))
    dip_idx = int(np.argmin(psnr))
    max_dip = med - float(psnr[dip_idx])

    # schedule-free event detector: frame-to-frame median depth L1 jump
    djump = np.abs(np.diff(depth))
    event_idx = int(np.nanargmax(djump)) if len(djump) else -1
    out = {
        "run_dir": run_dir,
        "n_eval_frames": len(rows),
        "median_psnr": med,
        "min_psnr": float(psnr[dip_idx]),
        "max_dip_db": max_dip,
        "dip_frame_idx": int(rows[dip_idx]["frame_idx"]),
        "dip_rel_pos": float(dip_idx / max(len(rows) - 1, 1)),
        "largest_depth_jump_cm": float(djump[event_idx]) if event_idx >= 0 else None,
        "event_frame_idx": int(rows[event_idx]["frame_idx"]) if event_idx >= 0 else None,
        "dip_identifiable": bool(max_dip >= dip_db),
        "dip_db_threshold": dip_db,
    }
    if report:
        print(json.dumps(out, indent=2))
    return out


if __name__ == "__main__":
    analyze(sys.argv[1])
