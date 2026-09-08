"""Offline vanilla 3DGS trainer on gsplat (renderer decoupled from monogs-ours).

Stage-0.5 protocol (evidence: NOTES 踩坑 + Codex review + literature):
- fused init from ALL training views, filtered by temporal static consistency
  (dynamic shells — robot/people/box — must not enter the map);
- per-point pixel-footprint scale init (z/focal * stride);
- per-view exposure compensation (log-gain + bias, regularized);
- SH degree ramp 0->max (degree-3 from step 0 encodes ghosts/exposure);
- depth-residual densification: insert static-consistent points where the
  render has holes (alpha<0.4) or depth residual > 20cm (replaces the broken
  gsplat DefaultStrategy gradient machinery, see NOTES);
- periodic low-opacity prune; scale clamp as a safety net.
"""

from __future__ import annotations

import json
import os
import time

import numpy as np
import torch
import torch.nn.functional as F
from gsplat import rasterization

from .dataset import TumFormatDataset
from .model import GaussianModel, static_agreement_ratio, unproject_frame

C0 = 0.28209479177387814


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

        self.steps = int(cfg.get("steps", 15000))
        self.depth_weight = float(cfg.get("depth_weight", 0.15))
        self.depth_alpha_min = float(cfg.get("depth_alpha_min", 0.5))
        self.scale_max = float(cfg.get("scale_max", 0.08))
        self.dssim_weight = float(cfg.get("dssim_weight", 0.2))
        self.opacity_init = float(cfg.get("opacity_init", 0.1))
        self.static_filter = bool(cfg.get("static_filter", True))
        self.densify_every = int(cfg.get("densify_every", 250))
        self.densify_start = int(cfg.get("densify_start", 2000))
        self.densify_max_px = int(cfg.get("densify_max_px", 3000))
        self.densify_depth_thr = float(cfg.get("densify_depth_thr", 0.2))
        self.densify_alpha_thr = float(cfg.get("densify_alpha_thr", 0.4))
        self.prune_every = int(cfg.get("prune_every", 2000))
        self.prune_opa = float(cfg.get("prune_opa", 0.01))
        # stage-1 lifecycle gate (M-a retire / M-b confirm)
        self.lifecycle = str(cfg.get("lifecycle", "off"))  # off | retire | full
        self.ev_tau = float(cfg.get("ev_tau", 0.15))       # EMA rate per update
        self.retire_every = int(cfg.get("retire_every", 1000))
        self.retire_ev = float(cfg.get("retire_ev", 0.2))  # evidence below -> retire
        self.retire_min_age = int(cfg.get("retire_min_age", 2000))
        self.confirm_every = int(cfg.get("confirm_every", 1000))
        self.confirm_ev = float(cfg.get("confirm_ev", 0.6))
        self.confirm_min_vis = int(cfg.get("confirm_min_vis", 3))
        self.n_train = len(dataset.train_indices)
        self._rng = np.random.default_rng(int(cfg.get("seed", 0)))

        self._build_model(cfg)

        lrs = {
            "means": cfg.get("lr_means", 1.6e-4),
            "quats": cfg.get("lr_quats", 1e-3),
            "scales": cfg.get("lr_scales", 2.5e-3),
            "opacities": cfg.get("lr_opacities", 5e-2),
            "sh0": cfg.get("lr_sh0", 2.5e-3),
            "shN": cfg.get("lr_shN", 1.25e-4),
        }
        self.opts = self.model.optimizers(lrs)
        frac = float(cfg.get("final_lr_frac", 0.1))
        self.scheds = self.model.schedulers(self.opts, self.steps, final_lr_frac=frac)
        # per-training-view exposure compensation (log-gain, bias) per channel
        self.use_exposure = bool(cfg.get("use_exposure", True))
        if self.use_exposure:
            self.exp_gain = torch.zeros(self.n_train, 3, device=device, requires_grad=True)
            self.exp_bias = torch.zeros(self.n_train, 3, device=device, requires_grad=True)
            self.opt_exp = torch.optim.Adam(
                [{"params": [self.exp_gain], "lr": 5e-3},
                 {"params": [self.exp_bias], "lr": 5e-3}])
        else:
            self.exp_gain = self.exp_bias = self.opt_exp = None
        self._train_row = {int(v): k for k, v in enumerate(dataset.train_indices)}
        self.max_sh = self.model.sh_degree
        if self.lifecycle != "off":
            self.model.init_ledger(device=device, birth_step=0)

    # ------------------------------------------------------------------ init
    def _soft_opacity(self, ratio: np.ndarray) -> np.ndarray:
        """Soft static-consistency opacity prior: consensus surfaces keep the
        base opacity; dynamic shells / never-observed points start dim (they
        can still grow if photometrically supported)."""
        floor = float(self.cfg.get("sc_opacity_floor", 0.15))
        base = float(self.cfg.get("opacity_init", 0.1))
        return base * np.clip(floor + (1 - floor) * ratio, floor, 1.0)

    def _build_model(self, cfg: dict):
        t_indices = self.ds.train_indices
        pts_all, cols_all, sc_all, op_all = [], [], [], []
        for k, si in enumerate(t_indices):
            frame = self.ds.get_frame(int(si))
            p, c, s = unproject_frame(frame, self.ds.K, int(cfg.get("init_stride", 4)))
            if self.static_filter:
                ratio = static_agreement_ratio(
                    self.ds, int(si), p,
                    n_ref=int(cfg.get("sc_refs", 4)),
                    tol_base=float(cfg.get("sc_tol_base", 0.08)),
                    tol_rel=float(cfg.get("sc_tol_rel", 0.03)),
                )
                o = self._soft_opacity(ratio)
            else:
                o = np.full(p.shape[0], self.opacity_init, dtype=np.float32)
            pts_all.append(p); cols_all.append(c); sc_all.append(s); op_all.append(o)
            if k % 100 == 0:
                print(f"[trainer] init fuse {k}/{len(t_indices)} "
                      f"(kept {p.shape[0]})", flush=True)
        pts = np.concatenate(pts_all); cols = np.concatenate(cols_all)
        scs = np.concatenate(sc_all); ops = np.concatenate(op_all)
        pts, idx = voxel_downsample_idx(pts, float(cfg.get("init_voxel", 0.02)))
        cols, scs, ops = cols[idx], scs[idx], ops[idx]
        print(f"[trainer] init cloud: {pts.shape[0]} points from {len(t_indices)} "
              f"train views (static_filter={self.static_filter})", flush=True)
        self.model = GaussianModel(
            pts, cols, scs,
            sh_degree=int(cfg.get("sh_degree", 3)),
            device=self.device,
            opacity_init=self.opacity_init,
            opacities=ops,
        )

    # --------------------------------------------------------------- render
    def active_sh_degree(self, step: int) -> int:
        ramp = int(self.cfg.get("sh_ramp", 1))
        if not ramp:
            return self.max_sh
        # degree d unlocked at 2000*(d+1) steps (0deg: 0-2k, 1: 2-4k, 2: 4-6k, 3: 6k+)
        d = max(0, (step // 2000) - 1)
        return min(d, self.max_sh)

    def render(self, frame: dict, step: int | None = None):
        T = frame["T_cw"].to(self.device)
        params = self.model.params
        sh = torch.cat([params["sh0"], params["shN"]], dim=1)
        deg = self.active_sh_degree(step) if step is not None else self.max_sh
        renders, alphas, info = rasterization(
            params["means"],
            torch.nn.functional.normalize(params["quats"], dim=-1),
            torch.exp(params["scales"]),
            torch.sigmoid(params["opacities"]),
            sh,
            T[None],
            self.K[None],
            self.width,
            self.height,
            sh_degree=deg,
            render_mode="RGB+ED",
            near_plane=0.01,
            far_plane=1e10,
            packed=False,
        )
        # gsplat quirk: renders height-first (C,H,W,D); alphas (C,H,W,1)
        if alphas.dim() == 4:
            alphas = alphas[..., 0]
        return renders, alphas, info

    # ------------------------------------------------------- param surgery
    def _rebuild_opts(self):
        lrs = {g["name"]: g["lr"] for o in self.opts.values()
               for g in o.param_groups if "name" in g}
        self.opts = self.model.optimizers(lrs)
        frac = float(self.cfg.get("final_lr_frac", 0.1))
        self.scheds = self.model.schedulers(self.opts, self.steps, final_lr_frac=frac)

    def _insert(self, pts: np.ndarray, cols: np.ndarray, scs: np.ndarray,
                opacities: np.ndarray | None = None):
        dev = self.device
        n = pts.shape[0]
        if opacities is None:
            o = np.full(n, np.clip(self.opacity_init, 1e-3, 0.9))
        else:
            o = np.clip(opacities, 1e-3, 0.9)
        new = {
            "means": torch.from_numpy(pts).float().to(dev),
            "quats": torch.tensor([[1.0, 0, 0, 0]], device=dev).repeat(n, 1),
            "scales": torch.log(torch.clamp(
                torch.from_numpy(scs).float().to(dev), 1e-4, 1.0))[:, None].repeat(1, 3),
            "opacities": torch.from_numpy(np.log(o / (1 - o))).float().to(dev),
            "sh0": ((torch.from_numpy(cols).float().to(dev) - 0.5) / C0).unsqueeze(1),
            "shN": torch.zeros(n, (self.max_sh + 1) ** 2 - 1, 3, device=dev),
        }
        for k, p in self.model.params.items():
            self.model.params[k] = torch.nn.Parameter(
                torch.cat([p.data, new[k]]), requires_grad=p.requires_grad)
        self._rebuild_opts()

    def _prune_low_opacity(self):
        with torch.no_grad():
            keep = torch.sigmoid(self.model.params["opacities"]) >= self.prune_opa
        if bool(keep.all()):
            return 0
        for k, p in self.model.params.items():
            self.model.params[k] = torch.nn.Parameter(
                p.data[keep], requires_grad=p.requires_grad)
        self._rebuild_opts()
        return int((~keep).sum())

    # ----------------------------------------------------------- train step
    def train_step(self, step: int) -> dict:
        row = int(self._rng.integers(self.n_train))
        idx = int(self.ds.train_indices[row])
        frame = self.ds.get_frame(idx)
        rgb_gt = frame["rgb"].to(self.device)[None]
        depth_gt = frame["depth"].to(self.device)[None, None]

        renders, alphas, info = self.render(frame, step)
        rgb = renders[0, :, :, :3].permute(2, 0, 1)[None]
        depth = renders[0, :, :, 3][None, None]

        if self.use_exposure:
            g = self.exp_gain[row]
            b = self.exp_bias[row]
            rgb = rgb * torch.exp(g)[None, :, None, None] + b[None, :, None, None]
            rgb = rgb.clamp(0.0, 1.0)

        cov = (alphas[0] >= self.depth_alpha_min) & (depth_gt[0, 0] > 0)
        l1_depth = (torch.abs(depth - depth_gt)[0, 0][cov]).mean() if bool(cov.any()) \
            else torch.zeros((), device=self.device)
        # RGB also masked to covered pixels: uncovered ones render black and
        # would dominate the loss; hole coverage is densification's job
        l1_rgb = torch.abs(rgb - rgb_gt)[0, :, cov].mean() if bool(cov.any()) \
            else torch.abs(rgb - rgb_gt).mean()
        loss = (1 - self.dssim_weight) * l1_rgb + self.dssim_weight * ssim_loss(rgb, rgb_gt)
        loss = loss + self.depth_weight * l1_depth
        if self.use_exposure:
            loss = loss + 1e-3 * (self.exp_gain[row] ** 2).sum() \
                        + 1e-3 * (self.exp_bias[row] ** 2).sum()

        loss.backward()
        for o in self.opts.values():
            o.step()
            o.zero_grad(set_to_none=True)
        if self.use_exposure:
            self.opt_exp.step()
            self.opt_exp.zero_grad(set_to_none=True)
        with torch.no_grad():
            self.model.params["scales"].clamp_(max=float(np.log(self.scale_max)))
        for s in self.scheds.values():
            s.step()

        densified = 0
        if self.densify_every and step >= self.densify_start and step % self.densify_every == 0:
            densified = self._densify_residual(step)
            if self.lifecycle != "off" and densified:
                self.model.ledger_append(birth_step=step, confirmed=(self.lifecycle != "full"))
        pruned = 0
        if self.prune_every and step % self.prune_every == 0:
            pruned = self._prune_low_opacity()

        retired = confirmed_n = 0
        if self.lifecycle != "off":
            self._update_evidence(step)
            if step % self.retire_every == 0:
                retired = self._retire(step)
            if self.lifecycle == "full" and step % self.confirm_every == 0:
                confirmed_n = self._confirm()

        return {"loss": float(loss.item()), "l1_rgb": float(l1_rgb.item()),
                "l1_depth": float(l1_depth.item()) if cov.any() else float("nan"),
                "n_gauss": self.model.n_gaussians,
                "inserted": densified, "pruned": pruned,
                "retired": retired, "confirmed": confirmed_n}

    # ------------------------------------------------- lifecycle ledger ops
    def _update_evidence(self, step: int):
        """Batched per-gaussian static-consistency evidence update (EMA).

        Reuses the init-time agreement machinery on the CURRENT parameter
        positions; runs every retire_every steps (O(N x n_ref) numpy)."""
        from .model import static_agreement_ratio
        pts = self.model.params["means"].detach().cpu().numpy()
        n_ref = int(self.cfg.get("sc_refs", 4))
        ratio = static_agreement_ratio(
            self.ds, int(step) % max(len(self.ds), 1), pts,
            n_ref=n_ref,
            tol_base=float(self.cfg.get("sc_tol_base", 0.08)),
            tol_rel=float(self.cfg.get("sc_tol_rel", 0.03)),
        )
        ev = torch.from_numpy(ratio).float().to(self.model.ledger["evidence"].device)
        with torch.no_grad():
            self.model.ledger["evidence"].mul_(1 - self.ev_tau).add_(ev, alpha=self.ev_tau)

    def _retire(self, step: int) -> int:
        """Remove gaussians with age >= retire_min_age and evidence < retire_ev."""
        with torch.no_grad():
            age = step - self.model.ledger["birth"]
            bad = (age >= self.retire_min_age) &                   (self.model.ledger["evidence"] < self.retire_ev)
        n = int(bad.sum())
        if n == 0:
            return 0
        keep = ~bad
        for k, p in self.model.params.items():
            self.model.params[k] = torch.nn.Parameter(
                p.data[keep], requires_grad=p.requires_grad)
        self.model.ledger_prune_keep(keep)
        self._rebuild_opts()
        return n

    def _confirm(self) -> int:
        """M-b: probation points (low-opacity inserts) become full members when
        evidence is high and they are old enough to have been observed."""
        with torch.no_grad():
            elig = (~self.model.ledger["confirmed"]) &                    (self.model.ledger["evidence"] >= self.confirm_ev)
        n = int(elig.sum())
        if n == 0:
            return 0
        with torch.no_grad():
            self.model.ledger["confirmed"][elig] = True
        return n

    def _densify_residual(self, step: int) -> int:
        """Insert static-consistent points where the render has holes or large
        depth residuals (SplaTAM-style, using GT depth — no gradient ADC)."""
        row = int(self._rng.integers(self.n_train))
        idx = int(self.ds.train_indices[row])
        frame = self.ds.get_frame(idx)
        with torch.no_grad():
            renders, alphas, _ = self.render(frame, step)
            rgb_c = renders[0, :, :, :3].permute(2, 0, 1)
            if self.use_exposure:
                g = self.exp_gain[row]; b = self.exp_bias[row]
                rgb_c = (rgb_c * torch.exp(g)[:, None, None] + b[:, None, None]).clamp(0, 1)
            depth = renders[0, :, :, 3]
            alpha = alphas[0]
        gt = frame["depth"].to(self.device)
        err_mask = (gt > 0) & (alpha < self.densify_alpha_thr) | \
                   ((gt > 0) & (alpha >= self.densify_alpha_thr) &
                    ((depth - gt).abs() > self.densify_depth_thr))
        cand = err_mask.nonzero().cpu()
        if cand.shape[0] == 0:
            return 0
        sel = cand[self._rng.choice(cand.shape[0],
                    size=min(self.densify_max_px, cand.shape[0]), replace=False)]
        v = sel[:, 0].numpy().astype(np.float32)
        u = sel[:, 1].numpy().astype(np.float32)
        gt_np = frame["depth"].numpy()
        z = gt_np[v.astype(int), u.astype(int)]
        m = z > 0
        u, v, z = u[m], v[m], z[m]
        if z.size == 0:
            return 0
        K = self.ds.K
        x = (u - K[0, 2]) / K[0, 0] * z
        y = (v - K[1, 2]) / K[1, 1] * z
        pts_cam = np.stack([x, y, z], 1)
        T_wc = np.linalg.inv(frame["T_cw"].numpy())
        pts_w = (T_wc[:3, :3] @ pts_cam.T).T + T_wc[:3, 3]
        ratio = static_agreement_ratio(self.ds, idx, pts_w)
        o = self._soft_opacity(ratio)
        vi = v.astype(int)[m]; ui = u.astype(int)[m]
        cols = rgb_c[:, vi, ui].cpu().numpy().T  # (K,3)
        s = z / float(K[0, 0]) * 2.0  # ~2-pixel footprint
        if self.lifecycle == "full":
            # probation: entry gate halves the soft prior until confirmed
            o = np.clip(o * 0.5, 0.02, 0.9)
        self._insert(pts_w.astype(np.float32), cols.astype(np.float32),
                     s.astype(np.float32), opacities=o.astype(np.float32))
        return int(pts_w.shape[0])

    # -------------------------------------------------------------- public
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
                      f"n={stats['n_gauss']} ins={stats['inserted']} "
                      f"pru={stats['pruned']}", flush=True)
        return log

    def save(self, path: str):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        np.savez_compressed(path, **self.model.state_dict())


def voxel_downsample_idx(points: np.ndarray, voxel: float) -> tuple:
    """First-occurrence-per-voxel downsample; returns (points, keep_idx)."""
    keys = np.floor(points / voxel).astype(np.int64)
    _, idx = np.unique(keys, axis=0, return_index=True)
    idx = np.sort(idx)
    return points[idx], idx
