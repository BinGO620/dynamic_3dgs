# legacy_core — Phase A 底座验收实验（预注册）

日期：2026-09-09。判据在本实验开跑前写下，跑完后不改。

## 假设

自造 gsplat trainer 是 PSNR 平台（12-13dB）的主要瓶颈。把 stock MonoGS
（upstream of monogs-ours，6c9254c）的映射核心（Inria 风格 GaussianModel +
w-pose 栅格化器 + keyframe 窗口映射循环 + 26k 色彩精修）搬为离线驱动、
GT 位姿直接喂入后，动态序列的 held-out 渲染质量应达到或追平文献 RGB-D
SLAM 基线水平。

## 手术范围（与 monogs-ours 的边界）

- 基底 = stock MonoGS（**非** monogs-ours 魔改版）：gaussian_model 695 行
  干净版（无 causal_twin/lineage/static 账目），unique_kfIDs/n_obs 保留
  （prune 语义需要）。
- 砍掉：tracking、BA、回环、子图、GUI、多进程队列。位姿 = 数据集真值。
- 渲染后端 = rmurai0610/diff-gaussian-rasterization-w-pose（返回 n_touched），
  从上游 pin 源码编译进本仓库 env（不碰 monogs-ours 编译产物）。
- 评测半边 = monogs-ours eval_utils 的 eval_rendering + _compute_depth_l1_cm。
- 数据解析复用本项目已验证的 TumFormatDataset（Bonn 去畸变/位姿插值）。

## 判据（预注册）

| 门 | 序列 | 指标（held-out 帧，GT 位姿渲染） | 门槛 | 文献锚点 |
|---|---|---|---|---|
| A1 | TUM fr3 walking_xyz | PSNR | ≥ 15 dB | SplaTAM 14.54 / MonoGS(mono) 14.41；DGS-SLAM(RGB-D) 20.48 / DyGS-SLAM 22.15 |
| A2 | bonn removing_nonobstructing_box | PSNR | ≥ 19 dB | 弱底座 v3 为 11-12dB 平台 |
| A3 | bonn placing_nonobstructing_box | PSNR | ≥ 19 dB | 同上 |

辅读数：depth L1-cm、SSIM/LPIPS、高斯数；全部 run rc=0。
L2 门禁：同 config 同 seed 两次，PSNR 差 ≤ 0.3 dB（o3d random_down_sample
不可种子化，允许该来源的小浮动；超差须先归因）。

达标后 → Phase B（生命周期机制在强底座上重开配对实验，弱底座上的阴性
结论全部重测，不作数）；A5 软一致性先验等机制作为插件单变量重验。
未达标 → 穷尽改善路径（NOTES 踩坑纪律），不得机制包装负结果。

## 配置

- configs/legacy/{tum,bonn}_base.yaml：Training/opt_params 全部 = stock
  MonoGS rgbd/tum 值，未调；sh_degree=0（stock SLAM 配置）；Bonn 继承同
  超参（MonoGS 无 Bonn preset，畸变由 loader 处理）。
- eval_stride=5（held-out 与阶段0 协议一致），train_views=-1（流式全训练帧）。
- 本机 2060 冒烟/全序列（≤640×480 符合孵化政策）；若显存不足 → 3090。

## 预期

- TUM walking_xyz：15-20dB 区间（RGB-D+GT 位姿应显著优于 MonoGS 单目 14.41）。
- Bonn transition：≥19dB（MonoGS 论文 Bonn RGB-D ≈ 27-33dB @ PSNR，但那是
  全帧 keyframe 评测口径；held-out + transition 家族应低数 dB）。
- depth L1 < 20cm 量级（v3 已到 34-49cm，强底座应更好）。

## 运行

```bash
# 冒烟（已过，40 帧 rc=0：17.5dB / 23.4cm @20 refine iters）
python scripts/run_legacy.py --config configs/legacy/tum_walking_xyz.yaml \
  --out results/debug_x --max-frames 40 --refine-iters 20
# 验收
python scripts/run_legacy.py --config configs/legacy/tum_walking_xyz.yaml \
  --out results/legacy_core/tum_walking_xyz/seed_0
python scripts/run_legacy.py --config configs/legacy/bonn_removing_nonobstructing_box.yaml \
  --out results/legacy_core/bonn_removing/seed_0
python scripts/run_legacy.py --config configs/legacy/bonn_placing_nonobstructing_box.yaml \
  --out results/legacy_core/bonn_placing/seed_0
```
