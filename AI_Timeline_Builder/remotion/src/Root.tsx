/**
 * 只有一个 Composition：TimelineVideo。
 *
 * fps / 分辨率 / 时长全部由 Timeline JSON 的 meta 与元素推导，
 * 不写死在这里，这样改 JSON 就能改成品规格，无需碰 TSX。
 */

import React from "react";
import { Composition } from "remotion";
import { TimelineVideo, timelineDurationInFrames } from "./TimelineVideo";
import type { TimelineVideoProps } from "./TimelineVideo";
import { ASSET_MANIFEST, TIMELINE } from "./timeline-data";

export const RemotionRoot: React.FC = () => {
  return (
    <Composition
      id="TimelineVideo"
      component={TimelineVideo}
      durationInFrames={timelineDurationInFrames(TIMELINE)}
      fps={TIMELINE.meta.fps}
      width={TIMELINE.meta.width}
      height={TIMELINE.meta.height}
      defaultProps={{
        timeline: TIMELINE,
        manifest: ASSET_MANIFEST,
      }}
      calculateMetadata={({ props }: { props: TimelineVideoProps }) => {
        const timeline = props.timeline ?? TIMELINE;
        return {
          durationInFrames: timelineDurationInFrames(timeline),
          fps: timeline.meta.fps,
          width: timeline.meta.width,
          height: timeline.meta.height,
        };
      }}
    />
  );
};
