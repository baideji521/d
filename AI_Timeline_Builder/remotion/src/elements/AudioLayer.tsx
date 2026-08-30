/**
 * 音频：BGM / 人声 / 音效共用。
 *
 * fade.in / fade.out 通过 volume 回调实现，回调收到的是相对本 Sequence 的帧号。
 * source.start 换算成 trimBefore，速度用 playbackRate。
 * 最终音量 = 元素 volume × fade 系数 × meta.master_volume。
 */

import React from "react";
import { Audio, useVideoConfig } from "remotion";
import { assetUrl } from "../lib/assets";
import type { AssetManifest, Timeline, TimelineElement } from "../lib/timeline";
import { masterVolume, resolveVolume, toFrames } from "../lib/timeline";

type Props = {
  element: TimelineElement;
  manifest: AssetManifest;
  timeline: Timeline;
};

export const AudioLayer: React.FC<Props> = ({ element, manifest, timeline }) => {
  const { fps } = useVideoConfig();
  const url = assetUrl(manifest, element.asset);
  if (!url) {
    return null;
  }

  const master = masterVolume(timeline);
  const baseVolume = resolveVolume(element.volume ?? 1, master);
  const fadeIn = element.fade?.in ?? 0;
  const fadeOut = element.fade?.out ?? 0;
  const totalFrames = Math.max(1, toFrames(element.duration ?? 0, fps));
  const fadeInFrames = toFrames(fadeIn, fps);
  const fadeOutFrames = toFrames(fadeOut, fps);

  const volume =
    fadeInFrames > 0 || fadeOutFrames > 0
      ? (frame: number) => {
          let factor = 1;
          if (fadeInFrames > 0 && frame < fadeInFrames) {
            factor = Math.min(factor, frame / fadeInFrames);
          }
          if (fadeOutFrames > 0 && frame > totalFrames - fadeOutFrames) {
            factor = Math.min(factor, (totalFrames - frame) / fadeOutFrames);
          }
          return baseVolume * Math.max(0, Math.min(1, factor));
        }
      : baseVolume;

  const trimBefore = toFrames(element.source?.start ?? 0, fps);

  return (
    <Audio
      src={url}
      trimBefore={trimBefore > 0 ? trimBefore : undefined}
      playbackRate={element.speed ?? 1}
      volume={volume}
    />
  );
};
