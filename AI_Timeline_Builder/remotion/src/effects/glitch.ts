/** glitch 故障：叠几条随机偏移的半透明色带，制造条带错位的观感。 */

import React from "react";
import { AbsoluteFill } from "remotion";
import type { ScreenEffectEntry } from "./types.ts";
import { int, num } from "./types.ts";

export const glitch: ScreenEffectEntry = {
  name: "glitch",
  kind: "screen",
  Component: ({ ctx }) => {
    const intensity = num(ctx.params, "intensity", 0.6);
    if (intensity <= 0.01) {
      return null;
    }
    const slices = int(ctx.params, "slices", 12, 2);
    const bands: React.ReactNode[] = [];
    for (let index = 0; index < slices; index += 1) {
      // 确定性伪随机，保证同一帧每次渲染结果一致（渲染必须可复现）
      const seed = Math.sin((index + 1) * 12.9898 + ctx.progress * 78.233) * 43758.5453;
      const noise = seed - Math.floor(seed);
      if (noise > 0.55) {
        continue;
      }
      const shift = (noise - 0.5) * 2 * intensity * 12;
      bands.push(
        React.createElement("div", {
          key: index,
          style: {
            position: "absolute",
            left: `${shift}%`,
            top: `${(index / slices) * 100}%`,
            width: "100%",
            height: `${100 / slices + 0.2}%`,
            backgroundColor:
              noise > 0.3 ? "rgba(0,255,255,0.12)" : "rgba(255,0,120,0.12)",
            mixBlendMode: "screen",
          },
        }),
      );
    }
    return React.createElement(AbsoluteFill, null, bands);
  },
};
