/**
 * slide 滑入 / push 推移。
 *
 * 两者唯一区别：slide 时旧片段不动，push 时旧片段被一起推走。
 * 两侧都是 alpha 1，靠位移交接，所以不会有半透明叠影。
 */

import type { TransitionEntry } from "./types.ts";
import { directionVector } from "./types.ts";

const makeSlide = (name: string, moveFrom: boolean): TransitionEntry => ({
  name,
  render: (ctx) => {
    const progress = ctx.progress;
    const [vx, vy] = directionVector(ctx.params);
    return [
      {
        kind: "side",
        role: "from",
        key: "from",
        alpha: 1,
        offset: moveFrom ? [vx * progress, vy * progress] : [0, 0],
      },
      {
        kind: "side",
        role: "to",
        key: "to",
        alpha: 1,
        offset: [-vx * (1 - progress), -vy * (1 - progress)],
      },
    ];
  },
});

export const slide = makeSlide("slide", false);
export const push = makeSlide("push", true);
