# JSON → Remotion 字段映射表

每一行都是从源码读出来的实际链路，格式统一为：

```
JSON 字段 → Python 产出位置 → Exporter → TSX 消费位置 → Remotion API
```

Exporter 一列全部是 `render/remotion_exporter.py:RemotionExporter.export()`，
它把 timeline **原样**写进 `remotion/timeline.json` 与 `src/timeline-data.ts`，
**不做任何字段转换**，所以这一列在下文统一简写为 `原样透传`。

秒 → 帧的换算只发生在 Remotion 侧，唯一入口是
`remotion/src/lib/timeline.ts` 的 `toFrames(seconds, fps) = Math.round(seconds * fps)`
与 `toDurationFrames(seconds, fps) = Math.max(1, toFrames(...))`。

> 已知违规：`remotion/src/TimelineVideo.tsx:195` 的 `timelineDurationInFrames()`
> 自己写了一遍 `Math.round(seconds * fps)`，未复用 `toDurationFrames`。见 ARCHITECTURE_AUDIT.md P0-2。

---

## 1. 顶层与 meta

| JSON | Python | TSX | Remotion API |
| --- | --- | --- | --- |
| `version` | `core/timeline.py:18 SCHEMA_VERSION` | `lib/timeline.ts:93` | 仅类型，不参与渲染 |
| `time_unit` | `core/timeline.py:19 TIME_UNIT` | `lib/timeline.ts:94` | 仅校验用 |
| `meta.name` | `empty_timeline()` | `render.mjs:55` 日志 | — |
| `meta.fps` | `empty_timeline()` | `Root.tsx:20,31` | `<Composition fps>` / `useVideoConfig().fps` |
| `meta.width` | `empty_timeline()` | `Root.tsx:21,32` | `<Composition width>` |
| `meta.height` | `empty_timeline()` | `Root.tsx:22,33` | `<Composition height>` |
| `meta.background` | `empty_timeline()` | `TimelineVideo.tsx:136` | 根 `<AbsoluteFill style.backgroundColor>` |
| （派生总时长） | `core/timeline.py:445 timeline_duration()` | `TimelineVideo.tsx:190 timelineDurationInFrames()` | `<Composition durationInFrames>` + `calculateMetadata` |

## 2. tracks

| JSON | Python | TSX | Remotion API |
| --- | --- | --- | --- |
| `tracks[].id` | `core/timeline.py:24 DEFAULT_TRACKS` | `lib/timeline.ts:260 trackZIndex()` | `<Sequence style.zIndex>` |
| `tracks[].kind` | `core/timeline.py:40 TYPE_TRACK_KIND` | — | 仅 GUI/校验用（`RULE_TRACK_002`） |
| `tracks[].hidden` | `timeline_model.py:588 toggle_track_flag` | `TimelineVideo.tsx:123,132` | 整条轨不生成 `<Sequence>` |
| `tracks[].locked` | 同上 | — | 仅 GUI（禁止拖动），不影响渲染 |
| 轨道**顺序** | `core/timeline.py:454 track_z_index()` = `index * 10` | `lib/timeline.ts:260` 同算法 | `zIndex` |

## 3. 所有元素共有

```
element.id
  → core/timeline.py:489 next_element_id()   （clip_001 / effect_003 …）
  → 原样透传
  → TimelineVideo.tsx:139 key / :140 Sequence name
  → <Sequence name>（仅 Studio 里显示）

element.type
  → core/timeline.py:52 ELEMENT_TYPE_LABELS 的 9 种
  → 原样透传
  → TimelineVideo.tsx:68 ElementRenderer 的 switch
  → 决定用哪个 Layer 组件

element.start                    ← Timeline Time（成片时间）
  → core/timeline.py 各 make_* 的 start
  → 原样透传
  → TimelineVideo.tsx:141 toFrames(element.start, fps)
  → <Sequence from>

element.duration                 ← Timeline Time
  → core/timeline.py 各 make_*
  → 原样透传
  → TimelineVideo.tsx:142 toDurationFrames(element.duration, fps)
  → <Sequence durationInFrames>

element.track
  → 原样透传
  → TimelineVideo.tsx:143 trackZIndex(timeline, element.track)
  → <Sequence style.zIndex>

element.z_index                  ← 可选，覆盖轨道推导值
  → TimelineVideo.tsx:126,143 element.z_index ?? trackZIndex(...)
  → <Sequence style.zIndex>

element.label / element.note
  → 不参与渲染（note 在 schema 里注明"人工实验备注"）
```

