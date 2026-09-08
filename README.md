# dynamic_3dgs — 非SLAM动态场景 3DGS 生命周期建模

已知相机位姿的离线重建语境下，研究"物体出现/消失事件"（放置/移走/绑架）发生时，
3DGS 地图该长出什么、该抹掉什么、残影如何消除——把地图生命周期管理机制从
SLAM 在线语境迁移到纯 3DGS 渲染与建模语境。

## 定位

- **姊妹项目**：[monogs-ours](../monogs-ours)（monocular 3DGS-SLAM，paper2 子图+LCD 路线）。
  本仓库独立演进：不共享分支、不抢实验时段、**绝不改动 monogs-ours 仓库及其 conda env**。
- 与 SLAM 线的边界：本仓库**不搬 SLAM 侧代码**（tracking/BA/回环/子图），
  位姿直接用数据集真值；只读复用旧仓库的机制资产（证据账本/生命周期门控/评测）。
- 差异化赛道：动态 transition（placing/removing/kidnapping 家族）的生命周期评测，
  不在静态榜单（MipNeRF360/T&T）刷分。

## 快速开始

```bash
# 1. 环境（独立 conda env dynamic_3dgs：torch 2.1.0+cu118 + 原版 gsplat 1.5.3，
#    与 monogs-ours env 完全解耦；建库时由 wildgs-slam env 硬链接复制而来，
#    新机重建可用 pip install torch==2.1.0+cu118 gsplat==1.5.3）
export CUDA_HOME=/usr/local/cuda-11.8  # gsplat JIT 编译需要 nvcc 11.8

# 2. 数据（软链接，不复制）
ln -sfn /data/monogs-ours/datasets datasets

# 3. 门禁
python tests/test_config_valid.py   # L1: config 完整性

# 4. 冒烟（本机 2060，跑前先 nvidia-smi 查占用——见 DISCIPLINE.md GPU 政策）
python scripts/run_baseline.py --config configs/bonn/rgbd_bonn_removing_nonobstructing_box.yaml \
    --max-frames 30 --steps 300 --exp-id smoke

# 5. 基线
python scripts/run_baseline.py --config configs/bonn/rgbd_bonn_removing_nonobstructing_box.yaml
```

## 机器与环境矩阵（2026-09-08 定稿）

| 机器 | 地址 | GPU | 仓库路径 | conda env | 数据 | 备注 |
|---|---|---|---|---|---|---|
| 本机（cb） | — | RTX 2060 6GB | /data/dynamic_3dgs | /data/conda_envs/dynamic_3dgs（硬链接克隆自 wildgs-slam：torch 2.1.0+cu118 + gsplat 1.5.3） | datasets→/data/monogs-ours/datasets | 孵化/冒烟；与 monogs-ours 会话共用，上卡前查占用 |
| jiangwenheng | `ssh jiangwenheng`（172.16.227.24） | 3090×2（卡0=ComfyUI 少量占用可用；卡1=正式实验） | ~/cron/dynamic_3dgs | ~/anaconda3/envs/dynamic_3dgs（cp -al 克隆自 monogs-ours-3090 + gsplat；**只用 `python -m pip`**） | datasets/{bonn,replica,tum}→/mnt/app/datasets | JIT 编译：`CUDA_HOME=$HOME/anaconda3/envs/nvcc118` |
| chenfan | `ssh remote`（100.72.201.57） | 3090（卡0）+ V100S（卡1） | ~/dynamic_3dgs | ~/miniconda3/envs/dynamic_3dgs（torch 2.1.0+cu118 + gsplat 1.5.3） | ~/dynamic_3dgs_data（仅 3 个 transition 序列；setuptools<81，**JIT 需 `export CC=gcc-11 CXX=g++-11`**） | 网络不稳，能用则用 |

铁律（DISCIPLINE.md）：不触碰 /data/monogs-ours 仓库与 /data/conda_envs/monogs-ours；
正式实验 3090 每卡≤2 并发、固定 worker 池、与 monogs 会话错峰并先查占用；
本地 push → 远程 pull → HEAD 一致才跑。

## 阶段0基线（2026-09-08，seed 0，姜伟恒 3090）

vanilla 融合初始化 + 纯精调（真值位姿+深度，held-out 帧，判据与判决见
`results/baseline_vanilla/`）：

| 序列 | PSNR | SSIM | LPIPS | depth L1 (cm) | coverage |
|---|---|---|---|---|---|
| static | 10.96 | 0.617 | 0.795 | 135.1 | 0.861 |
| removing_nobox | 12.07 | 0.657 | 0.792 | 136.4 | 0.864 |
| placing_nobox | 11.25 | 0.616 | 0.882 | 143.4 | 0.861 |
| kidnapping_box | 12.31 | 0.636 | 0.813 | 142.4 | 0.861 |

**阶段0判决：G0.2 未达标（<20dB）→ 不进阶段1，先做阶段0.5 管线质量修复**
（细节致密化阈值修复，见 NOTES 踩坑与 results/baseline_vanilla/README.md）。

## 目录结构

```
dynamic_3dgs/          # 包：数据加载 / 高斯模型 / 离线trainer / 评测
configs/               # 每序列一个 yaml
scripts/               # 基线启动器、批量runner
results/               # 轻量产物进 git（tables/config/manifest）；重数据(PLY/render)不进
ROADMAP.md             # 预注册判据、实验矩阵、边界声明 —— 实验前写，不改
NOTES.md               # 实验登记与已验证结论
```

## 纪律（继承自 monogs-ours，同等约束力）

1. 最小单元 commit：每个可验证小步立即 commit+push。
2. 效果优先：指标不达标不写论文，禁止机制包装负结果。
3. 反过拟合：机制针对 transition 问题类别而非具体序列；终验含 held-out 序列且静态/易序列不退化。
4. GPU：正式实验只用远程 3090（每卡≤2并发），与本仓库错峰先查占用；本机 2060 只做孵化。
5. 实验登记：立项先写四件套（假设/判据/配置/预期），结果入 NOTES.md。
