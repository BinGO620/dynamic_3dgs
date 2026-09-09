#!/usr/bin/env python
"""Offline vanilla 3DGS baseline runner.

Usage:
    python scripts/run_baseline.py --config configs/bonn/rgbd_bonn_static.yaml \
        [--exp-id baseline_vanilla] [--seed 0] [--max-frames 50] [--steps 1000]

Outputs (light files only) under results/{exp_id}/{seq_name}/seed_{n}/:
    config.yml (merged copy), train_log.json, summary_eval.json,
    per_frame_eval.csv, model.npz (gitignored)
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys

import numpy as np
import torch
import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dynamic_3dgs.config import load_config
from dynamic_3dgs.dataset import make_dataset
from dynamic_3dgs.eval import PhotometricEvaluator
from dynamic_3dgs.trainer import Trainer


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--exp-id", default="baseline_vanilla")
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--max-frames", type=int, default=None)
    ap.add_argument("--steps", type=int, default=None)
    ap.add_argument("--eval-stride", type=int, default=None)
    ap.add_argument("--train-frame-stride", type=int, default=None)
    ap.add_argument("--lifecycle", default=None, choices=["off", "placebo", "retire", "full"])
    ap.add_argument("--retire-ev", type=float, default=None)
    ap.add_argument("--stream-pass", action="store_true",
                    help="E0: temporal single-pass streaming schedule")
    ap.add_argument("--stream-k", type=int, default=None)
    ap.add_argument("--tag", default="eval")
    args = ap.parse_args()

    cfg = load_config(args.config)
    if args.seed is not None:
        cfg["seed"] = args.seed
    if args.steps is not None:
        cfg["steps"] = args.steps
    if args.max_frames is not None:
        cfg["dataset"]["max_frames"] = args.max_frames
    if args.eval_stride is not None:
        cfg["dataset"]["eval_stride"] = args.eval_stride
    if args.lifecycle is not None:
        cfg["lifecycle"] = args.lifecycle
    if args.retire_ev is not None:
        cfg["retire_ev"] = args.retire_ev
    if args.stream_pass:
        cfg["stream_pass"] = True
    if args.stream_k is not None:
        cfg["stream_k"] = args.stream_k
    if args.train_frame_stride is not None:
        cfg["dataset"]["train_frame_stride"] = args.train_frame_stride

    seed = int(cfg.get("seed", 0))
    torch.manual_seed(seed)
    np.random.seed(seed)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    seq_name = os.path.splitext(os.path.basename(args.config))[0]
    out_dir = os.path.join("results", args.exp_id, seq_name, f"seed_{seed}")
    os.makedirs(out_dir, exist_ok=True)

    print(f"[run_baseline] seq={seq_name} seed={seed} steps={cfg['steps']} device={device}",
          flush=True)
    ds = make_dataset(cfg)
    print(f"[run_baseline] frames={len(ds)} (train {len(ds.train_indices)}, "
          f"eval {len(ds.eval_indices)})", flush=True)

    trainer = Trainer(ds, cfg, device=device)
    log = trainer.train(log_every=max(cfg["steps"] // 10, 1))

    with open(os.path.join(out_dir, "config.yml"), "w") as f:
        yaml.safe_dump(cfg, f)
    with open(os.path.join(out_dir, "train_log.json"), "w") as f:
        json.dump(log, f, indent=2)

    model_path = os.path.join(out_dir, "model.npz")
    trainer.save(model_path)

    def render_fn(frame):
        renders, alphas, _ = trainer.render(frame)
        rgb = renders[0, :, :, :3].permute(2, 0, 1).clamp(0.0, 1.0)
        depth = renders[0, :, :, 3]
        return rgb, depth, alphas[0]

    evaluator = PhotometricEvaluator(ds, device=device)
    summary_eval = evaluator.evaluate(render_fn, ds.eval_indices, out_dir, tag="eval")
    print("[run_baseline] eval:", json.dumps(summary_eval), flush=True)

    manifest = {
        "exp_id": args.exp_id,
        "sequence": seq_name,
        "seed": seed,
        "steps": cfg["steps"],
        "n_frames": len(ds),
        "n_train": len(ds.train_indices),
        "n_eval": len(ds.eval_indices),
        "n_gaussians_final": trainer.model.n_gaussians,
        "summary_eval": summary_eval,
        "model_file": "model.npz",
        "code_state": os.popen("git rev-parse HEAD 2>/dev/null").read().strip(),
    }
    with open(os.path.join(out_dir, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"[run_baseline] done -> {out_dir}", flush=True)


if __name__ == "__main__":
    main()
