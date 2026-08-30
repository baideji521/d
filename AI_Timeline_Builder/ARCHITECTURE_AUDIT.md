# ARCHITECTURE_AUDIT.md —— 现状架构审计

本文件由**逐文件读源码**得出，不含任何按文件名的推测。每条结论都标注了源码位置。

审计时间：2026-08-30
审计范围：`AI_Timeline_Builder/` 全部 Python / TypeScript / JSON（不含 `node_modules`、素材二进制）

---

## 0. 一句话结论

当前仓库**已经是** `GUI → TimelineModel → Timeline JSON → Validator → Remotion → MP4` 的形态，
没有出现 `GUI → FFmpeg 命令 → MP4`，也没有出现 `AI → TSX`。
架构方向正确，问题集中在四处：**DSL 未严格类型化**、**Remotion Runtime 未分层且有一个 P0 渲染错误**、
**校验器未分层**、**缺少 tests / docs / migrations**。

---

## 1. 装配入口

`main.py`（97 行）只做依赖装配，无业务逻辑，符合设计意图。

```
main.py:main()
  ├─ AssetManager(ROOT)                        core/asset_manager.py
  ├─ Libraries(assets_dir, asset_manager)      libraries/asset_library.py
  ├─ TimelineValidator(schemas_dir, am, libs)  core/timeline_validator.py
  ├─ UndoManager()                             core/undo_manager.py
  ├─ TimelineModel(undo_manager)               core/timeline_model.py
  ├─ PreviewRenderer(model, am, libs, cache)   render/preview_renderer.py
  ├─ RemotionExporter(ROOT, am)                render/remotion_exporter.py
  ├─ ProjectManager(ROOT)                      core/project_manager.py
  └─ MainWindow(...)                           gui/main_window.py
       └─ QTimer.singleShot(50, bootstrap)
            ├─ demo_project.bootstrap_demo(am, log)   core/demo_project.py
            └─ window.load_initial_timeline(timeline, "加载 Demo 项目")
```

输入：无（命令行无参数）。输出：`app.exec_()` 返回码。

---

## 2. 实际调用关系（逐层）

### 2.1 GUI → TimelineModel

`gui/timeline_widget.py` 的 `TrackCanvas` 是 `QAbstractScrollArea` 自绘控件。
它**不直接改 timeline dict**，全部走 model 方法：

| 交互 | 调用 | 位置 |
| --- | --- | --- |
| 拖动片段 | `TimelineModel.move_element(id, start, track)` | `core/timeline_model.py:376` |
| 拖边缘裁剪 | `TimelineModel.resize_element(id, start, duration)` | `core/timeline_model.py:403` |
| 单选 / 多选 | `select` / `select_many` / `toggle_select` / `select_all` | `core/timeline_model.py:208-238` |
| Alt 拖动复制 | `TimelineModel.duplicate_in_place(id)` | `core/timeline_model.py:365` |
| 播放头拖动 | `TimelineModel.set_playhead(seconds)` | `core/timeline_model.py:239` |

`gui/property_panel.py`（约 1.1k 行）改参数走 `set_element_field(id, path, value, description)`
（`core/timeline_model.py:431`），路径式写入，天然可撤销。

**已发现的唯一违规**：`gui/main_window.py:572-573`（已修）

```python
element["effect_name"] = name     # 直接改 dict，且 effect_name 全仓库无人读取
element["params"] = params
```

`effect_name` 在 `grep` 全仓库仅此一处出现，是死字段；且 `timeline_schema.json` 的 element 定义
没有 `additionalProperties: false`，所以它能悄悄通过校验。

需要澄清的是：这两行操作的是**还没进 model 的新元素**（`add_element` 在后面才调），
所以它不算"GUI 绕过 TimelineModel 改数据"，构造元素本身是合法的。
真正的问题只有 `effect_name` 是 schema 未声明的死字段。
已改为写进 schema 里声明过的 `label`，`params` 保留（`_referenced_assets` 会读 `params.asset`）。

