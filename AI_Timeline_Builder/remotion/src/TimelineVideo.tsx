/**
 * Timeline JSON → Remotion 画面。
 *
 * 渲染规则：
 * 1. 每个元素一个 <Sequence>，from/durationInFrames 由秒换算而来
 * 2. 轨道顺序决定 zIndex（tracks 数组越靠后越上层）
 * 3. 元素内部用自己的局部帧算 geometry，再把此刻生效的程序特效折叠进去
 * 4. 参与转场的片段照常渲染，只在转场那几帧里让位给 TransitionLayer
 * 5. 全屏特效最后盖在最上层
 */

import React from "react";
import { AbsoluteFill, Sequence, useCurrentFrame, useVideoConfig } from "remotion";
import { AudioLayer } from "./elements/AudioLayer";
import { CaptionLayer } from "./elements/CaptionLayer";
import { OverlayLayer } from "./elements/OverlayLayer";
import { TextLayer } from "./elements/TextLayer";
import { VideoLayer } from "./elements/VideoLayer";
import { ScreenEffects } from "./effects/ScreenEffects";
import { TransitionLayer } from "./transitions/TransitionLayer";
import { foldEffects } from "./effects/programEffects";
import type { AssetManifest, Timeline, TimelineElement } from "./lib/timeline";
import {
  baseGeometry,
  findTrack,
  isCoveredByTransition,
  timelineDuration,
  toDurationFrames,
  toFrames,
  trackZIndex,
} from "./lib/timeline";

export type TimelineVideoProps = {
  timeline: Timeline;
  manifest: AssetManifest;
};

const VISUAL_TYPES = new Set([
  "video",
  "overlay",
  "freeze",
  "text",
  "caption",
  "caption_group",
]);

/** 元素内部渲染：在 Sequence 里拿局部帧，算出绝对时间后折叠特效。 */
const ElementRenderer: React.FC<{
  element: TimelineElement;
  timeline: Timeline;
  manifest: AssetManifest;
  effects: TimelineElement[];
  transitions: TimelineElement[];
}> = ({ element, timeline, manifest, effects, transitions }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const localTime = frame / fps;
  const now = (element.start ?? 0) + localTime;

  // 转场那几帧里让位给 TransitionLayer，其余时间照常自己渲染
  if (isCoveredByTransition(element, transitions, now)) {
    return null;
  }

  const geometry = foldEffects(
    baseGeometry(element, localTime),
    effects.filter((effect) => {
      const start = effect.start ?? 0;
      return now >= start && now < start + (effect.duration ?? 0);
    }),
    element,
    now,
    fps,
  );

  switch (element.type) {
    case "video":
    case "freeze":
      return (
        <VideoLayer
          element={element}
          timeline={timeline}
          manifest={manifest}
          geometry={geometry}
        />
      );
    case "overlay":
      return <OverlayLayer element={element} manifest={manifest} geometry={geometry} />;
    case "text":
      return <TextLayer element={element} geometry={geometry} />;
    case "caption":
    case "caption_group":
      return <CaptionLayer element={element} geometry={geometry} />;
    default:
      return null;
  }
};

/** 全屏特效需要知道当前时间，单独包一层拿 frame。 */
const ScreenEffectsHost: React.FC<{ effects: TimelineElement[] }> = ({ effects }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const now = frame / fps;
  const active = effects.filter((effect) => {
    const start = effect.start ?? 0;
    return now >= start && now < start + (effect.duration ?? 0);
  });
  if (active.length === 0) {
    return null;
  }
  return <ScreenEffects effects={active} now={now} fps={fps} />;
};

export const TimelineVideo: React.FC<TimelineVideoProps> = ({
  timeline,
  manifest,
}) => {
  const { fps } = useVideoConfig();
  const elements = timeline.elements ?? [];

  const effects = elements.filter((e) => e.type === "effect");
  const transitions = elements.filter((e) => e.type === "transition");

  const visuals = elements
    .filter((e) => VISUAL_TYPES.has(e.type))
    .filter((e) => !findTrack(timeline, e.track)?.hidden)
    .sort(
      (a, b) =>
        (a.z_index ?? trackZIndex(timeline, a.track)) -
          (b.z_index ?? trackZIndex(timeline, b.track)) ||
        (a.start ?? 0) - (b.start ?? 0),
    );

  const audios = elements.filter(
    (e) => e.type === "audio" && !findTrack(timeline, e.track)?.hidden,
  );

  return (
    <AbsoluteFill style={{ backgroundColor: timeline.meta.background ?? "#000000" }}>
      {visuals.map((element) => (
        <Sequence
          key={element.id}
          name={`${element.type} ${element.id}`}
          from={toFrames(element.start ?? 0, fps)}
          durationInFrames={toDurationFrames(element.duration ?? 0, fps)}
          style={{ zIndex: element.z_index ?? trackZIndex(timeline, element.track) }}
        >
          <ElementRenderer
            element={element}
            timeline={timeline}
            manifest={manifest}
            effects={effects}
            transitions={transitions}
          />
        </Sequence>
      ))}

      {transitions.map((transition) => (
        <Sequence
          key={transition.id}
          name={`transition ${transition.name} ${transition.id}`}
          from={toFrames(transition.start ?? 0, fps)}
          durationInFrames={toDurationFrames(transition.duration ?? 0, fps)}
          style={{ zIndex: trackZIndex(timeline, transition.track) + 1 }}
        >
          <TransitionLayer
            transition={transition}
            timeline={timeline}
            manifest={manifest}
            effects={effects}
          />
        </Sequence>
      ))}

      {audios.map((element) => (
        <Sequence
          key={element.id}
          name={`audio ${element.id}`}
          from={toFrames(element.start ?? 0, fps)}
          durationInFrames={toDurationFrames(element.duration ?? 0, fps)}
        >
          <AudioLayer element={element} manifest={manifest} timeline={timeline} />
        </Sequence>
      ))}

      <AbsoluteFill style={{ zIndex: 9000 }}>
        <ScreenEffectsHost effects={effects} />
      </AbsoluteFill>
    </AbsoluteFill>
  );
};

/** 供 calculateMetadata 使用：总时长（帧）。秒→帧只走 lib/timeline 的唯一入口。 */
export const timelineDurationInFrames = (timeline: Timeline): number =>
  toDurationFrames(timelineDuration(timeline), timeline.meta?.fps ?? 30);
