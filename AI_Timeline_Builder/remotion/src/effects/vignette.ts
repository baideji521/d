/** vignette 暗角：径向渐变把四周压暗。不随时间变化。 */

import React from "react";
import { AbsoluteFill } from "remotion";
import type { ScreenEffectEntry } from "./types.ts";
import { num } from "./types.ts";

export const vignette: ScreenEffectEntry = {
  name: "vignette",
  kind: "screen",
  Component: ({ ctx }) => {
    const intensity = num(ctx.params, "intensity", 0.5);
    if (intensity <= 0.002) {
      return null;
    }
    const radius = num(ctx.params, "radius", 0.75);
    const inner = Math.max(0, Math.min(100, radius * 55));
    return React.createElement(AbsoluteFill, {
      style: {
        background: `radial-gradient(circle at 50% 50%, rgba(0,0,0,0) ${inner}%, rgba(0,0,0,${(
          0.92 * intensity
        ).toFixed(3)}) 100%)`,
      },
    });
  },
};
