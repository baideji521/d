/**
 * motion_blur 运动模糊。
 *
 * CSS 没有方向性模糊，这里退化成等量的高斯模糊（amount 的一半），
 * angle 参数暂时不参与计算。预览端 render/preview_renderer.py 用同样的近似，
 * 两边保持一致比各自「更准」更重要。
 */

import type { GeometryEffectEntry } from "./types.ts";
import { num } from "./types.ts";

export const motionBlur: GeometryEffectEntry = {
  name: "motion_blur",
  kind: "geometry",
  apply: (geometry, ctx) => ({
    ...geometry,
    blur: geometry.blur + num(ctx.params, "amount", 0) * 0.5,
  }),
};
