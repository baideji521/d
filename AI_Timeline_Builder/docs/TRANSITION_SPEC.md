# Transition 规范（阶段 7）

本文件是 Transition 这一层的唯一权威说明，回答阶段 7 指令第二十八条的 12 个问题。
结论全部来自源码（`libraries/transition_registry.py`、`remotion/src/transitions/*`、
`remotion/src/lib/timeline.ts`、`remotion/src/TimelineVideo.tsx`），不是设想。

---

## 1. Transition 是什么

Timeline JSON 里 `type="transition"` 的元素，表示**两个片段之间的交接**。
它自己不是画面内容，而是「在一段时间窗内，用某种算法把 from 和 to 两侧的画面混起来」的指令。

```json
{
  "id": "tr_001",
  "type": "transition",
  "track": "V1",
  "name": "whip",
  "from": "clip_001",
  "to": "clip_002",
  "start": 5.75,
  "duration": 0.5,
  "params": { "direction": "left", "intensity": 0.8, "blur": 0.6 }
}
```

## 2. 与 Effect 的区别

| | Effect | Transition |
|---|---|---|
| 语义 | 对一个已有对象施加变化 | 两个对象之间的交接 |
| 绑定 | `target`（1 个） | `from` + `to`（2 个） |
| 能力声明 | `supported_targets` | `supported_from` / `supported_to` |
| 校验 | `validate_target()` | `validate_pair()` |
| Registry | `libraries/effect_registry.py` | `libraries/transition_registry.py` |

两个 Registry **刻意不合并**。合并会逼出一个「target 有时是 1 个有时是 2 个」的抽象，
校验分支只会越来越多。共用的只有「参数怎么声明、怎么校验」这一层，实现在
`libraries/param_spec.py`，两边用同一套错误码，避免两份参数校验逻辑长期漂移。

注意：`zoom` / `blur` / `spin` / `glitch` 这些名字在 Effect 和 Transition 里都有，
**它们是两回事**。Effect 的 zoom 是让一个片段自己推近；Transition 的 zoom 是前一段推进、
后一段拉出。Transition 侧的实现不复用 Effect 的代码。

## 3. from / to

- `from`：交接的前一个元素 id
- `to`：交接的后一个元素 id
- 两者都必须指向 Timeline 里真实存在的元素，否则 `RULE_TRANSITION_001`
- 两者不得相同，否则 `RULE_TRANSITION_002`
- 两侧元素的 `type` 必须落在 `supported_from` / `supported_to` 内，否则 `RULE_TRANSITION_005`

## 4. start / duration

都是**秒**，与 Timeline 里其它元素同一套时间基准，外部永远不出现帧号。

- `start`：转场窗口的开始时刻（绝对时间，不是相对 from 的偏移）
- `duration`：窗口长度
- 窗口 = `[start, start + duration)`，**左闭右开**

GUI 默认把 `start` 放在 from 片段结束前 `duration/2` 处，这样交接点正好压在两段的边界上，
但这只是 GUI 的默认摆放，JSON 层不强制。

## 5. progress

`remotion/src/transitions/types.ts::makeTransitionContext()`：

```
localTime = now - start
progress  = clamp(localTime / max(duration, 1e-6), 0, 1)
eased     = applyEasing(progress, easing)
```

- `progress = 0` → 完全是 from
- `progress = 1` → 完全是 to
- `duration = 0` 时用 `1e-6` 兜底，不会出现除零 / NaN
- `easing` 优先取 `params.easing`，其次取元素上的 `easing` 字段，默认 `linear`；
  用的是 Effect 侧同一个 `applyEasing`，**没有单独的 TransitionEasing**

## 6. 参数

`params` 是一个扁平对象，键由该转场的参数表定义。参数表是结构化的
`ParameterDefinition`（key / label / type / default / min / max / step / options / ui），
与 Effect 共用同一个类。

- 缺参数 → warning `MISSING_PARAMETER`，Runtime 读取时补默认值，
  **绝不回写 Timeline JSON**
- 类型 / 范围 / 枚举不对 → error（`TYPE_MISMATCH` / `OUT_OF_RANGE` / `INVALID_OPTION`）
- 参数表之外的键 → warning `UNKNOWN_PARAMETER`，渲染时忽略
- `params` 不是对象 → error `INVALID_PARAMS`

