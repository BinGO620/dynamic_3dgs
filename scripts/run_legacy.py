"""Offline runner for the legacy (MonoGS-derived) mapping core.

Phase A acceptance protocol (preregistered in results/legacy_core/README.md):
GT poses feed the mapper directly (no tracking/BA); keyframe-window mapping
loop + final color refinement; eval on held-out non-keyframe frames.
"""

import argparse
import json
import os
import random
import sys

import numpy as np
import torch
import yaml


def seed_everything(seed: int):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def load_config(path: str) -> dict:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from dynamic_3dgs.config import load_config as _load

    return _load(path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--out", required=True, help="results/{exp_id}/{seq}/seed_n")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--max-frames", type=int, default=-1, help="smoke-test cap")
    parser.add_argument("--refine-iters", type=int, default=-1,
                        help="override Training.color_refine_iters")
    parser.add_argument("--save-ply", action="store_true")
    args = parser.parse_args()

    cfg = load_config(args.config)
    seed_everything(args.seed)

    from dynamic_3dgs.legacy_core.dataset_adapter import load_monogs_dataset
    from dynamic_3dgs.legacy_core.mapping import OfflineMapper

    ds_cfg = dict(cfg["dataset"])
    if args.max_frames > 0:
        ds_cfg["max_frames"] = args.max_frames
    cfg["dataset"] = ds_cfg
    dataset = load_monogs_dataset(cfg)

    if args.refine_iters >= 0:
        cfg["Training"]["color_refine_iters"] = args.refine_iters

    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "config_used.yaml"), "w") as f:
        yaml.safe_dump(cfg, f)

    mapper = OfflineMapper(cfg, dataset, save_dir=args.out)
    mapper.run()

    if args.save_ply:
        from dynamic_3dgs.legacy_core.gaussian_model import GaussianModel  # noqa: F401
        ply_path = os.path.join(args.out, "point_cloud", "final")
        os.makedirs(ply_path, exist_ok=True)
        mapper.gaussians.save_ply(os.path.join(ply_path, "point_cloud.ply"))

    result = mapper.final_eval(None)
    result["n_kf"] = len(mapper.kf_indices)
    result["n_gauss"] = int(mapper.gaussians.get_xyz.shape[0])
    result["seed"] = args.seed
    with open(os.path.join(args.out, "result.json"), "w") as f:
        json.dump(result, f, indent=2)
    print("[run_legacy] done:", json.dumps({k: result[k] for k in
          ("mean_psnr", "mean_ssim", "mean_lpips", "mean_depth_l1_cm", "n_gauss")}))


if __name__ == "__main__":
    main()
