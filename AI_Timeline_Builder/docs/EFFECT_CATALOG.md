# Effect 目录

由 `python tools/build_catalog.py` 扫描真实注册表生成，**请勿手改**。

- Python 注册表：`libraries/effect_library.py`（`EffectRegistry`）
- Remotion renderer：`remotion/src/effects/index.ts`
- 共 24 个特效：material 10 个、program 14 个

`kind=program` 是程序特效（`type=effect` 元素，靠 `target` 绑定被作用元素）；
`kind=material` 是素材特效（写成 `type=overlay` 元素，本质是叠加一段素材）。

## Renderer 覆盖（program 特效）

探测方式：已从 Remotion 运行时注册表读取

- Python 注册表：14 个
- Remotion 注册表：14 个
- Python 有、Remotion 缺 renderer：无
- Remotion 有、Python 未登记：无

## 一览

| name | 中文名 | 分类 | kind | renderer | 默认时长 |
| --- | --- | --- | --- | --- | --- |
| `bounce` | Bounce 弹跳 | 运动（geometry） | `program` | `bounce` | 0.5s |
| `pulse` | Pulse 呼吸 | 运动（geometry） | `program` | `pulse` | 0.8s |
| `shake` | Shake 抖动 | 运动（geometry） | `program` | `shake` | 0.4s |
| `spin` | Spin 旋转 | 运动（geometry） | `program` | `spin` | 0.5s |
| `zoom` | Zoom 推拉 | 运动（geometry） | `program` | `zoom` | 0.6s |
| `dust` | Dust 灰尘 | 素材特效（overlay） | `material` | `—` | 2s |
| `explosion` | Explosion 爆炸 | 素材特效（overlay） | `material` | `—` | 0.8s |
| `fire` | Fire 火焰 | 素材特效（overlay） | `material` | `—` | 1.2s |
| `glow` | Glow 光晕 | 素材特效（overlay） | `material` | `—` | 0.8s |
| `light_leak` | Light Leak 漏光 | 素材特效（overlay） | `material` | `—` | 1s |
| `lightning` | Lightning 闪电 | 素材特效（overlay） | `material` | `—` | 0.5s |
| `particle` | Particle 粒子 | 素材特效（overlay） | `material` | `—` | 1.5s |
| `smoke` | Smoke 烟雾 | 素材特效（overlay） | `material` | `—` | 1.5s |
| `spark` | Spark 火花 | 素材特效（overlay） | `material` | `—` | 0.6s |
| `speed_lines` | Speed Lines 速度线 | 素材特效（overlay） | `material` | `—` | 0.5s |
| `flash` | Flash 闪白 | 光效（screen） | `program` | `flash` | 0.2s |
| `glitch` | Glitch 故障 | 风格（screen） | `program` | `glitch` | 0.35s |
| `rgb_split` | RGB Split 色差 | 风格（screen） | `program` | `rgb_split` | 0.3s |
| `vignette` | Vignette 暗角 | 光效（screen） | `program` | `vignette` | 1s |
| `blur` | Blur 模糊 | 画质（visual） | `program` | `blur` | 0.5s |
| `brightness` | Brightness 亮度 | 调色（visual） | `program` | `brightness` | 0.5s |
| `contrast` | Contrast 对比度 | 调色（visual） | `program` | `contrast` | 0.5s |
| `motion_blur` | Motion Blur 运动模糊 | 画质（visual） | `program` | `motion_blur` | 0.3s |
| `saturation` | Saturation 饱和度 | 调色（visual） | `program` | `saturation` | 0.5s |

## 逐个说明

### `bounce` · Bounce 弹跳

- 分类：运动（`geometry`）
- kind：`program`　scope：`element`
- renderer：`bounce`
- 默认时长：0.5s
- 可作用元素：`video`、`freeze`、`image`、`overlay`、`text`、`caption`、`caption_group`
- 说明：垂直方向弹跳衰减

| 参数 | 名称 | 类型 | 默认 | 取值 |
| --- | --- | --- | --- | --- |
| `height` | 弹跳高度（画面比例） | `number` | 0.08 | 0 ~ 0.5，步长 0.01 |
| `bounces` | 弹跳次数 | `int` | `2` | `1` ~ `8`，步长 `1` |