校验结果永远是 `{valid, errors, warnings}` 结构，**永远不抛异常到 GUI**。

## 7. supported_from

`from` 侧允许的元素 `type` 列表。当前是 `["video", "freeze"]`。

## 8. supported_to

`to` 侧允许的元素 `type` 列表。当前同样是 `["video", "freeze"]`。

这个限制**来自 renderer 的真实能力，不是凭空设的**：
`remotion/src/transitions/TransitionLayer.tsx` 的 `renderSide()` 用 `VideoLayer` 渲染两侧，
而 `VideoLayer` 只认 `video`（走 asset）和 `freeze`（走 target）。
把 `text` / `caption` / `overlay` 交给它会画不出东西，所以不列入。
以后 `renderSide` 支持了更多元素类型，这两个列表才应该跟着放宽。

## 9. Renderer

Python 侧 `TransitionDefinition.renderer` 是一个字符串，等于 Remotion 侧
`remotion/src/transitions/index.ts` 注册的键。当前约定 `renderer == name`。
**这个字符串是 Python 与 Remotion 之间关于转场的唯一契约。**

Renderer 的签名是纯函数，不返回 JSX，只返回一份**层描述（plan）**：

```ts
type TransitionRenderer = (ctx: TransitionContext) => TransitionLayerSpec[];

// side：某一侧的画面，带 alpha / offset / scale / rotation / blur / clip
// veil：一层纯色遮罩（fade / flash 用）
```

好处是：算法可以在 `node --test` 里直接断言，不需要跑渲染器；
「怎么把两个画面组合起来」只在 `TransitionLayer.tsx` 一处发生。

11 个内置转场：

- basic：`fade`（经中间色）、`crossfade`（直接叠化）
- impact：`flash`、`whip`、`zoom`
- geometric：`wipe`、`slide`、`push`
- stylized：`spin`、`blur`、`glitch`

全部有真实 renderer，`registry.without_renderer()` 为空。

## 10. TransitionLayer 怎么用它

1. `TimelineVideo.tsx` 为每个 transition 元素挂一个 `Sequence`，
   范围就是 `[start, start+duration)`
2. `TransitionLayer` 用 `useCurrentFrame()` 算出绝对时间 `now`，
   构造 `TransitionContext`
3. `transitionRenderers.resolve(name)` 取 renderer，拿到 plan
4. 按 plan 逐层渲染：`side` → `renderSide()`，`veil` → 一层纯色 `AbsoluteFill`
5. `renderSide()` 里两侧照常走 `baseGeometry` + `foldEffects`，
   也就是**转场窗口内两侧片段上的 Effect 依然生效**

## 11. 时间边界

**Transition 是 Overlay 窗口，不是 Clip Replacement。** 它不修改任何片段的
`start` / `duration`，只是在自己的窗口内接管画面。窗口内两侧片段让位
（`isCoveredByTransition()` 返回 true → `TimelineVideo` 跳过它们），窗口外照常各自渲染。

```
时间轴 ──────────────────────────────────────────────────────────────►
                    5.75          6.25
clip_001  ├───────────────────────┤                (0.0 → 6.25)
clip_002                  ├───────────────────────┤ (5.75 → 12.0)
tr_001                    ╞═══════╡                 start=5.75 dur=0.5

渲染结果：
  [0.00, 5.75)   clip_001 自己渲染          clip_002 未开始
  [5.75, 6.25)   两侧都让位 → TransitionLayer 统一画（progress 0→1）
  [6.25, 12.0)   clip_001 已结束            clip_002 自己渲染

progress:        5.75 → 0.0    6.00 → 0.5    6.25 → 1.0（右开，实际最后一帧 <1）
```

三种片段时间关系，当前 Runtime 的实际表现：

- **情况 A：两段首尾相接（无缝）** —— 窗口内两侧都在自身时间范围内，正常交接。
- **情况 B：两段有重叠** —— 同上，正常交接；重叠区本来就两段都有画面。
- **情况 C：两段之间有缝** —— 窗口内某一侧超出自身范围，
  `renderSide()` 的 `sampleTime` 会把取帧时刻夹到 `[start, end - 1/fps]`，
  于是那一侧退化为**端点定格画面**，不是黑帧。

