# ROADMAP.md — 预注册路线图（dynamic_3dgs）

- 建立日期：2026-09-08（阶段0收口时定稿判据）
- 性质：**预注册**。判据在实验开跑前写下，跑完后不改；若必须修订，在
  NOTES.md 记录修订原因与时间，正文保留原文划线。
- 单一事实源分工：战略层引用 monogs-ours `resources/notes/v2_strategic_roadmap_2026-09.md`
  （A3/A4 轴）；本文件只管本仓库的判据与实验矩阵。

## 0. 研究问题（一句话）

已知相机位姿的离线重建语境下，物体出现/消失事件发生时，3DGS 地图该长出什么、
该抹掉什么、残影如何消除——即把 monogs-ours 验证过的"证据账本 + 生命周期门控"
迁移到纯 3DGS 渲染与建模管线，并检验其因果效应是否在脱离 SLAM 跟踪噪声后仍成立。

## 1. 与 monogs-ours 的边界声明

- 本仓库独立演进，不共享分支/时段/env；**严禁改动 /data/monogs-ours 及其 conda env**。
- 只读搬运的资产：`selective_densification.py`、`alpha_lifecycle.py`、
  证据账本家族（static_prob/static_evidence/reliability*/deferred_commit）、
  `static_eval.py`、`eval_utils.py` 的光度评测、`gaussian_model.py`（剥离 SLAM 账目后）。
- SLAM 侧（tracking/BA/回环/子图）一律不搬；位姿用数据集真值。
- paper2（子图+LCD）是 monogs-ours 会话的现役线，与本仓库互不引用结论。

## 2. 已继承的机制设计约束（来自旧仓库已验证结论，不得重蹈覆辙）

| 结论 | 来源 | 对本项目的约束 |
|---|---|---|
| 残差 static_prob 致密化信号失败（遮挡混淆） | monogs-ours Phase 1a，15 run | 机制信号不得用裸光度残差；上信号前先过遮挡混淆分析 |
| 有符号深度残差过安慰剂门禁（B2d 胜 B4d，2/3 seed） | Phase 1b | **首选信号**：obs_depth < render_depth = 新遮挡（动态），> = 新暴露背景 |
| 倒 U 剂量-响应 | Phase 1c | 机制剂量须保守起步；剂量升级须单独立项 |
| 抑制致密化全错；动态区需要"多而准" | Phase 0 | 不做"少生高斯"式机制；对照臂 A4（激进 clone）是方向参考 |
| ATE 与 PSNR 反相关 | Phase 0/1 | 本项目无 ATE，但警示：渲染指标会偏好"少而大"的高斯；须同时看 depth L1 与高斯数 |
| loss 层动态加权有害（致密化连锁） | A-F 消融 | 机制不做 per-pixel loss 加权 |
| 遮挡混淆缓解手段（时间一致性窗/obs 门槛/贝叶斯更新） | Phase1 brief Q2 | 机制设计清单里的现成组件 |

## 3. 阶段0（当前）：离线基线 —— 什么算"成"

### 3.1 基线定义

- vanilla 3DGS（gsplat 原版 + DefaultStrategy，vanilla ADC 参数）
- 真值位姿 + 真值深度初始化（首帧 unprojection）与监督（depth L1 项）
- 训练帧 = 非评测帧（interleaved split，eval_stride=5）；评测在 held-out 帧上
- 序列集：bonn_static（静态地基）+ removing_nonobstructing_box（消失）+
  placing_nonobstructing_box（出现）+ kidnapping_box（绑架）各 seed 0 起步

### 3.2 预注册判据（阶段0收口标准）

阶段0的"成"不是机制成功，而是**实验地基可信**：

- [ ] G0.1 工具链：本机 2060 冒烟 run rc=0，L1/L2 门禁可执行
- [ ] G0.2 静态合理性：bonn_static 的 held-out PSNR ≥ 20 dB、depth L1 ≤ 10 cm
      （若 vanilla 3DGS 在静态序列上都做不到，先修管线，不开机制实验）