### `pulse` · Pulse 呼吸

- 分类：运动（`geometry`）
- kind：`program`　scope：`element`
- renderer：`pulse`
- 默认时长：0.8s
- 可作用元素：`video`、`freeze`、`image`、`overlay`、`text`、`caption`、`caption_group`
- 说明：周期性缩放，适合持续强调

| 参数 | 名称 | 类型 | 默认 | 取值 |
| --- | --- | --- | --- | --- |
| `scale_min` | 最小 Scale | `number` | 1 | 0.1 ~ 3，步长 0.01 |
| `scale_max` | 最大 Scale | `number` | 1.08 | 0.1 ~ 3，步长 0.01 |
| `cycles` | 周期数 | `int` | `2` | `1` ~ `10`，步长 `1` |

### `shake` · Shake 抖动

- 分类：运动（`geometry`）
- kind：`program`　scope：`element`
- renderer：`shake`
- 默认时长：0.4s
- 可作用元素：`video`、`freeze`、`image`、`overlay`、`text`、`caption`、`caption_group`
- 说明：按频率随机位移画面，制造冲击感

| 参数 | 名称 | 类型 | 默认 | 取值 |
| --- | --- | --- | --- | --- |
| `amplitude` | 幅度（画面比例） | `number` | 0.02 | 0 ~ 0.3，步长 0.005 |
| `frequency` | 频率（次/秒） | `number` | 18 | 1 ~ 60，步长 1 |
| `rotation` | 附带旋转（度） | `number` | 1.5 | 0 ~ 30，步长 0.5 |

### `spin` · Spin 旋转

- 分类：运动（`geometry`）
- kind：`program`　scope：`element`
- renderer：`spin`
- 默认时长：0.5s
- 可作用元素：`video`、`freeze`、`image`、`overlay`、`text`、`caption`、`caption_group`
- 说明：画面整体旋转

| 参数 | 名称 | 类型 | 默认 | 取值 |
| --- | --- | --- | --- | --- |
| `from` | 起始角度 | `number` | 0 | -720 ~ 720，步长 5 |
| `to` | 结束角度 | `number` | 15 | -720 ~ 720，步长 5 |

### `zoom` · Zoom 推拉

- 分类：运动（`geometry`）
- kind：`program`　scope：`element`
- renderer：`zoom`
- 默认时长：0.6s
- 可作用元素：`video`、`freeze`、`image`、`overlay`、`text`、`caption`、`caption_group`
- 说明：以指定中心点缩放画面，最常用的高光强调手法

| 参数 | 名称 | 类型 | 默认 | 取值 |
| --- | --- | --- | --- | --- |
| `scale_from` | 起始 Scale | `number` | 1 | 0.1 ~ 5，步长 0.01 |
| `scale_to` | 结束 Scale | `number` | 1.35 | 0.1 ~ 5，步长 0.01 |
| `origin_x` | 中心 X | `number` | 0.5 | 0 ~ 1，步长 0.01 |
| `origin_y` | 中心 Y | `number` | 0.45 | 0 ~ 1，步长 0.01 |

### `dust` · Dust 灰尘

- 分类：素材特效（`overlay`）
- kind：`material`　scope：`asset`
- renderer：`—`
- 默认时长：2s
- 可作用元素：—
- 说明：空气尘埃，做氛围层

| 参数 | 名称 | 类型 | 默认 | 取值 |
| --- | --- | --- | --- | --- |
| `asset` | 素材 | `asset` | （空） | — |
| `scale` | 缩放 | `number` | 1 | 0.1 ~ 4，步长 0.05 |
| `opacity` | 不透明度 | `number` | 1 | 0 ~ 1，步长 0.05 |
| `blend` | 混合模式 | `enum` | `screen` | `normal` / `screen` / `add` |

### `explosion` · Explosion 爆炸

- 分类：素材特效（`overlay`）
- kind：`material`　scope：`asset`
- renderer：`—`
- 默认时长：0.8s
- 可作用元素：—
- 说明：爆炸素材，常配 Impact 音效

