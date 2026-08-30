/**
 * contrast 对比度。
 *
 * Geometry 里没有独立的 contrast 通道，这里用亮度做近似：
 * 把对比度偏移量的一半折算成亮度偏移。方向和强度手感对得上，但不是真对比度。
 * 预览端 render/preview_renderer.py 用完全相同的近似，两边必须同时改。
 */

import type { GeometryEffectEntry } from "./types.ts";
import { num } from "./types.ts";

export const contrast: GeometryEffectEntry = {
  name: "contrast",
  kind: "geometry",
  apply: (geometry, ctx) => {
    const from = num(ctx.params, "value_from", 1);
    const to = num(ctx.params, "value_to", 1);
    const value = from + (to - from) * ctx.eased;
    return { ...geometry, brightness: geometry.brightness * (1 + (value - 1) * 0.5) };
  },
};
