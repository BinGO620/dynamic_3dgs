# baseline_vanilla — 阶段0离线基线（vanilla 融合初始化 + 纯精调）

## 目的

按 ROADMAP §3 预注册判据，验证"GT位姿+GT深度的离线 3DGS 管线"作为阶段1
生命周期机制实验的地基是否可信，并给出 transition 家族的基线数字。

## 配置（判据见 ROADMAP §3.2 + 修正案 A1-A4）

- gsplat 1.5.3，`use_adc=false`：深度融合稠密初始化（全部 500 训练视图反投影，
  体素 2cm）+ 纯 Adam 精调，尺度 clamp 8cm
- 真值位姿 + 真值深度（RGB+ED 期望深度，alpha≥0.5 掩码损失）
- eval_stride=5，held-out 评测；seed=0；steps=15000
- 机器：姜伟恒 3090 GPU1（CUDA_VISIBLE_DEVICES=1），batch4 + 补跑（2026-09-08 夜）

## 基线表（held-out 帧，seed 0）

| 序列 | n_eval | PSNR | SSIM | LPIPS | depth L1 (cm) | coverage | max dip (dB) | dip 位置 |
|---|---|---|---|---|---|---|---|---|
| static | 2002 | 10.96 | 0.617 | 0.795 | 135.1 | 0.861 | 7.75* | 0.43 |
| removing_nobox | 99 | 12.07 | 0.657 | 0.792 | 136.4 | 0.864 | 1.96 | 0.79 |
| placing_nobox | 144 | 11.25 | 0.616 | 0.882 | 143.4 | 0.861 | **2.37** | 0.60 |
| kidnapping_box | 218 | 12.31 | 0.636 | 0.813 | 142.4 | 0.861 | **3.10** | 0.89 |

\* static 的"凹陷"是序列内移动机器人的动态污染（A4），不是 transition 事件。

逐帧曲线：`{seq}/seed_0/per_frame_eval.csv`；汇总 `transition_analysis.json`。

## G0 判据核查（预注册 ROADMAP §3.2）

| 判据 | 结果 | 结论 |
|---|---|---|
| G0.1 工具链（冒烟 rc=0，L1/L2 可执行） | ✅ | L1 PASS；L2 同 seed diff=0.000（全确定） |
| G0.2 static held-out PSNR ≥20dB 且 depth≤10cm | ❌ 10.96dB / 135cm | 未达标 |
| G0.3 transition 凹陷 ≥2dB 且 3 序列一致 | ⚠️ 2/3 | placing 2.37 ✓、kidnapping 3.10 ✓、removing 1.96 边缘未过 |
| G0.4 同 config 同 seed 复现 ≤0.3dB | ✅ | L2 diff=0.000；3090 与 V100 轨迹逐值一致 |

## 判决

**阶段0：未达标收口，不进入阶段1机制实验。**

- 事实：全部 4 序列 held-out PSNR 11-12dB（目标 ≥20）；深度 L1 135-143cm。
- 归因（可复核）：①无细节致密化——ADC 阈值语义在米制场景失效（NOTES 踩坑），
  2cm 融合云的纹理细节无法生长；②移动物体残影（robot/box）在多时刻融合地图中
  互相冲突，正是本研究要解决的 ghosting 现象，但基线尚不能把静态背景拟合到
  足以分离残影信号的水平（depth-consistent 像素 PSNR 18dB vs 全图 12dB）。
- 依据：本目录 summary_eval.json、per_frame_eval.csv、NOTES 踩坑记录、
  ROADMAP 修正案 A1-A4。

## 下一步（阶段0.5，管线质量修复后重跑本基线）

1. 修复细节致密化：以**原始梯度单位**重标定 ADC 阈值（实测 p50≈2e-7、
   p99≈1.5e-5 → 阈值带 1e-6~1e-5），或自研 sub-cm clone 规则；启用后重测
   100帧 static 冒烟，目标 train-view PSNR ≥20dB。
2. 修正 opacity reset 触发语义（现版 gsplat 该行 `== 0 & step > 0` 实际恒真）。
3. 重跑本基线四序列，达成 G0.2 后方开阶段1。

## 运行信息

- code_state: 见 manifest.json / git log（e43a51f 之后为修补提交）
- 跨机复核：同 seed 同 config 在 chenfan V100 上轨迹逐值一致（6000/9000/10500
  步 loss/l1_rgb 完全相同）；V100 的完整 eval 因重跑时缺 gcc-11 环境变量未完成，
  不影响主结果。
