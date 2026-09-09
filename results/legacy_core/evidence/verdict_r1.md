# legacy_core verdict — 第一轮（2026-09-09，本机 2060）

## 结果（held-out 帧，eval_stride=5，GT 位姿，seed 0）

| 门 | 序列 | PSNR | 门槛 | 判 | SSIM | LPIPS | dL1(cm) raw | n_kf / n_frames | n_gauss |
|---|---|---|---|---|---|---|---|---|---|
| A1 | TUM fr3 walking_xyz | **16.03** | ≥15 | ✅ | 0.574 | 0.441 | 90.4 | 45 / 826 | 31134 |
| A2 | bonn removing_nonobstructing_box | 16.62 | ≥19 | ❌ | 0.710 | 0.683 | 45.2 | 14 / 492 | 25977 |
| A3 | bonn placing_nonobstructing_box | 16.02 | ≥19 | ❌ | 0.677 | 0.733 | 53.2 | 19 / 718 | 18359 |

- 全部 run rc=0；L2 门禁：TUM seed_0 复跑 16.039 vs 16.025，Δ=0.014dB ≤ 0.3 ✅
  （差异来源=o3d random_down_sample 不可种子化，已按预案允许）。
- 对照弱底座 v3（removing 13.34dB / 34.0cm）：PSNR +3.3dB，但深度 L1 变差
  （45.2 vs 34.0；raw 指标把 0 深度空洞按全权重计——coverage 掩码变体已加入
  eval，本轮 runs 未含）。
- 耗时：TUM 全序列 ~12 分钟（2060，含 26k 精修）。

## 归因（只写事实）

- A2/A3 未达标的同时，keyframe 数极稀疏（14/492、19/718）：stock
  kf_overlap=0.9 + kf_interval=5 的选择策略为**在线 SLAM**设计（前端要与
  tracking 错峰、算力受限）；离线语境下无此约束，地图覆盖不足直接压
  PSNR/LPIPS（LPIPS 0.68-0.73 = 结构欠拟合特征）。
- 评测未做曝光对齐（stock 口径），Bonn 亮度变化序列会低估 ~0.5-1dB
  （v3 实验已有先例），但不足以解释 3dB 缺口。

## 判决与下一步

- **A1 达标，A2/A3 未达标 → 不收口**。改善路径（预注册修正案 A7，单变量）：
  离线协议下 keyframe 密度放开（kf_interval 5→1，重叠规则不变），
  其余超参全部保持 stock。重跑 A1-A3。
- 若 A7 后仍 <19：下一杠杆 = mapping iters/kf 与 eval 曝光对齐（再单变量）。
