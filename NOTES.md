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

- （待记）
