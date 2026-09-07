"""Gaussian model + optimizers in gsplat DefaultStrategy convention.

No SLAM-side accounts (no causal_twin / lineage_id / submap bookkeeping from
the monogs-ours variant) — this is a clean offline vanilla 3DGS model.
"""

from __future__ import annotations

import numpy as np
import torch


class GaussianModel:
    """Params dict + per-key optimizers, keys matching gsplat strategy spec."""

    def __init__(self, points: np.ndarray, colors: np.ndarray,
                 sh_degree: int = 3, device: str = "cuda"):
        """``points`` (N,3) world coords, ``colors`` (N,3) rgb in [0,1].

        Vanilla ADC cannot grow the map into regions where no gaussian exists,
        so callers must build the cloud from MULTIPLE frames spread over the
        sequence (see unproject_frame / voxel_downsample).
        """
        self.device = device
        self.sh_degree = sh_degree
        pts_w, cols = points, colors
        n = pts_w.shape[0]

        # init scale = median nearest-neighbour distance (NOT scene-span pairwise
        # median, which would give metre-scale blobs that block all learning)
        base_scale = 0.02
        if n > 1:
            sub = torch.from_numpy(pts_w[:: max(n // 2000, 1)])
            d = torch.cdist(sub, sub)
            d.fill_diagonal_(float("inf"))
            nn_d = d.min(dim=1).values
            nn_d = nn_d[torch.isfinite(nn_d) & (nn_d > 0)]
            if nn_d.numel():
                base_scale = float(torch.median(nn_d).clamp_min(1e-4))
        base_scale = float(np.log(base_scale))

        self.params = {
            "means": torch.nn.Parameter(torch.from_numpy(pts_w).float().to(device)),
            "quats": torch.nn.Parameter(
                torch.tensor([[1.0, 0.0, 0.0, 0.0]], device=device).repeat(n, 1)
            ),
            "scales": torch.nn.Parameter(
                torch.full((n, 3), base_scale, device=device)
            ),
            "opacities": torch.nn.Parameter(torch.zeros(n, device=device)),
            "sh0": torch.nn.Parameter(
                _rgb_to_sh0(torch.from_numpy(cols).float().to(device), sh_degree)
            ),
            "shN": torch.nn.Parameter(
                torch.zeros(n, (sh_degree + 1) ** 2 - 1, 3, device=device)
            ),
        }

    def optimizers(self, lrs: dict) -> dict:
        self.lrs = lrs
        opts = {}
        for k, p in self.params.items():
            lr = lrs.get(k, 0.0)
            opts[k] = torch.optim.Adam([{"params": [p], "lr": lr, "name": k}], eps=1e-15)
        return opts

    def schedulers(self, opts: dict, n_steps: int, final_lr_frac: float = 1 / 160):
        """Exponential lr decay for `means` (vanilla 3DGS style)."""
        def _make(opt, lr0):
            def fn(step):
                return (final_lr_frac ** (step / n_steps)) * lr0
            return torch.optim.lr_scheduler.LambdaLR(opt, fn)

        return {k: _make(o, self.lrs[k]) for k, o in opts.items() if k in self.lrs}

    @property
    def n_gaussians(self) -> int:
        return self.params["means"].shape[0]

    def state_dict(self) -> dict:
        return {k: p.detach().cpu().numpy() for k, p in self.params.items()}


def unproject_frame(frame: dict, K: np.ndarray, stride: int = 4):
    """Depth-unproject one frame to world coords; returns (points, colors)."""
    depth = frame["depth"]  # (H, W) metres
    rgb = frame["rgb"]  # (3, H, W) [0,1]
    T_wc = np.linalg.inv(frame["T_cw"].numpy())  # stored T_cw is world-to-camera
    H, W = depth.shape
    ys, xs = torch.meshgrid(
        torch.arange(H, dtype=torch.float32),
        torch.arange(W, dtype=torch.float32),
        indexing="ij",
    )
    valid = (depth > 0.0) & torch.isfinite(depth)
    sel = valid & ((ys + xs) % stride == 0)
    u, v, z = xs[sel], ys[sel], depth[sel]
    fx, fy = float(K[0, 0]), float(K[1, 1])
    cx, cy = float(K[0, 2]), float(K[1, 2])
    x = (u - cx) / fx * z
    y = (v - cy) / fy * z
    pts_cam = np.stack([x.numpy(), y.numpy(), z.numpy()], axis=1)  # (N,3)
    pts_w = (T_wc[:3, :3] @ pts_cam.T).T + T_wc[:3, 3]
    cols = rgb[:, sel].numpy().T  # (N,3)
    return pts_w.astype(np.float32), cols.astype(np.float32)


def voxel_downsample(points: np.ndarray, colors: np.ndarray, voxel: float):
    """First-occurrence-per-voxel downsample (order-stable)."""
    keys = np.floor(points / voxel).astype(np.int64)
    _, idx = np.unique(keys, axis=0, return_index=True)
    idx = np.sort(idx)
    return points[idx], colors[idx]


def _rgb_to_sh0(colors: torch.Tensor, sh_degree: int) -> torch.Tensor:
    """(N,3) rgb [0,1] -> DC SH coefficients, vanilla 3DGS convention."""
    C0 = 0.28209479177387814
    dc = (colors - 0.5) / C0
    return dc.unsqueeze(1)  # (N,1,3)


def sh_params_from_rgb(colors: torch.Tensor, sh_degree: int) -> torch.Tensor:
    return _rgb_to_sh0(colors, sh_degree)
