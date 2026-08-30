/**
 * wipe 擦除：新片段用硬边 clip-path 沿方向揭开，两侧都不透明。
 *
 * feather 参数当前**不参与计算** —— clip-path 的 inset 没有羽化能力。
 * 要做羽化得换成 mask-image，那会改变现有观感，留到后续阶段。
 */

import type { TransitionEntry } from "./types.ts";
import { directionVector } from "./types.ts";

/** 按方向算出「揭开 percent%」的 inset。 */
export const wipeClip = (
  vector: [number, number],
  percent: number,
): string => {
  const rest = 100 - percent;
  if (vector[0] < 0) {
    return `inset(0 ${rest}% 0 0)`;
  }
  if (vector[0] > 0) {
    return `inset(0 0 0 ${rest}%)`;
  }
  if (vector[1] < 0) {
    return `inset(0 0 ${rest}% 0)`;
  }
  return `inset(${rest}% 0 0 0)`;
};

export const wipe: TransitionEntry = {
  name: "wipe",
  render: (ctx) => [
    { kind: "side", role: "from", key: "from", alpha: 1 },
    {
      kind: "side",
      role: "to",
      key: "to",
      alpha: 1,
      clip: wipeClip(directionVector(ctx.params), ctx.progress * 100),
    },
  ],
};
