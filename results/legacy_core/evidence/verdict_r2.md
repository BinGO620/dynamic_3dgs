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

monogs-ours NOTES 实勘（只读）：**23.66±0.26dB = TUM walking_xyz 上
完整 gsplat 1.5.3 多轮 trainer**（interleaved 全训练帧 + 完整致密化体系）的
A 臂基线——不是 MonoGS 流式管线、也不是 Bonn。即同一序列上：
多轮离线 3DGS 23.66 vs MonoGS 流式 16.0 → **流式语义代价 ≈ 7.7dB**。
DGS-SLAM/DyGS-SLAM 的 20-22dB 是动态 SLAM 口径（含动态处理/mask）。

## 下一步（新立项）

底座手术改为搬 **monogs-ours 的完整 gsplat trainer 引擎**（多轮离线 3DGS，
按边界声明只读按文件复制）或等价地给本仓库 v3 trainer 补齐致密化体系；
验收线 A1-A3 不变（TUM ≥15 已过线但按可达上限 23.66 重标期望；Bonn ≥19
在静态-map ceiling 证据下需重新论证或改为"静区 PSNR+动态处理机制后"口径）。
