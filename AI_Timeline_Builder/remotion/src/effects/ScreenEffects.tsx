/**
 * 全屏类特效的宿主。
 *
 * 阶段 6 之后这里不再有 switch —— 具体渲染在 effects/<name>.tsx，
 * 本文件只负责按 name 查注册表并把上下文喂给它。
 *
 * 这些效果不改变单个元素的几何，而是盖在整个画面上，
 * 所以在 TimelineVideo 里最后渲染。它们会忽略 effect.target。
 */

import React from "react";
import type { TimelineElement } from "../lib/timeline";
import { effectRenderers } from "./index";
import { makeEffectContext } from "./types";

type Props = {
  effects: TimelineElement[];
  now: number;
  fps?: number;
};

export const ScreenEffects: React.FC<Props> = ({ effects, now, fps = 30 }) => (
  <>
    {effects.map((effect) => {
      const entry = effectRenderers.screen(effect.name);
      if (!entry) {
        // 未注册 / 不是全屏类：安全跳过，拦截交给 Validator
        return null;
      }
      const { Component } = entry;
      return <Component key={effect.id} ctx={makeEffectContext(effect, now, fps)} />;
    })}
  </>
);