| 参数 | 名称 | 类型 | 默认 | 取值 |
| --- | --- | --- | --- | --- |
| `asset` | 素材 | `asset` | （空） | — |
| `scale` | 缩放 | `number` | 1 | 0.1 ~ 4，步长 0.05 |
| `opacity` | 不透明度 | `number` | 1 | 0 ~ 1，步长 0.05 |
| `blend` | 混合模式 | `enum` | `screen` | `normal` / `screen` / `add` |

### `fire` · Fire 火焰

- 分类：素材特效（`overlay`）
- kind：`material`　scope：`asset`
- renderer：`—`
- 默认时长：1.2s
- 可作用元素：—
- 说明：火焰素材叠加，建议放 V3/V4 轨

| 参数 | 名称 | 类型 | 默认 | 取值 |
| --- | --- | --- | --- | --- |
| `asset` | 素材 | `asset` | （空） | — |
| `scale` | 缩放 | `number` | 1 | 0.1 ~ 4，步长 0.05 |
| `opacity` | 不透明度 | `number` | 1 | 0 ~ 1，步长 0.05 |
| `blend` | 混合模式 | `enum` | `screen` | `normal` / `screen` / `add` |

### `glow` · Glow 光晕

- 分类：素材特效（`overlay`）
- kind：`material`　scope：`asset`
- renderer：`—`
- 默认时长：0.8s
- 可作用元素：—
- 说明：光晕素材

| 参数 | 名称 | 类型 | 默认 | 取值 |
| --- | --- | --- | --- | --- |
| `asset` | 素材 | `asset` | （空） | — |
| `scale` | 缩放 | `number` | 1 | 0.1 ~ 4，步长 0.05 |
| `opacity` | 不透明度 | `number` | 1 | 0 ~ 1，步长 0.05 |
| `blend` | 混合模式 | `enum` | `screen` | `normal` / `screen` / `add` |

### `light_leak` · Light Leak 漏光

- 分类：素材特效（`overlay`）
- kind：`material`　scope：`asset`
- renderer：`—`
- 默认时长：1s
- 可作用元素：—
- 说明：漏光素材，适合做转场衔接

| 参数 | 名称 | 类型 | 默认 | 取值 |
| --- | --- | --- | --- | --- |
| `asset` | 素材 | `asset` | （空） | — |
| `scale` | 缩放 | `number` | 1 | 0.1 ~ 4，步长 0.05 |
| `opacity` | 不透明度 | `number` | 1 | 0 ~ 1，步长 0.05 |
| `blend` | 混合模式 | `enum` | `screen` | `normal` / `screen` / `add` |

### `lightning` · Lightning 闪电

- 分类：素材特效（`overlay`）
- kind：`material`　scope：`asset`
- renderer：`—`
- 默认时长：0.5s
- 可作用元素：—
- 说明：闪电，配合 Flash 效果更强

| 参数 | 名称 | 类型 | 默认 | 取值 |
| --- | --- | --- | --- | --- |
| `asset` | 素材 | `asset` | （空） | — |
| `scale` | 缩放 | `number` | 1 | 0.1 ~ 4，步长 0.05 |
| `opacity` | 不透明度 | `number` | 1 | 0 ~ 1，步长 0.05 |
| `blend` | 混合模式 | `enum` | `screen` | `normal` / `screen` / `add` |

### `particle` · Particle 粒子

- 分类：素材特效（`overlay`）
- kind：`material`　scope：`asset`
- renderer：`—`
- 默认时长：1.5s
- 可作用元素：—
- 说明：通用粒子素材

| 参数 | 名称 | 类型 | 默认 | 取值 |
| --- | --- | --- | --- | --- |
| `asset` | 素材 | `asset` | （空） | — |
| `scale` | 缩放 | `number` | 1 | 0.1 ~ 4，步长 0.05 |
| `opacity` | 不透明度 | `number` | 1 | 0 ~ 1，步长 0.05 |
| `blend` | 混合模式 | `enum` | `screen` | `normal` / `screen` / `add` |

