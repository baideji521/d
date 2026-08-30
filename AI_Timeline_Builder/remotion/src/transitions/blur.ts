/** blur 模糊转场：两边同步模糊到中点最大再恢复，同时交叉淡化。 */

import type { TransitionEntry } from "./types.ts";
import { num } from "./types.ts";

export const blur: TransitionEntry = {
  name: "blur",
  render: (ctx) => {
    const progress = ctx.progress;
    const amount = num(ctx.params, "amount", 24);
    // 三角波：progress 0 和 1 时为 0，0.5 时为 1
    const wave = 1 - Math.abs(progress - 0.5) * 2;
    return [
      {
        kind: "side",
        role: "from",
        key: "from",
        alpha: 1 - progress,
        blur: amount * wave,
      },
      {
        kind: "side",
        role: "to",
        key: "to",
        alpha: progress,
        blur: amount * wave,
      },
    ];
  },
};
