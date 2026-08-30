/** whip 甩镜：两侧沿方向反向位移 + 模糊，同时交叉淡化。 */

import type { TransitionEntry } from "./types.ts";
import { directionVector, num } from "./types.ts";

export const whip: TransitionEntry = {
  name: "whip",
  render: (ctx) => {
    const progress = ctx.progress;
    const intensity = num(ctx.params, "intensity", 0.8);
    const blur = num(ctx.params, "blur", 0.6) * 40;
    const [vx, vy] = directionVector(ctx.params);
    return [
      {
        kind: "side",
        role: "from",
        key: "from",
        alpha: 1 - progress,
        offset: [vx * progress * intensity, vy * progress * intensity],
        blur: blur * progress,
      },
      {
        kind: "side",
        role: "to",
        key: "to",
        alpha: progress,
        offset: [
          -vx * (1 - progress) * intensity,
          -vy * (1 - progress) * intensity,
        ],
        blur: blur * (1 - progress),
      },
    ];
  },
};
