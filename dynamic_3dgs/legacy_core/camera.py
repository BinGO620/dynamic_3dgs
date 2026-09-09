"""Camera for the legacy (MonoGS-derived) offline mapping core.

Adapted from stock MonoGS utils/camera_utils.py: the tracking-only pieces
(grad_mask for pose refinement, init_from_gui) are dropped; poses are
ground-truth and never optimized, but cam_rot_delta / cam_trans_delta are
kept as zero parameters because the w-pose rasterizer API requires them.
Exposure parameters are kept and optimized exactly as in MonoGS mapping.
"""

import torch
from torch import nn

from dynamic_3dgs.legacy_core.utils.graphics_utils import (
    getProjectionMatrix2,
    getWorld2View2,
)


class Camera(nn.Module):
    def __init__(
        self,
        uid,
        color,
        depth,
        gt_T,
        projection_matrix,
        fx,
        fy,
        cx,
        cy,
        fovx,
        fovy,
        image_height,
        image_width,
        device="cuda:0",
    ):
        super().__init__()
        self.uid = uid
        self.device = device

        # GT world-to-camera pose; R/T are never updated (no tracking/BA here).
        T = gt_T.to(device=device).float()
        self.R = T[:3, :3]
        self.T = T[:3, 3]
        self.R_gt = self.R.clone()
        self.T_gt = self.T.clone()

        # CHW RGB in [0, 1]; kept on CPU (data_device="cpu" policy) and moved
        # to CUDA inside the loss, same as MonoGS with CPU-stored keyframes.
        self.original_image = color
        # HxW float32 numpy (metres), as MonoGS get_loss_mapping_rgbd expects.
        self.depth = depth

        self.fx = fx
        self.fy = fy
        self.cx = cx
        self.cy = cy
        self.FoVx = fovx
        self.FoVy = fovy
        self.image_height = image_height
        self.image_width = image_width

        self.cam_rot_delta = nn.Parameter(
            torch.zeros(3, requires_grad=True, device=device)
        )
        self.cam_trans_delta = nn.Parameter(
            torch.zeros(3, requires_grad=True, device=device)
        )

        self.exposure_a = nn.Parameter(
            torch.tensor([0.0], requires_grad=True, device=device)
        )
        self.exposure_b = nn.Parameter(
            torch.tensor([0.0], requires_grad=True, device=device)
        )

        self.projection_matrix = projection_matrix.to(device=device)

    @staticmethod
    def init_from_dataset(dataset, idx, projection_matrix):
        gt_color, gt_depth, gt_pose = dataset[idx]
        return Camera(
            idx,
            gt_color,
            gt_depth,
            gt_pose,
            projection_matrix,
            dataset.fx,
            dataset.fy,
            dataset.cx,
            dataset.cy,
            dataset.fovx,
            dataset.fovy,
            dataset.height,
            dataset.width,
            device=dataset.device,
        )

    @property
    def world_view_transform(self):
        return getWorld2View2(self.R, self.T).transpose(0, 1)

    @property
    def full_proj_transform(self):
        return (
            self.world_view_transform.unsqueeze(0).bmm(
                self.projection_matrix.unsqueeze(0)
            )
        ).squeeze(0)

    @property
    def camera_center(self):
        return self.world_view_transform.inverse()[3, :3]
