/**
 * 程序特效求值：把 effect 元素折叠进目标元素的 geometry。
 *
 * 阶段 6 之后这里不再有 switch —— 具体算法在 effects/<name>.ts，
 * 本文件只负责「筛出该生效的特效 → 查表 → 依次折叠」。
 *
 * 与 Python 侧 render/preview_renderer.py 的 _apply_geometry_effect 一一对应。
 * 改单个特效的算法就改对应的 effects/<name>.ts，并同步改那边，否则预览与成品会不一致。
 */

import type { Geometry, TimelineElement } from "../lib/timeline.ts";
import { effectRenderers } from "./index.ts";
import { makeEffectContext } from "./types.ts";

/** 判断某个特效此刻是否作用于给定元素。 */
export const effectAppliesTo = (
  effect: TimelineElement,
  element: TimelineElement,
): boolean => {
  if (effect.target) {
    return effect.target === element.id;
  }
  // 未指定 target 的特效只作用于视频类元素
  return element.type === "video" || element.type === "freeze";
};

/**
 * 折叠单个特效。
 *
 * 名字查不到 renderer 就原样返回 —— 未知特效必须安全失败，
 * 拦截它是 Validator 的职责，不是渲染期的（第二十二条）。
 */
export const applyGeometryEffect = (
  geometry: Geometry,
  effect: TimelineElement,
  now: number,
  fps = 30,
): Geometry => {
  const entry = effectRenderers.geometry(effect.name);
  if (!entry) {
    return geometry;
  }
  return entry.apply(geometry, makeEffectContext(effect, now, fps));
};

/** 把此刻所有生效的特效依次折叠进 geometry。 */
export const foldEffects = (
  geometry: Geometry,
  effects: TimelineElement[],
  element: TimelineElement,
  now: number,
  fps = 30,
): Geometry => {
  let result = geometry;
  for (const effect of effects) {
    if (effectAppliesTo(effect, element)) {
      result = applyGeometryEffect(result, effect, now, fps);
    }
  }
  return result;
};

/** 只影响整屏的特效名单，由 ScreenEffects 单独渲染。现在直接从注册表推导。 */
export const SCREEN_EFFECT_NAMES = new Set(
  effectRenderers
    .all()
    .filter((entry) => entry.kind === "screen")
    .map((entry) => entry.name),
);
