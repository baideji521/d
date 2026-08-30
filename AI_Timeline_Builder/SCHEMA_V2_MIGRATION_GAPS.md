# SCHEMA_V2_MIGRATION_GAPS.md

阶段 5 的遗留清单。**没有任何字段被偷偷删掉**，下面逐条说明去处。

当前状态：

- `schemas/timeline_schema.json` —— v1，**仍然是运行时格式**。GUI、PreviewRenderer、
  RemotionExporter、Remotion Runtime 全部读写它。
- `schemas/timeline_schema_v2.json` —— v2，目标协议。已定稿、已被 30 个用例覆盖，
  但**还没有任何运行时代码切过去**。
- `core/migrations/migration_v1_v2.py` —— 双向迁移，v1 → v2 → v1 逐字段无损（有测试）。

这样做的原因：一次性把 GUI + 预览 + Remotion 全切到 v2，改动面会横跨十几个文件，
不符合"一阶段一验收"。v2 先以"可校验、可迁移、可测试"的形态落地。

---

## 1. 字段形状变化（有迁移，无丢失）

- `start` / `duration`（元素顶层）→ `timing: {start, duration}`
  当前位置：所有元素。v2 对应：`timing`。需要迁移：是（`_element_to_v2`）。
- `source: {start, end}`（video / audio）→ `source: {start, duration}`
  `duration = end - start`，单位是**源素材内部时长**，不是成片时长。需要迁移：是。
- `speed`（video / audio）→ `playback: {speed}`
  需要迁移：是。
- `name` / `params` / `easing`（effect 顶层）→ `effect: {name, params, easing}`
  需要迁移：是。
- `name` / `params`（transition 顶层）→ `transition: {name, params}`
  需要迁移：是。`from` / `to` 保持在元素顶层。

## 2. 形状不变、原样搬运的字段

`id`、`type`、`track`、`label`、`note`、`z_index`、`asset`、`transform`、
`keyframes`、`animation`、`audio{enabled,volume}`、`volume`、`fade{in,out}`、
`content{text}`、`content{words}`、`style`、`caption_style`、`template`、
`highlight`、`target`、`source_time`。

这些在 v2 里逐字保留，`additionalProperties: false` 已经把它们全部登记在案。

## 3. v1 有、v2 里**刻意不收**的字段

目前没有。v1 schema 声明过的每一个 element 属性都在 v2 的某个变体里有对应。

唯一被移除的是 `effect_name` —— 它在阶段 4 就删掉了（全仓库无人读取、
v1 schema 也没声明，属于会静默通过校验的死数据），来路信息改写进 `label`。

## 4. v2 有、v1 里没有的东西

- `image` 元素类型。v1 里图片走 `overlay`。
  迁移策略：**不做自动转换**。仅凭 JSON 无法可靠区分"静态图片"与"透明视频 Overlay"
  （要查素材类型），硬猜会改变渲染行为。v1 的 overlay 迁到 v2 后仍是 overlay。
- `group` 元素类型 + `children` + 元素上的 `group` 回指。
  v1 完全没有对应物，`migrate_v2_to_v1()` 会丢掉这两个字段 ——
  这是唯一一处 v2 → v1 的有损方向，因为 v1 里确实无处安放。
  影响范围：只要 GroupElement 还没启用（阶段 12 才做），就不会触发。
- `playback` 子对象。v1 只有裸 `speed`。

## 5. 已知的、刻意保留的宽松点

- **v1 的 element 定义没有 `additionalProperties: false`。**
  一旦打开，任何历史项目里的额外字段都会立刻变成 error。
  按指令第十条，严格化交给 v2 承担；v1 保持宽松直到运行时切换完成。
  已有测试固定住这个差异：`tests/test_timeline_model.py::test_未知字段_v1_放过_v2_拦下`。

- **数值范围规则在两层都有。**
  `start >= 0`、`duration > 0`、`scale > 0`、`volume <= 4` 这些既写在 schema 里
  （按指令第二十八条属于 Schema 层职责），`rules.json` 里也有同名语义规则
  （`RULE_TIME_002` / `RULE_VIDEO_002` / `RULE_TRANSFORM_001` / `RULE_AUDIO_001`）。
  jsonschema 可用时 Schema 层先命中，语义规则是缺依赖时的兜底，不算重复实现。

- **`asset` 的位置与指令原文有出入。**
  指令第十一条的示例把 asset 放在 `source.asset`，第十二/十三条又放在元素顶层。
  v2 统一采用**元素顶层 `asset` + `source` 只装 trim 窗口**，理由是第十条要求
  "所有元素引用 `asset: 'explosion_001'`"，一条规则覆盖 video / image / overlay / audio
  比按类型分两套更不容易出错。这是有意偏离，不是遗漏。

## 6. 切到 v2 时还要动的地方（阶段 6 之后）

- `core/timeline.py` 的 11 个 `make_*` 工厂 —— 目前产出 v1 形状
- `core/timeline_model.py` 里读 `element["start"]` / `element["source"]["end"]` 的位置
- `gui/property_panel.py` 的字段路径（`["transform","scale"]` 之类要变成 `["timing","start"]`）
- `render/preview_renderer.py`
- `remotion/src/lib/timeline.ts` 的类型定义与 `toFrames` 调用点
- `schemas/rules.json` 的规则字段路径描述

在那之前，`TimelineModel.to_v2_dict()` / `from_dict()` 已经能承担
"对外说 v2、对内跑 v1"的翻译职责。
