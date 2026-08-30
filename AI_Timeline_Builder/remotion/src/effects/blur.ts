/** blur 模糊：radius_from → radius_to（px），叠加到 geometry.blur。 */

import type { GeometryEffectEntry } from "./types.ts";
import { num } from "./types.ts";

export const blur: GeometryEffectEntry = {
  name: "blur",
  kind: "geometry",
  apply: (geometry, ctx) => {
    const from = num(ctx.params, "radius_from", 0);
    const to = num(ctx.params, "radius_to", 0);
    return { ...geometry, blur: geometry.blur + from + (to - from) * ctx.eased };
  },
};
