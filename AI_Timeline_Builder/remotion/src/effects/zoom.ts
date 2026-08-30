/** zoom 推拉：按缓动进度插值 scale，并按中心点补偿位移。 */

import type { GeometryEffectEntry } from "./types.ts";
import { num } from "./types.ts";

export const zoom: GeometryEffectEntry = {
  name: "zoom",
  kind: "geometry",
  apply: (geometry, ctx) => {
    const from = num(ctx.params, "scale_from", 1);
    const to = num(ctx.params, "scale_to", 1.3);
    const scale = geometry.scale * (from + (to - from) * ctx.eased);
    const originX = num(ctx.params, "origin_x", 0.5);
    const originY = num(ctx.params, "origin_y", 0.5);
    return {
      ...geometry,
      scale,
      x: geometry.x + (0.5 - originX) * (scale - 1),
      y: geometry.y + (0.5 - originY) * (scale - 1),
    };
  },
};
