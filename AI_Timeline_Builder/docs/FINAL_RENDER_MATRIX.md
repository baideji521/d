# 最终渲染矩阵（真实 MP4 + ffprobe 核对）

所有数字来自实跑，没有一处是估算。

- 批量渲染器：`out/acceptance/render_batch.mjs`（bundle 一次，循环 `renderMedia`）
- 特征用例日志：`out/acceptance/logs/cases.json`、`render*.json`、`final_rows.json`
- GUI 用例日志：`out/acceptance/logs/render_gui.json`、`render_gui_p8.json`
- 探针结果：`out/acceptance/logs/p8_probe_gui.json`、`p8_frames_gui.json`
- 自动生成的全量矩阵：`out/acceptance/reports/FINAL_RENDER_MATRIX.md`、`FINAL_VALIDATION.md`

## 1. 特征用例全量（155 条）

`python out/acceptance/analyze.py final` 的判定：

- PASS 155、FAIL 0、SKIPPED 11、NOT_IMPLEMENTED 2
- 两个源视频完整渲染对照（demo / demo1）PASS，P0 转场 PASS，音频 PASS，黑帧检测 PASS

**转场覆盖**：真实渲染出 MP4 的转场共 11 个，与 Remotion 运行时注册表
（`node out/acceptance/discover_renderers.mjs`）一一对应，无遗漏：
crossfade / fade / flash / whip / zoom / wipe / slide / push / spin / blur / glitch。

**特效覆盖**：真实渲染出 MP4 的 program effect 共 14 个，与运行时注册表一致：
zoom / shake / spin / bounce / pulse / blur / motion_blur / brightness / contrast /
saturation / flash / vignette / rgb_split / glitch。
Python 侧另有 10 个**素材特效**（dust / explosion / fire / glow / light_leak /
lightning / particle / smoke / spark / speed_lines），它们不是 program renderer，
而是 overlay 元素 + 素材文件，单独在 overlay 用例里渲染。

## 2. GUI 手势产出的渲染（第一批 5 个，540×960）

`gui_drag_demo` / `gui_drag_demo1` / `gui_multi_track` / `gui_snap` / `gui_resize`
全部 OK，ffprobe 复核 540×960 / 30fps / duration == `meta.duration`，均带 AAC 立体声。

## 3. GUI 手势产出的渲染（阶段 8 新增 5 个）

JSON 全部由真实 Qt 事件（拖放 / 裁剪 / 属性面板 / 项目设置对话框 / 音量滑块）产出，
渲染 5/5 OK，ffprobe 逐个核对：

- `gui_res_3x4`：**1080×1440**（3:4）、30fps、60 帧、2.048s、aac 48kHz 立体声 → PASS
- `gui_res_9x16`：**1080×1920**（9:16）、30fps、60 帧、2.048s、aac 48kHz 立体声 → PASS
- `gui_sfx`：540×960、2.048s、音效 `sfx_impact` 落在 A3，`volume = 0.6`、
  `fade = {"in": 0.05, "out": 0.1}`，实测 mean −26.5dB / max −9.9dB → PASS
- `gui_master_volume`：与 `gui_sfx` **同一条时间线，只多了 `meta.master_volume = 0.5`**，
  实测 mean −32.5dB / max −16.0dB → PASS
- `demo_full_timeline`：810×1080（3:4）、4.053s、120 帧、mean −24.5dB → PASS

容器时长 2.048s / 4.053s 与 `meta.duration` 2.0 / 4.0 的差是 MP4 容器把
音频末帧补齐造成的（视频帧数 60 / 120 正好等于 2s / 4s × 30fps），不是时长算错。

### 音量真的生效（不是"看着像"）

`gui_sfx` 与 `gui_master_volume` 的 JSON 只差一个 `meta.master_volume = 0.5`：

- 实测响度差 **6.0 dB**
- 理论值 20·log₁₀(0.5) = **6.02 dB**

这条对照是「音量参数真的走到最终 MP4」的证据，不依赖人耳。

### 画面异常抽帧检测

每个 MP4 抽 4～5 帧缩到 32×32 计算均值 / 标准差 / 相邻帧差：
无全黑（均值均 > 100，唯一一次 36.83 出现在 `demo_full_timeline` 2.0s 处，
正是 fade 转场中点，属预期）、无纯色（标准差 44～71）、无冻结（相邻帧差 11～85）。
明细：`out/acceptance/logs/p8_frames_gui.json`。

## 4. 分辨率矩阵的覆盖情况（如实说明）

预置档位共 6 个：3:4 = 810×1080 / 1080×1440 / 1440×1920，
9:16 = 720×1280 / 1080×1920 / 1440×2560。

- **真实渲染并 ffprobe 核对过**：810×1080（`demo_full_timeline` 与全量特征用例）、
  1080×1440、1080×1920、540×960（特征用例的小画布）。
- **未逐个渲染**：720×1280、1440×1920、1440×2560。
  原因是渲染耗时随像素线性增长，而分辨率这条链路（GUI 下拉 → `meta.width/height`
  → Composition → MP4）在 1080×1440 与 1080×1920 上已经端到端验证过，
  剩下三档只是同一条路上的不同数字。档位表本身由 `tests/test_resolution.py` 锁死。
  这是一处**如实标注的取舍**，不是当成 PASS。
