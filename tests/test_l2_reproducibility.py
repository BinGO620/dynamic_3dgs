"""L2 gate: same config + seed reproduces within tolerance (DISCIPLINE.md).

    python tests/test_l2_reproducibility.py --config configs/bonn/rgbd_bonn_static.yaml \
        --max-frames 20 --steps 200

Runs training twice in-process with fixed seeds, compares final held-out PSNR.
"""

from __future__ import annotations

import argparse
import os
import sys

import numpy as np
import torch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dynamic_3dgs.config import load_config
from dynamic_3dgs.dataset import make_dataset
from dynamic_3dgs.trainer import Trainer


def run_once(cfg: dict) -> float:
    torch.manual_seed(int(cfg["seed"]))
    np.random.seed(int(cfg["seed"]))
    ds = make_dataset(cfg)
    trainer = Trainer(ds, cfg, device="cuda")
    trainer.train(log_every=cfg["steps"] + 1)

    from dynamic_3dgs.eval import _psnr
    vals = []
    with torch.no_grad():
        for idx in ds.eval_indices:
            frame = ds.get_frame(int(idx))
            renders, _, _ = trainer.render(frame)
            rgb = renders[0, :, :, :3].permute(2, 0, 1).clamp(0.0, 1.0)
            vals.append(_psnr(rgb, frame["rgb"].cuda()))
    vals = np.array(vals, dtype=float)
    vals = vals[np.isfinite(vals)]
    return float(vals.mean())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--max-frames", type=int, default=20)
    ap.add_argument("--steps", type=int, default=200)
    ap.add_argument("--tol", type=float, default=0.3)
    args = ap.parse_args()

    cfg = load_config(args.config)
    cfg["dataset"]["max_frames"] = args.max_frames
    cfg["steps"] = args.steps

    p1, p2 = run_once(cfg), run_once(cfg)
    diff = abs(p1 - p2)
    status = "PASS" if diff <= args.tol else "FAIL"
    print(f"L2 {status}: psnr1={p1:.3f} psnr2={p2:.3f} diff={diff:.3f} (tol={args.tol})")
    sys.exit(0 if status == "PASS" else 1)


if __name__ == "__main__":
    main()