### `smoke` · Smoke 烟雾

- 分类：素材特效（`overlay`）
- kind：`material`　scope：`asset`
- renderer：`—`
- 默认时长：1.5s
- 可作用元素：—
- 说明：烟雾素材叠加

| 参数 | 名称 | 类型 | 默认 | 取值 |
| --- | --- | --- | --- | --- |
| `asset` | 素材 | `asset` | （空） | — |
| `scale` | 缩放 | `number` | 1 | 0.1 ~ 4，步长 0.05 |
| `opacity` | 不透明度 | `number` | 1 | 0 ~ 1，步长 0.05 |
| `blend` | 混合模式 | `enum` | `screen` | `normal` / `screen` / `add` |

### `spark` · Spark 火花

- 分类：素材特效（`overlay`）
- kind：`material`　scope：`asset`
- renderer：`—`
- 默认时长：0.6s
- 可作用元素：—
- 说明：火花粒子

| 参数 | 名称 | 类型 | 默认 | 取值 |
| --- | --- | --- | --- | --- |
| `asset` | 素材 | `asset` | （空） | — |
| `scale` | 缩放 | `number` | 1 | 0.1 ~ 4，步长 0.05 |
| `opacity` | 不透明度 | `number` | 1 | 0 ~ 1，步长 0.05 |
| `blend` | 混合模式 | `enum` | `screen` | `normal` / `screen` / `add` |

### `speed_lines` · Speed Lines 速度线

- 分类：素材特效（`overlay`）
- kind：`material`　scope：`asset`
- renderer：`—`
- 默认时长：0.5s
- 可作用元素：—
- 说明：速度线，强调运动方向

| 参数 | 名称 | 类型 | 默认 | 取值 |
| --- | --- | --- | --- | --- |
| `asset` | 素材 | `asset` | （空） | — |
| `scale` | 缩放 | `number` | 1 | 0.1 ~ 4，步长 0.05 |
| `opacity` | 不透明度 | `number` | 1 | 0 ~ 1，步长 0.05 |
| `blend` | 混合模式 | `enum` | `screen` | `normal` / `screen` / `add` |

### `flash` · Flash 闪白

- 分类：光效（`screen`）
- kind：`program`　scope：`screen`
- renderer：`flash`
- 默认时长：0.2s
- 可作用元素：`video`、`freeze`、`image`、`overlay`、`text`、`caption`、`caption_group`
- 说明：叠加一层纯色并快速衰减，常配合 Impact 音效

| 参数 | 名称 | 类型 | 默认 | 取值 |
| --- | --- | --- | --- | --- |
| `color` | 颜色 | `color` | `#FFFFFF` | — |
| `intensity` | 强度 | `number` | 0.85 | 0 ~ 1，步长 0.05 |
| `decay` | 衰减曲线 | `enum` | `easeOut` | `linear` / `easeIn` / `easeOut` / `easeInOut` |

### `glitch` · Glitch 故障

- 分类：风格（`screen`）
- kind：`program`　scope：`screen`
- renderer：`glitch`
- 默认时长：0.35s
- 可作用元素：`video`、`freeze`、`image`、`overlay`、`text`、`caption`、`caption_group`
- 说明：横向条带错位 + 颜色抖动

| 参数 | 名称 | 类型 | 默认 | 取值 |
| --- | --- | --- | --- | --- |
| `intensity` | 强度 | `number` | 0.6 | 0 ~ 1，步长 0.05 |
| `slices` | 条带数量 | `int` | `12` | `2` ~ `60`，步长 `1` |
| `color_shift` | 颜色偏移 px | `number` | 6 | 0 ~ 40，步长 1 |

### `rgb_split` · RGB Split 色差

- 分类：风格（`screen`）
- kind：`program`　scope：`screen`
- renderer：`rgb_split`
- 默认时长：0.3s
- 可作用元素：`video`、`freeze`、`image`、`overlay`、`text`、`caption`、`caption_group`
- 说明：红蓝通道错开，制造强烈的冲击感