## 4. transform → CSS（唯一实现）

`transform` 与 `keyframes` 先合成 `Geometry`，再由**一个**函数翻译成 CSS，
所有 Layer 共用，不重复实现：

```
transform.x / y / scale / rotation / opacity
keyframes.x / y / scale / rotation / opacity / blur / brightness / contrast / saturation
  → core/timeline.py:425 resolve_animated_value()      （GUI 预览侧）
  → 原样透传
  → lib/timeline.ts:190 resolveValue()  →  :219 baseGeometry()
  → effects/programEffects.ts:115 foldEffects()        （叠加此刻生效的 effect）
  → lib/timeline.ts:234 geometryToStyle()
  → React.CSSProperties
```

`geometryToStyle` 的具体产出（`lib/timeline.ts:248-256`）：

- `x` → `left: ${x*100}%`
- `y` → `top: ${y*100}%`
- `scale` / `rotation` → `transform: translate(-50%,-50%) scale(...) rotate(...deg)`
- `opacity` → `opacity`
- `blur` → `filter: blur(Npx)`（阈值 0.05）
- `brightness` → `filter: brightness(N)`（阈值 0.005）
- `saturation` → `filter: saturate(N)`（阈值 0.005）

关键帧语义（两侧必须一致，已核对）：
`keyframes[param][].time` **相对元素自身起点**，区间外端点保持，
区间内按**后一个**关键帧的 `easing` 插值 ——
`core/timeline.py:396 evaluate_keyframes()` ≡ `lib/timeline.ts:160 evaluateKeyframes()`。

`easing` 四种：`linear` / `easeIn` / `easeOut` / `easeInOut`，
`core/timeline.py:382 apply_easing()` ≡ `lib/timeline.ts:131 applyEasing()`。

## 5. type = "video"

```
asset            → lib/assets.ts assetUrl(manifest, id) → staticFile() → <OffthreadVideo src>
source.start     → VideoLayer.tsx:62  toFrames(source.start, fps)        → <OffthreadVideo trimBefore>
source.end       → VideoLayer.tsx:63  max(trimBefore+1, toFrames(end))   → <OffthreadVideo trimAfter>
speed            → VideoLayer.tsx:73                                     → <OffthreadVideo playbackRate>
audio.enabled    → VideoLayer.tsx:65  muted = (enabled === false)        → <OffthreadVideo muted>
audio.volume     → VideoLayer.tsx:75  muted ? 0 : volume ?? 1            → <OffthreadVideo volume>
transform/keyframes → geometry → :68 外层 div style
```

**Timeline Time 与 Source Time 严格分离**，已在源码确认无混淆：
`start` / `duration` 进 `<Sequence>`，`source.start` / `source.end` 进 `trimBefore` / `trimAfter`。
`core/timeline.py:154` 还额外保证 `duration = (source.end - source.start) / speed`，
`RULE_VIDEO_004` 会对不一致发 warning。

画面填充：`VideoLayer.tsx:21-25 FILL` 用 `objectFit: "cover"`（铺满裁切）。

## 6. type = "freeze"

```
target       → VideoLayer.tsx:36 findElement(timeline, target) → 取 target.asset
source_time  → VideoLayer.tsx:41 toFrames(source_time, fps) = freezeFrame
             → :47 <OffthreadVideo trimBefore={freezeFrame} trimAfter={freezeFrame+1}>
start        → <Sequence from>        （成片里从哪一刻开始冻）
duration     → <Sequence durationInFrames>  （冻多久）
             → :44 <Freeze frame={0}> 把那一帧按住
```

