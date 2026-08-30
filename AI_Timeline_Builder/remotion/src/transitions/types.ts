/**
 * Transition Renderer 的最小接口。
 *
 * 与 Effect 的分工（阶段 7 指令第五、十六条）：
 *   Effect      对一个已有对象施加变化   → 一个 target
 *   Transition  两个对象之间的交接       → from + to
 * 所以这里没有 geometry 折叠，只有「两侧各自怎么摆、上面再盖什么」。
 *
 * Renderer 返回的是**层描述（plan）**而不是 JSX：
 * - 组合两个画面这件事只在 TransitionLayer 一处发生（第十五条）
 * - plan 是纯数据，`node --test` 能直接断言，不需要渲染器
 */

import type { Easing, TimelineElement } from "../lib/timeline.ts";
import { applyEasing } from "../lib/timeline.ts";

/** 一个转场在某一帧的全部上下文。Renderer 只能看到这些，看不到 Timeline。 */
export type TransitionContext = {
  /** 线性进度 0..1 */
  progress: number;
  /** 按 easing 缓动后的进度 0..1（多数转场刻意用线性 progress） */
  eased: number;
  /** 相对转场起点的秒数 */
  localTime: number;
  /** 转场时长（秒），至少 1e-6，可以直接做除数 */
  duration: number;
  fps: number;
  params: Record<string, unknown>;
};

/** 两侧之一。from = 前一个片段，to = 后一个片段。 */
export type SideRole = "from" | "to";

/** 一层「某一侧的画面」。字段语义与 Geometry 一致，都是叠加量。 */
export type SideLayer = {
  kind: "side";
  role: SideRole;
  /** React key。glitch 会为同一侧产出多层，所以 key 必须由 renderer 决定 */
  key: string;
  alpha: number;
  offset?: [number, number];
  scale?: number;
  rotation?: number;
  blur?: number;
  /** CSS clip-path，用于擦除 / 条带 */
  clip?: string;
};

/** 一层纯色遮罩，盖在画面之上（fade / flash 的中间色）。 */
export type VeilLayer = {
  kind: "veil";
  key: string;
  color: string;
  opacity: number;
};

export type TransitionLayerSpec = SideLayer | VeilLayer;

/** 数组顺序 = 渲染顺序，越靠后越上层。 */
export type TransitionRenderer = (ctx: TransitionContext) => TransitionLayerSpec[];

export type TransitionEntry = {
  name: string;
  render: TransitionRenderer;
};

/** 从 transition 元素和当前绝对时间构造上下文。时间语义只在这一处定义。 */
export const makeTransitionContext = (
  transition: TimelineElement,
  now: number,
  fps: number,
): TransitionContext => {
  const start = transition.start ?? 0;
  const duration = Math.max(1e-6, transition.duration ?? 0);
  const localTime = now - start;
  const progress = Math.min(1, Math.max(0, localTime / duration));
  const params = (transition.params ?? {}) as Record<string, unknown>;
  // easing 可以写在 params 里（crossfade 就有这个参数），也可以写在元素上
  const easing = (typeof params.easing === "string"
    ? params.easing
    : transition.easing ?? "linear") as Easing;
  return {
    progress,
    eased: applyEasing(progress, easing),
    localTime,
    duration,
    fps,
    params,
  };
};

/** 参数读取：类型不对就退回默认值，绝不抛异常。 */
export const num = (
  params: Record<string, unknown>,
  key: string,
  fallback: number,
): number => {
  const value = params[key];
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
};

export const str = (
  params: Record<string, unknown>,
  key: string,
  fallback: string,
): string => {
  const value = params[key];
  return typeof value === "string" ? value : fallback;
};

export const int = (
  params: Record<string, unknown>,
  key: string,
  fallback: number,
  minimum = 1,
): number => Math.max(minimum, Math.round(num(params, key, fallback)));

const DIRECTION_VECTOR: Record<string, [number, number]> = {
  left: [-1, 0],
  right: [1, 0],
  up: [0, -1],
  down: [0, 1],
};

/** direction 参数 → 单位向量。未知方向退回 left，与既有行为一致。 */
export const directionVector = (
  params: Record<string, unknown>,
): [number, number] => DIRECTION_VECTOR[str(params, "direction", "left")] ?? [-1, 0];

export const clamp01 = (value: number): number =>
  Math.min(1, Math.max(0, value));
