# 最终媒体能力清单

这份文档是给人看的汇总；**机器可读的唯一真相源是
`docs/AI_MEDIA_CATALOG.json`**，由 `python tools/build_catalog.py` 从真实注册表、
真实素材清单、Remotion 运行时注册表生成，`--check` 可查漂移
（`tests/test_catalog.py` 会因文档未重新生成而失败）。

## 1. 特效

- 库里共 **24 个**：program effect 14 个 + 素材特效 10 个
- program effect（有 Remotion renderer，全部真实渲染过）：
  zoom / shake / spin / bounce / pulse / blur / motion_blur / brightness /
  contrast / saturation / flash / vignette / rgb_split / glitch
- 素材特效（overlay 元素 + 素材文件，不是 renderer）：
  dust / explosion / fire / glow / light_leak / lightning / particle / smoke /
  spark / speed_lines
- 明细：`docs/EFFECT_CATALOG.md`

## 2. 转场

- 共 **11 个**，与 Remotion 运行时注册表一一对应，全部真实渲染过：
  fade / crossfade / flash / whip / zoom / wipe / slide / push / spin / blur / glitch
- 清单来自源码扫描 + 运行时注册表（`out/acceptance/discover_renderers.mjs`），
  不是手写。工厂函数生成的 renderer（fade / slide / push）靠运行时探测才拿得到，
  只做正则扫源码会漏。
- 明细：`docs/TRANSITION_CATALOG.md`

## 3. 音效

「系统支持的类型」与「本地实际存在的文件」严格分开，不虚构本地文件：

- 支持的类型 **13 类**：bgm（→A1）、tts（→A2），其余全部落 A3 ——
  boom / impact / whoosh / riser / glass / metal / wood / footstep / ui / soft / imported
- 本地实际存在 **240 个**文件，缺失 **0** 个
- 各类数量：ui 100、impact 41、footstep 25、metal 20、wood 20、glass 15、soft 10、
  whoosh 3、boom 2、riser 2、bgm 1、tts 1、**imported 0（支持但本地暂无文件，如实显示）**
- 音效元素形状（真实产出，稀疏）：
  ```json
  {"id": "audio_001", "type": "audio", "track": "A3", "asset": "<asset id>",
   "start": 0.0, "duration": 0.6, "source": {"start": 0.0, "end": 0.6},
   "volume": 0.8, "fade": {"in": 0.05, "out": 0.1}}
  ```
- 明细：`docs/SOUND_EFFECT_CATALOG.md`；真实播放验证见 `docs/FINAL_RENDER_MATRIX.md`

## 4. 分辨率

- 3:4：810×1080（默认）/ 1080×1440 / 1440×1920
- 9:16：720×1280 / 1080×1920 / 1440×2560
- 唯一真相源 `core/resolution.py`；GUI 下拉与比例联动，宽高一路走到 MP4
- 明细：`docs/RESOLUTION_GUIDE.md`

## 5. 轨道与落位

9 条轨道：V1 主视频 / V2 视频叠加 / V3 图片 Overlay / V4 高层 Overlay /
A1 背景音乐 / A2 语音 / A3 音效 / T1 字幕 / T2 普通文字。
落位策略只有一处实现（`gui/asset_placement.py`）：视频→V1（占用顺延 V2/V3/V4）、
图片→V3、overlay→V4、音乐→A1、语音（含 tts）→A2、音效→A3、字幕→T1、文字→T2。

## 6. 标记

写在 `meta.markers`，类型 normal / highlight / transition / caption / sfx /
ai_highlight，各带颜色。为空时**整个键不出现**；v1/v2 schema 都显式允许，
Remotion 侧忽略——兼容扩展，不是 schema 破坏。

## 7. AI 契约

- AI 只产出 **Timeline JSON**，永远不产出 TSX
- 输出保持稀疏：等于 Runtime 默认值的字段一律不写
- 时间单位永远是秒，帧率只用于帧对齐与渲染
- 完整契约（含元素类型、默认值、落位策略、示例）见 `docs/AI_MEDIA_CATALOG.json`
  与 `docs/TIMELINE_JSON_EXAMPLES.md`；GUI 操作说明见 `docs/TIMELINE_GUI_GUIDE.md`
- 全类型示例时间线：`docs/demo_full_timeline.json`
  （由真实 GUI 手势产出，并真实渲染成
  `out/acceptance/render/gui/demo_full_timeline.mp4`）