四要素齐全：冻结哪个素材（`target` → `target.asset`）、冻源素材哪一刻（`source_time`）、
成片从哪开始（`start`）、冻多久（`duration`）。

## 7. type = "overlay"

```
asset  → OverlayLayer.tsx:21 findAsset() / :22 assetUrl()
       → :34 若 path 匹配 /\.(mp4|mov|webm|mkv)$/i
              → <OffthreadVideo muted transparent>   （透明视频 Overlay）
         否则 → <Img>                                 （PNG / WebP 等）
transform/keyframes → geometry → :31 wrapper style
```

填充方式与 video 不同：`objectFit: "contain"`（等比适配，不裁切），
避免 PNG 构图被切掉。

素材特效（`libraries/effect_library.py` 里 `kind="material"` 的 fire / smoke / explosion …）
写入 Timeline 时 **type 就是 `overlay`**，靠 `asset` 指向素材文件，
不是 `type="effect"`。

## 8. type = "audio"

```
asset          → AudioLayer.tsx:21 assetUrl()          → <Audio src>
source.start   → AudioLayer.tsx:47 toFrames(...)       → <Audio trimBefore>（0 时传 undefined）
speed          → AudioLayer.tsx:53                     → <Audio playbackRate>
volume         → AudioLayer.tsx:26 baseVolume          → <Audio volume>
fade.in        → AudioLayer.tsx:30,37-39               → volume 回调，frame < fadeInFrames 时线性淡入
fade.out       → AudioLayer.tsx:31,40-42               → volume 回调，frame > total-fadeOutFrames 时线性淡出
start/duration → <Sequence from> / <Sequence durationInFrames>
```

`fade` 全为 0 时 `volume` 传常数而不是回调（`AudioLayer.tsx:33-45`），少一层开销。
音频完全独立于视觉，不参与 `visuals` 的 zIndex 排序（`TimelineVideo.tsx:131`）。

## 9. type = "text"

```
content.text → TextLayer.tsx → 直接作为子节点
style        → lib/textStyle.ts textStyleToCss() → React.CSSProperties
transform/keyframes → geometry → geometryToStyle()
```

`style` 支持的字段（`schemas/timeline_schema.json:93-124`）：
`fontFamily` / `fontSize` / `fontWeight` / `color` / `backgroundColor` / `align` /
`lineHeight` / `letterSpacing` / `stroke{width,color}` / `shadow{x,y,blur,color}`。

## 10. type = "caption" / "caption_group"

两者共用 `CaptionLayer.tsx`，由 `caption_style` 分派：

```
caption_style = "plain"            → :61 整段文本直出
              = "char_by_char"     → :53 按 localTime/duration 截取字符数
              = "two_line"         → :56 splitTwoLines()
              = "pop"              → :33 scale 从 0.7 缓出 + sin 过冲
              = "bounce"           → :36 scale 0.85→1 + translateY 余弦衰减
              = "word_by_word"     → :71 words.filter(word.start <= now)   逐词出现
              = "highlight_current"→ :102 当前词换 highlight.color + scale
              = "karaoke"          → :106 已读词（含当前）换 highlight.color
```

逐词时间戳链路（**绝对时间线秒数**，不是相对时间）：

```
content.words[].text  → CaptionLayer.tsx:122 <span> 内容
content.words[].start → :96 isCurrent = word.start <= now && now < word.end
content.words[].end   → :97 isPast   = now >= word.end
```

`now` 的算法（`CaptionLayer.tsx:22-23`）：
`now = element.start + useCurrentFrame()/fps`
—— 因为 `useCurrentFrame()` 是相对本 `<Sequence>` 的，必须加回 `element.start`
才能和 `words[].start` 的绝对时间对齐。这一点组件头注释也写明了。