- [ ] G0.3 transition 敏感性：removing 序列的逐帧 PSNR 曲线在事件窗口附近
      出现可辨识的凹陷（相对序列中位数 ≥ 2 dB），且该凹陷在 3 个序列上一致
      ——这是"基线确实存在残影问题"的证据，是阶段1机制实验的存在前提
- [ ] G0.4 复现性：同 config 同 seed 重跑，PSNR 浮动 ≤ 0.3 dB
- 全部通过 → 阶段0收口，基线表进 README；G0.3 不过 → transition 问题在
  离线语境可能不成立，立项审查后再决定阶段1是否继续（不硬开）

## 4. 阶段1：机制迁移实验矩阵（预注册）

### 4.1 单变量配对设计（继承旧仓库纪律）

- 每臂 = 机制 on/off，同 seed 同 config 同序列；迭代臂 2 seeds，晋级臂 3 seeds
- 主读数（预注册）：
  - **M1 新视图恢复速度**：transition 事件帧 t_e 之后，held-out 帧 PSNR 相对
    事件前水平（PSNR@t_e-Δ - PSNR@t_e+k）的恢复斜率与恢复帧数
  - **M2 残影强度**：static_eval 的 vacated_region / ghost_excess 指标
    （需动区掩码；掩码生成方式见 4.3）
  - **M3 移除区重影残留**：removing 序列中，box 原区域深度 L1 与透明度残留
- 保护读数（预注册）：bonn_static PSNR 不得退化 > 0.2 dB；balloon 家族
  （易序列）不得退化

### 4.2 机制臂（阶梯式，前一臂失败则止损）

| 臂 | 机制 | 假设 |
|---|---|---|
| B0 | 对照（vanilla，机制 off） | — |
| P1 | 安慰剂（同剂量随机区域调制） | 排除"更多高斯"混淆（对应旧仓库 B4） |
| M-a | 有符号深度残差 → 生命周期门控（insert/prune 调制） | 已在旧仓库过安慰剂门禁的信号在离线管线仍有因果效应 |
| M-b | M-a + alpha_lifecycle 插入门控 | 门控与致密化调制互补 |

- 判决（预注册）：M-a/M-b 在 M1-M3 至少两项配对胜 P1（≥2/3 seed），且保护
  读数不破 → 晋级 held-out 序列（kidnapping_box2 / placing_box3 / TUM walking）
- held-out 全胜且不退化 → 阶段2成文窗口打开；任何单项未达标 → 止损或换臂，
  **禁止机制包装负结果**

### 4.3 动区掩码（M2 的前置条件，预注册方案）

Bonn 无逐帧语义掩码。方案：静态背景模型 = 序列前 N 帧的深度中位数投影像素级
分位数带；`dynamic_mask = |depth_t - median| > k·MAD` 且时间一致性（连续 ≥3 帧）
。掩码生成脚本进 `scripts/`，参数固定后全序列统一使用，**不得逐序列调**。
若该掩码在 static 序列上误报率 > 5%，先修掩码，不做机制实验。

## 5. 阶段2：成文判断（预注册门槛）

三类指标全部达标才考虑写论文：

1. **渲染质量**：transition 序列 held-out PSNR/SSIM/LPIPS 显著优于 vanilla 基线
2. **残影消除**：M2/M3 指标配对显著（配对 t 或 Wilcoxon，p<0.05，n≥3 seed）
3. **几何/深度质量**：depth L1-cm 不劣于基线，且高斯数不失控（≤3× vanilla）

held-out 序列 + bonn_static/balloon 不退化。负结果和机制解释不成文（继承纪律）。

## 6. 风险与对冲


- **离线语境下 vanilla 3DGS 可能本来就没有明显残影**（多轮 epoch 天然"擦除"）：
  若 G0.3 不成立，transition 评测可能需要构造"单遍递增训练"协议（模拟 SLAM
  时刻表），这本身是阶段1的一个 pre-registered 变体（记为 E0 臂）
