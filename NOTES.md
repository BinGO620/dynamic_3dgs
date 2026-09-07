# NOTES.md — 研究笔记本（dynamic_3dgs）

## 实验清单（时间线）

| # | 日期 | 实验 | 状态 | 一句话结论 |
|---|---|---|---|---|
| 1 | 2026-09-08 | baseline_vanilla（阶段0基线） | 🔄 进行 | 本机2060孵化中；判据见 ROADMAP.md §3.2（G0.1-G0.4） |

（新实验立项时在此追加一行；详细结论写入下方"已验证结论"，证据在 results/{exp_id}/）

## 当前方向

非 SLAM 的动态场景 3DGS 生命周期建模：transition 家族（placing/removing/kidnapping）
上，把 monogs-ours 验证过的证据账本+生命周期门控迁到离线 vanilla 3DGS，单变量配对
验证因果效应。判据唯一入口：`ROADMAP.md`（预注册）。

## 已验证结论

（项目新建于 2026-09-08，尚无本地验证结论。继承自 monogs-ours 的机制设计约束
已固化在 ROADMAP.md §2，不在此重复。）

## 工程备忘

- 本机：RTX 2060 6GB（cb）；正式机：`ssh jiangwenheng`（3090×2，172.16.227.24，
  本机 ~/.bashrc 有别名）；备用：`ssh remote`（V100S，chenfan）。
- conda env `dynamic_3dgs`：由 wildgs-slam（python3.10 + torch 2.1.0+cu118）clone
  而来 + gsplat 独立安装。**与 /data/conda_envs/monogs-ours 无任何关联**。
  clone 原因：外网代理（corkscrew:7890）限速 ~0.3MB/s，torch cu118 直下需数小时；
  本地 clone 只读复制源 env，不影响 wildgs-slam。
- 数据：`datasets -> /data/monogs-ours/datasets`（软链，实际在 /data/Datasets）。
  Bonn 内参/畸变/depth_scale=5000 与 monogs-ours configs/rgbd/bonn 一致；
  去畸变方式沿用 MonoGS（newCameraMatrix=K，rgb LINEAR / depth NEAREST）。
- Bonn groundtruth.txt 与 rgb 时间戳同钟（mocap 硬件同步），线性插值取位姿。

## 踩坑记录

- **cp -al 硬链接复制 conda env 后，bin/pip 的 shebang 仍指向源 env 的 python**
  （2026-09-08）：`/data/conda_envs/dynamic_3dgs/bin/pip install` 实际把包装进了
  wildgs-slam（pip 脚本内容是硬链接共享的，shebang 是源路径绝对地址）。
  已完整恢复 wildgs-slam（卸载误装包、重装 numpy==1.26.3 与 opencv-python==4.8.1.78，
  验证 torch/cv2 导入正常）。**规矩：克隆 env 里一律用
  `python -m pip install`，绝不用其 bin/pip 入口。**
- torch cu118 直下走 corkscrew 代理仅 ~0.3MB/s（2.3GB 需数小时）；清华镜像
  pypi.tuna.tsinghua.edu.cn 直连快。小包一律走镜像。
- gsplat 1.5.3 实际 API：`rasterization(means, quats, scales, opacities, colors,
  viewmats, Ks, width, height)`——SH 系数作为 colors 第 5 位置参数传入；
  `DefaultStrategy.step_post_backward` 无 lr 参数（读 optimizer param_groups）；
  字段名是 `reset_every`/`refine_stop_iter`。
- **2060 与 monogs-ours 会话共用**：其 submap_lcd 调试 run 会占满 6GB
  （observed 5.7GB/6144MB，400 帧 person_tracking ~40min 级）。上卡前必须
  `nvidia-smi` 查占用；显存不足时 cusolver 会报 CUSOLVER_STATUS_INTERNAL_ERROR
  （torch.inverse 创建句柄失败），不是代码 bug。
