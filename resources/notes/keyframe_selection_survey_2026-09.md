# 关键帧/视图选择方法图谱与本项目落地分析（2026-09-09）

> 调研动机：Phase A 实证发现 keyframe 调度对建图质量影响巨大——stock MonoGS
> 启发式（overlap<0.9 + 间隔≥5 + SLAM-prune）作为离线底座 16.0dB，逐帧全选也
> 只有 16.65dB；说明"哪些帧进地图 + 地图用哪些帧精修"的**调度**本身是一等
> 公民问题，而非参数调优。调研源：tavily web（4 轮）+ arXiv API（1 轮），
> Codex 通道当日不可用，结构化分析由本项目自行完成。

## 0. 先分清两个问题（文献常混在一起）

- **A 类：跟踪用的选帧**（服务位姿估计：够不够约束、会不会退化）——我们 GT
  位姿，**不需要**。
- **B 类：建图用的选帧/精修调度**（服务地图质量：覆盖、信息量、新鲜度）——
  我们只要 B 类。以下按 B 类视角筛选。

## 1. 经典几何/信息论准则（B 类可用部分）

| 方法/概念 | 机制 | 对本项目可迁移性 |
|---|---|---|
| ORB-SLAM 关键帧策略 | 视差 + 共视点覆盖 + 局部 BA 冗余度，滞后触发 | **我们已有等价物（MonoGS overlap 规则）且已证明不够**——它是 A 类优先设计 |
| 视差/基线窗 | 帧间平移在 [min, max] 基线带内才入帧；过近=退化、过远=匹配失败 | 离线下无匹配失败风险，可放宽 max；对 Bonn 慢运动序列有效 |
| Fisher 信息 / D-最优性 | 帧对地图参数 Hessian 的信息增益；选 λ_min(H) 增益大的帧 | **高可迁移**：3DGS 显式参数使 Hessian 可逐高斯算（见 §4） |
| 熵/互信息（GauSS-MI） | Shannon MI 选信息量大的视点 | 同上，但 MI 估计贵；Fisher 更实用 |
| InfoLa-SLAM（LiDAR） | Fisher 信息评估帧间配准贡献，冗余帧 -35~48% | 思路同上，证明 Fisher 选帧在实机有效 |
| Active SLAM 综述（Nature-index） | utility = EIG/entropy reduction，OED 准则 | 离线语境 = "预算受限的视图子集选择"，理论可直接用 |

## 2. 子模优化/组合优化视角（**图论直觉的正规化**）

| 论文 | 机制 | 可迁移性 |
|---|---|---|
| **Thorne+ ICRA2025 arXiv:2410.05576**（Submodular KF Selection & Usage in SLAM） | ①选择：描述子空间最小距离的边际增益（cover-type submodular）+ 退化检测（λ_min(H) 增益 ≥ β 才存"constructive keyframe"）；②子图：贪心选最能约束配准的帧集；③流式 submodular 摘要。LiDAR 80%↓ 帧数不掉定位 | **Top 落地**：我们的"帧覆盖 = 共视高斯集合覆盖"天然是 weighted set cover；贪心 1-1/e 保证；离线还可全局重选 |
| GCVD arXiv:2208.02709 | flow-guided keyframes + compact pose graph 做全局一致 SfM | 光流我们暂无；思想（帧选择服务全局一致性）可借 |
| CSES arXiv:2608.00714 | 覆盖饱和即停：相关性+时间冗余+视觉冗余联合的 monotone submodular | LVLM 域但调度思想同构；"覆盖饱和"可做我们精修轮数调度 |
| NBV-Gym（CVPR2026 benchmark） | 视图选择 = 最小化 metric；**KD-tree 过滤近邻候选** | 数据结构直接可用：候选帧按视点 KD-tree 剪枝再精评 |

**图论关联的正确打开方式**：把每帧表示为其共视高斯集合 S_i ⊂ G，
- 帧图 = 集合交/并权的相似图（Jaccard，MonoGS 的 point_ratio 就是它的 1-近似）；
- 关键帧选择 = **带基线约束的加权 dominating set / set cover**（每帧须被某 kf
  覆盖至 IoU≥θ，且 kf 间基线在有效窗内）——NP-hard 但子模贪心有保证；