| 参数 | 名称 | 类型 | 默认 | 取值 |
| --- | --- | --- | --- | --- |
| `offset` | 偏移 px | `number` | 8 | 0 ~ 60，步长 1 |
| `angle` | 偏移角度 | `number` | 0 | 0 ~ 360，步长 5 |

### `vignette` · Vignette 暗角

- 分类：光效（`screen`）
- kind：`program`　scope：`screen`
- renderer：`vignette`
- 默认时长：1s
- 可作用元素：`video`、`freeze`、`image`、`overlay`、`text`、`caption`、`caption_group`
- 说明：四周压暗，把注意力收到中心

| 参数 | 名称 | 类型 | 默认 | 取值 |
| --- | --- | --- | --- | --- |
| `intensity` | 强度 | `number` | 0.5 | 0 ~ 1，步长 0.05 |
| `radius` | 半径比例 | `number` | 0.75 | 0.1 ~ 1.5，步长 0.05 |

### `blur` · Blur 模糊

- 分类：画质（`visual`）
- kind：`program`　scope：`element`
- renderer：`blur`
- 默认时长：0.5s
- 可作用元素：`video`、`freeze`、`image`、`overlay`、`text`、`caption`、`caption_group`
- 说明：高斯模糊，从 from 值过渡到 to 值

| 参数 | 名称 | 类型 | 默认 | 取值 |
| --- | --- | --- | --- | --- |
| `radius_from` | 起始半径 px | `number` | 0 | 0 ~ 80，步长 1 |
| `radius_to` | 结束半径 px | `number` | 12 | 0 ~ 80，步长 1 |

### `brightness` · Brightness 亮度

- 分类：调色（`visual`）
- kind：`program`　scope：`element`
- renderer：`brightness`
- 默认时长：0.5s
- 可作用元素：`video`、`freeze`、`image`、`overlay`、`text`、`caption`、`caption_group`
- 说明：1.0 为原始亮度

| 参数 | 名称 | 类型 | 默认 | 取值 |
| --- | --- | --- | --- | --- |
| `value_from` | 起始值 | `number` | 1 | 0 ~ 3，步长 0.05 |
| `value_to` | 结束值 | `number` | 1.4 | 0 ~ 3，步长 0.05 |

### `contrast` · Contrast 对比度

- 分类：调色（`visual`）
- kind：`program`　scope：`element`
- renderer：`contrast`
- 默认时长：0.5s
- 可作用元素：`video`、`freeze`、`image`、`overlay`、`text`、`caption`、`caption_group`
- 说明：1.0 为原始对比度

| 参数 | 名称 | 类型 | 默认 | 取值 |
| --- | --- | --- | --- | --- |
| `value_from` | 起始值 | `number` | 1 | 0 ~ 3，步长 0.05 |
| `value_to` | 结束值 | `number` | 1.3 | 0 ~ 3，步长 0.05 |

### `motion_blur` · Motion Blur 运动模糊

- 分类：画质（`visual`）
- kind：`program`　scope：`element`
- renderer：`motion_blur`
- 默认时长：0.3s
- 可作用元素：`video`、`freeze`、`image`、`overlay`、`text`、`caption`、`caption_group`
- 说明：沿指定方向拉伸模糊

| 参数 | 名称 | 类型 | 默认 | 取值 |
| --- | --- | --- | --- | --- |
| `amount` | 强度 px | `number` | 14 | 0 ~ 100，步长 1 |
| `angle` | 方向角度 | `number` | 0 | 0 ~ 360，步长 5 |

### `saturation` · Saturation 饱和度

- 分类：调色（`visual`）
- kind：`program`　scope：`element`
- renderer：`saturation`
- 默认时长：0.5s
- 可作用元素：`video`、`freeze`、`image`、`overlay`、`text`、`caption`、`caption_group`
- 说明：0 为黑白，1.0 为原始饱和度

| 参数 | 名称 | 类型 | 默认 | 取值 |
| --- | --- | --- | --- | --- |
| `value_from` | 起始值 | `number` | 1 | 0 ~ 3，步长 0.05 |
| `value_to` | 结束值 | `number` | 1.6 | 0 ~ 3，步长 0.05 |
