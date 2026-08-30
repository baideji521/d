# 最终渲染矩阵（真实 MP4 + ffprobe 核对）

所有数字来自实跑，没有一处是估算。

- 批量渲染器：`out/acceptance/render_batch.mjs`（bundle 一次，循环 `renderMedia`）
- 特征用例日志：`out/acceptance/logs/cases.json`、`render*.json`、`final_rows.json`
- GUI 用例日志：`out/acceptance/logs/render_gui.json`、`render_gui_p8.json`、`render_gui_final.json`
- 夹具日志：`out/acceptance/logs/fixtures_render.json`、`fixtures_probe.json`
- 探针结果：`out/acceptance/logs/p8_probe_gui.json`、`p8_frames_gui.json`、`probe_gui_final.json`
- 自动生成的全量矩阵：`out/acceptance/reports/FINAL_RENDER_MATRIX.md`、`FINAL_VALIDATION.md`
- 统一探针实现：`tools/build_fixtures.py probe`（夹具与 GUI 两批共用同一套判定）

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

预置档位共 **17** 个（`core/resolution.py::ASPECT_PRESETS`）：
3:4 五档（720×960 / 810×1080 / 1080×1440 / 1440×1920 / 2160×2880）、
9:16 四档（720×1280 / 1080×1920 / 1440×2560 / 2160×3840）、
16:9 四档（1280×720 / 1920×1080 / 2560×1440 / 3840×2160）、
1:1 四档（720×720 / 1080×1080 / 1440×1440 / 2160×2160）。

- **真实渲染并 ffprobe 核对过**：810×1080、1080×1440、1080×1920、1920×1080、
  1080×1080，以及非预置的 540×960（特征用例的小画布）。
  → **四种比例全部覆盖**（3:4 / 9:16 / 16:9 / 1:1）。
- **未逐个渲染**：其余 12 档，全是已覆盖比例下的其它像素档
  （720 省流 / 1440 高清 / 2160 4K）。
  原因是渲染耗时随像素数线性增长，2160 档单条就要几分钟，而这条链路
  （GUI 下拉 → `meta.width/height` → Composition → MP4 → ffprobe）
  在同一比例的 1080 档上已经端到端验证过，剩下的只是同一条路上的不同数字。
  档位表本身由 `tests/test_resolution.py` 锁死（含反查 `aspect_of`、档位命名、
  默认档位、容差匹配）。
  这是一处**如实标注的取舍**，不是当成 PASS。

## 5. 元素夹具矩阵（16 条，全部真实渲染 + 探针）

`python tools/build_fixtures.py build` 产出 JSON，`out/acceptance/render_batch.mjs` 渲染，
`python tools/build_fixtures.py probe` 逐条核对分辨率 / fps / 视频流时长 / 帧数 / 亮度 / 音量。
结果 **16/16 OK，failures 全空，非预期黑帧 0**（明细 `out/acceptance/logs/fixtures_probe.json`）：

- `basic_video` 540×960 / 90 帧 / 3.0s / mean −26.7dB
- `dual_video` 540×960 / 120 帧 / 4.0s / mean −26.6dB
- `overlay` 540×960 / 90 帧 / 3.0s / mean −26.7dB（素材特效叠加层）
- `audio` 540×960 / 90 帧 / 3.0s / mean −25.6dB
- `caption` 540×960 / 90 帧 / 3.0s / mean −26.7dB
- `caption_group` 540×960 / 90 帧 / 3.0s / mean −26.7dB
- `freeze` 540×960 / 90 帧 / 3.0s / mean −28.6dB（2.233s 起亮度锁定 113.89，方差锁定 2447.9 → 画面真的冻住了）
- `effect` 540×960 / 90 帧 / 3.0s / mean −26.7dB
- `transition` 540×960 / 120 帧 / 4.0s / mean −26.0dB（1.8s 亮度 90.17、方差 918.9，正是 crossfade 中点）
- `keyframe` 540×960 / 90 帧 / 3.0s / mean −26.7dB（0.033s 亮度 47.2 → 0.867s 120.9，opacity 关键帧真的在渐显）
- `complex_timeline` 540×960 / 150 帧 / 5.0s / mean −27.9dB（4.4–5.0s 全黑，因为该区间只有 BGM 没有画面主体，已被 `_uncovered_ranges` 判为预期）
- `demo_timeline` 810×1080 / 210 帧 / 7.0s / mean −27.4dB
- `res_3x4` **1080×1440** / 75 帧 / 2.5s / mean −25.7dB
- `res_9x16` **1080×1920** / 75 帧 / 2.5s / mean −25.7dB
- `res_16x9` **1920×1080** / 75 帧 / 2.5s / mean −25.7dB
- `res_1x1` **1080×1080** / 75 帧 / 2.5s / mean −25.7dB

