/**
 * glitch 故障转场：条带逐条切换到新片段。
 *
 * from 整层铺底，然后按 progress 逐条放出 to 的横向条带，
 * 每条带用确定性伪随机做横向错位（渲染必须可复现，不能用 Math.random）。
 */

import type { TransitionEntry, TransitionLayerSpec } from "./types.ts";
import { int, num } from "./types.ts";

/** 第 index 条带的 polygon clip。shift 是横向错位百分比。 */
export const glitchBandClip = (
  index: number,
  slices: number,
  intensity: number,
): string => {
  const top = (index / slices) * 100;
  const height = 100 / slices;
  const shift = Math.sin(index * 12.9898) * intensity * 8;
  return `polygon(${shift}% ${top}%, ${100 + shift}% ${top}%, ${100 + shift}% ${
    top + height
  }%, ${shift}% ${top + height}%)`;
};

export const glitch: TransitionEntry = {
  name: "glitch",
  render: (ctx) => {
    const slices = int(ctx.params, "slices", 14, 2);
    const intensity = num(ctx.params, "intensity", 0.7);
    const layers: TransitionLayerSpec[] = [
      { kind: "side", role: "from", key: "from", alpha: 1 },
    ];
    for (let index = 0; index < slices; index += 1) {
      if (index / slices > ctx.progress) {
        continue;
      }
      layers.push({
        kind: "side",
        role: "to",
        key: `to-${index}`,
        alpha: 1,
        clip: glitchBandClip(index, slices, intensity),
      });
    }
    return layers;
  },
};
