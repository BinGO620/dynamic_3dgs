"""Offline vanilla 3DGS trainer on gsplat (renderer decoupled from monogs-ours).

GT poses + GT depth supervision; adaptive density control via
gsplat.strategy.DefaultStrategy (vanilla clone/split/prune semantics).
"""

from __future__ import annotations

import json
import os
import time

import numpy as np
import torch
import torch.nn.functional as F
from gsplat import rasterization
from gsplat.strategy import DefaultStrategy

from .dataset import TumFormatDataset
from .model import GaussianModel, unproject_frame, voxel_downsample

C0 = 0.28209479177387814


def sh_coeff_to_rgb(sh: torch.Tensor, dirs: torch.Tensor | None = None) -> torch.Tensor:
    """DC-only color (sh0). Higher bands handled inside rasterization."""
    return torch.clamp(sh[..., 0, :] * C0 + 0.5, 0.0, 1.0)


def ssim_loss(img1: torch.Tensor, img2: torch.Tensor, window_size: int = 11) -> torch.Tensor:
    """Standard SSIM on (1,C,H,W); returns 1 - ssim (to add to loss)."""
    c = img1.shape[1]
    coords = torch.arange(window_size, device=img1.device, dtype=torch.float32) - window_size // 2
    g = torch.exp(-(coords ** 2) / (2 * 1.5 ** 2))
    g = (g / g.sum())
    win = (g[:, None] @ g[None, :]).expand(c, 1, window_size, window_size)
    pad = window_size // 2
    mu1 = F.conv2d(img1, win, padding=pad, groups=c)
    mu2 = F.conv2d(img2, win, padding=pad, groups=c)
    m1, m2 = mu1 * mu1, mu2 * mu2
    m12 = mu1 * mu2
    s1 = F.conv2d(img1 * img1, win, padding=pad, groups=c) - m1
    s2 = F.conv2d(img2 * img2, win, padding=pad, groups=c) - m2
    s12 = F.conv2d(img1 * img2, win, padding=pad, groups=c) - m12
    c1, c2 = 0.01 ** 2, 0.03 ** 2
    ssim_map = ((2 * m12 + c1) * (2 * s12 + c2)) / ((m1 + m2 + c1) * (s1 + s2 + c2))
    return 1.0 - ssim_map.mean()


