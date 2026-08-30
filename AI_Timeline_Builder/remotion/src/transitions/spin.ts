/** spin 旋转转场：两侧反向旋转并叠加缩放。 */

import type { TransitionEntry } from "./types.ts";
import { num } from "./types.ts";

export const spin: TransitionEntry = {
  name: "spin",
  render: (ctx) => {
    const progress = ctx.progress;
    const angle = num(ctx.params, "angle", 90);
    const scale = num(ctx.params, "scale", 1.3);
    return [
      {
        kind: "side",
        role: "from",
        key: "from",
        alpha: 1 - progress,
        rotation: angle * progress,
        scale: 1 + (scale - 1) * progress,
      },
      {
        kind: "side",
        role: "to",
        key: "to",
        alpha: progress,
        rotation: -angle * (1 - progress),
        scale: scale - (scale - 1) * progress,
      },
    ];
  },
};