### 2.2 TimelineModel → Timeline JSON

`TimelineModel`（`core/timeline_model.py`，546 行）持有唯一一份 `Dict[str, Any]`，
元素都是普通 dict（`core/timeline.py:9` 明确写了"JSON 就是唯一真相，不做成 Python 类"）。

信号（`core/timeline_model.py:28-38`）：
`timelineChanged` / `elementUpdated(str)` / `selectionChanged(str)` / `historyChanged` / `playheadChanged(float)` / `logMessage(str)`

撤销机制：`_begin(description)` 打快照 → 改 dict → `_commit(structural, element_id)`
（`core/timeline_model.py:103-116`），由 `UndoManager` 保存整棵 timeline 的深拷贝。

纯函数与工厂全在 `core/timeline.py`（509 行，不依赖 PyQt）：
`empty_timeline` / `make_video` / `make_overlay` / `make_text` / `make_caption` /
`make_caption_group` / `make_audio` / `make_effect` / `make_transition` / `make_freeze` /
`apply_easing` / `evaluate_keyframes` / `resolve_animated_value` / `timeline_duration` /
`track_z_index` / `get_track` / `get_element` / `elements_on_track` / `element_end` / `next_element_id`

### 2.3 JSON 面板双向同步

`gui/json_panel.py`（265 行）：
- 正向：`TimelineModel.to_json_text()`（`core/timeline_model.py:84`）
- 反向：解析文本 → `TimelineModel.set_timeline(data, description)`（`core/timeline_model.py:150`）

`set_timeline` 内部调 `_normalize()`（`core/timeline_model.py:174`）补齐缺省字段。

### 2.4 Validator

`core/timeline_validator.py`（634 行）**一个类同时做 Schema 与语义校验**：

```
TimelineValidator.validate(timeline) -> List[Issue]        # 634 行文件的 92 行
  ├─ _validate_schema()      jsonschema 校验 timeline_schema.json（HAS_JSONSCHEMA 为 False 时静默跳过）
  ├─ _validate_global()      RULE_TIME_001（time_unit / 禁止 frame 字段）
  ├─ _validate_unique_ids()  RULE_ID_001
  └─ 逐元素：
       _validate_common()      RULE_TIME_002 / RULE_VIDEO_002 / RULE_TRACK_001 / RULE_TRACK_002
       _validate_video()       RULE_VIDEO_001 / 003 / 004
       _validate_asset_ref()   RULE_ASSET_001 / 002
       _validate_audio()       RULE_AUDIO_001 / 002
       _validate_text()        RULE_TEXT_001
       _validate_caption()     RULE_CAPTION_001 / 002
       _validate_effect()      RULE_EFFECT_001 / 002
       _validate_transition()  RULE_TRANSITION_001 / 002 / 003
       _validate_freeze()      RULE_FREEZE_001 / 002
       _validate_keyframes()   RULE_KEYFRAME_001 / 002
       _validate_transform()   RULE_TRANSFORM_001
```

`Issue` 是 dataclass（`core/timeline_validator.py:29`）：`rule_id` / `level` / `message` / `element_id` / `fields`。
`schemas/rules.json`（148 行）声明 25 条规则的 id + level + description，
`_level(rule_id)` 从这里取 error/warning —— **规则引擎已经是数据驱动的，不是硬编码的 if/else 文案**。

`invalid_element_ids()`（`core/timeline_validator.py:131`）返回 `{element_id: level}`，
Timeline 面板据此标红/标黄，错误定位到元素这一层已经通了。

### 2.5 GUI 预览（与 Remotion 并行的第二套实现）

`render/preview_renderer.py`（约 1.1k 行）用 QPainter 独立复现了一遍 Remotion 的语义，
`FrameWorker(QThread)` 调 FFmpeg 批量抽帧。
**这是"Python 自己实现视频合成"的边界情况**：它只用于 GUI 实时预览，
不参与出片，出片 100% 走 Remotion。判定为符合指令（FFmpeg 只作媒体工具链底层）。

