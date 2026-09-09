"""Offline rendering evaluation for the legacy mapping core.

eval_rendering adapted from monogs-ours utils/eval_utils.py (which itself
extends stock MonoGS): adds per-frame depth L1 in cm via
_compute_depth_l1_cm and robust finite-mean aggregation. SLAM-side pieces
(eval_ate, wandb, depth-ratio debug) are dropped — poses are GT here.
"""

import json
import os

import cv2
import numpy as np
import torch
from torchmetrics.image import LearnedPerceptualImagePatchSimilarity

from dynamic_3dgs.legacy_core.renderer import render
from dynamic_3dgs.legacy_core.utils.image_utils import psnr
from dynamic_3dgs.legacy_core.utils.loss_utils import ssim
from dynamic_3dgs.legacy_core.utils.system_utils import mkdir_p


def _compute_depth_l1_cm(render_depth, gt_depth):
    if gt_depth is None:
        return None
    depth = render_depth.squeeze()
    gt_depth_t = torch.as_tensor(gt_depth, device=depth.device, dtype=depth.dtype)
    valid = (gt_depth_t > 0) & torch.isfinite(gt_depth_t) & torch.isfinite(depth)
    if not valid.any():
        return None
    return torch.mean(torch.abs(depth[valid] - gt_depth_t[valid])).item() * 100.0


def _compute_depth_l1_cm_coverage(render_depth, gt_depth):
    """Coverage-masked variant: only pixels where the map actually renders
    depth (>1cm). Raw _compute_depth_l1_cm charges uncovered (0-depth) pixels
    at full weight, so sparse-keyframe maps look metres off. Supplementary
    metric — the preregistered gate is PSNR."""
    if gt_depth is None:
        return None, None
    depth = render_depth.squeeze()
    gt_depth_t = torch.as_tensor(gt_depth, device=depth.device, dtype=depth.dtype)
    valid = (gt_depth_t > 0) & torch.isfinite(gt_depth_t) & torch.isfinite(depth)
    cov = valid & (depth > 0.01)
    l1_all = torch.mean(torch.abs(depth[valid] - gt_depth_t[valid])).item() * 100.0
    if not cov.any():
        return l1_all, 0.0
    l1_cov = torch.mean(torch.abs(depth[cov] - gt_depth_t[cov])).item() * 100.0
    return l1_cov, cov.float().sum().item() / valid.float().sum().item()


def eval_rendering(
    dataset,
    gaussians,
    save_dir,
    pipe,
    background,
    kf_indices,
    projection_matrix,
    iteration="final",
    eval_exposure_aligned=True,
):
    """Render every 5th frame with GT pose and report PSNR (raw +
    exposure-aligned) / SSIM / LPIPS / depth L1-cm.

    Cameras are built on the fly from the dataset: held-out frames are
    never instantiated by the mapper. Keyframes (trained-on) are skipped,
    so frame 0 — the exempt init keyframe — is also skipped.
    """
    interval = 5
    end_idx = len(dataset) if iteration == "final" else int(iteration)
    psnr_array, ssim_array, lpips_array, depth_l1_array = [], [], [], []
    depth_l1_cov_array, cov_ratio_array, psnr_aligned_array = [], [], []
    saved_frame_idx = []
    cal_lpips = LearnedPerceptualImagePatchSimilarity(
        net_type="alex", normalize=True
    ).to("cuda")
    from dynamic_3dgs.legacy_core.camera import Camera

    for idx in range(0, end_idx, interval):
        if idx in kf_indices:
            continue
        saved_frame_idx.append(idx)
        frame = Camera.init_from_dataset(dataset, idx, projection_matrix)
        gt_image, gt_depth, _ = dataset[idx]
        gt_image = gt_image.cuda()  # images are CPU-stored; metrics run on CUDA

        render_pkg = render(frame, gaussians, pipe, background)
        rendering = render_pkg["render"]
        image = torch.clamp(rendering, 0.0, 1.0)

        mask = gt_image > 0
        psnr_array.append(
            psnr((image[mask]).unsqueeze(0), (gt_image[mask]).unsqueeze(0)).item()
        )
        ssim_array.append(ssim((image).unsqueeze(0), (gt_image).unsqueeze(0)).item())
        lpips_array.append(
            cal_lpips((image).unsqueeze(0), (gt_image).unsqueeze(0)).item()
        )
        # exposure-aligned PSNR (v3 precedent: report raw + aligned): closed-form
        # per-frame least-squares a,b  min ||a*img+b-gt||  over valid pixels
        if eval_exposure_aligned:
            img_v = image[mask].reshape(-1, 1)
            gt_v = gt_image[mask].reshape(-1, 1)
            A = torch.cat([img_v, torch.ones_like(img_v)], dim=1)
            sol = torch.linalg.lstsq(A, gt_v).solution
            img_a = torch.clamp((A @ sol).reshape_as(image[mask]), 0.0, 1.0)
            psnr_aligned_array.append(
                psnr(img_a.unsqueeze(0), (gt_image[mask]).unsqueeze(0)).item()
            )
        depth_l1_cm = _compute_depth_l1_cm(render_pkg["depth"], gt_depth)
        depth_l1_cov, cov_ratio = _compute_depth_l1_cm_coverage(
            render_pkg["depth"], gt_depth
        )
        if depth_l1_cm is not None:
            depth_l1_array.append(depth_l1_cm)
            depth_l1_cov_array.append(depth_l1_cov)
            cov_ratio_array.append(cov_ratio)

    output = dict()
    output["frames"] = saved_frame_idx

    def _finite_mean(vals):
        arr = np.asarray(vals, dtype=float)
        finite = arr[np.isfinite(arr)]
        return (float(np.mean(finite)) if finite.size else float("nan")), int(
            arr.size - finite.size
        )

    output["mean_psnr"], n_drop = _finite_mean(psnr_array)
    output["mean_psnr_aligned"], _ = _finite_mean(psnr_aligned_array)
    output["mean_ssim"], _ = _finite_mean(ssim_array)
    output["mean_lpips"], _ = _finite_mean(lpips_array)
    output["mean_depth_l1_cm"] = (
        float(np.mean(depth_l1_array)) if depth_l1_array else None
    )
    output["mean_depth_l1_cm_cov"] = (
        float(np.mean(depth_l1_cov_array)) if depth_l1_cov_array else None
    )
    output["mean_depth_coverage"] = (
        float(np.mean(cov_ratio_array)) if cov_ratio_array else None
    )
    output["n_eval_frames"] = len(psnr_array)
    if n_drop:
        print(f"[eval] dropped {n_drop}/{len(psnr_array)} non-finite eval frames")
    print(
        f"[eval] psnr: {output['mean_psnr']:.3f} ssim: {output['mean_ssim']:.4f} "
        f"lpips: {output['mean_lpips']:.4f} depth_l1_cm: {output['mean_depth_l1_cm']}"
    )

    psnr_save_dir = os.path.join(save_dir, "psnr", str(iteration))
    mkdir_p(psnr_save_dir)
    with open(os.path.join(psnr_save_dir, "final_result.json"), "w") as f:
        json.dump(output, f, indent=4)
    return output
