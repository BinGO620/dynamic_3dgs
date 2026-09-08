# NOTES.md — 研究笔记本（dynamic_3dgs）

## 实验清单（时间线）

| # | 日期 | 实验 | 状态 | 一句话结论 |
|---|---|---|---|---|
| 1 | 2026-09-08 | baseline_vanilla（阶段0基线） | 🔄 进行 | 3090 GPU1 跑 static；chenfan V100 待 env 装完跑 3 个 transition 序列。判据 G0.1-G0.4（ROADMAP §3.2）。G0.1 ✅、L2 ✅（diff=0.000 同seed全确定）。两轮关键 bug 修复：init 位姿方向反（T_cw→T_wc）+ 初始尺度用场景跨度（米级大团块，应为最近邻距离）→ 修复后 4000 步验证健康（l1_rgb 0.07-0.24、致密化正常生长、eval PSNR 18.4 爬升中） |

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
