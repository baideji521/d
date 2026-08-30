# AI 剪辑能力白名单 AI_CAPABILITIES

由 `python tools/build_catalog.py` 扫描真实注册表生成，**请勿手改**。

> AI 只能使用本文件列出的能力与参数。**没列的就是不存在的**：
> 未注册的特效 / 转场会被 Validator 报错，编造的 asset id 会被拦下，
> 白名单外的动作会被 Editing Planner 报 `UNKNOWN_ACTION`。

## 链路

1. AI 输出 EditingDecision（做什么 / 什么时候 / 多久 / 为什么）
2. core/editing_planner.py 展开成 Timeline 元素
3. core/timeline_validator.py 校验（Schema + 语义 + Registry + Rule Engine）
4. Remotion Runtime 渲染成 MP4
5. ffprobe / 抽帧 / 音频探针验收

## 动作白名单

| 动作 | 说明 | 需要 target | 备注 |
| --- | --- | --- | --- |
| `cut` | 切一刀（把片段拆成两段） | 是 | — |
| `trim` | 裁剪片段的头或尾 | 是 | — |
| `highlight` | 高光强调（冻帧 + 推镜 + 音效 + 字幕） | 否 | 展开为 `freeze_frame` + `zoom` + `impact_sfx` + `caption_emphasis` |
| `freeze` | 冻结帧 | 是 | — |
| `zoom` | 推拉镜头 | 否 | — |
| `effect` | 施加程序特效 | 否 | name 必须在 Registry 里 |
| `transition` | 在两个片段之间加转场 | 否 | name 必须在 Registry 里 |
| `overlay` | 叠加素材（图片 / 透明视频） | 否 | 必须给 asset |
| `caption` | 加字幕 | 否 | — |
| `sfx` | 加音效 | 否 | — |
| `voice` | 加配音 | 否 | 必须给 asset |
| `music` | 加背景音乐 | 否 | 必须给 asset |

决策形状：

```json
{
  "action": "zoom",
  "target": "clip_003",
  "start": 12.4,
  "duration": 0.6,
  "params": {
    "scale_to": 1.2
  },
  "reason": "强调反应瞬间"
}
```


## 元素类型

| type | 说明 |
| --- | --- |
| `video` | 视频片段 |
| `overlay` | 图片/Overlay |
| `text` | 文字 |
| `caption` | 字幕 |
| `caption_group` | 逐词字幕 |
| `audio` | 音频 |
| `effect` | 特效 |
| `transition` | 转场 |
| `freeze` | 冻结帧 |

## 特效 / 转场

- 程序特效 14 个，素材特效 10 个 —— 逐条参数见 `EFFECT_CATALOG.md`
- 转场 11 个 —— 逐条参数见 `TRANSITION_CATALOG.md`
- 音效 238 个 —— 逐条清单见 `SFX_CATALOG.md`

## 画面比例

| 比例 | 默认分辨率 | 可选档位 |
| --- | --- | --- |
| `3:4` | 1080×1440 | 720×960、810×1080、1080×1440、1440×1920、2160×2880 |
| `9:16` | 1080×1920 | 720×1280、1080×1920、1440×2560、2160×3840 |
| `16:9` | 1920×1080 | 1280×720、1920×1080、2560×1440、3840×2160 |
| `1:1` | 1080×1080 | 720×720、1080×1080、1440×1440、2160×2160 |

## 安全区

元素写 safe_area: true 才受约束；内缩比例是各平台界面的实测估算值，不是平台官方规范，只用于提示与自动收位，不改渲染结果

| 档位 | 说明 | x 范围 | y 范围 |
| --- | --- | --- | --- |
| `tiktok` | 右侧头像与按钮列、底部文案与导航栏占位最多 | 0.05 ~ 0.86 | 0.11 ~ 0.79 |
| `youtube_shorts` | 底部标题 + 订阅条，右侧互动按钮 | 0.04 ~ 0.88 | 0.08 ~ 0.84 |
| `instagram_reels` | 底部文案区最高，右侧按钮列略窄 | 0.04 ~ 0.87 | 0.10 ~ 0.80 |
| `generic` | 不确定投放平台时的保守值 | 0.05 ~ 0.95 | 0.05 ~ 0.95 |

## 规则

校验规则全表。level=error 会阻止导出，warning 只提示
（普通片段上限 15s，收尾片段豁免：是）

