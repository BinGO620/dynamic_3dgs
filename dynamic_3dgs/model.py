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
                 scales: np.ndarray, sh_degree: int = 3, device: str = "cuda",
                 opacity_init: float = 0.1):
        """``points`` (N,3) world coords, ``colors`` (N,3) rgb [0,1],
        ``scales`` (N,) per-point world scale (pixel-footprint rule).

        Vanilla ADC cannot grow the map into regions where no gaussian exists,
        so callers must build the cloud from MULTIPLE frames spread over the
        sequence (see unproject_frame / voxel_downsample / static_consistency_mask).
        """
        self.device = device
        self.sh_degree = sh_degree
        pts_w, cols = points, colors
        n = pts_w.shape[0]

        self.params = {
            "means": torch.nn.Parameter(torch.from_numpy(pts_w).float().to(device)),
            "quats": torch.nn.Parameter(
                torch.tensor([[1.0, 0.0, 0.0, 0.0]], device=device).repeat(n, 1)
            ),
            "scales": torch.nn.Parameter(
                torch.log(torch.clamp(
                    torch.from_numpy(scales).float().to(device), 1e-4, 1.0
                ))[:, None].repeat(1, 3)),
            "opacities": torch.nn.Parameter(
                torch.full((n,), float(np.log(
                    np.clip(opacity_init, 1e-3, 0.9) / (1 - np.clip(opacity_init, 1e-3, 0.9))
                )), device=device)
            ),
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
    """Depth-unproject one frame to world coords; returns (points, colors, scales).

    Per-point scale = pixel footprint at that depth (SplaTAM / Geometry-Aware
    Online Mapping rule): s = z / focal * stride, NOT a global NN statistic —
    a fixed world scale over-blurs near surfaces and undersamples far ones.
    """
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
    s = z.numpy() / fx * stride  # isotropic world scale ≈ stride-pixel footprint
    return pts_w.astype(np.float32), cols.astype(np.float32), s.astype(np.float32)


def static_consistency_mask(dataset, frame_idx: int, points: np.ndarray,
                            n_ref: int = 4, tol_base: float = 0.05,
                            tol_rel: float = 0.02, min_ratio: float = 0.5):
    """True where `points` (from frame `frame_idx`) agree with other frames.

    Points whose reprojection into `n_ref` other frames disagrees with the
    observed depth (beyond tol_base + tol_rel*z) are dynamic-content shells
    (robot/people/box) and must not enter the static map. Points never seen
    by any reference frame (no valid observation) are dropped: unverifiable.
    """
    n = points.shape[0]
    if n == 0:
        return np.zeros(0, dtype=bool)
    total = np.zeros(n, dtype=np.int32)
    valid = np.zeros(n, dtype=np.int32)
    n_frames = len(dataset.samples)
    refs = np.linspace(0, n_frames - 1, min(n_ref + 1, n_frames)).astype(int)
    refs = [j for j in refs if abs(j - frame_idx) > 2][:n_ref]
    for j in refs:
        T_cw = dataset.samples[j][3]
        P = points.T
        z = T_cw[:3, :3] @ P
        x = z[0] + T_cw[0, 3]; y = z[1] + T_cw[1, 3]; z = z[2] + T_cw[2, 3]
        dj = dataset._load_depth(dataset.samples[j][2])
        K = dataset.K
        ui = np.round(x / z * K[0, 0] + K[0, 2]).astype(np.int64)
        vi = np.round(y / z * K[1, 1] + K[1, 2]).astype(np.int64)
        ok = (z > 0.2) & (ui >= 0) & (ui < dataset.width) & (vi >= 0) & (vi < dataset.height)
        ui_c = np.clip(ui, 0, dataset.width - 1)
        vi_c = np.clip(vi, 0, dataset.height - 1)
        djv = dj[vi_c, ui_c]
        seen = ok & (djv > 0)
        agree = seen & (np.abs(djv - z) < tol_base + tol_rel * z)
        total += agree
        valid += seen
    need = np.maximum(1, (min_ratio * np.maximum(valid, 1)).astype(np.int32))
    return (valid > 0) & (total >= need)


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