正因为有 `sampleTime` 夹取这条兜底，语义层**没有**写死
`transition.end <= timeline.duration` —— 越界不会黑，只会定格，判死会误伤合法用法。
真正的硬边界由 v1 Schema 层负责：`start >= 0`、`duration > 0`，
不合法的 JSON 在语义校验之前就被 `SCHEMA_*` 拦住了。

时长过长只作提示：`duration` 超过任一侧片段时长一半 → `RULE_TRANSITION_003`（warning）。
有人就是要做长溶解，不该判死。

## 12. 黑帧避免机制

阶段 2 的 P0-1 事故：当时的实现把参与转场的片段整体从渲染列表里剔除
（`consumed.add(from)` / `consumed.add(to)`），结果转场窗口**之外**整条轨都是黑的。

现在有三道防线，任何一道被拆掉都会重新黑屏：

1. **让位只限窗口内。** `isCoveredByTransition(element, transitions, now)` 只在
   `now ∈ [start, start+duration)` 时返回 true。
   **绝不能恢复 `consumed.add(from)` / `consumed.add(to)` 这种整体剔除。**
2. **renderer 查不到时退回兜底。** `transitionRenderers.resolve()` 查不到就返回
   `crossfade`。因为窗口内两侧已经让位了，renderer 返回空就意味着这段时间没人画 → 黑。
   兜底项本身受保护，`unregister("crossfade")` 会被拒绝。
   同时 Registry 层的 `get()` 保持严格查表（未注册返回 `undefined`），
   校验和渲染两种用途不混在一个方法里。
3. **两侧超范围时夹取端点帧。** `sampleTime` 夹取保证片段有缝 / 有重叠时是定格而不是黑。

另外 `RULE_TRANSITION_004`（`UNKNOWN_TRANSITION`）在 Python 侧拦住未注册的转场名，
让它**在导出之前**就被发现，而不是靠 Remotion 的兜底遮过去。
阶段 7 之前 `_validate_transition` 完全没检查 `name`，这是个真实存在的缺口。

---

## 校验规则一览

- `RULE_TRANSITION_001`（error）：`from` / `to` 指向的元素不存在
- `RULE_TRANSITION_002`（error）：`from == to`
- `RULE_TRANSITION_003`（warning）：`duration` 超过某一侧片段时长的一半
- `RULE_TRANSITION_004`（error）：`name` 未在 TransitionRegistry 注册
- `RULE_TRANSITION_005`（error）：某一侧元素类型不被该转场支持
- `RULE_TRANSITION_006`（error）：参数类型 / 范围 / 枚举错误
- `RULE_TRANSITION_007`（warning）：参数表之外的未知参数

`name` 不认识时不再重复报参数错（004 已经说明问题，再刷一堆 006/007 只会淹掉重点）。

## 新增一个转场要改什么

1. `libraries/transition_library.py`：加一条定义（含 `params` / `default_duration`）
   与 `_TRANSITION_CATEGORIES` 一行分类；或者往 `assets/transitions/*.json` 丢一份自定义 JSON
2. `remotion/src/transitions/<name>.ts`：写 renderer，返回 plan
3. `remotion/src/transitions/index.ts`：注册

**不需要**改 `TimelineModel`、`TimelineValidator`、GUI 属性面板、`TransitionLayer.tsx`。

## 已知局限（阶段 7 未做）

- `supported_from` / `supported_to` 目前所有转场都是同一份 `["video", "freeze"]`，
  尚无按转场区分侧类型的真实需求
- 转场不支持关键帧，`params` 在整个窗口内是常量
- `slide` / `push` / `wipe` / `glitch` 只支持四个正交方向，没有任意角度
- GUI 属性面板还没读 `ParameterDefinition.ui`，控件仍按老逻辑生成
- 没有音频交叉淡化（转场只处理画面）
- **画面正确性尚未由真实 MP4 验证。** 当前证据是 Python 64 项 + Remotion 34 项单元测试，
  证明的是「Registry 数据层与 plan 层正确」。真实渲染验收在阶段 15。
