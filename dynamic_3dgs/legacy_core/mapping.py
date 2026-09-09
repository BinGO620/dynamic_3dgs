"""Offline mapping driver for the legacy (MonoGS-derived) core.

Single-process re-implementation of MonoGS's backend mapping loop with GT
poses: no tracking, no BA, no multiprocessing queues. Semantics ported 1:1
from stock MonoGS utils/slam_backend.py + slam_frontend.py:

- keyframe selection: n_touched-overlap rule (kf_overlap/kf_cutoff/
  kf_translation/kf_min_translation on median depth), sliding window of
  ``window_size`` keyframes with the 2-most-recent untouchable;
- on each keyframe event: extend map with the observed depth
  (invalid-RGB pixels zeroed), then ``map(window, iters=10)``;
- map(): loss over all window keyframes + 2 random older keyframes,
  alpha-blended RGB-D loss, isotropic scale regularizer (weight 10),
  densify_and_prune every ``gaussian_update_every`` iters, non-visible
  opacity reset every ``gaussian_reset`` iters, ``prune_mode="slam"``
  (n_obs <= 3 among recent-window gaussians);
- final: color_refinement (26k iters, no densification), then eval on
  held-out frames with GT pose.

Everything SLAM-side (tracking, pose/delta optimization, BA, loop closure,
submaps) is intentionally absent.
"""

import random

import numpy as np
import torch
from tqdm import tqdm

from dynamic_3dgs.legacy_core.camera import Camera
from dynamic_3dgs.legacy_core.gaussian_model import GaussianModel
from dynamic_3dgs.legacy_core.renderer import render
from dynamic_3dgs.legacy_core.utils.graphics_utils import (
    getProjectionMatrix2,
    getWorld2View2,
)
from dynamic_3dgs.legacy_core.utils.loss_utils import l1_loss, ssim
from dynamic_3dgs.legacy_core.utils.slam_utils import (
    get_loss_mapping,
    get_median_depth,
)


