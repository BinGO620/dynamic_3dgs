"""Photometric + depth evaluation (port of monogs-ours eval_rendering /
_compute_depth_l1_cm, restructured; renderer-agnostic: takes rendered tensors).

Outputs per-frame metrics table (PSNR/SSIM/LPIPS + depth L1-cm) so that
transition-window analysis (recovery speed, ghosting) can be computed post hoc.
"""

from __future__ import annotations

import csv
import json
import os

import numpy as np
import torch


def compute_depth_l1_cm(render_depth: torch.Tensor, gt_depth: torch.Tensor) -> float | None:
    """Port of monogs-ours utils/eval_utils.py:_compute_depth_l1_cm."""
    depth = render_depth.squeeze()
    gt = torch.as_tensor(gt_depth, device=depth.device, dtype=depth.dtype)
    valid = (gt > 0) & torch.isfinite(gt) & torch.isfinite(depth)
    if not bool(valid.any()):
        return None
    return torch.mean(torch.abs(depth[valid] - gt[valid])).item() * 100.0


def _psnr(pred: torch.Tensor, gt: torch.Tensor) -> float:
    mse = torch.mean((pred - gt) ** 2).item()
    if mse <= 0:
        return float("inf")
    return -10.0 * np.log10(mse)


def _ssim(pred: torch.Tensor, gt: torch.Tensor) -> float:
    from .trainer import ssim_loss  # reuse window impl (returns 1 - ssim)
    return 1.0 - float(ssim_loss(pred[None], gt[None]).item())


class PhotometricEvaluator:
    def __init__(self, dataset, device: str = "cuda", lpips_net: str = "alex"):
        self.ds = dataset
        self.device = device
        from lpips import LPIPS
        self.lpips_fn = LPIPS(net_type=lpips_net, normalize=True).to(device).eval()

    @torch.no_grad()
    def evaluate(self, render_fn, indices, save_dir: str | None = None,
                 tag: str = "eval") -> dict:
        """``render_fn(frame) -> (rgb (3,H,W) [0,1], depth (H,W) metres)``."""
        rows = []
        for idx in indices:
            frame = self.ds.get_frame(int(idx))
            rgb_pred, depth_pred = render_fn(frame)
            rgb_gt = frame["rgb"].to(self.device)
            depth_gt = frame["depth"].to(self.device)
            row = {
                "frame_idx": int(idx),
                "t": frame["t"],
                "psnr": _psnr(rgb_pred, rgb_gt),
                "ssim": _ssim(rgb_pred, rgb_gt),
                "lpips": float(self.lpips_fn(
                    rgb_pred[None], rgb_gt[None]).item()),
                "depth_l1_cm": compute_depth_l1_cm(depth_pred, depth_gt),
            }
            rows.append(row)

        def _mean(key: str) -> float:
            vals = np.array([r[key] for r in rows if r[key] is not None], dtype=float)
            vals = vals[np.isfinite(vals)]
            return float(vals.mean()) if vals.size else float("nan")

        summary = {
            "tag": tag,
            "n_frames": len(rows),
            "mean_psnr": _mean("psnr"),
            "mean_ssim": _mean("ssim"),
            "mean_lpips": _mean("lpips"),
            "mean_depth_l1_cm": _mean("depth_l1_cm"),
        }

        if save_dir:
            os.makedirs(save_dir, exist_ok=True)
            with open(os.path.join(save_dir, f"per_frame_{tag}.csv"), "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                w.writeheader()
                w.writerows(rows)
            with open(os.path.join(save_dir, f"summary_{tag}.json"), "w") as f:
                json.dump(summary, f, indent=2)
        return summary