class Trainer:
    def __init__(self, dataset: TumFormatDataset, cfg: dict, device: str = "cuda"):
        self.ds = dataset
        self.cfg = cfg
        self.device = device
        self.K = torch.from_numpy(dataset.K.astype(np.float32)).to(device)
        self.width, self.height = dataset.width, dataset.height

        t_indices = dataset.train_indices
        n_init = int(cfg.get("init_frames", 10))
        sel = np.linspace(0, len(t_indices) - 1, min(n_init, len(t_indices))).astype(int)
        pts_all, cols_all = [], []
        for si in sel:
            frame = dataset.get_frame(int(t_indices[si]))
            p, c = unproject_frame(frame, dataset.K, int(cfg.get("init_stride", 4)))
            pts_all.append(p)
            cols_all.append(c)
        pts = np.concatenate(pts_all)
        cols = np.concatenate(cols_all)
        pts, cols = voxel_downsample(pts, cols, float(cfg.get("init_voxel", 0.04)))
        print(f"[trainer] init cloud: {pts.shape[0]} points "
              f"from {len(sel)} frames (voxel {cfg.get('init_voxel', 0.04)}m)", flush=True)
        self.model = GaussianModel(
            pts, cols,
            sh_degree=int(cfg.get("sh_degree", 3)),
            device=device,
        )
        lrs = {
            "means": cfg.get("lr_means", 1.6e-4),
            "quats": cfg.get("lr_quats", 1e-3),
            "scales": cfg.get("lr_scales", 5e-3),
            "opacities": cfg.get("lr_opacities", 5e-2),
            "sh0": cfg.get("lr_sh0", 2.5e-3),
            "shN": cfg.get("lr_shN", 2.5e-3 / 20),
        }
        self.opts = self.model.optimizers(lrs)
        self.scheds = self.model.schedulers(self.opts, int(cfg.get("steps", 15000)))
        self.depth_weight = float(cfg.get("depth_weight", 0.15))
        self.dssim_weight = float(cfg.get("dssim_weight", 0.2))
        self.steps = int(cfg.get("steps", 15000))
        self.n_train = len(dataset.train_indices)
        self._rng = np.random.default_rng(int(cfg.get("seed", 0)))

        self.strategy = DefaultStrategy(
            prune_opa=cfg.get("prune_opa", 0.005),
            grow_grad2d=cfg.get("grow_grad2d", 0.0002),
            grow_scale3d=cfg.get("grow_scale3d", 0.01),
            grow_scale2d=cfg.get("grow_scale2d", 0.05),
            refine_start_iter=cfg.get("refine_start_iter", 500),
            refine_stop_iter=self.steps,
            reset_every=cfg.get("reset_every", 3000),
            refine_every=cfg.get("refine_every", 100),
            revised_opacity=True,
            verbose=False,
        )
        # scene_scale in METRES (gsplat default 1.0 assumes normalized scenes;
        # a metre-scale indoor scene would be mass-pruned by prune_scale3d)
        with torch.no_grad():
            means0 = self.model.params["means"].detach()
            scene_scale = float((means0.max(0).values - means0.min(0).values).norm())
        self.strategy_state = self.strategy.initialize_state(
            scene_scale=max(scene_scale, 1.0)
        )

    def render(self, frame: dict):
        T = frame["T_cw"].to(self.device)
        viewmat = T[None]  # (1,4,4) w2c
        K = self.K[None]
        params = self.model.params
        sh = torch.cat([params["sh0"], params["shN"]], dim=1)  # (N,K,3)
        max_sh = int(np.log2(sh.shape[1] - 1)) if sh.shape[1] > 1 else 0
        renders, alphas, info = rasterization(
            params["means"],
            torch.nn.functional.normalize(params["quats"], dim=-1),
            torch.exp(params["scales"]),
            torch.sigmoid(params["opacities"]),
            sh,  # colors: SH coefficients (used when sh_degree is set)
            viewmat,
            K,
            self.width,
            self.height,
            sh_degree=max_sh,
            render_mode="RGB+D",
            near_plane=0.01,
            far_plane=1e10,
            backgrounds=None,
            packed=False,  # must match DefaultStrategy.step_post_backward(packed=False)
            absgrad=False,
        )
        return renders, alphas, info

    def train_step(self, step: int) -> dict:
        idx = int(self.ds.train_indices[self._rng.integers(self.n_train)])
        frame = self.ds.get_frame(idx)
        rgb_gt = frame["rgb"].to(self.device)[None]  # (1,3,H,W)
        depth_gt = frame["depth"].to(self.device)[None, None]  # (1,1,H,W)

        renders, alphas, info = self.render(frame)
        rgb = renders[0, :, :, :3].permute(2, 0, 1)[None]  # (1,3,H,W)
        depth = renders[0, :, :, 3][None, None]

        self.strategy.step_pre_backward(
            self.model.params, self.opts, self.strategy_state, step, info
        )

        l1_rgb = torch.abs(rgb - rgb_gt).mean()
        loss = (1 - self.dssim_weight) * l1_rgb + self.dssim_weight * ssim_loss(rgb, rgb_gt)
        dmask = (depth_gt > 0).float()
        l1_depth = (torch.abs(depth - depth_gt) * dmask).sum() / dmask.sum().clamp_min(1)
        loss = loss + self.depth_weight * l1_depth

        loss.backward()
        self.strategy.step_post_backward(
            self.model.params, self.opts, self.strategy_state, step, info
        )

        for o in self.opts.values():
            o.step()
            o.zero_grad(set_to_none=True)
        for s in self.scheds.values():
            s.step()

        return {"loss": float(loss.item()), "l1_rgb": float(l1_rgb.item()),
                "l1_depth": float(l1_depth.item()), "n_gauss": self.model.n_gaussians}

    def train(self, log_every: int = 500) -> list:
        log = []
        t_start = time.time()
        for step in range(1, self.steps + 1):
            stats = self.train_step(step)
            if step % log_every == 0 or step == self.steps:
                stats["step"] = step
                stats["elapsed_s"] = round(time.time() - t_start, 1)
                log.append(stats)
                print(f"[step {step:6d}] loss={stats['loss']:.4f} "
                      f"l1_rgb={stats['l1_rgb']:.4f} l1_depth={stats['l1_depth']:.4f} "
                      f"n_gauss={stats['n_gauss']}", flush=True)
        return log

    def save(self, path: str):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        np.savez_compressed(path, **self.model.state_dict())