```
highlight.color           → :65,103,107  当前词/已读词的颜色
highlight.backgroundColor → :66,105      当前词背景
highlight.scale           → :67,104      当前词放大倍数
template                  → 仅 GUI 侧套预设（libraries/caption_library.py），不进渲染分支
```

`core/timeline.py:250 make_caption_group()` 会用首尾词自动推出 `start` / `duration`。

## 11. type = "effect"

Effect 分两条完全不同的通路，由 `name` 决定：

### 11.1 geometry 类（折叠进目标元素的 geometry）

```
effect.target   → programEffects.ts:12 effectAppliesTo()
                  有 target → 只作用于该 id
                  无 target → 作用于所有 video / freeze 元素
effect.start    → :29  progress = (now - start) / duration
effect.duration → :30
effect.easing   → :32  eased = applyEasing(progress, easing ?? "easeInOut")
effect.name     → :39  switch 分派
effect.params   → :34  num(key, fallback) 逐个取
  ↓
TimelineVideo.tsx:58 foldEffects(baseGeometry(...), 生效的 effects, element, now)
  ↓
lib/timeline.ts:234 geometryToStyle() → CSS
```

各 effect 的 params → geometry 分量（`programEffects.ts:39-111`）：

- `zoom`：`scale_from` / `scale_to` → `geometry.scale *=`；`origin_x` / `origin_y` → 反向补偿 `x` / `y`
- `shake`：`amplitude` / `frequency` → `x` / `y` 正余弦位移；`rotation` → `geometry.rotation`
- `spin`：`from` / `to` → `geometry.rotation +=`
- `bounce`：`bounces` / `height` → `geometry.y -=`（带 `(1-progress)` 衰减）
- `pulse`：`scale_min` / `scale_max` / `cycles` → `geometry.scale *=`（余弦波）
- `blur`：`radius_from` / `radius_to` → `geometry.blur +=`
- `motion_blur`：`amount` → `geometry.blur += amount * 0.5`
- `brightness`：`value_from` / `value_to` → `geometry.brightness *=`
- `saturation`：`value_from` / `value_to` → `geometry.saturation *=`
- `contrast`：`value_from` / `value_to` → **用亮度近似**，`brightness *= 1 + (v-1)*0.5`
  （`programEffects.ts:104` 与 `render/preview_renderer.py` 两边都这么做，刻意保持一致）

### 11.2 screen 类（整屏叠加，不改 geometry）

名单在 `programEffects.ts:131 SCREEN_EFFECT_NAMES`：`flash` / `vignette` / `rgb_split` / `glitch`。

```
TimelineVideo.tsx:182-184 <AbsoluteFill zIndex=9000> → ScreenEffectsHost
  → :96 按 now 过滤出生效的 effect
  → ScreenEffects.tsx:147 switch(effect.name)
```

- `flash` → `ScreenEffects.tsx:36`：`color` / `intensity` / `decay` → 纯色 `<AbsoluteFill>` 的 opacity 随 easing 衰减
- `vignette` → `:59`：`intensity` / `radius` → `radial-gradient` 背景
- `rgb_split` → `:82`：`offset` / `angle` → 两个方向的 `drop-shadow` + `mixBlendMode: screen`
  （注明：不是真正的通道分离，是手感等价的近似）
- `glitch` → `:106`：`slices` / `intensity` → N 条横向色带随机偏移，
  用 `Math.sin(i*12.9898...)` 做**确定性**伪随机，保证同帧可复现

未被两条通路认领的 `name`（如 `color_shift`）在渲染端是 no-op。

## 12. type = "transition"

```
transition.from     → TransitionLayer.tsx:58 findElement(timeline, from)
transition.to       → :59 findElement(timeline, to)
transition.start    → :54 now = start + localTime
transition.duration → :56 progress = localTime / duration
transition.name     → :124 switch 分派 11 种
transition.params   → :61 num() / :65 text() 逐个取
transition.track    → TimelineVideo.tsx:160 trackZIndex(...) + 1（压在两侧片段之上）
```

