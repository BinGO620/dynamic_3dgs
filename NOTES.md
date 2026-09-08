# NOTES.md — 研究笔记本（dynamic_3dgs）

## 实验清单（时间线）

| # | 日期 | 实验 | 状态 | 一句话结论 |
|---|---|---|---|---|
| 1 | 2026-09-08 | baseline_vanilla（阶段0基线） | ✅ 完成 | 四序列 rc=0（姜伟恒3090）。**G0.2 未达标**：held-out PSNR 11-12dB（目标≥20），depth L1 135-143cm。G0.1/G0.4 ✅（L2 diff=0.000，跨机逐值一致）；G0.3 ⚠️ 2/3（placing 2.37✓ kidnapping 3.10✓ removing 1.96✗）。**判决：不进阶段1，先做阶段0.5管线质量修复**（细节致密化阈值修复）。verdict: results/baseline_vanilla/evidence/verdict.md |
| 2 | 2026-09-09 | baseline_v3（阶段0.5，A5协议） | ✅ 完成 | 外部调研+Codex 定位根因后重做：深度 L1 **135→34-49cm（3.1-3.8×改善）**、LPIPS 改善、G0.3 三序列凹陷全过（4.54/2.63/2.54dB）。PSNR 仅 +0.4~+1.3dB；曝光对齐只 +0.5dB（排除曝光主因）。图像证据确认：动态物体近距视角对静态地图是**原理上不可重建像素**。G0.2 改判（A6）：深度线✅、静区 12.2dB 未达 18dB。60k 长跑验证访问次数杠杆中（baseline_v3_long）。verdict: results/baseline_v3/evidence/verdict.md |

（新实验立项时在此追加一行；详细结论写入下方"已验证结论"，证据在 results/{exp_id}/）

## 当前方向

非 SLAM 的动态场景 3DGS 生命周期建模：transition 家族（placing/removing/kidnapping）
上，把 monogs-ours 验证过的证据账本+生命周期门控迁到离线 vanilla 3DGS，单变量配对
验证因果效应。判据唯一入口：`ROADMAP.md`（预注册）。

## 已验证结论

- **阶段0基线判决（2026-09-08，baseline_vanilla，姜伟恒3090，seed0）**：
  融合初始化+纯精调在 Bonn 四序列 held-out PSNR 11-12dB，远低于 20dB 门槛。
  归因证据：①depth-consistent 像素 PSNR 18dB vs 全图 12dB → 移动机器人/box
  残影拖累是真实构成部分；②无细节致密化（ADC 阈值语义失效，见踩坑）是主因。
  G0.3 凹陷信号存在（placing 2.37dB、kidnapping 3.10dB）但噪声地板高。
  **已验证：同 seed 同 config 跨机（3090/V100）训练轨迹逐值一致**——管线确定性
  成立，配对机制实验的内部效度有保障。
- **阶段0.5 判决（2026-09-09，baseline_v3）**：A5 协议把深度质量做对了
  （ghost 壳被软一致率先验压制，静态共识面保留），**"静态融合地图在动态近距
  视角有原理性误差地板"已用渲染图像证实**——全帧 PSNR 门槛（≥20dB）对该
  任务本身不可达，改用 depth L1 + 静区 PSNR（A6）。剩余光度缺口在细节锐度
  （60k 长跑验证中）。
- **阶段0.5 文献落地**（tavily 调研 + Codex 审阅）：像素足迹尺度初始化与
  空洞/残差致密化=SplaTAM 与 Geometry-Aware Online Mapping (2608.14902) 的
  在线映射规则；training-free 稠密种子=CoGS-SLAM；首帧致密化后固定数量=
  Dynamic3DGS；曝光对齐评测采纳其"报告 raw+aligned"建议。

（项目新建于 2026-09-08，其余继承自 monogs-ours 的机制设计约束
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
  （2026-09-08）：`pip install` 实际把包装进了 wildgs-slam；已完整恢复源 env
  （卸载误装包、重装 numpy==1.26.3 / opencv-python==4.8.1.78 并验证）。
  **规矩：克隆 env 里一律用 `python -m pip install`，绝不用其 bin/pip 入口。**
- torch cu118 直下走 corkscrew 代理仅 ~0.3MB/s；清华镜像直连快，小包一律走镜像。
- gsplat 1.5.3 API：`rasterization(means, quats, scales, opacities, colors,
  viewmats, Ks, width, height)`——SH 作为 colors 第 5 位置参数；DefaultStrategy
  字段名是 `reset_every`/`refine_stop_iter`；renders=(C,H,W,D)、alphas=(C,H,W,1)。
- **2060 与 monogs-ours 会话共用**：其调试 run 会占满 6GB。上卡前必须
  `nvidia-smi` 查占用；显存不足时 cusolver 报 CUSOLVER_STATUS_INTERNAL_ERROR
  （torch.inverse 创建句柄失败），不是代码 bug。
- **gsplat 1.5.3 DefaultStrategy 阈值不迁移到米制场景**（2026-09-08）：梯度归一化
  `grads *= width/2 × n_cameras` 的语义与 Inria 原版不一致，实测 means2d 梯度
  范数 p50≈2e-7，vanilla 阈值 0.0002（×320 后有效阈值 6.25e-7）导致 24% 高斯
  永远超阈 → clone/split 指数爆炸（单视图 4.8k→146k）且拟合崩坏（17.5dB→9.5dB）；
  阈值×320（0.064）则完全不致密化。**结论：离线 RGB-D 基线弃用 ADC，
  改用深度融合稠密初始化 + 纯精调**（SplaTAM 式哲学；且每个高斯有出生帧，
  正好是阶段1生命周期机制的挂点）。ADC 留作 cfg.use_adc=true 的研究路径。
- **gsplat render_mode="RGB+D" 的深度是未归一化累积值**：alpha<1 处系统性偏近，
  深度损失/评测必须用 "RGB+ED"（期望深度）+ alpha≥0.5 覆盖掩码，否则空洞按
  |0−gt| 计入损失，米级量纲的梯度会摧毁 RGB 优化（单视图过拟合正常、
  多视图崩坏的"假象"即由此而来）。
- **pkill 自匹配**（重蹈旧仓库覆辙）：`pkill -f run_baseline.py` 会匹配到自身
  shell 的命令行导致自杀，必须用 `pkill -f "run_baseline[.]py"` 括号技巧。
- **nvcc 11.8 + gcc13 不兼容**（chenfan 机）：`#error unsupported GNU version`；
  解决 = `export CC=gcc-11 CXX=g++-11`。setuptools≥81 移除 pkg_resources，
  torch cpp_extension 需要 → 固定 setuptools<81。
- **移动物体污染静态假设**：rgbd_bonn_static 里有移动机器人，多时刻融合的云
  中机器人外壳互相冲突，深度 L1 被抬到几十 cm——这不是 bug，正是无生命周期
  管理的 vanilla 融合地图的 ghosting 现象本身，基线的价值就是量化它。
