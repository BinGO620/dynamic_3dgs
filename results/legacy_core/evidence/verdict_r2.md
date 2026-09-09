# legacy_core verdict — R2（A7 修正案三轮，2026-09-09，本机 2060）

## 结论（止损）

**MonoGS 流式映射核心（stock 语义）作为离线底座 = 弱底座**，达不到 A2/A3
（Bonn ≥19dB）。Phase A 的手术目标形态选错了：SLAM 在线映射语义（稀疏
keyframe、SLAM-prune、无多轮、无 SH）天然不是离线重建引擎。**本轮记为
已排除方向**；正确底座形态 = 多轮离线 3DGS（证据见下）。

## 各轮数字（bonn removing_nonobstructing_box，held-out，eval_stride=5）

| 轮 | 协议 | PSNR | dL1(cm) | 备注 |
|---|---|---|---|---|
| R1（stock kf 策略，含 eval 泄漏） | kf_overlap=0.9，14 kf | 16.62 | 45.2 | 结果对泄漏不敏感 |
| rev3（逐帧 kf + 泄漏修复） | 394 kf | 16.65 | 52.3 | 密度无增益 |
| rev3+SH2+小足迹+52k 精修 | debug | 17.04 | 63.5 | 锐度参数无效 |
| rev4（refine 致密化+存活阈值） | debug | 16.86 | **190.9** | 漂浮丝状高斯，更糟 |
| TUM walking_xyz（同泄漏修复后） | stock | 16.00-16.04 | 79-90 | A1 ✅（≥15） |

L2 门禁：ΔPSNR=0.014dB ✅（o3d 不可种子化来源）。

## 根因证据链（渲染图 + 插桩）

1. **视觉证据**（evidence/rev3_blur_gt_render.png）：render 是全帧颜色糊，
   无结构——不是动态残影问题，是地图整体欠拟合。
2. **prune 吃掉一切**（插桩 60 帧）：新点入图 ~14.4 万、存活 1.8 万——
   `gaussian_th=0.7`（新点初始 opacity 0.5 必须在 150 iter 内涨过 0.7）+
   `size_threshold=20px`（大足迹即杀）= SLAM 轻地图语义。
3. **致密化有触发但净效应为负**：split/clone 各 15 次/60 帧，剪掉更多；
   refine 期开致密化 → 高斯 10.8 万但漂浮丝状伪影、深度崩坏。
4. **逐帧 keyframe 无增益**（16.62→16.65）：瓶颈不是覆盖。
5. **曝光排除**：对齐 PSNR 仅 +0.12dB。
6. **动态占比**：eval 帧 27% 像素为动区（深度带外），静态-map ceiling
   估算 ~17-18dB——但渲染糊说明静区本身也没做好。

## 锚点修正（重要，修正 handover 判据依据）

monogs-ours NOTES + 源码实勘（只读）：**23.66±0.26dB = TUM walking_xyz 上
monogs-ours 自己重度魔改的 MonoGS backend**（A-F 消融矩阵 A 臂，4 seeds）。
其 slam_backend.py 已从 stock 482 行魔改到 2380 行（逐高斯 grad/percent_dense
knobs、selective ledger、无害删除压缩、三臂生命周期、decay 家族）——**不是
stock MonoGS，也不是独立多轮 gsplat trainer**（NOTES 里"完整 gsplat trainer"
指另一条 mask-loss 实验）。同一序列上：monogs-ours 魔改 backend 23.66 vs
stock MonoGS（本仓库移植版）16.0 → **差距 ≈ 7.7dB 来自 monogs-ours 数周
backend 工程**，decay 族本身只贡献 +0.8~1.0（D/F vs A）。DGS-SLAM/DyGS-SLAM
的 20-22dB 是动态 SLAM 口径（含动态处理/mask）。

## 下一步（新立项，待用户拍板）

- 路线 X：把 monogs-ours 的 backend 工程增量（per-gaussian knobs + prune
  语义修复 + 无害删除压缩）按文件移植进 legacy_core —— 手术量 1-2 天级别，
  且该 backend 是 monogs-ours 会话的现役资产（边界允许只读搬运，但迭代会
  漂移）。
- 路线 Y：放弃"SLAM 流式语义"，直接做多轮离线 3DGS（Inria ADC 语义 +
  多 epoch + GT 深度）——本仓库 v3 trainer 的正确化版本；与 Phase B
  生命周期机制的"多轮重访擦除"语境更贴合（ROADMAP §6 风险预注册过）。
- 无论路线，Bonn ≥19 的可达性须先在所选底座上单独验证（当前证据：静态
  -map + 27% 动区像素的 ceiling 未测出精确值，rev4 前 ~17）。
