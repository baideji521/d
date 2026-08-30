/**
 * 转场：在 from / to 两个 Clip 的交界处混合两侧画面。
 *
 * 阶段 7 之后这里不再有 switch —— 每种转场的算法在 transitions/<name>.ts，
 * 各自返回一份**层描述（plan）**，本文件只负责把 plan 画出来。
 * 「怎么组合两个画面」只在这一处发生。
 *
 * 时间关系（详见 docs/TRANSITION_SPEC.md）：
 * - 转场自己是一个 Sequence，占据 [start, start+duration) 这个窗口
 * - 窗口内两侧片段在 TimelineVideo 里让位（isCoveredByTransition），由这里统一画
 * - 窗口外两侧片段照常各自渲染 —— 绝不能把它们从渲染列表里整体删掉，
 *   那就是阶段 2 P0-1 的黑帧成因
 * - 某一侧此刻超出自身时间范围时取端点帧（sampleTime 夹取），所以片段之间
 *   有缝或有重叠都不会黑，只是变成定格画面
 */

import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig } from "remotion";
import { VideoLayer } from "../elements/VideoLayer";
import { foldEffects } from "../effects/programEffects";
import type {
  AssetManifest,
  Geometry,
  Timeline,
  TimelineElement,
} from "../lib/timeline";
import { baseGeometry, findElement } from "../lib/timeline";
import { transitionRenderers } from "./index";
import type { SideLayer } from "./types";
import { makeTransitionContext } from "./types";

type Props = {
  transition: TimelineElement;
  timeline: Timeline;
  manifest: AssetManifest;
  effects: TimelineElement[];
};

export const TransitionLayer: React.FC<Props> = ({
  transition,
  timeline,
  manifest,
  effects,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const now = (transition.start ?? 0) + frame / fps;
  const ctx = makeTransitionContext(transition, now, fps);

  const sides: Record<"from" | "to", TimelineElement | undefined> = {
    from: findElement(timeline, transition.from),
    to: findElement(timeline, transition.to),
  };

  /** 渲染一层「某一侧的画面」。element 超出自身时间范围时取端点帧。 */
  const renderSide = (layer: SideLayer): React.ReactNode => {
    const element = sides[layer.role];
    if (!element) {
      return null;
    }
    const start = element.start ?? 0;
    const end = start + (element.duration ?? 0);
    const sampleTime = Math.min(Math.max(now, start), Math.max(start, end - 1 / fps));
    const sampleLocal = sampleTime - start;

    let geometry: Geometry = baseGeometry(element, sampleLocal);
    geometry = foldEffects(geometry, effects, element, sampleTime, fps);
    const [dx, dy] = layer.offset ?? [0, 0];
    geometry = {
      ...geometry,
      x: geometry.x + dx,
      y: geometry.y + dy,
      scale: geometry.scale * (layer.scale ?? 1),
      rotation: geometry.rotation + (layer.rotation ?? 0),
      opacity: geometry.opacity * Math.max(0, Math.min(1, layer.alpha)),
      blur: geometry.blur + (layer.blur ?? 0),
    };

    // 转场内部要按「元素自身时间轴」去取视频帧，所以用一个偏移后的副本
    const shifted: TimelineElement = {
      ...element,
      start: (transition.start ?? 0) - sampleLocal,
    };

    return (
      <AbsoluteFill key={layer.key} style={layer.clip ? { clipPath: layer.clip } : undefined}>
        <VideoLayer
          element={shifted}
          timeline={timeline}
          manifest={manifest}
          geometry={geometry}
        />
      </AbsoluteFill>
    );
  };

  // 查不到就退回 crossfade：这里返回 null 会让整个转场窗口变黑
  const entry = transitionRenderers.resolve(transition.name);
  if (!entry) {
    return null;
  }

  return (
    <AbsoluteFill>
      {entry.render(ctx).map((layer) =>
        layer.kind === "side" ? (
          renderSide(layer)
        ) : (
          <AbsoluteFill
            key={layer.key}
            style={{
              backgroundColor: layer.color,
              opacity: Math.max(0, Math.min(1, layer.opacity)),
            }}
          />
        ),
      )}
    </AbsoluteFill>
  );
};