| 规则 | 级别 | 说明 |
| --- | --- | --- |
| `RULE_ASSET_001` | 错误 | 所有 asset 必须存在于 Asset Library |
| `RULE_ASSET_002` | 错误 | asset 引用的文件必须在磁盘上真实存在 |
| `RULE_AUDIO_001` | 错误 | volume 必须在 0 到 4 之间，fade 不得为负 |
| `RULE_AUDIO_002` | 警告 | fade.in + fade.out 不应超过 duration |
| `RULE_CAPTION_001` | 错误 | Caption 必须存在 text 或 words |
| `RULE_CAPTION_002` | 错误 | caption_group 的 words 时间必须递增且不重叠 |
| `RULE_CLIP_001` | 警告 | 普通视频片段时长不应超过 15 秒 |
| `RULE_CLIP_002` | 警告 | 每条视频轨上最后一个片段（收尾片段）允许超过 15 秒，不受 RULE_CLIP_001 限制（豁免条件） |
| `RULE_EFFECT_001` | 错误 | Effect 的 name 必须已在 EffectRegistry 注册 |
| `RULE_EFFECT_002` | 警告 | Effect 的 target 若指定，必须指向已存在的元素 |
| `RULE_EFFECT_003` | 错误 | Effect 的 target 元素类型必须在该特效的 supported_targets 内 |
| `RULE_EFFECT_004` | 错误 | Effect 的 params 必须符合 EffectRegistry 声明的类型与取值范围 |
| `RULE_EFFECT_005` | 警告 | Effect 的 params 里存在参数表之外的键，渲染时会被忽略 |
| `RULE_EFFECT_006` | 错误 | 素材特效（kind=material）必须写成 type=overlay，不能作为 type=effect 的 name |
| `RULE_FREEZE_001` | 错误 | Freeze 的 target 必须指向已存在的 Video Clip |
| `RULE_FREEZE_002` | 错误 | Freeze 的 source_time 必须落在目标 Clip 的源素材区间内 |
| `RULE_ID_001` | 错误 | 元素 id 必须全局唯一 |
| `RULE_KEYFRAME_001` | 错误 | Keyframe 时间必须递增，且不得超出元素 duration |
| `RULE_KEYFRAME_002` | 错误 | Keyframe 参数名必须在允许列表内 |
| `RULE_NUMBER_001` | 错误 | 所有数值字段必须是有限数字，不允许 NaN / Infinity |
| `RULE_SAFE_AREA_001` | 错误 | 声明了 safe_area 的元素，其 transform 位置必须落在当前平台安全区内 |
| `RULE_TEXT_001` | 错误 | Text 元素必须有非空 content.text |
| `RULE_TIME_001` | 错误 | 所有时间必须使用秒，禁止出现 frame 字段 |
| `RULE_TIME_002` | 错误 | start 不得小于 0 |
| `RULE_TIME_003` | 错误 | start / duration 不得超过 86400 秒（24 小时），否则 Runtime 会算出渲染不完的帧数 |
| `RULE_TRACK_001` | 错误 | 元素引用的 track 必须存在于 tracks 定义中 |
| `RULE_TRACK_002` | 警告 | 元素类型应与轨道类型匹配（视频元素放视频轨、音频元素放音频轨） |
| `RULE_TRACK_003` | 警告 | 需要落轨的元素必须写 track，否则时间轴上看不见它、Z 序也没有依据 |
| `RULE_TRANSFORM_001` | 错误 | opacity 必须在 0 到 1 之间，scale 必须大于 0 |
| `RULE_TRANSITION_001` | 错误 | Transition 必须连接两个已存在的 Video Clip |
| `RULE_TRANSITION_002` | 错误 | Transition 的 from 与 to 不得为同一个 Clip |
| `RULE_TRANSITION_003` | 警告 | Transition 时长不得超过任一相邻 Clip 时长的一半 |
| `RULE_TRANSITION_004` | 错误 | Transition 的 name 必须已在 TransitionRegistry 注册 |
| `RULE_TRANSITION_005` | 错误 | Transition 两侧元素类型必须在 supported_from / supported_to 内 |
| `RULE_TRANSITION_006` | 错误 | Transition 的 params 必须符合 TransitionRegistry 声明的类型与取值范围 |
| `RULE_TRANSITION_007` | 警告 | Transition 的 params 里存在参数表之外的键，渲染时会被忽略 |
| `RULE_VIDEO_001` | 错误 | source.end 不得超过源视频长度 |
| `RULE_VIDEO_002` | 错误 | duration 必须大于 0 |
| `RULE_VIDEO_003` | 错误 | source.start 必须小于 source.end |
| `RULE_VIDEO_004` | 警告 | duration 应与 (source.end - source.start) / speed 一致 |

## 配音

配音走 VoiceProvider 抽象，不绑定任何一家 TTS。timing_source=estimated 表示逐词时间戳是按字符比例估算的，不是引擎给的

| provider | 逐词时间戳 | 支持参数 |
| --- | --- | --- |
| `system` | 估算 | `voice_id` `language` `speed` |

## 示例库

tests/fixtures/ 下每份都过校验、且每轮验收都真实渲染成 MP4

- `tests/fixtures/audio.json`
- `tests/fixtures/basic_video.json`
- `tests/fixtures/caption.json`
- `tests/fixtures/caption_group.json`
- `tests/fixtures/complex_timeline.json`
- `tests/fixtures/demo_timeline.json`
- `tests/fixtures/dual_video.json`
- `tests/fixtures/effect.json`
- `tests/fixtures/freeze.json`
- `tests/fixtures/keyframe.json`
- `tests/fixtures/overlay.json`
- `tests/fixtures/res_16x9.json`
- `tests/fixtures/res_1x1.json`
- `tests/fixtures/res_3x4.json`
- `tests/fixtures/res_9x16.json`
- `tests/fixtures/transition.json`
