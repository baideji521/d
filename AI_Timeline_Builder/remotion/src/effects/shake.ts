/** shake 抖动：按频率做正弦位移，附带轻微旋转。用 localTime 保证相位可复现。 */

import type { GeometryEffectEntry } from "./types.ts";
import { num } from "./types.ts";

export const shake: GeometryEffectEntry = {
  name: "shake",
  kind: "geometry",
  apply: (geometry, ctx) => {
    const amplitude = num(ctx.params, "amplitude", 0.02);
    const frequency = num(ctx.params, "frequency", 18);
    const phase = ctx.localTime * frequency * Math.PI * 2;
    return {
      ...geometry,
      x: geometry.x + Math.sin(phase) * amplitude,
      y: geometry.y + Math.cos(phase * 1.37) * amplitude,
      rotation:
        geometry.rotation + Math.sin(phase * 0.73) * num(ctx.params, "rotation", 0),
    };
  },
};