代价是语义要人工双写：`render/preview_renderer.py` 的 `_apply_geometry_effect`
与 `remotion/src/effects/programEffects.ts` 的 `applyGeometryEffect` 必须一致，
后者文件头第 4-5 行也明确写了这个约束。

### 2.6 TimelineModel → Remotion 工程

`render/remotion_exporter.py:90 RemotionExporter.export(timeline)` 做四件事：

1. `remotion/timeline.json` ← timeline **原样写入，零转换**（`_write_json`）
2. `remotion/asset_manifest.json` ← 只含被引用的 asset（`_referenced_assets` + `_build_manifest`）
3. `remotion/src/timeline-data.ts` ← 重新生成，供 Studio 与 render.mjs 用（`_write_timeline_data`）
4. 把素材拷进 `remotion/public/`，保持 manifest 里的相对路径（`_copy_assets`，按 mtime 增量）

`_referenced_assets`（:114）会额外收集 `element.params.asset`，覆盖素材特效。

### 2.7 Remotion → MP4

```
RemotionRenderWorker(QThread).run()          render/remotion_exporter.py:212
  ├─ find_node() / find_npm()                :35 / :49（PATH 找不到时兜底扫常见安装目录）
  ├─ [可选] npm install --no-audit --no-fund
  └─ node render.mjs --out=<path>
       remotion/render.mjs:39 main()
         ├─ readJson(timeline.json) / readJson(asset_manifest.json)
         ├─ inputProps = { timeline, manifest }      ← 与 GUI 里的 JSON 完全一致
         ├─ bundle({ entryPoint: src/index.ts })
         ├─ selectComposition({ id: "TimelineVideo", inputProps })
         └─ renderMedia({ codec: h264, outputLocation, scale, concurrency })
```

成功判定用的是**输出文件是否存在**而非退出码（`render/remotion_exporter.py:234-240`），
注释说明是为了绕开 Node 24 退出时的 libuv 断言。

`remotion/src/Root.tsx` 只注册一个 Composition `TimelineVideo`，
`fps` / `width` / `height` / `durationInFrames` 全部由 `calculateMetadata` 从 `props.timeline.meta` 推导，
没有写死 —— 改 JSON 就能改成品规格。

### 2.8 Remotion 内部结构

```
remotion/src/index.ts (3 行)
  └─ Root.tsx  Composition id="TimelineVideo"
       └─ TimelineVideo.tsx (197 行)
            ├─ 拆分 elements：effects / transitions / visuals / audios
            ├─ consumed = 所有 transition.from + transition.to
            ├─ visuals 过滤掉 consumed 与 hidden 轨，按 z_index ?? trackZIndex 排序
            ├─ <Sequence from=toFrames(start) durationInFrames=toDurationFrames(duration)>
            │    └─ ElementRenderer (同文件 :47，内联组件)
            │         ├─ geometry = foldEffects(baseGeometry(el, localTime), 生效的 effects, el, now)
            │         └─ switch(element.type)
            │              video/freeze → elements/VideoLayer.tsx
            │              overlay      → elements/OverlayLayer.tsx
            │              text         → elements/TextLayer.tsx
            │              caption/caption_group → elements/CaptionLayer.tsx
            ├─ transitions.map → effects/TransitionLayer.tsx (310 行，name 分派 11 种)
            ├─ audios.map → elements/AudioLayer.tsx
            └─ ScreenEffectsHost (:92) → effects/ScreenEffects.tsx (165 行)，zIndex 9000

remotion/src/lib/timeline.ts (280 行)
  类型定义 + toFrames / toDurationFrames / applyEasing / evaluateKeyframes
  + resolveValue / baseGeometry / geometryToStyle / trackZIndex / elementEnd
  + findElement / findTrack / timelineDuration
remotion/src/lib/assets.ts (29 行)   findAsset / assetUrl（staticFile 包装）
remotion/src/lib/textStyle.ts (50 行) textStyleToCss / splitTwoLines
remotion/src/effects/programEffects.ts (137 行)
  effectAppliesTo / applyGeometryEffect / foldEffects / SCREEN_EFFECT_NAMES
```

