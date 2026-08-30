/**
 * 视频片段与冻结帧。
 *
 * 视频：trimBefore / trimAfter 从 source 区间换算而来（秒 → 帧在这里完成）。
 * 冻结帧：先用 trimBefore 定位到要冻的那一帧，再用 <Freeze frame={0}> 把它按住。
 */

import React from "react";
import { Freeze, OffthreadVideo, useVideoConfig } from "remotion";
import { assetUrl } from "../lib/assets";
import type { AssetManifest, Geometry, Timeline, TimelineElement } from "../lib/timeline";
import { findElement, geometryToStyle, masterVolume, resolveVolume, toFrames } from "../lib/timeline";

type Props = {
  element: TimelineElement;
  timeline: Timeline;
  manifest: AssetManifest;
  geometry: Geometry;
};

const FILL: React.CSSProperties = {
  width: "100%",
  height: "100%",
  objectFit: "cover",
};

export const VideoLayer: React.FC<Props> = ({
  element,
  timeline,
  manifest,
  geometry,
}) => {
  const { fps } = useVideoConfig();

  if (element.type === "freeze") {
    const target = findElement(timeline, element.target);
    const url = assetUrl(manifest, target?.asset);
    if (!url) {
      return null;
    }
    const freezeFrame = toFrames(element.source_time ?? 0, fps);
    return (
      <div style={{ ...geometryToStyle(geometry), width: "100%", height: "100%" }}>
        <Freeze frame={0}>
          <OffthreadVideo
            src={url}
            trimBefore={freezeFrame}
            trimAfter={freezeFrame + 1}
            muted
            style={FILL}
          />
        </Freeze>
      </div>
    );
  }

  const url = assetUrl(manifest, element.asset);
  if (!url) {
    return null;
  }
  const source = element.source ?? { start: 0, end: element.duration ?? 1 };
  const trimBefore = toFrames(source.start, fps);
  const trimAfter = Math.max(trimBefore + 1, toFrames(source.end, fps));
  const audio = element.audio ?? {};
  const muted = audio.enabled === false;
  const master = masterVolume(timeline);

  return (
    <div style={{ ...geometryToStyle(geometry), width: "100%", height: "100%" }}>
      <OffthreadVideo
        src={url}
        trimBefore={trimBefore}
        trimAfter={trimAfter}
        playbackRate={element.speed ?? 1}
        muted={muted || master <= 0}
        volume={muted ? 0 : resolveVolume(audio.volume ?? 1, master)}
        style={FILL}
      />
    </div>
  );
};
