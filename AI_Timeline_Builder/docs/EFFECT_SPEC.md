# EFFECT_SPEC —— 特效规范

阶段 6 产物。本文档只描述**当前源码里真实存在**的行为；
尚未实现的部分会明确标注「未实现」，不写成已完成的样子。

---

## 1. Effect 是什么

Effect 是一个**独立的时间线元素**（`type: "effect"`），它自己不产生画面内容，
而是在自己的时间窗内修改别人的画面。

它有三个必要属性：

```text
target    ── 作用在哪个元素上
start     ── 什么时候开始（秒）
duration  ── 持续多久（秒）
```

再加上决定「做什么」的三个：

```text
name      ── 特效标识，Registry 与 Renderer 的对接键
params    ── 参数
easing    ── 进度曲线
```

---

## 2. Effect 与 Video 的关系

Effect **不拥有素材**，它没有 `asset` 字段。Video 元素负责「画面从哪来」，
Effect 负责「这段时间里这个画面怎么变形」。

在渲染期二者的关系是折叠（fold）：

```text
VideoLayer 的 geometry
  ← baseGeometry(transform + keyframes)
  ← 折叠此刻生效的 effect 1
  ← 折叠此刻生效的 effect 2
  → geometryToStyle() → CSS
```

代码位置：`remotion/src/effects/programEffects.ts` 的 `foldEffects()`，
调用点是 `remotion/src/TimelineVideo.tsx` 的 `ElementRenderer`。

**Effect 不限于作用在 Video 上**。`supported_targets` 声明了它能作用的元素类型，
当前所有元素级特效都是 `video / freeze / image / overlay / text / caption / caption_group`
（与 `TimelineVideo.tsx` 的 `VISUAL_TYPES` 一致）。`audio` 不在其中。

---

## 3. Effect 与 Transition 的区别

- **Effect 作用于一个元素**（`target` 是单个 id），改的是这个元素的表现。
- **Transition 作用于两个元素之间**（`from` / `to`），它在自己的时间窗里
  接管两侧画面并混合，被接管的元素在那几帧里自己不渲染
  （`isCoveredByTransition()`，`remotion/src/lib/timeline.ts`）。

一句话：Effect 是「修饰」，Transition 是「接管」。
两者可以叠加 —— TransitionLayer 内部同样会调 `foldEffects`，
所以转场期间片段上的特效仍然生效。

---

## 4. Effect 如何表达时间

时间单位一律是**秒**，帧只出现在 Remotion 的 `Sequence` 边界换算里。

```text
start = 24        绝对时间轴上的起点
duration = 0.6    持续时长
```

进度的定义（`remotion/src/effects/types.ts` 的 `makeEffectContext`）：

```text
localTime = now - start
progress  = clamp(localTime / duration, 0, 1)
eased     = applyEasing(progress, easing)
```

例：`start = 24`、`duration = 0.6`

```text
now = 24.0  →  localTime 0.0   progress 0
now = 24.3  →  localTime 0.3   progress 0.5
now = 24.6  →  localTime 0.6   progress 1
```

时间窗之外的处理：
- `TimelineVideo` / `ScreenEffectsHost` 只把 `start ≤ now < start + duration`
  的特效传进来，窗外的特效根本不参与折叠
- `progress` 本身也被夹在 0..1，`duration = 0` 时用 `1e-6` 兜底，不会除零

**shake / bounce / pulse 这类周期特效用 `progress` 或 `localTime` 而不是 `eased`** ——
缓动会破坏周期节奏。具体用哪个看各自的 `effects/<name>.ts`。

---

## 5. Effect 如何表达参数

`params` 是一个扁平对象，键名由 Registry 的参数表固定：

```json
{
  "name": "zoom",
  "params": {
    "scale_from": 1.0,
    "scale_to": 1.35,
    "origin_x": 0.5,
    "origin_y": 0.45
  }
}
```

每个参数在 Python 侧都有结构化定义（`ParameterDefinition`）：

```python
{
    "key": "scale_to",
    "label": "结束 Scale",
    "type": "number",
    "default": 1.35,
    "min": 0.1,
    "max": 5.0,
    "step": 0.01,
}
```

