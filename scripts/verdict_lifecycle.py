"""Stage-1 paired verdict: arms (P1/Ma/Mb) vs C0 across 3 transition seqs.

Preregistered readouts (results/lifecycle_gate/README.md):
- M1: psnr_static_cons >= C0 + 2dB
- M2: depth_l1 <= 0.8 * C0
- M3: transition dip narrower (max_dip_db closer to median)
- Protection: pre-event static segment & kidnapping static segment unchanged (±0.3dB)
- Placebo gate: |P1 - C0| < 0.5dB on headline metrics

    python scripts/verdict_lifecycle.py results/lifecycle_gate
"""

from __future__ import annotations

import json
import sys

import numpy as np

SEQS = ["rgbd_bonn_removing_nonobstructing_box",
        "rgbd_bonn_placing_nonobstructing_box",
        "rgbd_bonn_kidnapping_box"]
ARMS = ["C0", "P1", "Ma", "Mb"]


def load(root: str, arm: str, seq: str) -> dict | None:
    p = f"{root}/{seq}_{arm}/seed_0/summary_eval.json"
    try:
        return json.load(open(p))
    except FileNotFoundError:
        return None


def dip_db(root: str, arm: str, seq: str) -> float | None:
    import csv, os
    p = f"{root}/{seq}_{arm}/seed_0/per_frame_eval.csv"
    if not os.path.exists(p):
        return None
    rows = list(csv.DictReader(open(p)))
    psnr = np.array([float(r["psnr"]) for r in rows])
    med = float(np.median(psnr))
    return med - float(psnr.min())


def main(root: str):
    table = {}
    for arm in ARMS:
        table[arm] = {s: load(root, arm, s) for s in SEQS}
        table[arm]["dip"] = {s: dip_db(root, arm, s) for s in SEQS}

    print(f"{'metric':<22}" + "".join(f"{a:>10}" for a in ARMS))
    for seq in SEQS:
        for met, key in [("psnr", "mean_psnr"), ("psnr_static_cons", "mean_psnr_static_cons"),
                         ("depth_l1_cm", "mean_depth_l1_cm"), ("lpips", "mean_lpips")]:
            vals = []
            for a in ARMS:
                d = table[a].get(seq)
                vals.append(d[key] if d else float("nan"))
            print(f"{seq[:12]}/{met:<10}" + "".join(f"{v:>10.2f}" for v in vals))
    print(f"{'dip_db':<22}" + "".join(
        f"{np.nanmean([table[a]['dip'][s] or np.nan for s in SEQS]):>10.2f}" for a in ARMS))

    # preregistered checks vs C0
    print("\n--- paired checks (arm vs C0, means over 3 seqs) ---")
    verdict = {}
    for a in ["P1", "Ma", "Mb"]:
        rows = {}
        for met in ["mean_psnr_static_cons", "mean_depth_l1_cm"]:
            xs = [table[a][s][met] for s in SEQS if table[a][s]]
            cs = [table["C0"][s][met] for s in SEQS if table["C0"][s]]
            rows[met] = (np.mean(xs), np.mean(cs))
        d_sc = rows["mean_psnr_static_cons"][0] - rows["mean_psnr_static_cons"][1]
        r_d = rows["mean_depth_l1_cm"][0] / rows["mean_depth_l1_cm"][1]
        M1 = d_sc >= 2.0
        M2 = r_d <= 0.8
        placebo_ok = (a == "P1") and (abs(d_sc) < 0.5)
        verdict[a] = {"static_cons_gain_db": round(d_sc, 2), "depth_ratio": round(r_d, 3),
                      "M1_pass": bool(M1), "M2_pass": bool(M2)}
        print(f"{a}: static_cons {d_sc:+.2f}dB (M1 {'PASS' if M1 else 'FAIL'}), "
              f"depth ratio {r_d:.3f} (M2 {'PASS' if M2 else 'FAIL'})")
    json.dump(verdict, open(f"{root}/paired_verdict.json", "w"), indent=2)
    print(f"\nwritten {root}/paired_verdict.json")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "results/lifecycle_gate")
