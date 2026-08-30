/**
 * Effect Renderer 的最小接口。
 *
 * 与 Python 侧 libraries/effect_registry.py 的分工（阶段 6 指令第十一、十六条）：
 * - Python Registry 知道「参数叫什么、什么类型、什么范围、renderer 叫什么」
 * - 这里的 Renderer 知道「拿到 progress 和 params 之后怎么算」
 * 两边只靠 effect.name 这个字符串对接，不共享代码。
 */

import type React from "react";
import type { Easing, Geometry, TimelineElement } from "../lib/timeline.ts";
import { applyEasing } from "../lib/timeline.ts";

/** 一个特效在某一帧的全部上下文。Renderer 只能看到这些，看不到 Timeline。 */
export type EffectContext = {
  /** 线性进度 0..1 */
  progress: number;
  /** 按 effect.easing 缓动后的进度 0..1 */
  eased: number;
  /** 相对特效起点的秒数，可能超过 duration */
  localTime: number;
  /** 特效时长（秒），至少 1e-6，可以直接做除数 */
  duration: number;
  fps: number;
  params: Record<string, unknown>;
};

/** 几何类 renderer：把 geometry 折叠一层后返回新的 geometry（不得就地修改）。 */
export type GeometryEffectRenderer = (
  geometry: Geometry,
  ctx: EffectContext,
) => Geometry;

/** 全屏类 renderer：返回盖在画面上的一层。 */
export type ScreenEffectRenderer = React.FC<{ ctx: EffectContext }>;

export type GeometryEffectEntry = {
  name: string;
  kind: "geometry";
  apply: GeometryEffectRenderer;
};

export type ScreenEffectEntry = {
  name: string;
  kind: "screen";
  Component: ScreenEffectRenderer;
};

export type EffectEntry = GeometryEffectEntry | ScreenEffectEntry;

/** 从 effect 元素和当前绝对时间构造上下文。时间语义只在这一处定义。 */
export const makeEffectContext = (
  effect: TimelineElement,
  now: number,
  fps: number,
): EffectContext => {
  const start = effect.start ?? 0;
  const duration = Math.max(1e-6, effect.duration ?? 0);
  const localTime = now - start;
  const progress = Math.min(1, Math.max(0, localTime / duration));
  return {
    progress,
    eased: applyEasing(progress, (effect.easing ?? "easeInOut") as Easing),
    localTime,
    duration,
    fps,
    params: (effect.params ?? {}) as Record<string, unknown>,
  };
};

/** 参数读取：类型不对就退回默认值，绝不抛异常（第二十二条）。 */
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
