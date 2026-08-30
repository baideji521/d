/** pulse 呼吸：余弦波在 scale_min → scale_max 之间往复 cycles 次。 */

import type { GeometryEffectEntry } from "./types.ts";
import { int, num } from "./types.ts";

export const pulse: GeometryEffectEntry = {
  name: "pulse",
  kind: "geometry",
  apply: (geometry, ctx) => {
    const min = num(ctx.params, "scale_min", 1);
    const max = num(ctx.params, "scale_max", 1.08);
    const cycles = int(ctx.params, "cycles", 2);
    const wave = (1 - Math.cos(ctx.progress * Math.PI * 2 * cycles)) / 2;
    return { ...geometry, scale: geometry.scale * (min + (max - min) * wave) };
  },
};
