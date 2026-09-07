# DISCIPLINE.md — 实验纪律（dynamic_3dgs）

> 从 monogs-ours/DISCIPLINE.md 继承改写。约束力同等；本项目特有差异集中在
> 第一验收标准、序列集、GPU 政策三节。

## 最高准则

0. **每次会话、每个任务开工前必须先读本文件**，并逐条对照即将做的事。
   切换项目（含回 monogs-ours）时先读对应仓库的纪律文件再动手。
1. **没有 test 的实验不算完成**
2. **config 是实验的唯一定义**，跑实验只改 config，不改代码
3. **results 只写不改**，原始输出不可覆盖
4. **代码必须完全一致**，本地改了没 push 就让远程跑 = 大忌
5. **每完成一个最小完成单元就 commit+push**（写完一个文件、跑完一个臂、
   得到一个判决都是一个单元），不攒批、不用问用户。好结果坏结果都提交。
6. **负结果不是终点**：先穷尽改善路径（查 bug→调 config→换机制角度）；
   禁止用"诚实负结果也是贡献"收尾；失效机制分析只能出现在"下一步止损
   或改善决策"的位置，不得起包装性命名当结论。
7. **第一验收标准 = 渲染质量 + 残影指标**（本项目与 SLAM 线的根本差异）：
   - 主表：PSNR / SSIM / LPIPS + depth L1-cm（离线全帧 + held-out 帧）
   - 机制指标：transition 后新视图 PSNR 恢复速度、残影强度
     （static_eval 的 vacated/ghost_excess 拆分）、物体移除区重影残留
   - **位姿用数据集真值，无 ATE 问题**——所有质量差异都归因于地图生命周期机制
8. **方法通用性（反过拟合，继承）**：机制针对 transition/生命周期问题
   类别而非具体序列；机制参数须有诊断依据（log 数据/原理），不得逐序列
   试出；任何机制验证必须包含未参与调参的 held-out 序列，且静态/易序列
   （bonn_static、balloon 家族）不得退化。

## 与 monogs-ours 的边界（铁律）

1. **严禁改动 /data/monogs-ours**：不 commit、不 checkout、不 stash、
   不 pip install、不动其 conda env（/data/conda_envs/monogs-ours，
   内含定制 diff_gaussian_rasterization 编译产物）。
2. 复用方式 = 只读引用 + 按文件复制搬运；搬来的文件按本项目结构重构，
   **不得保留对旧仓库的运行时依赖**（含 import 路径、config 字段）。
3. SLAM 侧（tracking/BA/回环/子图）一律不搬；位姿用数据集真值。
4. 不与 monogs-ours 会话抢同一批正式实验时段（错峰，见 GPU 政策）。

## 机器与 GPU 政策

| 机器 | 别名（本机 ~/.bashrc） | 硬件 | 用途 |
|---|---|---|---|
| 本机（cb） | — | RTX 2060 6GB | **主演化**：孵化、冒烟、小规模基线 |
| jiangwenheng | `ssh jiangwenheng`（172.16.227.24） | RTX 3090 ×2 24GB | **正式实验** |
| chenfan | `ssh remote`（100.72.201.57） | V100S 32GB | 备用（非本仓库正式实验机） |

- 正式实验只用 3090 双卡；**每卡最多两个并发**，用固定 worker 池派发
  （禁止运行期动态选卡）。
- **错峰纪律**：3090 与 monogs-ours 会话共用。上卡前必查
  `ssh jiangwenheng nvidia-smi`（GPU0 常被占用）；正式批量跑前在本仓库
  NOTES.md 实验清单登记（时间/序列/占用卡）。
- 本机 2060 只跑孵化与 ≤640×480 的小规模验证，跑前 `nvidia-smi` 确认空闲。

## 标准序列集

| 类别 | 序列 | 用途 |
|---|---|---|
| transition 主战场 | bonn `placing_{non,}obstructing_box×4`、`removing_{non,}obstructing_box×3`、`kidnapping_box×2` | 生命周期机制主实验 |
| 静态对照 | bonn `static`、`static_close_far` | 不退化保护 + 地基验证 |
| 运动体制谱系 | bonn `balloon*`、`crowd×3`、`person_tracking*`、`synchronous×2` | 泛化/压力测试 |
| 跨数据集 | TUM fr3 `walking/sitting` 家族 | held-out 泛化 |
| 静态高质量 | Replica office0-4 / room0-2 | 机制通用性验证 |

