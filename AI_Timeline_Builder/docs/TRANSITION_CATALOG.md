# Transition 目录

由 `python tools/build_catalog.py` 扫描真实注册表生成，**请勿手改**。

- Python 注册表：`libraries/transition_library.py`（`TransitionRegistry`）
- Remotion renderer：`remotion/src/transitions/index.ts`
- 共 11 个转场，覆盖 4 个分类

转场元素必须同时绑定 `from` / `to` 两个片段，且窗口要落在两者的重叠区间内；
Remotion 侧未知名字会退回 `crossfade`（拦截未知名字是 Validator 的职责）。

## Renderer 覆盖（转场）

探测方式：已从 Remotion 运行时注册表读取

- Python 注册表：11 个
- Remotion 注册表：11 个
- Python 有、Remotion 缺 renderer：无
- Remotion 有、Python 未登记：无

## 一览

| name | 中文名 | 分类 | renderer | 默认时长 | from → to |
| --- | --- | --- | --- | --- | --- |
| `crossfade` | Crossfade 交叉溶解 | 基础（basic） | `crossfade` | 0.5s | video/freeze → video/freeze |
| `fade` | Fade 淡入淡出 | 基础（basic） | `fade` | 0.5s | video/freeze → video/freeze |
| `push` | Push 推移 | 几何（geometric） | `push` | 0.5s | video/freeze → video/freeze |
| `slide` | Slide 滑入 | 几何（geometric） | `slide` | 0.5s | video/freeze → video/freeze |
| `wipe` | Wipe 擦除 | 几何（geometric） | `wipe` | 0.5s | video/freeze → video/freeze |
| `flash` | Flash 闪白转场 | 冲击（impact） | `flash` | 0.3s | video/freeze → video/freeze |
| `whip` | Whip 甩镜 | 冲击（impact） | `whip` | 0.5s | video/freeze → video/freeze |
| `zoom` | Zoom 缩放转场 | 冲击（impact） | `zoom` | 0.4s | video/freeze → video/freeze |
| `blur` | Blur 模糊转场 | 风格（stylized） | `blur` | 0.5s | video/freeze → video/freeze |
| `glitch` | Glitch 故障转场 | 风格（stylized） | `glitch` | 0.35s | video/freeze → video/freeze |
| `spin` | Spin 旋转转场 | 风格（stylized） | `spin` | 0.5s | video/freeze → video/freeze |

## 逐个说明

### `crossfade` · Crossfade 交叉溶解

- 分类：基础（`basic`）
- renderer：`crossfade`
- 默认时长：0.5s
- 接受的 from：`video`、`freeze`
- 接受的 to：`video`、`freeze`
- 说明：两个片段直接叠化，没有中间色

| 参数 | 名称 | 类型 | 默认 | 取值 |
| --- | --- | --- | --- | --- |
| `easing` | 缓动 | `enum` | `easeInOut` | `linear` / `easeIn` / `easeOut` / `easeInOut` |

```json
{
  "id": "transition_001",
  "type": "transition",
  "track": "V1",
  "name": "crossfade",
  "from": "clip_001",
  "to": "clip_002",
  "start": 1.0,
  "duration": 0.5,
  "params": {}
}
```

### `fade` · Fade 淡入淡出

- 分类：基础（`basic`）
- renderer：`fade`
- 默认时长：0.5s
- 接受的 from：`video`、`freeze`
- 接受的 to：`video`、`freeze`
- 说明：经过纯色过渡，最稳的接法

| 参数 | 名称 | 类型 | 默认 | 取值 |
| --- | --- | --- | --- | --- |
| `color` | 过渡颜色 | `color` | `#000000` | — |

```json
{
  "id": "transition_001",
  "type": "transition",
  "track": "V1",
  "name": "fade",
  "from": "clip_001",
  "to": "clip_002",
  "start": 1.0,
  "duration": 0.5,
  "params": {}
}
```

### `push` · Push 推移

- 分类：几何（`geometric`）
- renderer：`push`
- 默认时长：0.5s
- 接受的 from：`video`、`freeze`
- 接受的 to：`video`、`freeze`
- 说明：新片段把旧片段推出画面

| 参数 | 名称 | 类型 | 默认 | 取值 |
| --- | --- | --- | --- | --- |
| `direction` | 方向 | `enum` | `left` | `left` / `right` / `up` / `down` |

```json
{
  "id": "transition_001",
  "type": "transition",
  "track": "V1",
  "name": "push",
  "from": "clip_001",
  "to": "clip_002",
  "start": 1.0,
  "duration": 0.5,
  "params": {}
}
```

### `slide` · Slide 滑入

- 分类：几何（`geometric`）
- renderer：`slide`
- 默认时长：0.5s
- 接受的 from：`video`、`freeze`
- 接受的 to：`video`、`freeze`
- 说明：新片段滑入，旧片段不动

| 参数 | 名称 | 类型 | 默认 | 取值 |
| --- | --- | --- | --- | --- |
| `direction` | 方向 | `enum` | `left` | `left` / `right` / `up` / `down` |

```json
{
  "id": "transition_001",
  "type": "transition",
  "track": "V1",
  "name": "slide",
  "from": "clip_001",
  "to": "clip_002",
  "start": 1.0,
  "duration": 0.5,
  "params": {}
}
```

### `wipe` · Wipe 擦除

- 分类：几何（`geometric`）
- renderer：`wipe`
- 默认时长：0.5s
- 接受的 from：`video`、`freeze`
- 接受的 to：`video`、`freeze`
- 说明：沿方向用硬边擦过

