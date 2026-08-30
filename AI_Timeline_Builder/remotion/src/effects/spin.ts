/** spin 旋转：按缓动进度在 from → to 之间插值角度（度）。 */

import type { GeometryEffectEntry } from "./types.ts";
import { num } from "./types.ts";

export const spin: GeometryEffectEntry = {
  name: "spin",
  kind: "geometry",
  apply: (geometry, ctx) => {
    const from = num(ctx.params, "from", 0);
    const to = num(ctx.params, "to", 0);
    return {
      ...geometry,
      rotation: geometry.rotation + from + (to - from) * ctx.eased,
    };
  },
};