支持的类型：`number` / `int` / `bool` / `string` / `enum` / `color` / `asset`。
`integer` / `boolean` / `str` / `text` 是别名，加载时归一化。
指令里提到的 `point` 当前没有任何参数需要，**未实现**，不预先造。

### 默认值

`params` 可以只写一部分，甚至完全省略。缺的参数由
`EffectDefinition.fill_defaults()` 在**读取时**补上，
**绝不回写 Timeline JSON** —— JSON 里必须只有用户/AI 真正指定的东西。

因此「缺参数」在校验里是 warning（`MISSING_PARAMETER`），不是 error，
而且 Validator 刻意不把它上报到界面，否则每个省略的参数都会刷一条告警。

### Easing

统一四条曲线：`linear` / `easeIn` / `easeOut` / `easeInOut`。
定义在 `core/timeline.py` 的 `EASINGS` + `apply_easing()`，
Remotion 侧是 `remotion/src/lib/timeline.ts` 的 `applyEasing()`，两边算法必须一致。
特效不许自己定义一套 easing 字符串。

`flash` 的 `decay` 参数是个 enum，取值就是这四条，属于复用而非另立一套。

### Keyframes

Effect 元素本身当前**不读 `keyframes`** —— 关键帧是元素级能力，
在 `baseGeometry()` 里生效，Effect 是折叠在它之上的一层。
`params` 内部的关键帧化（例如让 `scale_to` 自己走一条曲线）**未实现**，
留给后续阶段的 Keyframe Engine。Registry 的参数定义结构不阻碍这个扩展。

---

## 6. Effect 如何指定 target

```json
{ "type": "effect", "name": "zoom", "target": "clip_001" }
```

- `target` 指定 → 只作用于该 id 的元素
- `target` 留空 → 只作用于 `video` / `freeze` 类元素（`effectAppliesTo()` 的兜底规则）
- `screen` 类特效（flash / vignette / rgb_split / glitch）**忽略 target**，
  它们盖在整个画面上。为了不让存量数据变非法，它们的
  `supported_targets` 仍然接受视觉元素，但 renderer 不看这个字段。

校验链：

```text
effect.target
  → by_id 里查到目标元素          → 查不到：RULE_EFFECT_002（warning）
  → 取 element.type
  → registry.validate_target()   → 不支持：RULE_EFFECT_003（error）
```

例：`zoom` + `target` 指向 audio 元素 → `RULE_EFFECT_003` 错误。

---

## 7. Registry 做什么

`libraries/effect_registry.py`。它是 Effect 这条链路的唯一权威来源，负责：

- 定义：`name` / `display_name` / `category` / `description` / `default_duration`
- 参数：`parameters`（每个都有类型、默认值、范围、UI 提示）
- 分类：`geometry` / `visual` / `screen` / `overlay` / `audio`
- 目标约束：`supported_targets`
- 校验：`validate(name, params)`、`validate_target(name, element_type)`
- renderer 身份：`renderer` 字符串

它**不负责**：`currentFrame`、`interpolate`、任何时间计算、任何渲染。
本文件里不出现一行时间数学。

API：

```python
registry.register(definition)
registry.unregister(name)
registry.get(name)          # → EffectDefinition | None
registry.has(name)
registry.all()
registry.categories()
registry.by_category(category)
registry.validate(name, params)         # → {valid, errors, warnings}
registry.validate_target(name, type)    # → {valid, errors, warnings}
registry.renderers()                    # name → renderer
registry.without_renderer()
```

`EffectLibrary`（`libraries/effect_library.py`）是预填了内置定义的
`EffectRegistry` 子类，另外提供 `program_effects()` / `material_effects()` /
`default_params()` / `param_spec()` / `label_of()` / `display_categories()`。

### 分类含义

分类按「作用层面」划分，不是按视觉风格：

- `geometry` —— 改位置 / 缩放 / 旋转：zoom、shake、spin、bounce、pulse
- `visual` —— 改滤镜通道：blur、motion_blur、brightness、contrast、saturation
- `screen` —— 盖整屏：flash、vignette、rgb_split、glitch
- `overlay` —— 依赖素材文件，写成 overlay 元素：fire、smoke、explosion、spark、
  lightning、light_leak、particle、speed_lines、glow、dust
- `audio` —— 分类已定义，**当前没有任何音频特效**