- 每个实验提案先回答："若成功，transition 指标改善多少？静态/易序列
  会不会退化？"答不上来不开工。
- 非标准序列（如静态 MipNeRF360 类）不引入——差异化在 transition，
  不在静态刷榜。

## 目录结构

| 目录 | 职责 |
|---|---|
| `configs/` | 输入：每序列/每实验 config（yaml） |
| `scripts/` | 工具：run/eval/批量脚本 |
| `tests/` | 门禁：验证测试 |
| `results/{exp_id}/` | 输出：README + evidence/{verdict.md, manifest.json} + run 目录 |

results/ 内轻量文件（tables/config/README/verdict/manifest）进 git；
重数据（PLY/render 图/point_cloud）不进 git（见 .gitignore）。

## 命名规范

- 实验 ID：小写字母 + 下划线，不加版本号、不加日期
- 种子目录：`seed_0`, `seed_1`, `seed_2`
- 临时文件：`debug_` 前缀，跑完必须清理

## 实验流程

```
1. 立项四件套      →  假设/判据/配置/预期 写入 results/{exp_id}/README.md
2. 写 config       →  configs/{exp_id 或序列}/
3. 写 run 脚本     →  scripts/
4. 本机 2060 孵化  →  小规模跑通 + L1/L2 门禁
5. 3090 正式跑     →  查占用 → NOTES 登记 → sync → run → pull
6. eval + verdict  →  results/{exp_id}/ + NOTES.md 实验清单
7. pytest 全通过   →  实验完成
```

## 本地→远程工作流

铁律：**本地 commit+push → 远程 git pull → HEAD 一致 → 才能跑**。

## 三层门禁

| 层级 | 验证内容 |
|---|---|
| L1 config | 语法正确、字段完整、路径存在（新建 config 后、启动 run 前必跑） |
| L2 run | 同 config 同 seed 两次跑结果一致（允许小浮动） |
| L3 eval | 指标在预期范围、与 baseline 对照合理 |

## results 规范

- 跑完实验必须写 `verdict.md`（只写事实：达标/未达标/终止 + 改善或止损
  动作）和 `manifest.json`（可追溯元数据）
- 原始输出不可覆盖、禁止手动编辑；重复跑生成新 seed 目录
- run 目录布局：`{sequence}/seed_{n}/`（按序列）或 `{arm}_seed{n}/`（多臂）

## 文档系统

| 文档 | 给谁看 | 唯一职责 |
|---|---|---|
| `README.md` | 外部用户 | 项目是什么、怎么装、怎么跑 |
| `DISCIPLINE.md` | AI 智能体 | 实验纪律（本文件） |
| `ROADMAP.md` | 研究者 | 预注册判据、实验矩阵、边界声明——实验前写，判据不改 |
| `NOTES.md` | 研究者 | 研究笔记本（实验清单/结论/坑） |
| `resources/` | — | 外部参考资料 |

单一事实源：一个事实只写在一个文档里，其他地方引用。

| 事件 | 必须更新 |
|---|---|
| 新实验立项 | 四件套 + `NOTES.md` 实验清单追加一行 |
| 实验完成 | `results/{exp_id}/`（README+verdict+manifest）+ `NOTES.md` |
| 踩坑 | `NOTES.md` 踩坑记录 |
| 纪律变更 | 只改 `DISCIPLINE.md` |
| 安装/用法变化 | `README.md` |

## AI 智能体规范

- 跑前说清楚：跑什么、为什么、预期；跑后给结论：成功/失败、关键指标、下一步
- 外部审阅意见（Codex/文献）只作参考；最终决策 = 本项目实际数据 + 自己的
  思考 + 对方案的理解
- 跑实验不许改核心代码（`dynamic_3dgs/` 包），只能改 config 和 scripts；
  改代码前必须确认
- 每个实验全部产出在 `results/{exp_id}/` 下，不许散落根目录

## 禁止事项

- ❌ 改 config 后不跑 L1 就 commit / 开跑
- ❌ 手动编辑 results/ 原始输出
- ❌ 跑实验不保存 config 副本
- ❌ 没有 eval 脚本就声称实验完成
- ❌ 本地改代码没 push 就让远程跑
- ❌ 负结果不尝试改善就写机制解释当结论
- ❌ 完成多个文件后才一起提交（攒批）
- ❌ 未查 3090 占用就上正式批量
- ❌ 触碰 /data/monogs-ours 仓库或 /data/conda_envs/monogs-ours
