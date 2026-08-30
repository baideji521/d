# TEMPLATE_SPEC —— 模板（一键组合）

实现在 `libraries/template_library.py`。模板是「一个落点 → 一组元素」的展开规则，
不是新的元素类型 —— 展开后落进 JSON 的还是普通的 freeze / effect / audio / caption。

## 内置模板

- `template_high_point` 高光冲击 —— Freeze + Zoom + Flash + Impact 音效 + 弹跳字幕（1.5s）
- `template_shock_cut` 震撼切点 —— Shake + RGB Split + 速度线素材 + 短促文字（0.8s）
- `template_intro_title` 开场标题 —— Punch In 标题 + Vignette + 逐词字幕（2.5s）
- `template_slow_emphasis` 慢放强调 —— Pulse 呼吸 + 光晕素材 + 黑底字幕（2.0s）

自定义模板放 `assets/templates/*.json`，与内置同 id 时以自定义为准。

## 模板结构

```json
{
  "id": "template_high_point",
  "name": "高光冲击",
  "description": "...",
  "duration": 1.5,
  "elements": [
    {"type": "freeze", "offset": 0.0, "duration": 1.2, "track": "V1"},
    {"type": "effect", "name": "zoom", "offset": 0.0, "duration": 0.6,
     "track": "V1", "params": {"scale_from": 1.0, "scale_to": 1.35}},
    {"type": "audio", "asset_role": "impact", "offset": 0.0,
     "duration": 0.8, "track": "A3", "volume": 0.9},
    {"type": "caption", "template": "bounce_big", "offset": 0.1,
     "duration": 1.0, "track": "T1", "text": "就是这里"}
  ]
}
```

`offset` 是相对落点的秒数；`asset_role` 是「要哪一类素材」而不是写死 id ——
具体 id 由调用方按当前素材库解析。

## 展开

```python
TemplateLibrary().expand(template_id, at_time, context, make_id)
```

`context` 必须提供：

- `base_clip_id` —— 落点所在的视频片段（Freeze / Effect 的 target）
- `base_source_time` —— 该片段在落点处对应的**源素材**时间（Freeze 冻哪一帧）
- `impact_asset` —— Impact 类音效 id；**为空就跳过那个音频元素**，不编一个 id 出来
- `caption_library` / `animation_library` —— 套样式与关键帧

`make_id` 由调用方给，保证不和现有元素撞 id。
拿不到必需上下文的元素会被跳过而不是塞默认值 —— 模板不负责编造素材。

## 与 Planner 的关系

`core/editing_planner.py` 的 `highlight` 动作是**同一套编辑意图的代码实现**
（Freeze → Zoom → Impact 音效 → 字幕强调），
模板库则是 GUI 里「一键套用」的入口。两者都只产出普通元素，
所以后续的校验、稀疏化、渲染路径完全一致。