| 参数 | 名称 | 类型 | 默认 | 取值 |
| --- | --- | --- | --- | --- |
| `direction` | 方向 | `enum` | `left` | `left` / `right` / `up` / `down` |
| `feather` | 边缘羽化 px | `number` | 20 | 0 ~ 200，步长 5 |

```json
{
  "id": "transition_001",
  "type": "transition",
  "track": "V1",
  "name": "wipe",
  "from": "clip_001",
  "to": "clip_002",
  "start": 1.0,
  "duration": 0.5,
  "params": {}
}
```

### `flash` · Flash 闪白转场

- 分类：冲击（`impact`）
- renderer：`flash`
- 默认时长：0.3s
- 接受的 from：`video`、`freeze`
- 接受的 to：`video`、`freeze`
- 说明：闪白过渡，节奏点上最常用

| 参数 | 名称 | 类型 | 默认 | 取值 |
| --- | --- | --- | --- | --- |
| `color` | 闪光颜色 | `color` | `#FFFFFF` | — |
| `intensity` | 强度 | `number` | 0.9 | 0 ~ 1，步长 0.05 |

```json
{
  "id": "transition_001",
  "type": "transition",
  "track": "V1",
  "name": "flash",
  "from": "clip_001",
  "to": "clip_002",
  "start": 1.0,
  "duration": 0.3,
  "params": {}
}
```

### `whip` · Whip 甩镜

- 分类：冲击（`impact`）
- renderer：`whip`
- 默认时长：0.5s
- 接受的 from：`video`、`freeze`
- 接受的 to：`video`、`freeze`
- 说明：带模糊的快速横甩，短视频里出现频率最高

| 参数 | 名称 | 类型 | 默认 | 取值 |
| --- | --- | --- | --- | --- |
| `direction` | 方向 | `enum` | `left` | `left` / `right` / `up` / `down` |
| `intensity` | 位移强度 | `number` | 0.8 | 0 ~ 2，步长 0.05 |
| `blur` | 模糊量 | `number` | 0.6 | 0 ~ 2，步长 0.05 |

```json
{
  "id": "transition_001",
  "type": "transition",
  "track": "V1",
  "name": "whip",
  "from": "clip_001",
  "to": "clip_002",
  "start": 1.0,
  "duration": 0.5,
  "params": {}
}
```

### `zoom` · Zoom 缩放转场

- 分类：冲击（`impact`）
- renderer：`zoom`
- 默认时长：0.4s
- 接受的 from：`video`、`freeze`
- 接受的 to：`video`、`freeze`
- 说明：前一段推进、后一段拉出

| 参数 | 名称 | 类型 | 默认 | 取值 |
| --- | --- | --- | --- | --- |
| `scale` | 缩放倍数 | `number` | 1.6 | 1 ~ 5，步长 0.1 |
| `blur` | 模糊量 | `number` | 0.3 | 0 ~ 2，步长 0.05 |

```json
{
  "id": "transition_001",
  "type": "transition",
  "track": "V1",
  "name": "zoom",
  "from": "clip_001",
  "to": "clip_002",
  "start": 1.0,
  "duration": 0.4,
  "params": {}
}
```

### `blur` · Blur 模糊转场

- 分类：风格（`stylized`）
- renderer：`blur`
- 默认时长：0.5s
- 接受的 from：`video`、`freeze`
- 接受的 to：`video`、`freeze`
- 说明：两边都模糊到最大再恢复

| 参数 | 名称 | 类型 | 默认 | 取值 |
| --- | --- | --- | --- | --- |
| `amount` | 最大模糊 px | `number` | 24 | 0 ~ 120，步长 2 |

```json
{
  "id": "transition_001",
  "type": "transition",
  "track": "V1",
  "name": "blur",
  "from": "clip_001",
  "to": "clip_002",
  "start": 1.0,
  "duration": 0.5,
  "params": {}
}
```

### `glitch` · Glitch 故障转场

- 分类：风格（`stylized`）
- renderer：`glitch`
- 默认时长：0.35s
- 接受的 from：`video`、`freeze`
- 接受的 to：`video`、`freeze`
- 说明：条带错位切换

| 参数 | 名称 | 类型 | 默认 | 取值 |
| --- | --- | --- | --- | --- |
| `intensity` | 强度 | `number` | 0.7 | 0 ~ 1，步长 0.05 |
| `slices` | 条带数量 | `int` | `14` | `2` ~ `60`，步长 `1` |

```json
{
  "id": "transition_001",
  "type": "transition",
  "track": "V1",
  "name": "glitch",
  "from": "clip_001",
  "to": "clip_002",
  "start": 1.0,
  "duration": 0.35,
  "params": {}
}
```

### `spin` · Spin 旋转转场

- 分类：风格（`stylized`）
- renderer：`spin`
- 默认时长：0.5s
- 接受的 from：`video`、`freeze`
- 接受的 to：`video`、`freeze`
- 说明：旋转叠加缩放

| 参数 | 名称 | 类型 | 默认 | 取值 |
| --- | --- | --- | --- | --- |
| `angle` | 旋转角度 | `number` | 90 | -720 ~ 720，步长 15 |
| `scale` | 缩放倍数 | `number` | 1.3 | 1 ~ 4，步长 0.1 |

```json
{
  "id": "transition_001",
  "type": "transition",
  "track": "V1",
  "name": "spin",
  "from": "clip_001",
  "to": "clip_002",
  "start": 1.0,
  "duration": 0.5,
  "params": {}
}
```
