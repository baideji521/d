# AI_EDITING_SPEC —— AI 怎么参与剪辑

## 唯一允许的链路

```
AI → EditingDecision（JSON）→ EditingPlanner → TimelineModel → 稀疏 Timeline JSON → Remotion
```

**AI 绝对不能直接生成 TSX**，也不能直接写 Timeline JSON 的元素。
它只输出「编辑意图」，剩下的换算、帧对齐、字段填充、校验都由 Python 做。

## EditingDecision

定义在 `core/editing_planner.py`：

```json
{ "action": "highlight", "target": "clip_001", "start": 3.2,
  "duration": 1.5, "params": { }, "reason": "这里是高光点" }
```

`from_dict()` 同时接受两种写法：`{"action": ...}` 与
`{"decision": ..., "time": ..., "actions": [...]}`。

允许的动作（`ACTIONS`）：
`cut trim highlight freeze zoom effect transition overlay caption sfx voice music`

`reason` 会写进元素的 `note` 字段 —— 决策理由跟着数据走，方便回溯。

## 高光点是一组动作

`highlight` 会展开成 `HIGHLIGHT_STEPS`：
`freeze_frame` → `zoom` → `impact_sfx` → `caption_emphasis`，
默认时长在 `HIGHLIGHT_DEFAULTS`（freeze 1.0s / zoom 0.6s / sfx 0.6s / caption 1.0s），
放大到 `HIGHLIGHT_SCALE_TO = 1.25`，音效从
`IMPACT_CATEGORIES = impact, boom, whoosh` 里挑。

## 硬拒绝：编不出来的东西一律不接

Planner 对每一项都查表，查不到就报错而不是「尽力猜」：

- 特效 / 转场名字必须在 Registry 里（`_effect_definition`：
  没有 Registry → 警告；Registry 里没有这个名字 → 错误）；
- 素材 id 必须在清单里（`_asset_ok`）；
- 动作必须在 `ACTIONS` 里。

`PlanResult` 分开返回 `errors` / `warnings` / `applied`，
`plan()` 用 deepcopy，**永远不改传进来的时间线**。

## 时间处理

- 目标片段用 `target` 指定；没指定就找「那个时刻正在播的片段」（`_resolve_clip`）。
- 源时间换算考虑 `speed`（`_source_time_at`）。
- 所有时间落盘前过 `time_utils.snap_to_frame`（`_snap`）。

## 规则引擎

`core/rule_engine.py` 是「剪辑规则实验器」的规则层：
规则定义读 `schemas/rules.json`，实现扫 `core/timeline_validator.py` 与
`core/rule_engine.py`，双向一致（`consistency_report`）。
已实现：`RULE_CLIP_001`（单个片段过长，`MAX_CLIP_SECONDS = 15`，
每条轨道的最后一个片段豁免）、`RULE_SAFE_AREA_001`（声明了安全区却不在区内）。

## 能力目录

AI 能用的一切都在 `docs/AI_CAPABILITIES.json` / `.md`，
由 `tools/build_catalog.py` 从源码生成：媒体、特效、转场、音效、动作、规则、
安全区、配音、素材、示例。系统提示词在 `docs/AI_SYSTEM_PROMPT.md`。
这些文件不许手改 —— 手改会立刻和 `tests/test_catalog.py` 打起来。

## v1 边界

v1 **不接任何 AI API**：本仓库只实现「决策 → 时间线」这半段，
决策可以由人写、由脚本写、由外部模型写。优先用系统自带能力（如 SAPI 配音），
不引入需要密钥的服务。