class OfflineMapper:
    def __init__(self, config, dataset, save_dir):
        self.config = config
        self.dataset = dataset
        self.save_dir = save_dir
        self.device = "cuda"

        self.monocular = bool(config["Training"].get("monocular", False))
        self.background = torch.tensor(
            [0.0, 0.0, 0.0], dtype=torch.float32, device=self.device
        )
        self.pipeline_params = type(
            "Pipe", (), {"convert_SHs_python": False, "compute_cov3D_python": False}
        )()

        self.gaussians = GaussianModel(
            config["model_params"]["sh_degree"], config
        )  # params live on cuda by construction (stock MonoGS)
        self.cameras_extent = 6.0  # stock MonoGS slam.py constant
        self.gaussians.init_lr(self.cameras_extent)
        # stock MonoGS passes an OmegaConf object here; plain dict -> namespace
        opt_params = type("OptParams", (), dict(config["opt_params"]))()
        self.gaussians.training_setup(opt_params)

        t = config["Training"]
        self.init_itr_num = t["init_itr_num"]
        self.init_gaussian_update = t["init_gaussian_update"]
        self.init_gaussian_reset = t["init_gaussian_reset"]
        self.init_gaussian_th = t["init_gaussian_th"]
        self.init_gaussian_extent = self.cameras_extent * t["init_gaussian_extent"]
        self.gaussian_update_every = t["gaussian_update_every"]
        self.gaussian_update_offset = t["gaussian_update_offset"]
        self.gaussian_th = t["gaussian_th"]
        self.gaussian_extent = self.cameras_extent * t["gaussian_extent"]
        self.gaussian_reset = t["gaussian_reset"]
        self.size_threshold = t["size_threshold"]
        self.window_size = t["window_size"]
        self.kf_interval = t["kf_interval"]
        self.kf_translation = t["kf_translation"]
        self.kf_min_translation = t["kf_min_translation"]
        self.kf_overlap = t["kf_overlap"]
        self.kf_cutoff = t.get("kf_cutoff", 0.4)
        self.prune_mode = t.get("prune_mode", "slam")
        self.rgb_boundary_threshold = t["rgb_boundary_threshold"]
        self.alpha = t.get("alpha", 0.95)
        self.lambda_dssim = config["opt_params"]["lambda_dssim"]
        self.color_refine_iters = t.get("color_refine_iters", 26000)

        self.iteration_count = 0
        self.occ_aware_visibility = {}
        self.viewpoints = {}
        self.current_window = []
        self.kf_indices = []
        self.median_depth = None

    # ------------------------------------------------------------------
    # dataset / camera helpers
    # ------------------------------------------------------------------
    def make_projection_matrix(self):
        p = getProjectionMatrix2(
            znear=0.01,
            zfar=100.0,
            fx=self.dataset.fx,
            fy=self.dataset.fy,
            cx=self.dataset.cx,
            cy=self.dataset.cy,
            W=self.dataset.width,
            H=self.dataset.height,
        ).transpose(0, 1)
        return p.to(device=self.device)

    def camera_from_idx(self, idx, projection_matrix):
        return Camera.init_from_dataset(self.dataset, idx, projection_matrix)

    # ------------------------------------------------------------------
    # keyframe bookkeeping (from slam_frontend)
    # ------------------------------------------------------------------
    def _visibility(self, frame_idx, render_pkg):
        return (render_pkg["n_touched"] > 0).long()

    def is_keyframe(
        self, cur_frame_idx, last_keyframe_idx, curr_visibility, occ_aware_visibility
    ):
        curr_frame = self.viewpoints[cur_frame_idx]
        last_kf = self.viewpoints[last_keyframe_idx]
        pose_CW = getWorld2View2(curr_frame.R, curr_frame.T)
        last_kf_WC = torch.linalg.inv(getWorld2View2(last_kf.R, last_kf.T))
        dist = torch.norm((pose_CW @ last_kf_WC)[0:3, 3])
        dist_check = dist > self.kf_translation * self.median_depth
        dist_check2 = dist > self.kf_min_translation * self.median_depth

        union = torch.logical_or(
            curr_visibility, occ_aware_visibility[last_keyframe_idx]
        ).count_nonzero()
        intersection = torch.logical_and(
            curr_visibility, occ_aware_visibility[last_keyframe_idx]
        ).count_nonzero()
        point_ratio_2 = intersection / union
        return (point_ratio_2 < self.kf_overlap and dist_check2) or dist_check

    def add_to_window(
        self, cur_frame_idx, cur_frame_visibility_filter, occ_aware_visibility, window
    ):
        N_dont_touch = 2
        window = [cur_frame_idx] + window
        curr_frame = self.viewpoints[cur_frame_idx]
        to_remove = []
        removed_frame = None
        for i in range(N_dont_touch, len(window)):
            kf_idx = window[i]
            intersection = torch.logical_and(
                cur_frame_visibility_filter, occ_aware_visibility[kf_idx]
            ).count_nonzero()
            denom = min(
                cur_frame_visibility_filter.count_nonzero(),
                occ_aware_visibility[kf_idx].count_nonzero(),
            )
            point_ratio_2 = intersection / denom
            if point_ratio_2 <= self.kf_cutoff:
                to_remove.append(kf_idx)
        if to_remove:
            window.remove(to_remove[-1])
            removed_frame = to_remove[-1]

        if len(window) > self.window_size:
            inv_dist = []
            for i in range(N_dont_touch, len(window)):
                kf_i = self.viewpoints[window[i]]
                kf_i_CW = getWorld2View2(kf_i.R, kf_i.T)
                inv_dists = []
                for j in range(N_dont_touch, len(window)):
                    if i == j:
                        continue
                    kf_j = self.viewpoints[window[j]]
                    kf_j_WC = torch.linalg.inv(getWorld2View2(kf_j.R, kf_j.T))
                    T_CiCj = kf_i_CW @ kf_j_WC
                    inv_dists.append(1.0 / (torch.norm(T_CiCj[0:3, 3]) + 1e-6).item())
                kf_0 = self.viewpoints[window[0]]
                kf_0_WC = torch.linalg.inv(getWorld2View2(kf_0.R, kf_0.T))
                T_CiC0 = kf_i_CW @ kf_0_WC
                k = torch.sqrt(torch.norm(T_CiC0[0:3, 3])).item()
                inv_dist.append(k * sum(inv_dists))
            idx = int(np.argmax(inv_dist))
            removed_frame = window[N_dont_touch + idx]
            window.remove(removed_frame)

        return window, removed_frame

    # ------------------------------------------------------------------
    # mapping (from slam_backend)
    # ------------------------------------------------------------------
    def add_next_kf(self, frame_idx, viewpoint, init=False, depth_map=None):
        self.gaussians.extend_from_pcd_seq(
            viewpoint, kf_id=frame_idx, init=init, depthmap=depth_map
        )

    def initialize_map(self, cur_frame_idx, viewpoint):
        for mapping_iteration in range(self.init_itr_num):
            self.iteration_count += 1
            render_pkg = render(
                viewpoint, self.gaussians, self.pipeline_params, self.background
            )
            image = render_pkg["render"]
            depth = render_pkg["depth"]
            opacity = render_pkg["opacity"]
            loss_init = get_loss_mapping(
                self.config, image, depth, viewpoint, opacity, initialization=True
            )
            loss_init.backward()

            with torch.no_grad():
                visibility_filter = render_pkg["visibility_filter"]
                radii = render_pkg["radii"]
                self.gaussians.max_radii2D[visibility_filter] = torch.max(
                    self.gaussians.max_radii2D[visibility_filter],
                    radii[visibility_filter],
                )
                self.gaussians.add_densification_stats(
                    render_pkg["viewspace_points"], visibility_filter
                )
                if mapping_iteration % self.init_gaussian_update == 0:
                    self.gaussians.densify_and_prune(
                        self.config["opt_params"]["densify_grad_threshold"],
                        self.init_gaussian_th,
                        self.init_gaussian_extent,
                        None,
                    )
                if self.iteration_count == self.init_gaussian_reset:
                    self.gaussians.reset_opacity()
                self.gaussians.optimizer.step()
                self.gaussians.optimizer.zero_grad(set_to_none=True)

        self.occ_aware_visibility[cur_frame_idx] = (
            render_pkg["n_touched"] > 0
        ).long()

    def map(self, current_window, prune=False, iters=1):
        if len(current_window) == 0:
            return

        viewpoint_stack = [self.viewpoints[kf_idx] for kf_idx in current_window]
        current_window_set = set(current_window)
        random_viewpoint_stack = [
            v
            for idx, v in self.viewpoints.items()
            if idx not in current_window_set
        ]

        gaussian_split = False
        for _ in range(iters):
            self.iteration_count += 1

            loss_mapping = 0
            viewspace_point_tensor_acm = []
            visibility_filter_acm = []
            radii_acm = []
            n_touched_acm = []

            for viewpoint in viewpoint_stack:
                render_pkg = render(
                    viewpoint, self.gaussians, self.pipeline_params, self.background
                )
                loss_mapping += get_loss_mapping(
                    self.config,
                    render_pkg["render"],
                    render_pkg["depth"],
                    viewpoint,
                    render_pkg["opacity"],
                )
                viewspace_point_tensor_acm.append(render_pkg["viewspace_points"])
                visibility_filter_acm.append(render_pkg["visibility_filter"])
                radii_acm.append(render_pkg["radii"])
                n_touched_acm.append(render_pkg["n_touched"])

            for cam_idx in torch.randperm(len(random_viewpoint_stack))[:2]:
                viewpoint = random_viewpoint_stack[cam_idx]
                render_pkg = render(
                    viewpoint, self.gaussians, self.pipeline_params, self.background
                )
                loss_mapping += get_loss_mapping(
                    self.config,
                    render_pkg["render"],
                    render_pkg["depth"],
                    viewpoint,
                    render_pkg["opacity"],
                )
                viewspace_point_tensor_acm.append(render_pkg["viewspace_points"])
                visibility_filter_acm.append(render_pkg["visibility_filter"])
                radii_acm.append(render_pkg["radii"])

            scaling = self.gaussians.get_scaling
            isotropic_loss = torch.abs(scaling - scaling.mean(dim=1).view(-1, 1))
            loss_mapping += 10 * isotropic_loss.mean()
            loss_mapping.backward()

            with torch.no_grad():
                self.occ_aware_visibility = {}
                for idx in range(len(current_window)):
                    kf_idx = current_window[idx]
                    self.occ_aware_visibility[kf_idx] = (
                        n_touched_acm[idx] > 0
                    ).long()

                if prune:
                    if len(current_window) == self.window_size:
                        prune_coviz = 3
                        self.gaussians.n_obs.fill_(0)
                        for window_idx, visibility in self.occ_aware_visibility.items():
                            self.gaussians.n_obs += visibility.cpu()
                        to_prune = None
                        if self.prune_mode == "odometry":
                            to_prune = self.gaussians.n_obs < 3
                        if self.prune_mode == "slam":
                            sorted_window = sorted(current_window, reverse=True)
                            mask = self.gaussians.unique_kfIDs >= sorted_window[2]
                            to_prune = torch.logical_and(
                                self.gaussians.n_obs <= prune_coviz, mask
                            )
                        if to_prune is not None:
                            self.gaussians.prune_points(to_prune.cuda())
                            for idx in range(len(current_window)):
                                kf_idx = current_window[idx]
                                self.occ_aware_visibility[kf_idx] = (
                                    self.occ_aware_visibility[kf_idx][~to_prune]
                                )
                    return gaussian_split

                for idx in range(len(viewspace_point_tensor_acm)):
                    self.gaussians.max_radii2D[visibility_filter_acm[idx]] = torch.max(
                        self.gaussians.max_radii2D[visibility_filter_acm[idx]],
                        radii_acm[idx][visibility_filter_acm[idx]],
                    )
                    self.gaussians.add_densification_stats(
                        viewspace_point_tensor_acm[idx], visibility_filter_acm[idx]
                    )

                update_gaussian = (
                    self.iteration_count % self.gaussian_update_every
                    == self.gaussian_update_offset
                )
                if update_gaussian:
                    self.gaussians.densify_and_prune(
                        self.config["opt_params"]["densify_grad_threshold"],
                        self.gaussian_th,
                        self.gaussian_extent,
                        self.size_threshold,
                    )
                    gaussian_split = True

                if (self.iteration_count % self.gaussian_reset) == 0 and (
                    not update_gaussian
                ):
                    self.gaussians.reset_opacity_nonvisible(visibility_filter_acm)
                    gaussian_split = True

                self.gaussians.optimizer.step()
                self.gaussians.optimizer.zero_grad(set_to_none=True)
                self.gaussians.update_learning_rate(self.iteration_count)
        return gaussian_split

    def color_refinement(self):
        iteration_total = self.color_refine_iters
        for iteration in tqdm(range(1, iteration_total + 1), desc="color_refine"):
            viewpoint_idx_stack = list(self.viewpoints.keys())
            viewpoint_cam = self.viewpoints[
                viewpoint_idx_stack.pop(random.randint(0, len(viewpoint_idx_stack) - 1))
            ]
            render_pkg = render(
                viewpoint_cam, self.gaussians, self.pipeline_params, self.background
            )
            image = render_pkg["render"]
            visibility_filter = render_pkg["visibility_filter"]
            radii = render_pkg["radii"]

            gt_image = viewpoint_cam.original_image.cuda()
            Ll1 = l1_loss(image, gt_image)
            loss = (1.0 - self.lambda_dssim) * (Ll1) + self.lambda_dssim * (
                1.0 - ssim(image, gt_image)
            )
            loss.backward()
            with torch.no_grad():
                self.gaussians.max_radii2D[visibility_filter] = torch.max(
                    self.gaussians.max_radii2D[visibility_filter],
                    radii[visibility_filter],
                )
                self.gaussians.optimizer.step()
                self.gaussians.optimizer.zero_grad(set_to_none=True)
                self.gaussians.update_learning_rate(iteration)

    # ------------------------------------------------------------------
    # top-level offline run
    # ------------------------------------------------------------------
    def add_new_keyframe_depth(self, frame_idx, viewpoint):
        """Observed-depth depthmap for map extension (frontend rgbd branch)."""
        gt_img = viewpoint.original_image.cuda()
        valid_rgb = (gt_img.sum(dim=0) > self.rgb_boundary_threshold)[None]
        initial_depth = torch.from_numpy(viewpoint.depth).unsqueeze(0)
        initial_depth[~valid_rgb.cpu()] = 0
        return initial_depth[0].numpy()

    def run(self, log_every=200):
        projection_matrix = self.make_projection_matrix()
        n_frames = len(self.dataset)
        cur_frame_idx = 0

        while cur_frame_idx < n_frames:
            viewpoint = self.camera_from_idx(cur_frame_idx, projection_matrix)
            self.viewpoints[cur_frame_idx] = viewpoint

            if not self.kf_indices:
                # first frame: initialize the map
                self.median_depth = get_median_depth(
                    torch.from_numpy(viewpoint.depth).to(self.device),
                    opacity=None,
                )
                self.add_next_kf(cur_frame_idx, viewpoint, init=True)
                self.initialize_map(cur_frame_idx, viewpoint)
                self.current_window.append(cur_frame_idx)
                self.kf_indices.append(cur_frame_idx)
                cur_frame_idx += 1
                continue

            # "tracking" = GT pose only; render once to get visibility stats
            render_pkg = render(
                viewpoint, self.gaussians, self.pipeline_params, self.background
            )
            if render_pkg is None:
                cur_frame_idx += 1
                continue
            curr_visibility = self._visibility(cur_frame_idx, render_pkg)

            if self.median_depth is None:
                self.median_depth = get_median_depth(
                    torch.from_numpy(viewpoint.depth).to(self.device),
                    opacity=render_pkg["opacity"],
                )

            last_keyframe_idx = self.current_window[0]
            check_time = (cur_frame_idx - last_keyframe_idx) >= self.kf_interval
            create_kf = self.is_keyframe(
                cur_frame_idx,
                last_keyframe_idx,
                curr_visibility,
                self.occ_aware_visibility,
            )
            if len(self.current_window) < self.window_size:
                union = torch.logical_or(
                    curr_visibility, self.occ_aware_visibility[last_keyframe_idx]
                ).count_nonzero()
                intersection = torch.logical_and(
                    curr_visibility, self.occ_aware_visibility[last_keyframe_idx]
                ).count_nonzero()
                point_ratio = intersection / union
                create_kf = check_time and point_ratio < self.kf_overlap

            if create_kf:
                self.current_window, removed = self.add_to_window(
                    cur_frame_idx,
                    curr_visibility,
                    self.occ_aware_visibility,
                    self.current_window,
                )
                depth_map = self.add_new_keyframe_depth(cur_frame_idx, viewpoint)
                self.kf_indices.append(cur_frame_idx)
                self.add_next_kf(cur_frame_idx, viewpoint, depth_map=depth_map)
                # mapping on each keyframe event (single_thread cadence)
                self.map(self.current_window, iters=10)
                self.map(self.current_window, prune=True)
            if cur_frame_idx % log_every == 0:
                n_pts = self.gaussians.get_xyz.shape[0]
                print(
                    f"[mapper] frame {cur_frame_idx}/{n_frames} "
                    f"n_kf={len(self.kf_indices)} n_gauss={n_pts} "
                    f"iter={self.iteration_count}"
                )
            cur_frame_idx += 1

    def final_eval(self, eval_utils):
        self.color_refinement()
        from dynamic_3dgs.legacy_core.eval_utils import eval_rendering

        return eval_rendering(
            frames=[self.viewpoints[i] for i in sorted(self.viewpoints.keys())],
            gaussians=self.gaussians,
            dataset=self.dataset,
            save_dir=self.save_dir,
            pipe=self.pipeline_params,
            background=self.background,
            kf_indices=set(self.kf_indices),
            iteration="final",
        )