GUI 库面板显示的中文分组是另一个字段 `display_category`（运动 / 光效 / 画质 /
风格 / 调色 / 素材特效），纯展示用，不参与任何逻辑。

### 校验结果形状

```json
{ "valid": true, "errors": [], "warnings": [] }
```

```json
{
  "valid": false,
  "errors": [
    { "code": "OUT_OF_RANGE", "parameter": "scale_to",
      "effect": "zoom", "message": "结束 Scale：必须在 0.1～5.0 范围内" }
  ],
  "warnings": []
}
```

错误码：`UNKNOWN_EFFECT` / `INVALID_PARAMS` / `TYPE_MISMATCH` /
`OUT_OF_RANGE` / `INVALID_OPTION` / `UNSUPPORTED_TARGET`
警告码：`MISSING_PARAMETER` / `UNKNOWN_PARAMETER`

**永远不抛异常给 GUI。** 脏数据、错类型、`params` 不是对象、名字不认识，
一律返回上面这个形状。

---

## 8. Renderer 做什么

`remotion/src/effects/`。一个特效一个文件，各自只做数学。

```text
effects/
├── types.ts        EffectContext / 两种 renderer 接口 / makeEffectContext / 参数读取
├── registry.ts     EffectRendererRegistry
├── index.ts        装配点：把 14 个 renderer 注册进去
├── zoom.ts shake.ts spin.ts bounce.ts pulse.ts            geometry
├── blur.ts motionBlur.ts brightness.ts contrast.ts saturation.ts   visual
├── flash.ts vignette.ts rgbSplit.ts glitch.ts             screen
├── programEffects.ts   筛选 + 查表 + 折叠（不再有 switch）
├── ScreenEffects.tsx   全屏特效宿主（不再有 switch）
└── TransitionLayer.tsx 转场（阶段 6 未改动逻辑）
```

接口：

```ts
type EffectContext = {
  progress: number;   // 线性 0..1
  eased: number;      // 缓动后 0..1
  localTime: number;  // 相对特效起点的秒数
  duration: number;   // ≥ 1e-6，可直接做除数
  fps: number;
  params: Record<string, unknown>;
};

type GeometryEffectRenderer = (geometry: Geometry, ctx: EffectContext) => Geometry;
type ScreenEffectRenderer = React.FC<{ ctx: EffectContext }>;
```

`Geometry` 的通道：`x` `y` `scale` `rotation` `opacity` `blur` `brightness` `saturation`
（定义在 `lib/timeline.ts`）。geometry renderer 必须返回**新对象**，不得就地修改。

### 职责分界

Registry 知道 `from` 和 `to` 是 number；Renderer 知道
`interpolate(from, to, progress)`。两者不互相越界。
Renderer 里不出现范围检查，Registry 里不出现插值。

### 与 Python 的对接

```text
libraries/effect_library.py  _PROGRAM_META  ──► EffectDefinition.renderer
                                                      │  同一个字符串
Timeline JSON  { "name": "zoom" }  ───────────────────┤
                                                      ▼
remotion/src/effects/index.ts  effectRenderers.get("zoom")
```

Python 不执行 TS，TS 不读 Python 的定义文件。唯一契约是名字。
`tests/test_effect_registry.py::test_renderer_名与特效名一致` 和
`registry.test.ts::已注册的名字必须与 Python EffectDefinition.renderer 一致`
两边各自钉住这份名单。

### screen 特效为什么不用 JSX

`effects/index.ts` 整条依赖链刻意保持纯 `.ts`（screen 特效用
`React.createElement`），这样 `node --test` 的原生类型剥离能直接加载注册表来测试。
Node 处理不了 JSX。

---

## 9. GUI 如何读取参数

`gui/property_panel.py` 的 `_add_param_rows()` 已经是数据驱动的：
它遍历 `definition.get("params")`，按每个 spec 的 `type` / `min` / `max` / `step` /
`options` 生成控件，没有 `if effect == "zoom"` 这类硬编码。

`EffectDefinition` 和 `ParameterDefinition` 都实现了 Mapping 协议，
所以既能 `definition.supported_targets` 结构化访问，
也能 `definition["label"]` / `spec["key"]` 兼容既有代码 —— 引入 Registry
没有打断任何 GUI 调用点。