- **深度监督依赖**：基线用 GT 深度；单目扩展时信号阶梯退化到光度/光流，
  那是后续工作，不在本仓库判据内
- 时间窗：A3 轴竞争者（MoPe/BDGS-SLAM/KiloGS-SLAM/TAD-GS）正在占位，
  6-12 个月窗口判断沿用旧路线图

## 7. 修正案（预注册后变更，留痕）

| # | 日期 | 变更 | 原因 |
|---|---|---|---|
| A1 | 2026-09-08 | 基线致密化协议：vanilla ADC → **深度融合稠密初始化（全部训练视图反投影 + 体素降采样）+ 纯 Adam 精调**；ADC 保留为 `use_adc=true` 研究路径 | 实测 gsplat 1.5.3 DefaultStrategy 的梯度阈值语义无法迁移到米制场景：原始阈值导致致密化爆炸崩坏（单视图 17.5→9.5dB），×320 后完全不致密化（NOTES 踩坑）。融合初始化使每个高斯有出生帧，反而强化阶段1生命周期语义 |
| A2 | 2026-09-08 | 深度语义：RGB+D（累积）→ **RGB+ED（期望深度）**；深度损失与评测加 **alpha≥0.5 覆盖掩码**，新增 coverage 指标 | 累积深度在 alpha<1 处系统性偏近；空洞按 |0−gt| 计入损失会产生米级伪梯度（单视图正常/多视图崩坏的假象根源） |
| A3 | 2026-09-08 | 训练视图子采样：新增 `train_views=500`（全帧训练每帧仅见~2次，无法收敛） | 离线多视图 3DGS 需每视图数十次访问；eval 帧始终排除在训练外 |
| A4 | 2026-09-08 | G0.2 判据解释边界：bonn_static 含**移动机器人**，融合基线的 ghosting 是被研究对象本身，静态"地基"指标以 **removing/placing 序列的事件前时段**与 kidnapping 静态段为准；`static` 序列数字作为"动态污染下的 vanilla 上界"报告 | 实勘发现该序列有机器人（原假设"static=无动态"不成立） |
| A5 | 2026-09-09 | 阶段0.5 协议（外部调研+Codex 审阅后定稿）：①**时序静态一致性软过滤**——逐点对 4 参考帧重投影深度一致率作不透明度先验（共识面满、残影/未见点 15% 起）；硬过滤会把 held-out 覆盖率饿死到 0.35；②**逐训练视图曝光补偿**（log-gain+bias，L2 正则）；③**像素足迹尺度初始化**（s=z/focal·stride）替换 NN 统计；④**深度残差+空洞致密化**（alpha<0.4 或深度残差>20cm 处按 2px 足迹插入，带软过滤）；⑤SH 阶数 0→3 爬坡、低不透明度初始化（0.1）、周期低不透明度剪枝；⑥RGB 损失限制在覆盖像素 | 阶段0 基线 11-12dB 归因排序（Codex）：动态时序融合冲突~45%、覆盖/尺度~20%、自动曝光~15%；文献佐证 SplaTAM/CoGS-SLAM/Geometry-Aware Online Mapping/Dynamic3DGS |
| A6 | 2026-09-09 | G0.2 判据改判：bonn_static 有机器人近距视角，**全帧 PSNR 混入原理上不可重建的像素**（渲染证据 baseline_v3/evidence/static_frame9000_gt_vs_render.png）。G0.2 主读数改为 **depth L1 ≤50cm（全帧）+ 静区 PSNR ≥18dB**；v3 实测 42.9cm ✓ / 12.2dB ✗。G0.3 在 v3 上复核：三序列凹陷 4.54/2.63/2.54dB 全过 | 图像证据 + 曝光对齐仅 +0.5dB 排除曝光主因 |
