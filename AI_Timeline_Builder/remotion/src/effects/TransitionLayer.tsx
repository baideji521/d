/**
 * 转场：在 from / to 两个 Video Clip 的交界处混合。
 *
 * 转场元素自己是一个 Sequence，内部同时渲染两侧画面，
 * 因此参与转场的片段不会在 TimelineVideo 里再单独渲染一次（否则会画两遍）。
 *
 * 每种转场的参数含义与 libraries/transition_library.py 的参数表完全对应。
 */

import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import { VideoLayer } from "../elements/VideoLayer";
import type {
  AssetManifest,
  Geometry,
  Timeline,
  TimelineElement,
} from "../lib/timeline";
import { baseGeometry, findElement } from "../lib/timeline";
import { foldEffects } from "./programEffects";

type Props = {
  transition: TimelineElement;
  timeline: Timeline;
  manifest: AssetManifest;
  effects: TimelineElement[];
};

type SideOptions = {
  alpha: number;
  offset?: [number, number];
  scale?: number;
  rotation?: number;
  blur?: number;
  clip?: string;
};

const DIRECTION_VECTOR: Record<string, [number, number]> = {
  left: [-1, 0],
  right: [1, 0],
  up: [0, -1],
  down: [0, 1],
};

export const TransitionLayer: React.FC<Props> = ({
  transition,
  timeline,
  manifest,
  effects,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const localTime = frame / fps;
  const now = (transition.start ?? 0) + localTime;
  const duration = Math.max(1e-6, transition.duration ?? 0);
  const progress = Math.min(1, Math.max(0, localTime / duration));

  const fromElement = findElement(timeline, transition.from);
  const toElement = findElement(timeline, transition.to);
  const params = (transition.params ?? {}) as Record<string, unknown>;
  const num = (key: string, fallback: number): number => {
    const value = params[key];
    return typeof value === "number" ? value : fallback;
  };
  const text = (key: string, fallback: string): string => {
    const value = params[key];
    return typeof value === "string" ? value : fallback;
  };

  const vector = DIRECTION_VECTOR[text("direction", "left")] ?? [-1, 0];

  /** 渲染转场的一侧。element 超出自身时间范围时取端点帧。 */
  const side = (
    element: TimelineElement | undefined,
    options: SideOptions,
    key: string,
  ): React.ReactNode => {
    if (!element) {
      return null;
    }
    const start = element.start ?? 0;
    const end = start + (element.duration ?? 0);
    const sampleTime = Math.min(Math.max(now, start), Math.max(start, end - 1 / fps));
    const sampleLocal = sampleTime - start;

    let geometry: Geometry = baseGeometry(element, sampleLocal);
    geometry = foldEffects(geometry, effects, element, sampleTime);
    const [dx, dy] = options.offset ?? [0, 0];
    geometry = {
      ...geometry,
      x: geometry.x + dx,
      y: geometry.y + dy,
      scale: geometry.scale * (options.scale ?? 1),
      rotation: geometry.rotation + (options.rotation ?? 0),
      opacity: geometry.opacity * Math.max(0, Math.min(1, options.alpha)),
      blur: geometry.blur + (options.blur ?? 0),
    };

    // 转场内部要按「元素自身时间轴」去取视频帧，所以用一个偏移后的副本
    const shifted: TimelineElement = {
      ...element,
      start: (transition.start ?? 0) - sampleLocal,
    };

    const content = (
      <VideoLayer
        element={shifted}
        timeline={timeline}
        manifest={manifest}
        geometry={geometry}
      />
    );

    if (options.clip) {
      return (
        <AbsoluteFill key={key} style={{ clipPath: options.clip }}>
          {content}
        </AbsoluteFill>
      );
    }
    return <AbsoluteFill key={key}>{content}</AbsoluteFill>;
  };

  switch (transition.name) {
    case "fade":
    case "flash": {
      const color = text("color", transition.name === "flash" ? "#FFFFFF" : "#000000");
      const intensity = num("intensity", 1);
      const veil = (1 - Math.abs(progress - 0.5) * 2) * intensity;
      return (
        <AbsoluteFill>
          {progress < 0.5
            ? side(fromElement, { alpha: 1 - progress * 2 }, "from")
            : side(toElement, { alpha: (progress - 0.5) * 2 }, "to")}
          <AbsoluteFill
            style={{ backgroundColor: color, opacity: Math.max(0, Math.min(1, veil)) }}
          />
        </AbsoluteFill>
      );
    }

    case "whip": {
      const intensity = num("intensity", 0.8);
      const blur = num("blur", 0.6) * 40;
      return (
        <AbsoluteFill>
          {side(
            fromElement,
            {
              alpha: 1 - progress,
              offset: [vector[0] * progress * intensity, vector[1] * progress * intensity],
              blur: blur * progress,
            },
            "from",
          )}
          {side(
            toElement,
            {
              alpha: progress,
              offset: [
                -vector[0] * (1 - progress) * intensity,
                -vector[1] * (1 - progress) * intensity,
              ],
              blur: blur * (1 - progress),
            },
            "to",
          )}
        </AbsoluteFill>
      );
    }

    case "slide":
    case "push": {
      return (
        <AbsoluteFill>
          {side(
            fromElement,
            {
              alpha: 1,
              offset:
                transition.name === "push"
                  ? [vector[0] * progress, vector[1] * progress]
                  : [0, 0],
            },
            "from",
          )}
          {side(
            toElement,
            {
              alpha: 1,
              offset: [-vector[0] * (1 - progress), -vector[1] * (1 - progress)],
            },
            "to",
          )}
        </AbsoluteFill>
      );
    }

    case "zoom": {
      const zoom = num("scale", 1.6);
      const blur = num("blur", 0.3) * 40;
      return (
        <AbsoluteFill>
          {side(
            fromElement,
            { alpha: 1 - progress, scale: 1 + (zoom - 1) * progress, blur: blur * progress },
            "from",
          )}
          {side(
            toElement,
            { alpha: progress, scale: zoom - (zoom - 1) * progress, blur: blur * (1 - progress) },
            "to",
          )}
        </AbsoluteFill>
      );
    }

    case "spin": {
      const angle = num("angle", 90);
      const zoom = num("scale", 1.3);
      return (
        <AbsoluteFill>
          {side(
            fromElement,
            { alpha: 1 - progress, rotation: angle * progress, scale: 1 + (zoom - 1) * progress },
            "from",
          )}
          {side(
            toElement,
            {
              alpha: progress,
              rotation: -angle * (1 - progress),
              scale: zoom - (zoom - 1) * progress,
            },
            "to",
          )}
        </AbsoluteFill>
      );
    }

    case "blur": {
      const amount = num("amount", 24);
      const wave = 1 - Math.abs(progress - 0.5) * 2;
      return (
        <AbsoluteFill>
          {side(fromElement, { alpha: 1 - progress, blur: amount * wave }, "from")}
          {side(toElement, { alpha: progress, blur: amount * wave }, "to")}
        </AbsoluteFill>
      );
    }

    case "wipe": {
      const percent = progress * 100;
      const clip =
        vector[0] < 0
          ? `inset(0 ${100 - percent}% 0 0)`
          : vector[0] > 0
            ? `inset(0 0 0 ${100 - percent}%)`
            : vector[1] < 0
              ? `inset(0 0 ${100 - percent}% 0)`
              : `inset(${100 - percent}% 0 0 0)`;
      return (
        <AbsoluteFill>
          {side(fromElement, { alpha: 1 }, "from")}
          {side(toElement, { alpha: 1, clip }, "to")}
        </AbsoluteFill>
      );
    }

    case "glitch": {
      const slices = Math.max(2, Math.round(num("slices", 14)));
      const intensity = num("intensity", 0.7);
      const bands: string[] = [];
      for (let index = 0; index < slices; index += 1) {
        if (index / slices > progress) {
          continue;
        }
        const top = (index / slices) * 100;
        const height = 100 / slices;
        const shift = Math.sin(index * 12.9898) * intensity * 8;
        bands.push(
          `polygon(${shift}% ${top}%, ${100 + shift}% ${top}%, ${100 + shift}% ${
            top + height
          }%, ${shift}% ${top + height}%)`,
        );
      }
      return (
        <AbsoluteFill>
          {side(fromElement, { alpha: 1 }, "from")}
          {bands.map((clip, index) => (
            <AbsoluteFill key={index} style={{ clipPath: clip }}>
              {side(toElement, { alpha: 1 }, `to-${index}`)}
            </AbsoluteFill>
          ))}
        </AbsoluteFill>
      );
    }

    case "crossfade":
    default: {
      return (
        <AbsoluteFill>
          {side(fromElement, { alpha: 1 - progress }, "from")}
          {side(toElement, { alpha: progress }, "to")}
        </AbsoluteFill>
      );
    }
  }
};