`TimelineVideo.tsx` 目前 197 行，**还没有变成几千行巨型文件**，
但 `ElementRenderer` 与 `ScreenEffectsHost` 内联在里面，且没有独立的
`EffectRuntime` / `TransitionRuntime` / `CaptionRuntime` 抽象层。

---

## 3. 已确认的缺陷（按严重程度）

### P0-1　参与转场的片段在成品里几乎不出现

`remotion/src/TimelineVideo.tsx:115-122`

```ts
const consumed = new Set<string>();
for (const transition of transitions) {
  if (transition.from) consumed.add(transition.from);
  if (transition.to) consumed.add(transition.to);
}
const visuals = elements.filter((e) => VISUAL_TYPES.has(e.type) && !consumed.has(e.id))
```

`clip_001` / `clip_002` 被整体移出 `visuals`，只在 transition 自己那个
`<Sequence from=5.75s durationInFrames=0.5s>` 内部被 `TransitionLayer` 画出来。

用当前 Demo 验证（`remotion/timeline.json:130-142`：`whip`，`from=clip_001`，`to=clip_002`，
`start=5.75`，`duration=0.5`）：**0～5.75s 与 6.25s 之后，V1 轨是黑的**。

正确做法：transition 只该"消费"两侧片段在**转场时间窗内**的那一段，窗外仍须各自渲染。

### P0-2　`seconds → frames` 有第二处实现

指令第三十二条要求只允许一个地方做换算。`lib/timeline.ts` 提供了
`toFrames` / `toDurationFrames`，但 `TimelineVideo.tsx:195` 自己又算了一遍：

```ts
return Math.max(1, Math.round(seconds * (timeline.meta?.fps ?? 30)));
```

### P1-1　Element 未严格类型化

`schemas/timeline_schema.json:135-221` 的 `element` 是**一个扁平对象**，
把 9 种类型的字段全塞进同一个 `properties`，靠 `type` 的 enum 区分，
既没有 `oneOf`，也没有 `additionalProperties: false`。后果：

- `type="text"` 的元素写上 `source` / `speed` / `from` / `to` 也能过校验
- `effect_name` 这种拼错/废弃字段静默通过（见 2.1）
- `required` 只有 `["id", "type"]`，`video` 缺 `asset` 只能靠语义规则 `RULE_ASSET_001` 兜

### P1-2　timing / source 未分组

现状是**扁平** `start` / `duration` + `source: {start, end}`（`core/timeline.py:155-167`）。
指令第七/九/十一条要求 `timing: {start, duration}` + `source: {asset, start, duration}`。
两者语义等价（Timeline Time 与 Source Time 已经严格分开了，没有混淆），
但字段形状不同，属于**协议形状**差异，需要迁移而非重写。

### P1-3　Validator 未分层

Schema 校验与语义校验都在 `core/timeline_validator.py` 一个类里（见 2.4），
缺 `core/semantic_validator.py`。`validate()` 返回 `List[Issue]`，
不是指令第二十九条要求的 `{valid, errors[], warnings[]}` 结构。

### P1-4　Effect 分类不符合指令第二十条

`libraries/effect_library.py` 的 `category` 用的是中文标签：
`运动` / `光效` / `画质` / `风格` / `调色` / `素材特效`，
不是要求的 `geometry` / `visual` / `screen` / `overlay` / `audio`。

好消息：**参数元数据已经完备**（`key` / `label` / `type` / `default` / `min` / `max` / `step` / `options`），
`gui/property_panel.py:885-915` 已经按 `spec["type"]` 自动生成控件
（number / enum / color / asset 四种），指令第三十八条基本已满足。

### P2　缺失的文件与目录

