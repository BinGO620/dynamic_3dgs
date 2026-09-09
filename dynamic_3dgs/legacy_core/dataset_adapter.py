"""Adapter: our TumFormatDataset (dict interface) -> MonoGS mapping interface.

legacy_core expects a dataset with attributes fx/fy/cx/cy/fovx/fovy/width/
height/device and ``__getitem__(idx) -> (color CHW tensor [0,1], depth HxW
float32 numpy, pose 4x4 world-to-camera torch)``. Parsing, undistortion and
GT-pose interpolation stay in dynamic_3dgs.dataset (already validated).
"""

import numpy as np
import torch

from dynamic_3dgs.dataset import TumFormatDataset, make_dataset


def _fov_from_focal(focal: float, pixels: int) -> float:
    return float(2 * np.arctan(pixels / (2 * focal)))


class MonoGSStyleDataset:
    def __init__(self, inner: TumFormatDataset, device: str = "cuda:0"):
        # device is the Camera tensor device (CUDA — the w-pose rasterizer
        # requires device-side R/T/projection). Images stay CPU: Camera keeps
        # original_image/depth as loaded and the loss moves them per-use.
        self.inner = inner
        self.device = device
        calib = inner.calibration()
        self.width = int(calib["width"])
        self.height = int(calib["height"])
        K = calib["K"]
        self.fx = float(K[0, 0])
        self.fy = float(K[1, 1])
        self.cx = float(K[0, 2])
        self.cy = float(K[1, 2])
        self.fovx = _fov_from_focal(self.fx, self.width)
        self.fovy = _fov_from_focal(self.fy, self.height)

    def __len__(self):
        return len(self.inner)

    def __getitem__(self, idx):
        frame = self.inner.get_frame(idx)
        color = frame["rgb"]  # CHW float32 [0,1]
        depth = frame["depth"].numpy().astype(np.float32)  # HxW metres
        pose = frame["T_cw"].float()  # 4x4 world-to-camera
        return color, depth, pose

    @property
    def eval_indices(self):
        return self.inner.eval_indices

    @property
    def train_indices(self):
        return self.inner.train_indices


def load_monogs_dataset(cfg: dict, device: str = "cuda:0") -> MonoGSStyleDataset:
    # legacy core streams every non-eval frame (MonoGS semantics): disable the
    # train_views subsampling cap that the gsplat trainer protocol (A3) needs.
    cfg = dict(cfg)
    ds_cfg = dict(cfg["dataset"])
    ds_cfg["train_views"] = -1
    cfg["dataset"] = ds_cfg
    return MonoGSStyleDataset(make_dataset(cfg, device=device), device=device)