- 精修调度 = 在 kf 图上选**局部团（clique）**做窗口优化（= MonoGS 窗口 + 2
  随机帧的图论化：随机帧应换成图上"桥接节点/最大信息增益节点"）。

## 3. 图信号处理/图采样（新颖但可落地）

| 论文 | 机制 | 可迁移性 |
|---|---|---|
| Gershgorin 图采样 arXiv:2408.01859 / 2110.11420 | 帧序列建路径图，选帧 =最大化 λ_min(diag(h)+μL) 的图采样，GCT 下界线性时间 | 视频摘要域；若把边权换成共视/几何相似度，可当"离线一次性选帧"的快速算法；数学重，优先级低于 §2 |
| Essential graph / pose-graph sparsification（Strasdat; Vallvé factor descent; Carlevaris-Bianco） | 边稀疏化保持图一致性 | 我们无 PGO，但"最少 kf 保持地图一致性"的判据可借作离线 kf 数量下界 |
| ExplORB-SLAM arXiv:2209.03693 | 在 pose-graph 拓扑上做主动探索 utility | 主动探索我们不需要 |

## 4. 3DGS/NeRF 时代的选帧（与我们底座同构，**主战场**）

| 论文 | 机制 | 可迁移性 |
|---|---|---|
| **FisherRF（ECCV2024）** | 3DGS Fisher 信息选 NBV，无需 GT | **Top 落地**：离线下我们可对全部帧预计算 Fisher 增益再贪心；w-pose 栅格化器已有梯度通路 |
| **POp-GS（CVPR2025）** | OED 重构：T-optimality/D-optimality 胜 A/E；块对角近似含相关性 | 直接给"选帧准则"的理论升级；T/D 准则在 keyframe 实验大幅超 uniform/FisherRF |
| **AG-SLAM arXiv:2410.17422** | Fisher EIG + CRLB，主动 SLAM 位姿+地图联合 | EIG 可预算到"帧"粒度 |
| ActiveGAMER / ActiveSplat / NARUTO / HGS-Planner | 渲染不确定性驱动 NBV + 全局-局部 kf 选择 | 全局-局部两层 kf 架构可借 |
| CG-SLAM | 深度不确定性感知的 3DGS-SLAM | A 类为主，借其不确定性建模 |
| **RK-SLAM（Applied Sciences 2025）** | **相关关键帧窗口**：按共视+空间距离（非时序）选联合优化帧，跨序"loop-closure-like" | **Top 落地**：我们的精修窗口目前是"时序最近 8+随机 2"——换成共视图上的相关帧窗口，直接治"精修帧组合次优" |
| DGS-SLAM（arXiv:2411.10722） | kf 准则 = **共视 Gaussian 的 IoU** + 相对位姿 + unique_kfID 驱动的 loop-aware 窗口 | 我们已有 unique_kfID/n_obs 账目——把它升级为"高斯视角的共视图"是顺手的事 |
| GQGS-SLAM | CLIP 评视觉清晰度/冗余度辅助选帧 | 重模型；思想（帧质量分）可换轻量代理 |

## 5. 动态场景特化（**与我们 transition 语境最贴**）

| 论文 | 机制 | 可迁移性 |
|---|---|---|
| **GaME（CVPR2026, "Gaussian Mapping for Evolving Scenes"）** | **keyframe 管理 + DSA 模块**：kf 入图时触发"几何 add/remove/move（视外变化）"适配——渲染候选 remove 集到**共视 kf**做光度+几何一致性验证后删除；kf 管理器 mask stale 区域；共视窗口局部优化。深度 +325%、色彩 +29% vs 最强基线 | **本项目的直接对标物**：我们的 transition（placing/removing/kidnapping）就是"视外几何变化"。它证明了 kf 管理=生命周期机制的**载体**（与我们 A5 软先验+deferred_commit 的判词互印证）。必须精读+对标差异化 |
| 2510.23928（ROBOVIS2026） | 深度重投影 warping + 光度/SSIM 混合误差 + **动量感知动态阈值**（θ=μ+kσ，选中后衰减 γ=0.95 防连发） | 动量阈值=自调节 kf 密度，治我们 Bonn 慢运动"阈值卡死"问题；纯 numpy 开源，即插 |
| DGS-SLAM（MDPI 遥感2022 同名） | 语义帧选择策略：静态跟踪点+动态像素占比+位姿变化三阈值 | "动态像素占比"触发语义检测——对应我们"transition 窗口加密采样" |
| DYNEMO-SLAM | 动态实体感知 + 动态 kf 策略 + 场景图 | 场景图重；动态 kf 策略思想可借 |
| D2GSLAM / DyGS-SLAM / BDGS-SLAM | 静/动 4D 复合表示 + 贝叶斯静/动概率 | Phase B 机制层的对标，选帧层借"动态检测触发" |
| TAD-GS / RobustSplat / SplatMAP（monogs-ours NOTES 已录） | 短生命周期高斯致密化不足→梯度归一化/延迟致密化 | 非选帧但同谱系：调度感知致密化 |

