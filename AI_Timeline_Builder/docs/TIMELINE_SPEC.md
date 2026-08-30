# TIMELINE_SPEC —— Timeline JSON 协议

源码是唯一事实：结构定义在 `schemas/timeline_schema.json`（v1）与
`schemas/timeline_schema_v2.json`（v2），默认值定义在 `core/timeline.py`，
落盘规则定义在 `core/sparse.py`。本文档描述这三者已经实现的行为，不描述计划。

## 顶层结构

```json
{
  "version": 1,
  "time_unit": "seconds",
  "meta": { "name": "...", "fps": 30, "width": 810, "height": 1080, "duration": 7.0 },
  "tracks": [ { "id": "V1", "name": "V1 主视频", "kind": "video" } ],
  "elements": [ ... ]
}
```

- 时间单位永远是**秒**（`time_unit: "seconds"`）。fps 只用于帧对齐与渲染。
- `meta.duration` 是导出时算出来的（`tl.timeline_duration`），不是用户填的。
- `tracks` 只导出**被元素引用过**的轨道（`sparse.active_track_ids`）；
  编辑器内部始终有 9 条预设轨道。

## 轨道

来自 `core/timeline.py:DEFAULT_TRACKS`，列表顺序即图层顺序（越靠后越上层）：

- `A1` 背景音乐、`A2` 人声、`A3` 音效（kind=audio）
- `V1` 主视频、`V2` 视频叠加、`V3` 图片/Overlay、`V4` 高层 Overlay（kind=video）
- `T1` 字幕、`T2` 普通文字（kind=text）

显示顺序（自上而下）：`TRACK_DISPLAY_ORDER = T2 T1 V4 V3 V2 V1 A3 A2 A1`。
元素类型能落哪种轨道由 `TYPE_TRACK_KIND` 决定，Validator 会拦住错轨。

## 元素类型

`video` `image` `overlay` `text` `caption` `caption_group` `freeze` `audio`
`effect` `transition`（v2 另有 `group`，见 SCHEMA_V2_MIGRATION_GAPS.md）。

带 transform / keyframes 语义的类型：
`TRANSFORM_TYPES = video overlay text caption caption_group freeze`。

## 稀疏（Canonical Sparse）规则

由 `core/sparse.py` 实现，是**落盘前的最后一道**：

1. 用户没设置 → JSON 里不出现；
2. 用户设置了 → 写进 JSON；
3. 改回默认值 → 字段再删掉。

判断依据是「值 == Runtime 默认值」，绝不是真值判断 ——
`opacity: 0`、`enabled: false`、`volume: 0`、`master_volume: 0`
都是有意义的设置，必须落盘。

可省字段与默认值：

- `transform` = `{x: 0.5, y: 0.5, scale: 1.0, rotation: 0.0, opacity: 1.0}`
- `speed` = `1.0`
- `audio`（video 内嵌音轨）= `{enabled: true, volume: 1.0}`
- `volume`（audio 元素）= `1.0`
- `fade` = `{in: 0.0, out: 0.0}`
- `keyframes` / `params` 为空容器时整体删除
- `animation` 的「没有动画」就是空串
- `track.locked` / `track.hidden` = `false`
- `meta.background` = `#000000`、`meta.master_volume` = `1.0`
- `meta.markers` 为空列表时删除
- `meta.safe_area` 为「通用档」时删除（`core/safe_area.py:DEFAULT_PRESET_ID`）

`sparse.effective_timeline()` 是把默认值补齐的调试快照，**不要拿去保存**。

## 时间与帧

- 所有工厂函数把秒 `round(..., 3)`，所以帧对齐后的 16/30s 落盘是 `0.533`；
  判断帧准确性要用 `core/time_utils.seconds_to_frames`，不要拿小数比。
- `snap_to_frame` 用 Python 的银行家舍入（`round(16.5) → 16`）。
- Remotion 侧「秒 → 帧」只有一种换算：四舍五入，且时长至少 1 帧
  （`remotion/src/lib/timeline.ts`，有 node 测试守着）。

## 校验

`core/timeline_validator.py` 分两层，顺序固定：

1. NaN / Inf 预检 —— 放在 Schema 之前，否则真正的原因会被 Schema 报错盖掉；
2. jsonschema 结构校验 —— 不过就不进语义层，避免在坏结构上报一堆假问题；
3. 语义 / Registry / 素材存在性；
4. 规则引擎（`core/rule_engine.py`）。

规则 id 与实现是**双向**一致的：`rules.json` 里声明的每条规则都必须有实现，
实现里出现的每个 id 都必须在 `rules.json` 里声明；
只声明不产出的规则要显式写 `"kind": "exemption"`。
守门测试：`tests/test_validator.py::test_rules_json_与实现一一对应`。

## 分辨率与安全区

- 比例与档位表在 `core/resolution.py`：`3:4` / `9:16` / `16:9` / `1:1`，
  每个比例下 720 / 1080 / 1440 / 2160 四档（3:4 额外保留 810×1080 旧工程默认）。
- 档位按**短边**索引（`tier_of` = min(w, h)），所以横屏 1080 档是 1920×1080。
- 安全区档位在 `core/safe_area.py`：抖音 / YouTube Shorts / Instagram Reels / 通用。
  四边内缩**不对称**（抖音右侧按钮列约 14%），只影响预览参考框与
  `RULE_SAFE_AREA_001`，**不改画面、不进渲染**。内缩数值是实测估算，不是平台官方规格。

## 迁移

`core/migrations/migration_v1_v2.py` 提供 v1→v2 升级与 v2→v1 降级。
降级会丢信息（`group` 归属、`type: "group"` 的子元素），
`downgrade_losses()` 把这些损失显式列出来 —— 不允许静默丢数据。