| 指令要求 | 现状 |
| --- | --- |
| `core/timeline_document.py` | 不存在（职责在 `timeline_model.py` + `project_manager.py`） |
| `core/semantic_validator.py` | 不存在（见 P1-3） |
| `core/migrations/` | 不存在 |
| `libraries/*_registry.py` | 实际叫 `libraries/*_library.py`（asset / effect / transition / caption / animation / template，6 个都在） |
| `schemas/video_schema.json` | 不存在 |
| `schemas/overlay_schema.json` | 不存在 |
| `schemas/audio_schema.json` | 不存在 |
| `schemas/text_schema.json` | 不存在 |
| `schemas/freeze_schema.json` | 不存在（asset / caption / effect / transition / timeline / rules 这 6 个存在） |
| `render/render_manager.py` | 不存在（渲染编排散在 `main_window.py` + `RemotionRenderWorker`） |
| `remotion/src/runtime/` | 不存在 |
| `remotion/src/captions/` `animations/` `transitions/` | 不存在（transition 与 caption 各一个大文件） |
| `docs/` | 不存在 |
| `tests/` | 不存在（**0 个自动化测试**） |
| `requirements.txt` / `README.md` | 不存在 |

### P2-2　GroupElement / Template 元素类型缺失

`libraries/template_library.py`（316 行）存在，但 `core/timeline.py` 没有 `make_group`，
`TYPE_TRACK_KIND`（:40）与 schema 的 type enum 里都没有 `group`。
模板目前只能"展开成一堆平铺元素"，不能作为一个可折叠的逻辑单元。

---

## 4. 已经正常工作、必须保留的能力

以下均在源码中确认实现完整，后续阶段**只许重构不许破坏**：

| 能力 | Python 侧 | Remotion 侧 |
| --- | --- | --- |
| Video + trim + speed + 音频开关 | `core/timeline.py:144` | `elements/VideoLayer.tsx:57-79` |
| Overlay（图片 / 透明视频自动分派） | `core/timeline.py:170` | `elements/OverlayLayer.tsx:34-45` |
| Text | `core/timeline.py:190` | `elements/TextLayer.tsx` |
| Caption 8 种样式 | `core/timeline.py:218` | `elements/CaptionLayer.tsx:25-127` |
| CaptionGroup 逐词 + 高亮 | `core/timeline.py:250` | `elements/CaptionLayer.tsx:64-126` |
| Audio + fade in/out + trim | `core/timeline.py:283` | `elements/AudioLayer.tsx:33-55` |
| Freeze | `core/timeline.py:357` | `elements/VideoLayer.tsx:35-55` |
| Effect（geometry 类 10 种） | `libraries/effect_library.py:22` | `effects/programEffects.ts:39-111` |
| Effect（screen 类 4 种） | 同上 | `effects/ScreenEffects.tsx:147-164` |
| Transition 11 种 | `libraries/transition_library.py` | `effects/TransitionLayer.tsx:124-308` |
| Keyframe + 4 种 easing | `core/timeline.py:382-439` | `lib/timeline.ts:131-206` |
| Geometry → CSS 单点实现 | — | `lib/timeline.ts:234-257` |
| 撤销 / 重做 | `core/undo_manager.py` + `timeline_model.py:103` | — |
| 素材 id → 路径解析 | `core/asset_manager.py`（511 行） | `lib/assets.ts` |
| 剪映草稿导入 | `core/jianying_import.py`（195 行） | — |
| 离线 TTS | `core/tts.py` + `core/tts_synth.ps1` | — |
| 剪映风格快捷键 | `gui/shortcuts.py`（161 行） | — |

时间协议现状：`core/timeline.py:18-19` 声明 `SCHEMA_VERSION = 1` / `TIME_UNIT = "seconds"`，
`schemas/timeline_schema.json:10-11` 用 `const` 锁死。
帧只在 `lib/timeline.ts` 的 `toFrames` 出现（除 P0-2 那处），**对外协议确实是秒**。