四个 `res_*` 夹具补齐了**四种画面比例都真实渲染过**这一条：3:4 / 9:16 / 16:9 / 1:1。
它们共用同一条时间线（只改 `meta.width/height`），1.0–1.4s 的 fade 转场在四个成片里
都测到 1.133–1.3s 的黑窗（亮度约 30，方差 278～415），说明转场渲染与画布尺寸解耦。

### 黑帧判定不是白名单

探针不认名字，只认时间线 JSON：
- fade / flash 转场窗口 → 渲染器设计上会经过纯色，属预期（`_veil_windows`）
- 没有任何**画面主体**（video / image / overlay / freeze / group）的区间 → 预期黑
  （`_uncovered_ranges`；文字与字幕**不算**画面主体，所以"黑底字幕"是合法的暗帧）
- 以上都不覆盖的近黑采样点 → 判 FAIL

`complex_timeline` 4.4–5.0s 与 `gui_multi_track` 2.033s 这两处最初都被判 FAIL，
排查后确认是"只剩声音/文字、没有画面"的真实结构，才补出上面第二条规则——
规则是被现象逼出来的，不是为了让测试变绿加的豁免。

## 6. GUI 全流程成片（`gui_full_flow`）

由 `out/acceptance/gui_drag.py` 的 `case_full_flow` 用真实 Qt 事件走完
导入 → 裁剪 → 分段 → 转场 → V2 叠加 → 图片 → BGM → 音效 → 特效 → 字幕 → 字幕组 →
文字 → 定格 → 变换 → 关键帧 → 四比例切换 → 导出，然后把导出的 JSON 交给 Remotion 渲染。

覆盖 9 类元素、12 个元素实例，**1080×1080 / 480 帧 / 16.0s / mean −30.0dB**，
探针判定 OK（1 个黑窗全部落在 fade 转场或无画面区间内，非预期黑帧 0）。
细节与判定见 `docs/FINAL_GUI_VALIDATION.md`。

## 7. GUI 批次探针总表（11 份，`logs/probe_gui_final.json`）

`python tools/build_fixtures.py probe --batch=out/acceptance/logs/batch_gui_final.json`
→ **11 份成片，FAIL 0**：

- `gui_drag_demo` 540×960 / 60 帧 / −26.9dB / 异常黑帧 0
- `gui_drag_demo1` 540×960 / 60 帧 / −26.4dB / 异常黑帧 0
- `gui_multi_track` 540×960 / 63 帧 / −24.8dB / 异常黑帧 0
- `gui_snap` 540×960 / 60 帧 / −26.4dB / 异常黑帧 0
- `gui_resize` 540×960 / 60 帧 / −27.9dB / 黑帧 1（预期）/ 异常黑帧 0
- `gui_res_3x4` 1080×1440 / 60 帧 / −26.9dB / 异常黑帧 0
- `gui_res_9x16` 1080×1920 / 60 帧 / −26.4dB / 异常黑帧 0
- `gui_sfx` 540×960 / 60 帧 / −26.5dB / 异常黑帧 0
- `gui_master_volume` 540×960 / 60 帧 / −32.5dB / 异常黑帧 0
- `demo_full_timeline` 810×1080 / 120 帧 / −24.5dB / 异常黑帧 0
- `gui_full_flow` 1080×1080 / 480 帧 / −30.0dB / 黑帧 1（预期）/ 异常黑帧 0

夹具批与 GUI 批走的是**同一个** `probe_one()`，判定口径完全一致。
