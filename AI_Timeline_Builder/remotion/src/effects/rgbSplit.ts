/**
 * rgb_split 色差。
 *
 * 不是真正的通道分离，而是把红 / 蓝两层沿 angle 方向反向偏移后 screen 叠加：
 * 重叠区得到两层之和（洋红色偏），只被其中一层覆盖的边缘条带留下纯红 / 纯蓝，
 * 于是画面边缘出现色边，手感与色差一致，参数含义（offset 位移、angle 方向）能对上。
 *
 * 阶段 6.5 验收修复：原实现用 `backdropFilter: drop-shadow(...)`，
 * 渲染出来与无特效基线逐像素完全相同（luma 差 0.000）。根因是 drop-shadow 只在
 * alpha 轮廓「外面」可见，而 backdrop 是一整块不透明的满屏画面，没有任何透明区域，
 * 投影全部被自身遮住 —— 无论 offset 给 8 还是 60 都必然是空操作。
 * 所以改成和 glitch / vignette 一致的「自己画」路线，不再依赖 backdrop 滤镜。
 */

import React from "react";
import { AbsoluteFill } from "remotion";
import type { ScreenEffectEntry } from "./types.ts";
import { num } from "./types.ts";

export const rgbSplit: ScreenEffectEntry = {
  name: "rgb_split",
  kind: "screen",
  Component: ({ ctx }) => {
    const offset = num(ctx.params, "offset", 8);
    if (offset < 0.5) {
      return null;
    }
    const angle = (num(ctx.params, "angle", 0) * Math.PI) / 180;
    const dx = Math.cos(angle) * offset;
    const dy = Math.sin(angle) * offset;
    // offset 越大色差越明显：8px（默认）淡，60px（上限）浓，但不许糊掉整个画面
    const alpha = Math.min(0.45, 0.06 + offset / 90);
    const layer = (key: string, color: string, sx: number, sy: number) =>
      React.createElement("div", {
        key,
        style: {
          position: "absolute",
          inset: 0,
          backgroundColor: color,
          mixBlendMode: "screen",
          transform: `translate(${sx.toFixed(1)}px, ${sy.toFixed(1)}px)`,
        },
      });
    return React.createElement(
      AbsoluteFill,
      null,
      layer("r", `rgba(255,0,0,${alpha.toFixed(3)})`, dx, dy),
      layer("b", `rgba(0,128,255,${alpha.toFixed(3)})`, -dx, -dy),
    );
  },
};
