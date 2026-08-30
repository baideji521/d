/** brightness 亮度：value_from → value_to，1.0 为原始亮度。 */

import type { GeometryEffectEntry } from "./types.ts";
import { num } from "./types.ts";

export const brightness: GeometryEffectEntry = {
  name: "brightness",
  kind: "geometry",
  apply: (geometry, ctx) => {
    const from = num(ctx.params, "value_from", 1);
    const to = num(ctx.params, "value_to", 1);
    return {
      ...geometry,
      brightness: geometry.brightness * (from + (to - from) * ctx.eased),
    };
  },
};
