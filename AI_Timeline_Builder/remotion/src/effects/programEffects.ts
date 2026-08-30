/**
 * 程序特效求值：把 effect 元素折叠进目标元素的 geometry。
 *
 * 与 Python 侧 render/preview_renderer.py 的 _apply_geometry_effect 一一对应。
 * 改这里就必须同步改那边，否则预览与成品会不一致。
 */

import type { Geometry, TimelineElement } from "../lib/timeline";
import { applyEasing } from "../lib/timeline";

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

export const applyGeometryEffect = (
  geometry: Geometry,
  effect: TimelineElement,
  now: number,
): Geometry => {
  const params = (effect.params ?? {}) as Record<string, number | string>;
  const start = effect.start ?? 0;
  const duration = Math.max(1e-6, effect.duration ?? 0);
  const progress = Math.min(1, Math.max(0, (now - start) / duration));
  const eased = applyEasing(progress, (effect.easing ?? "easeInOut") as never);
  const next = { ...geometry };
  const num = (key: string, fallback: number): number => {
    const value = params[key];
    return typeof value === "number" ? value : fallback;
  };

  switch (effect.name) {
    case "zoom": {
      const from = num("scale_from", 1);
      const to = num("scale_to", 1.3);
      next.scale *= from + (to - from) * eased;
      const originX = num("origin_x", 0.5);
      const originY = num("origin_y", 0.5);
      next.x += (0.5 - originX) * (next.scale - 1);
      next.y += (0.5 - originY) * (next.scale - 1);
      break;
    }
    case "shake": {
      const amplitude = num("amplitude", 0.02);
      const frequency = num("frequency", 18);
      const phase = (now - start) * frequency * Math.PI * 2;
      next.x += Math.sin(phase) * amplitude;
      next.y += Math.cos(phase * 1.37) * amplitude;
      next.rotation += Math.sin(phase * 0.73) * num("rotation", 0);
      break;
    }
    case "spin": {
      const from = num("from", 0);
      const to = num("to", 0);
      next.rotation += from + (to - from) * eased;
      break;
    }
    case "bounce": {
      const bounces = Math.max(1, Math.round(num("bounces", 2)));
      const height = num("height", 0.08);
      next.y -= Math.abs(Math.sin(progress * Math.PI * bounces)) * height * (1 - progress);
      break;
    }
    case "pulse": {
      const min = num("scale_min", 1);
      const max = num("scale_max", 1.08);
      const cycles = Math.max(1, Math.round(num("cycles", 2)));
      const wave = (1 - Math.cos(progress * Math.PI * 2 * cycles)) / 2;
      next.scale *= min + (max - min) * wave;
      break;
    }
    case "blur": {
      const from = num("radius_from", 0);
      const to = num("radius_to", 0);
      next.blur += from + (to - from) * eased;
      break;
    }
    case "motion_blur": {
      next.blur += num("amount", 0) * 0.5;
      break;
    }
    case "brightness": {
      const from = num("value_from", 1);
      const to = num("value_to", 1);
      next.brightness *= from + (to - from) * eased;
      break;
    }
    case "saturation": {
      const from = num("value_from", 1);
      const to = num("value_to", 1);
      next.saturation *= from + (to - from) * eased;
      break;
    }
    case "contrast": {
      const from = num("value_from", 1);
      const to = num("value_to", 1);
      // 预览端用亮度近似对比度，这里保持同样处理以免两边不一致
      next.brightness *= 1 + (from + (to - from) * eased - 1) * 0.5;
      break;
    }
    default:
      break;
  }
  return next;
};

/** 把此刻所有生效的特效依次折叠进 geometry。 */
export const foldEffects = (
  geometry: Geometry,
  effects: TimelineElement[],
  element: TimelineElement,
  now: number,
): Geometry => {
  let result = geometry;
  for (const effect of effects) {
    if (effectAppliesTo(effect, element)) {
      result = applyGeometryEffect(result, effect, now);
    }
  }
  return result;
};

/** 只影响整屏的特效名单，由 ScreenEffects 单独渲染。 */
export const SCREEN_EFFECT_NAMES = new Set([
  "flash",
  "vignette",
  "rgb_split",
  "glitch",
]);
