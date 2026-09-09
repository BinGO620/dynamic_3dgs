"""Dataset loaders for offline dynamic 3DGS with ground-truth poses.

Bonn RGB-D and TUM RGB-D share the TUM directory layout:
    rgb.txt / depth.txt / groundtruth.txt / (associations.txt)
Ground-truth poses are TUM-format quaternions (camera-to-world); we invert to
world-to-camera for rasterization. Bonn images carry lens distortion
(MonoGS-compatible handling: remap with newCameraMatrix=K, depth via NEAREST).

This module is deliberately self-contained (no monogs-ours runtime dependency).
"""

from __future__ import annotations

import os

import cv2
import numpy as np
import torch
from PIL import Image


def _load_tum_list(filepath: str) -> np.ndarray:
    return np.loadtxt(filepath, comments="#").astype(np.float64)


def _load_tum_filelist(filepath: str):
    """rgb.txt / depth.txt rows: timestamp filename (3 header comment lines)."""
    rows = []
    with open(filepath) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            t, fname = line.split()[:2]
            rows.append((float(t), fname))
    return rows


def quat_to_mat(qx: float, qy: float, qz: float, qw: float) -> np.ndarray:
    """TUM quaternion (x, y, z, w) -> 3x3 rotation matrix."""
    q = np.array([qx, qy, qz, qw], dtype=np.float64)
    q = q / max(np.linalg.norm(q), 1e-12)
    x, y, z, w = q
    return np.array(
        [
            [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
            [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
            [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
        ]
    )


def _interp_pose(pose_data: np.ndarray, t: float) -> np.ndarray | None:
    """Linear interpolation of a TUM pose row set at time ``t`` (quaternion
    lerp + renormalize; pose stream is 100 Hz so gaps are small)."""
    ts = pose_data[:, 0]
    if t < ts[0] or t > ts[-1]:
        return None
    i = np.searchsorted(ts, t)
    if i == 0:
        row = pose_data[0]
    else:
        t0, t1 = ts[i - 1], ts[i]
        row0, row1 = pose_data[i - 1], pose_data[i]
        a = 0.0 if t1 == t0 else (t - t0) / (t1 - t0)
        row = row0 + a * (row1 - row0)
    T = np.eye(4)
    T[:3, :3] = quat_to_mat(row[4], row[5], row[6], row[7])
    T[:3, 3] = row[1:4]
    return T


class TumFormatDataset(torch.utils.data.Dataset):
    """Bonn / TUM RGB-D sequence with GT poses, undistortion, and frame split.

    Args mirror configs: ``path`` (sequence dir), calibration block
    (fx/fy/cx/cy/k1/k2/p1/p2/k3/width/height/depth_scale), ``max_frames``,
    ``eval_stride`` (frames with idx % eval_stride == 0 form the eval set;
    the rest are trained on).
    """

    def __init__(
        self,
        path: str,
        calibration: dict,
        max_frames: int = -1,
        eval_stride: int = 5,
        train_views: int = 500,
        max_dt: float = 0.02,
        device: str = "cpu",
    ):
        """``train_views`` caps the number of training views: offline 3DGS needs
        each view visited ~dozens of times; training on all frames (30Hz video)
        gives ~2 visits per view at 15k steps and the model never converges.
        Eval frames (i % eval_stride == 0) are always excluded from training.
        """
        self.path = path
        self.width = int(calibration["width"])
        self.height = int(calibration["height"])
        self.depth_scale = float(calibration.get("depth_scale", 5000.0))
        self.device = device

        self.K = np.array(
            [
                [calibration["fx"], 0.0, calibration["cx"]],
                [0.0, calibration["fy"], calibration["cy"]],
                [0.0, 0.0, 1.0],
            ]
        )
        self.dist_coeffs = np.array(
            [
                calibration.get("k1", 0.0),
                calibration.get("k2", 0.0),
                calibration.get("p1", 0.0),
                calibration.get("p2", 0.0),
                calibration.get("k3", 0.0),
            ]
        )
        distorted = bool(calibration.get("distorted", False))
        if distorted:
            self.map1x, self.map1y = cv2.initUndistortRectifyMap(
                self.K, self.dist_coeffs, np.eye(3), self.K,
                (self.width, self.height), cv2.CV_32FC1,
            )
        else:
            self.map1x, self.map1y = None, None

        rgb = _load_tum_filelist(os.path.join(path, "rgb.txt"))
        depth = _load_tum_filelist(os.path.join(path, "depth.txt"))
        poses = _load_tum_list(os.path.join(path, "groundtruth.txt"))

        # associate rgb <-> depth <-> pose by timestamp
        d_ts = np.array([t for t, _ in depth])
        samples = []
        n_missing = 0
        for t_rgb, rgb_f in rgb:
            j = np.searchsorted(d_ts, t_rgb)
            cand = [k for k in (j - 1, j) if 0 <= k < len(d_ts)]
            j = min(cand, key=lambda k: abs(d_ts[k] - t_rgb), default=-1)
            if j < 0 or abs(d_ts[j] - t_rgb) > max_dt:
                continue
            if not (os.path.isfile(os.path.join(path, rgb_f))
                    and os.path.isfile(os.path.join(path, depth[j][1]))):
                n_missing += 1
                continue
            T_wc = _interp_pose(poses, t_rgb)
            if T_wc is None:
                continue
            samples.append((t_rgb, rgb_f, depth[j][1], np.linalg.inv(T_wc)))
        if n_missing:
            print(f"[dataset] skipped {n_missing} frames with missing files")
        if max_frames > 0:
            samples = samples[:max_frames]
        self.samples = samples

        self.eval_stride = eval_stride
        self.is_eval = np.array([i % eval_stride == 0 for i in range(len(self.samples))])
        # fixed-count training views spread uniformly over non-eval frames
        # (train_views <= 0 = use ALL non-eval frames; legacy_core streaming)
        n_train = int(train_views)
        candidates = np.where(~self.is_eval)[0]
        if n_train > 0 and len(candidates) > n_train:
            sel = np.linspace(0, len(candidates) - 1, n_train).astype(int)
            candidates = candidates[sel]
        self.is_train = np.zeros(len(self.samples), dtype=bool)
        self.is_train[candidates] = True

    # --- convenience API -------------------------------------------------
    @property
    def train_indices(self) -> np.ndarray:
        return np.where(self.is_train)[0]

    @property
    def eval_indices(self) -> np.ndarray:
        return np.where(self.is_eval)[0]

    def __len__(self) -> int:
        return len(self.samples)

    def _load_rgb(self, fname: str) -> np.ndarray:
        img = np.array(Image.open(os.path.join(self.path, fname)))
        if self.map1x is not None:
            img = cv2.remap(img, self.map1x, self.map1y, cv2.INTER_LINEAR)
        return img

    def _load_depth(self, fname: str) -> np.ndarray:
        d = np.array(Image.open(os.path.join(self.path, fname))).astype(np.float32)
        d /= self.depth_scale
        if self.map1x is not None:
            d = cv2.remap(d, self.map1x, self.map1y, cv2.INTER_NEAREST)
        return d

    def get_frame(self, idx: int) -> dict:
        t, rgb_f, depth_f, T_cw = self.samples[idx]
        rgb = self._load_rgb(rgb_f)  # (H, W, 3) uint8
        depth = self._load_depth(depth_f)  # (H, W) float metres
        return {
            "idx": idx,
            "t": float(t),
            "rgb": torch.from_numpy(rgb.astype(np.float32) / 255.0)
            .permute(2, 0, 1)
            .clamp(0.0, 1.0),
            "depth": torch.from_numpy(depth),
            "T_cw": torch.from_numpy(T_cw.astype(np.float32)),
        }

    def __getitem__(self, idx: int) -> dict:
        return self.get_frame(idx)

    def calibration(self) -> dict:
        return {"K": self.K, "width": self.width, "height": self.height}


def make_dataset(cfg: dict, device: str = "cpu") -> TumFormatDataset:
    ds_cfg = cfg["dataset"]
    return TumFormatDataset(
        path=ds_cfg["path"],
        calibration=ds_cfg["calibration"],
        max_frames=int(ds_cfg.get("max_frames", -1)),
        eval_stride=int(ds_cfg.get("eval_stride", 5)),
        train_views=int(ds_cfg.get("train_views", 500)),
        max_dt=float(ds_cfg.get("max_dt", 0.02)),
        device=device,
    )