`TransitionLayer` 内部两侧各渲染一个 `VideoLayer`，靠 `side()`（`:73`）统一处理：
- `:83 sampleTime` 把时间夹到元素自身区间内，超出时取端点帧
- `:100-103` 造一个 `start` 被偏移过的元素副本，让 `VideoLayer` 按元素自身时间轴取帧
- `alpha` / `offset` / `scale` / `rotation` / `blur` / `clip` 叠到 geometry 上

各 transition 的 params（`TransitionLayer.tsx:124-308`）：

- `fade` / `flash`：`color` / `intensity` → 中间插一层纯色幕布，前半段出 `from`、后半段进 `to`
- `whip`：`direction` / `intensity` / `blur` → 两侧反向位移 + 位移量正比的模糊
- `slide` / `push`：`direction` → `to` 从画外推入；`push` 时 `from` 一起被推走
- `zoom`：`scale` / `blur` → `from` 放大淡出、`to` 从放大态缩回
- `spin`：`angle` / `scale` → 旋转 + 缩放交叉
- `blur`：`amount` → 两侧同步模糊，中点最强（`1 - |progress-0.5|*2`）
- `wipe`：`direction` → `clipPath: inset(...)` 擦除
- `glitch`：`slices` / `intensity` → 按 progress 逐条 `polygon()` 揭开 `to`
- `crossfade`（也是 default）：纯 alpha 交叉

`direction` → 向量映射在 `TransitionLayer.tsx:38-43 DIRECTION_VECTOR`：
`left [-1,0]` / `right [1,0]` / `up [0,-1]` / `down [0,1]`。

> **已知 P0 缺陷**：`TimelineVideo.tsx:115-122` 把 `transition.from` / `transition.to`
> 整体从 `visuals` 里剔除，两侧片段只在转场那几帧内出现，转场窗口之外是黑的。
> 详见 ARCHITECTURE_AUDIT.md P0-1。

## 13. asset id → 真实路径（JSON 里永远只有 id）

```
element.asset = "video_001"                    ← Timeline JSON 里只有 id
  ↓
core/asset_manager.py  asset_manifest.json     id → {name,type,path,duration,width,height,fps,tags}
  ↓
render/remotion_exporter.py:127 _build_manifest()   只导出被引用到的 asset
render/remotion_exporter.py:147 _copy_assets()      拷到 remotion/public/<path>（按 mtime 增量）
  ↓
remotion/asset_manifest.json  +  src/timeline-data.ts 的 ASSET_MANIFEST
  ↓
remotion/src/lib/assets.ts  findAsset(manifest, id) → assetUrl() → staticFile(path)
  ↓
<OffthreadVideo src> / <Img src> / <Audio src>
```

`staticFile()` 只能读 `public/` 下的文件，所以第 4 步的拷贝是必须的 ——
manifest 里的相对路径（如 `assets/videos/a.mp4`）拷成
`remotion/public/assets/videos/a.mp4` 后 `staticFile` 正好命中。

`render/remotion_exporter.py:114 _referenced_assets()` 会额外扫 `element.params.asset`，
所以素材特效引用的 overlay 也会被一并拷贝。

## 14. 完整时间关系示例（取自当前 Demo，remotion/timeline.json）

```
0      ─────────────────── clip_001 (video, V1, source 0→5.75)
5.75   ── transition_001 (whip, from=clip_001, to=clip_002, 0.5s)
6.25   ─────────────────── clip_002 (video, V1)
...    overlay / text / caption / caption_group / audio / freeze / effect 各自独立
```

对应到 Remotion：

```
<Sequence from=0     durationInFrames=173>  clip_001  → OffthreadVideo trimBefore=0 trimAfter=173
<Sequence from=173   durationInFrames=15 >  transition_001 → TransitionLayer(whip)
<Sequence from=188   durationInFrames=... >  clip_002
```

（`fps=30` 时 `5.75s → 173 帧`、`0.5s → 15 帧`。）