`ParameterDefinition.ui` 给出建议控件（`slider` / `spin` / `checkbox` /
`combo` / `color` / `asset` / `line`）。**属性面板当前还没有读这个字段**，
它是按 `type` 自己推的。让面板改读 `ui` 属于阶段 6 明确排除的 GUI 改造，未做。

创建入口（也都是数据驱动的）：
- `gui/main_window.py::_add_program_effect` 拖拽落点
- `gui/main_window.py::_add_effect_to` 右键菜单
- 两者都用 `libraries.effect.default_params(name)` 和
  `effect.get("default_duration")`，加新特效不需要改这两个函数

---

## 10. AI 如何生成 Effect

人类描述：

```text
24 秒开始，对 clip_001，做 0.6 秒快速放大，从 1 倍到 1.35 倍，easeOut
```

Timeline JSON（v1 Runtime 形状）：

```json
{
  "id": "fx_001",
  "type": "effect",
  "track": "V1",
  "name": "zoom",
  "target": "clip_001",
  "start": 24,
  "duration": 0.6,
  "easing": "easeOut",
  "params": { "scale_from": 1.0, "scale_to": 1.35 }
}
```

链路：

```text
Registry.has("zoom")                       ✔ 已注册
Registry.get("zoom").category              geometry
Registry.get("zoom").supported_targets     含 video → target 合法
Registry.validate("zoom", params)          valid
Registry.get("zoom").renderer              "zoom"
        ↓
effectRenderers.geometry("zoom")
        ↓
makeEffectContext → progress / eased
        ↓
interpolate(scale_from, scale_to, eased) → geometry.scale → CSS transform
```

### 未知特效

AI 写出 `"name": "super_magic_zoom"` 时：

```json
{
  "valid": false,
  "errors": [
    { "code": "UNKNOWN_EFFECT", "effect": "super_magic_zoom",
      "message": "特效 super_magic_zoom 未在 EffectRegistry 注册" }
  ],
  "warnings": []
}
```

Validator 上报 `RULE_EFFECT_001`（error），带 `element_id`，Timeline 面板可以标红。
渲染端 `effectRenderers.get()` 返回 `undefined`，geometry 原样返回，
`ScreenEffects` 返回 `null` —— **不崩，但也什么都不渲染**。

拦截职责在 Validator，安全兜底在 Renderer，两层都不许抛异常。

---

## 11. 新增一个特效要改哪些文件

```text
1. libraries/effect_library.py   加定义 + 在 _PROGRAM_META 里登记 (category, renderer)
2. remotion/src/effects/<name>.ts   写 renderer
3. remotion/src/effects/index.ts    注册进去
```

不需要改：`TimelineModel`、`TimelineValidator`、`gui/property_panel.py`、
`gui/main_window.py`、`TimelineVideo.tsx`、`ScreenEffects.tsx`、`programEffects.ts`。

`tests/test_effect_registry.py::test_新增特效不需要改_Validator` 用一个
运行时注册的 `warp` 特效钉住了这条保证。

自定义特效也可以完全不改代码：在 `assets/effects/*.json` 里按
`schemas/effect_schema.json` 的形状写定义，启动时会合并进 Registry。
但这种特效**没有 renderer**，只能过校验、不会出画面。

---

## 12. 当前状态与缺口

已实现且可渲染：14 个程序特效（10 geometry/visual + 4 screen）。

只有 metadata、没有 effect renderer：10 个素材特效。
它们不是缺功能 —— 它们写进 Timeline 时是 `type: "overlay"` 元素，
由 `OverlayLayer` 渲染。用它们做 `type: "effect"` 的 name 是错的，
会被 `RULE_EFFECT_006` 拦下。

明确未实现（后续阶段）：
- `audio` 分类下没有任何特效
- `params` 内部的关键帧化
- `point` 参数类型
- 属性面板读 `ParameterDefinition.ui`
- `motion_blur` 的 `angle` 参数不参与计算（CSS 无方向性模糊，退化成等量高斯模糊）
- `contrast` 用亮度近似，不是真对比度
- Remotion 端的实际出画效果尚未经过真渲染验证 —— 单测和 typecheck 只能证明
  查表与数学正确，不能证明画面对
