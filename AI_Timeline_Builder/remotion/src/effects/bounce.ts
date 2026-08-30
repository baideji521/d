/** bounce 弹跳：正弦绝对值做上抛，(1 - progress) 做衰减。用线性 progress，缓动会破坏节奏。 */

import type { GeometryEffectEntry } from "./types.ts";
import { int, num } from "./types.ts";

export const bounce: GeometryEffectEntry = {
  name: "bounce",
  kind: "geometry",
  apply: (geometry, ctx) => {
    const bounces = int(ctx.params, "bounces", 2);
    const height = num(ctx.params, "height", 0.08);
    const offset =
      Math.abs(Math.sin(ctx.progress * Math.PI * bounces)) * height * (1 - ctx.progress);
    return { ...geometry, y: geometry.y - offset };
  },
};
