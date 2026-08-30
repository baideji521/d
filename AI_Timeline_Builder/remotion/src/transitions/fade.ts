/**
 * fade 淡入淡出：经过一层纯色过渡。
 *
 * 前半段只画 from 并淡出，后半段只画 to 并淡入，中间色在最上面先浓后淡。
 * 注意这里**不是** crossfade —— 同一时刻只有一侧画面在，所以不会出现叠影。
 */

import type { TransitionEntry, TransitionLayerSpec } from "./types.ts";
import { clamp01, num, str } from "./types.ts";

/** fade 与 flash 只差默认颜色，算法完全一样。 */
export const makeVeiledFade = (
  name: string,
  defaultColor: string,
): TransitionEntry => ({
  name,
  render: (ctx) => {
    const progress = ctx.progress;
    const intensity = num(ctx.params, "intensity", 1);
    const layers: TransitionLayerSpec[] = [
      progress < 0.5
        ? {
            kind: "side",
            role: "from",
            key: "from",
            alpha: 1 - progress * 2,
          }
        : {
            kind: "side",
            role: "to",
            key: "to",
            alpha: (progress - 0.5) * 2,
          },
    ];
    layers.push({
      kind: "veil",
      key: "veil",
      color: str(ctx.params, "color", defaultColor),
      opacity: clamp01((1 - Math.abs(progress - 0.5) * 2) * intensity),
    });
    return layers;
  },
});

export const fade = makeVeiledFade("fade", "#000000");
