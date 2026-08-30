/** crossfade 交叉溶解：两侧直接叠化，没有中间色。也是未知转场的兜底 renderer。 */

import type { TransitionEntry } from "./types.ts";

export const crossfade: TransitionEntry = {
  name: "crossfade",
  render: (ctx) => [
    { kind: "side", role: "from", key: "from", alpha: 1 - ctx.progress },
    { kind: "side", role: "to", key: "to", alpha: ctx.progress },
  ],
};