## 6. 学习型/RL 选帧（只取调度思想，不引重模型）

| 论文 | 可取思想 |
|---|---|
| RL Meets VO（ECCV2024, RPG UZH） | VO 决策（kf/网格尺寸）→ 序列决策 + reward（位姿误差/耗时）——映射到我们：reward=held-out PSNR 增益/计算预算，但离线可先做 oracle 上限 |
| SumGraph / FocusGraph / AKS / ADA | 帧图递归建模、coverage 目标+自适应分段采样——共性思想：**先粗覆盖后精化、相关性+覆盖联合目标**；全部可翻译成"离线两阶段 kf 调度" |

## 7. 本项目 Top5 落地策略（排序）

前提：GT 位姿离线、6GB 可冒烟、目标是 transition 生命周期机制研究。

1. **GaME 式"keyframe 管理 = 生命周期机制载体"**（对标+差异化）：transition
   事件由 kf 管理器触发 DSA——候选 add/remove 集渲染到共视 kf 做一致性验证
   （我们 A5 软先验+deferred_commit 已有原型）。**注意**：GaME 处理"视外变
   化"，我们的 placing/removing 是**视内变化**——差异点正好是我们 E0/账本
   结论的用武之地（视内需证据账本+观察窗）。论文对标必读，避免撞车。
2. **共视图 + 子模贪心选帧**（治 Phase A "kf 稀疏卡死"）：帧=共视高斯集合，
   目标 = 基线约束下覆盖 IoU≥θ 的 weighted set cover，贪心选边际覆盖最大帧；
   动量阈值（2510.23928）自适应密度。替代 MonoGS overlap 启发式，1-1/e 有
   理论背书。**坑**：贪心按"当前地图"算共视 → 顺序依赖；离线可两遍（先
   GT 深度融合粗图再重选）。
3. **精修窗口 = 共视图相关帧**（RK-SLAM 思想）：把"最近 8+随机 2"换成
   "共视图上与当前帧 Jaccard top-k + 桥接帧"，直接治精修组合次优。**坑**：
   窗口爆炸需预算上限；与 lifecycle 账本交互时注意 kfID 对齐。
4. **Fisher/T-optimality 帧评分做精修预算分配**（POp-GS）：26k 精修均摊改
   为按帧信息增益加权采样。**坑**：Fisher 每帧 20s 量级（POp-GS 报告），需
   块对角/对角近似；先做 oracle 对照证明上限存在再上工程。
5. **KD-tree 视点剪枝**（NBV-Gym）：候选帧按位姿 KD-tree 取近邻再精评，6GB
   显存下的算力伸缩器。**坑**：近邻≠高共视（旋转不变平移近），用位姿测地
   距离更稳。

## 8. 与 Phase A 止损判决的连接

Phase A 证明"流式 SLAM 语义弱 + 逐帧无差别更强不了多少"——本图谱给出的
出路是：**把选帧从"阈值启发式"升级为"覆盖/信息目标下的组合优化"**（§7.2/3），
并把 kf 管理器升格为**生命周期机制的原生挂点**（§7.1，GaME 已证明该路线的
顶会可行性）。这与 ROADMAP §4.2 的 B0/M 臂设计兼容：B0 对照 = 新选帧调度，
M 臂 = 调度上的生命周期门控，单变量纪律不变。
