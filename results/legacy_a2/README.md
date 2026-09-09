# legacy_a2 — 路线 Y 阶梯实验（预注册，2026-09-09 晚，无人值守）

判据在开跑前写下，跑完后不改。

## 假设

Phase A 止损判决的两个根因（SLAM-prune 吃新点 + 精修期无致密化）可以用
**离线多轮精修（Inria 语义）**修复：在 legacy_core 流式建图（rev3，逐帧 kf，
bonn removing 16.65dB）之上，把 26k 色彩精修替换为"全训练帧多轮优化 +
前半程 ADC 致密化 + 周期 opacity reset"。**单变量阶梯**逐杠杆解锁，量化每级
增益。

## 阶梯臂（固定 4 臂，每臂全管线重建，bonn_removing seed_0）

| 臂 | 相对下一基线的单变量 | 预期机制 |
|---|---|---|
| a1 | refine_mode: color→**offline**（多轮全训练帧，无致密化） | 训练帧访问次数与梯度多样性：多轮 vs 单遍窗口采样 |
| a2 | a1 + **前半程致密化**（frac 0.5，grad_thr 0.0002，min_opa 0.005，reset@3k） | 治"prune 吃新点"：致密化净增长转正 |
| a3 | a2 + **sh_degree 2 + SH 爬坡** | 视角相关外观细节（rev3+SH2 探针曾 +0.4） |
| a4 | a2 + **建图期 gaussian_th 0.7→0.2** | 新点存活率（rev4 曾爆浮丝，此处仅在 offline 精修护栏下重试） |

## 判据（预注册）

- 主读数：bonn_removing held-out PSNR（eval_stride=5，同 legacy_core 口径）。
- **晋级**：4 臂中最高 PSNR者为 winner；每臂对 base(16.65) 增益≥0.2dB 记为
  有效杠杆。
- **确认**：winner 复跑 tum_walking_xyz + bonn_placing（A1/A3 门）。
- **达标**：bonn_removing ≥19dB（承接 legacy_core A2 判据）。
- **早停**：任一臂达 19dB → 跳过剩余臂直接确认。
- **失败语义**：全臂 ≤16.65+0.2 → 路线 Y 判伪，verdict 记止损（证据保全：
  每臂渲染 PNG 前 8 帧）。
- L1 门禁跑过才开跑；OOM 臂记 failed 不阻塞后续（2060 6GB 风险，3090 重跑
  列入 verdict）。

## 配置

- 基座 = configs/legacy/bonn_removing_nonobstructing_box.yaml（kf_every_frame，
  stock Training/opt_params）+ 臂级 override（configs/legacy/ladder/*.yaml）。
- 臂内不变量：seed=0、eval_stride=5、数据路径、内参（L1 已含家族校验）。

## 预期

- a1 +0~0.5dB（16.65→~17）；a2 是主赌注 +1~2dB（致密化净转正）；
  a3 +0.3~0.8；a4 ±1（高方差）。合计乐观 18-19dB；≥19 需 a2 强于预期。
- 静态对照不作本晚范围（保护读数留确认轮后）。

## 运行

```bash
nohup python scripts/overnight_ladder.py > results/legacy_a2/ladder.log 2>&1 &
# 进度: results/legacy_a2/progress.json (driver 每 run 追加)
```
