"""Overnight ladder driver for legacy_a2 (route-Y offline refinement).

Single-variable ladder on bonn_removing (seed 0), idempotent + early-stop.
After the ladder, the winner is confirmed on tum_walking_xyz + bonn_placing.

Progress is appended to results/legacy_a2/progress.json after every run so the
session can be resumed if interrupted (DISCIPLINE: results 只写不改 — we never
overwrite a completed run's result.json; we only create new seed dirs).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

import yaml

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = os.path.join(
    os.environ.get("CONDA_PREFIX", "/data/conda_envs/dynamic_3dgs"),
    "bin",
    "python",
)
RUN_LEGACY = os.path.join(REPO, "scripts", "run_legacy.py")
PROGRESS = os.path.join(REPO, "results", "legacy_a2", "progress.json")

# bonn removing is the gate sequence (A2). Each arm = one config override.
ARMS = [
    ("a1_offline_refine", "configs/legacy/ladder/a1_offline_refine.yaml"),
    ("a2_offline_densify", "configs/legacy/ladder/a2_offline_densify.yaml"),
    # a3/a4 skipped per README amendment M3 (uninformative under the buggy
    # depth-charged loss); M1/M2 arms isolate loss composition
    ("a5_color_loss", "configs/legacy/ladder/a5_color_loss.yaml"),
    ("a6_color_depth_masked", "configs/legacy/ladder/a6_color_depth_masked.yaml"),
]

GATE_TARGET = 19.0  # A2 preregistered target (dB)
CONFIRM = [
    ("tum_walking_xyz", "datasets/tum/rgbd_dataset_freiburg3_walking_xyz"),
    ("bonn_placing", "datasets/bonn/rgbd_bonn_placing_nonobstructing_box"),
]


def load_progress() -> dict:
    if os.path.exists(PROGRESS):
        return json.load(open(PROGRESS))
    return {"arms": {}, "best": None, "confirm": {}, "stopped": None}


def save_progress(p: dict):
    os.makedirs(os.path.dirname(PROGRESS), exist_ok=True)
    with open(PROGRESS, "w") as f:
        json.dump(p, f, indent=2)


def run_one(config_path: str, out_dir: str, seed: int = 0) -> dict | None:
    """Run one arm. Returns parsed result.json or None on failure.
    Idempotent: skip if result.json already present. run_legacy.py writes
    flat into --out, so the seed dir IS the --out (repo convention
    {arm}/{seq}/seed_{n})."""
    run_out = os.path.join(out_dir, f"seed_{seed}")
    result_path = os.path.join(run_out, "result.json")
    if os.path.exists(result_path):
        print(f"[ladder] skip (exists): {run_out}")
        return json.load(open(result_path))
    os.makedirs(run_out, exist_ok=True)
    cmd = [
        PY, RUN_LEGACY,
        "--config", config_path,
        "--out", run_out,
        "--seed", str(seed),
    ]
    print(f"[ladder] >>> {' '.join(cmd)}")
    t0 = time.time()
    proc = subprocess.run(cmd, cwd=REPO, capture_output=False)
    dt = time.time() - t0
    if proc.returncode != 0:
        print(f"[ladder] FAILED rc={proc.returncode} after {dt:.0f}s: {out_dir}")
        return None
    if not os.path.exists(result_path):
        print(f"[ladder] no result.json after success: {run_out}")
        return None
    res = json.load(open(result_path))
    res["_wall_s"] = dt
    print(f"[ladder] done {dt:.0f}s: PSNR={res.get('mean_psnr'):.3f}")
    return res


def make_confirm_config(src_config: str, dataset_path: str, tmp_dir: str) -> str:
    """Clone a ladder config and repoint it at a different dataset."""
    cfg = yaml.safe_load(open(src_config))
    cfg["dataset"]["path"] = dataset_path
    cfg.pop("abstract", None)
    out = os.path.join(tmp_dir, "confirm_" + os.path.basename(src_config))
    with open(out, "w") as f:
        yaml.safe_dump(cfg, f)
    return out


def main():
    p = load_progress()
    best_name, best_psnr, best_config = None, -1.0, None

    # ---- ladder on bonn_removing ----
    for arm_name, arm_config in ARMS:
        out_dir = os.path.join(REPO, "results", "legacy_a2", arm_name, "bonn_removing")
        if arm_name in p["arms"]:
            # already recorded (possibly from a prior interrupted run)
            r = p["arms"][arm_name]
        else:
            r = run_one(arm_config, out_dir)
            p["arms"][arm_name] = r
            save_progress(p)
        psnr = (r or {}).get("mean_psnr") or -1.0
        if psnr > best_psnr:
            best_psnr, best_name, best_config = psnr, arm_name, arm_config
        # early stop: gate met
        if psnr >= GATE_TARGET:
            p["stopped"] = f"early_stop@{arm_name}_{psnr:.3f}dB"
            save_progress(p)
            break

    p["best"] = {"arm": best_name, "psnr": best_psnr}
    save_progress(p)
    print(f"[ladder] best arm = {best_name} @ {best_psnr:.3f} dB")

    if best_config is None:
        print("[ladder] no successful arm — aborting confirm")
        return

    # ---- confirm winner on the other two sequences ----
    tmp_dir = tempfile.mkdtemp(prefix="ladder_confirm_")
    for seq_name, seq_path in CONFIRM:
        if seq_name in p["confirm"]:
            continue
        confirm_cfg = make_confirm_config(best_config, seq_path, tmp_dir)
        out_dir = os.path.join(REPO, "results", "legacy_a2", "confirm", seq_name)
        r = run_one(confirm_cfg, out_dir)
        p["confirm"][seq_name] = r
        save_progress(p)
    shutil.rmtree(tmp_dir, ignore_errors=True)

    # ---- summary ----
    print("\n===== LEGACY_A2 LADDER SUMMARY =====")
    for arm_name, _ in ARMS:
        r = p["arms"].get(arm_name)
        psnr = (r or {}).get("mean_psnr")
        print(f"  {arm_name:22s} bonn_removing = {psnr if psnr else 'FAIL'}")
    print(f"  BEST = {best_name} @ {best_psnr:.3f} dB")
    for seq_name, _ in CONFIRM:
        r = p["confirm"].get(seq_name)
        psnr = (r or {}).get("mean_psnr")
        print(f"  confirm {seq_name:18s} = {psnr if psnr else 'FAIL'}")
    print("  progress:", PROGRESS)


if __name__ == "__main__":
    main()
