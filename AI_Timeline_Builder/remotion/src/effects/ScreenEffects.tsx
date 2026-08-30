/**
 * 全屏类特效：闪白、暗角、色差、故障。
 *
 * 这些效果不改变单个元素的几何，而是盖在整个画面上，
 * 所以在 TimelineVideo 里最后渲染。
 */

import React from "react";
import { AbsoluteFill } from "remotion";
import type { TimelineElement } from "../lib/timeline";
import { applyEasing } from "../lib/timeline";

type Props = {
  effects: TimelineElement[];
  now: number;
};

const num = (
  params: Record<string, unknown>,
  key: string,
  fallback: number,
): number => {
  const value = params[key];
  return typeof value === "number" ? value : fallback;
};

const str = (
  params: Record<string, unknown>,
  key: string,
  fallback: string,
): string => {
  const value = params[key];
  return typeof value === "string" ? value : fallback;
};

const Flash: React.FC<{ effect: TimelineElement; now: number }> = ({
  effect,
  now,
}) => {
  const params = (effect.params ?? {}) as Record<string, unknown>;
  const start = effect.start ?? 0;
  const duration = Math.max(1e-6, effect.duration ?? 0);
  const progress = Math.min(1, Math.max(0, (now - start) / duration));
  const decayed = applyEasing(progress, str(params, "decay", "easeOut") as never);
  const opacity = num(params, "intensity", 0.85) * (1 - decayed);
  if (opacity <= 0.002) {
    return null;
  }
  return (
    <AbsoluteFill
      style={{
        backgroundColor: str(params, "color", "#FFFFFF"),
        opacity: Math.min(1, opacity),
      }}
    />
  );
};

const Vignette: React.FC<{ effect: TimelineElement }> = ({ effect }) => {
  const params = (effect.params ?? {}) as Record<string, unknown>;
  const intensity = num(params, "intensity", 0.5);
  const radius = num(params, "radius", 0.75);
  if (intensity <= 0.002) {
    return null;
  }
  const inner = Math.max(0, Math.min(100, radius * 55));
  return (
    <AbsoluteFill
      style={{
        background: `radial-gradient(circle at 50% 50%, rgba(0,0,0,0) ${inner}%, rgba(0,0,0,${(
          0.92 * intensity
        ).toFixed(3)}) 100%)`,
      }}
    />
  );
};

/**
 * 色差：靠 CSS drop-shadow 叠两个方向的彩色残影。
 * 这不是真正的通道分离，但方向和强度的手感一致，参数含义能对上。
 */
const RgbSplit: React.FC<{ effect: TimelineElement }> = ({ effect }) => {
  const params = (effect.params ?? {}) as Record<string, unknown>;
  const offset = num(params, "offset", 8);
  const angle = (num(params, "angle", 0) * Math.PI) / 180;
  if (offset < 0.5) {
    return null;
  }
  const dx = Math.cos(angle) * offset;
  const dy = Math.sin(angle) * offset;
  return (
    <AbsoluteFill
      style={{
        backdropFilter: `drop-shadow(${dx.toFixed(1)}px ${dy.toFixed(
          1,
        )}px 0 rgba(255,0,0,0.5)) drop-shadow(${(-dx).toFixed(1)}px ${(-dy).toFixed(
          1,
        )}px 0 rgba(0,128,255,0.5))`,
        mixBlendMode: "screen",
      }}
    />
  );
};

/** 故障：叠几条随机偏移的半透明色带，制造条带错位的观感。 */
const Glitch: React.FC<{ effect: TimelineElement; now: number }> = ({
  effect,
  now,
}) => {
  const params = (effect.params ?? {}) as Record<string, unknown>;
  const slices = Math.max(2, Math.round(num(params, "slices", 12)));
  const intensity = num(params, "intensity", 0.6);
  if (intensity <= 0.01) {
    return null;
  }
  const start = effect.start ?? 0;
  const duration = Math.max(1e-6, effect.duration ?? 0);
  const progress = Math.min(1, Math.max(0, (now - start) / duration));
  const bands = [];
  for (let index = 0; index < slices; index += 1) {
    // 确定性伪随机，保证同一帧每次渲染结果一致（渲染必须可复现）
    const seed = Math.sin((index + 1) * 12.9898 + progress * 78.233) * 43758.5453;
    const noise = seed - Math.floor(seed);
    if (noise > 0.55) {
      continue;
    }
    const shift = (noise - 0.5) * 2 * intensity * 12;
    bands.push(
      <div
        key={index}
        style={{
          position: "absolute",
          left: `${shift}%`,
          top: `${(index / slices) * 100}%`,
          width: "100%",
          height: `${100 / slices + 0.2}%`,
          backgroundColor:
            noise > 0.3 ? "rgba(0,255,255,0.12)" : "rgba(255,0,120,0.12)",
          mixBlendMode: "screen",
        }}
      />,
    );
  }
  return <AbsoluteFill>{bands}</AbsoluteFill>;
};

export const ScreenEffects: React.FC<Props> = ({ effects, now }) => (
  <>
    {effects.map((effect) => {
      switch (effect.name) {
        case "flash":
          return <Flash key={effect.id} effect={effect} now={now} />;
        case "vignette":
          return <Vignette key={effect.id} effect={effect} />;
        case "rgb_split":
          return <RgbSplit key={effect.id} effect={effect} />;
        case "glitch":
          return <Glitch key={effect.id} effect={effect} now={now} />;
        default:
          return null;
      }
    })}
  </>
);
