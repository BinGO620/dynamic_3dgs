# verdict — baseline_vanilla（阶段0）

## 判决

**阶段0：未达标收口，不进入阶段1机制实验。**

- 事实：全部 4 序列 held-out PSNR 11-12dB（目标 ≥20）；深度 L1 135-143cm。
- 归因（可复核）：①无细节致密化——ADC 阈值语义在米制场景失效（NOTES 踩坑），
  2cm 融合云的纹理细节无法生长；②移动物体残影（robot/box）在多时刻融合地图中
  互相冲突，正是本研究要解决的 ghosting 现象，但基线尚不能把静态背景拟合到
  足以分离残影信号的水平（depth-consistent 像素 PSNR 18dB vs 全图 12dB）。
- 依据：本目录 summary_eval.json、per_frame_eval.csv、NOTES 踩坑记录、
  ROADMAP 修正案 A1-A4。

完整记录与数字见 ../README.md 与 ../transition_analysis.json