---

## 5. 当前真实架构图（与目标图的差异用 ⚠ 标出）

```
                   ┌──────────────┐
                   │  PyQt5 GUI   │  main_window / timeline_widget / property_panel
                   │              │  preview_widget / json_panel / asset_panel / library_panel
                   └──────┬───────┘
                          │  move_element / resize_element / set_element_field / add_element
                          │  ⚠ main_window.py:572 有 1 处直接改 dict
                          ↓
                ┌──────────────────┐
                │  TimelineModel   │  唯一中间层，持有 dict，发 6 个信号，快照式撤销
                └────────┬─────────┘
                         │
                         ↓
                ┌──────────────────┐
                │  Timeline JSON   │  version=1, time_unit=seconds
                │  (core/timeline) │  ⚠ 扁平 start/duration，无 timing 分组
                └────────┬─────────┘  ⚠ 无 oneOf 严格类型
                         │
                 ┌───────┴────────┐
                 ↓                ↓
        TimelineValidator   （同一个类）⚠ 未拆出 semantic_validator
        _validate_schema    _validate_video / _transition / _freeze / ...
        (jsonschema)        rules.json 提供 25 条规则的 id + level
                 │                │
                 └───────┬────────┘
                         ↓
                ┌──────────────────┐
                │ RemotionExporter │  timeline.json 原样 + asset_manifest.json
                │                  │  + timeline-data.ts + public/ 素材拷贝
                └────────┬─────────┘
                         ↓
                 ┌───────────────┐
                 │  render.mjs   │  bundle → selectComposition → renderMedia
                 └───────┬───────┘
                         ↓
                 ┌───────────────┐
                 │ TimelineVideo │  ⚠ ElementRenderer 内联，无 runtime 分层
                 │     .tsx      │  ⚠ P0-1 转场吞掉两侧片段
                 └───────┬───────┘  ⚠ P0-2 第二处 seconds→frames
        ┌────────────────┼────────────────┐
        ↓                ↓                ↓
   VideoLayer      programEffects     AudioLayer
   OverlayLayer    ScreenEffects      CaptionLayer
   TextLayer       TransitionLayer
        └────────────────┼────────────────┘
                         ↓
                    renderMedia
                         ↓
                       MP4        ⚠ 无自动化 E2E 验证，无 render_report

  另有一条并行支路（仅用于 GUI 实时预览，不参与出片）：
  TimelineModel → render/preview_renderer.py (QPainter) → FFmpeg 抽帧
  ⚠ 特效语义需与 programEffects.ts 人工双写保持一致
```

---

## 6. 改造顺序（与指令第六十一条对齐）

已根据审计结论调整优先级：**P0 两个 Bug 先修**（指令第四十九条：先写测试 → 修复 → 保持 JSON 兼容），
再做协议演进。

1. 建 `tests/`，为 P0-1 / P0-2 写失败测试
2. 修 P0-1（transition 只消费时间窗内的片段）、P0-2（统一 `toDurationFrames`）
3. Schema / DSL v2：`oneOf` 严格类型 + `timing` 分组 + `additionalProperties: false`
4. `core/migrations/` v1 → v2，旧项目自动升级
5. TimelineModel 收口，清掉 `main_window.py:572` 的直接改 dict 与 `effect_name` 死字段
6. Validator 拆 `semantic_validator.py`，`validate()` 增加 `{valid, errors, warnings}` 形态
7. EffectRegistry 补 `geometry/visual/screen/overlay/audio` 分类
8. TransitionRegistry 元数据补齐
9. CaptionRuntime 抽出
10. Remotion Runtime 分层（`runtime/` + `elements/` + `effects/` + `transitions/` + `captions/`）
11. GroupElement + Template
12. 补 `schemas/{video,overlay,audio,text,freeze}_schema.json`
13. `docs/` 全套
14. Demo E2E + 真实 MP4 + ffprobe + `FINAL_VALIDATION.md`
