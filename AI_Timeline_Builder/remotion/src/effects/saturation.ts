/** saturation 饱和度：value_from → value_to，0 为黑白，1.0 为原始。 */

import type { GeometryEffectEntry } from "./types.ts";
import { num } from "./types.ts";

export const saturation: GeometryEffectEntry = {
  name: "saturation",
  kind: "geometry",
  apply: (geometry, ctx) => {
    const from = num(ctx.params, "value_from", 1);
    const to = num(ctx.params, "value_to", 1);
    return {
      ...geometry,
      saturation: geometry.saturation * (from + (to - from) * ctx.eased),
    };
  },
};
