/**
 * flash 闪白：叠一层纯色，按 decay 曲线衰减到透明。
 *
 * 这个文件（以及其他 screen 特效）刻意不用 JSX，改用 React.createElement——
 * 这样 effects/index.ts 整条依赖链都是纯 .ts，
 * `node --test` 的原生类型剥离就能直接加载注册表来测试（JSX 它处理不了）。
 */

import React from "react";
import { AbsoluteFill } from "remotion";
import type { Easing } from "../lib/timeline.ts";
import { applyEasing } from "../lib/timeline.ts";
import type { ScreenEffectEntry } from "./types.ts";
import { num, str } from "./types.ts";

export const flash: ScreenEffectEntry = {
  name: "flash",
  kind: "screen",
  Component: ({ ctx }) => {
    const decayed = applyEasing(
      ctx.progress,
      str(ctx.params, "decay", "easeOut") as Easing,
    );
    const opacity = num(ctx.params, "intensity", 0.85) * (1 - decayed);
    if (opacity <= 0.002) {
      return null;
    }
    return React.createElement(AbsoluteFill, {
      style: {
        backgroundColor: str(ctx.params, "color", "#FFFFFF"),
        opacity: Math.min(1, opacity),
      },
    });
  },
};
