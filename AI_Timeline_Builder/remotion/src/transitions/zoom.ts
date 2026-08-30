/** zoom 缩放转场：前一段推进、后一段拉出，两侧都带随进度衰减的模糊。 */

import type { TransitionEntry } from "./types.ts";
import { num } from "./types.ts";

export const zoom: TransitionEntry = {
  name: "zoom",
  render: (ctx) => {
    const progress = ctx.progress;
    const scale = num(ctx.params, "scale", 1.6);
    const blur = num(ctx.params, "blur", 0.3) * 40;
    return [
      {
        kind: "side",
        role: "from",
        key: "from",
        alpha: 1 - progress,
        scale: 1 + (scale - 1) * progress,
        blur: blur * progress,
      },
      {
        kind: "side",
        role: "to",
        key: "to",
        alpha: progress,
        scale: scale - (scale - 1) * progress,
        blur: blur * (1 - progress),
      },
    ];
  },
};
