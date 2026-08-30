/**
 * 图片 / 透明视频 Overlay。
 * 与视频不同，Overlay 用 contain 等比适配，不裁切，这样 PNG 的构图不会被切掉。
 */

import React from "react";
import { Img, OffthreadVideo } from "remotion";
import { assetUrl, findAsset } from "../lib/assets";
import type { AssetManifest, Geometry, TimelineElement } from "../lib/timeline";
import { geometryToStyle } from "../lib/timeline";

type Props = {
  element: TimelineElement;
  manifest: AssetManifest;
  geometry: Geometry;
};

const VIDEO_EXT = /\.(mp4|mov|webm|mkv)$/i;

export const OverlayLayer: React.FC<Props> = ({ element, manifest, geometry }) => {
  const asset = findAsset(manifest, element.asset);
  const url = assetUrl(manifest, element.asset);
  if (!url || !asset) {
    return null;
  }
  const style: React.CSSProperties = {
    width: "100%",
    height: "100%",
    objectFit: "contain",
  };
  const wrapper = { ...geometryToStyle(geometry), width: "100%", height: "100%" };

  // 透明 WebM / MOV 这类动态 Overlay 走视频通道
  if (VIDEO_EXT.test(asset.path)) {
    return (
      <div style={wrapper}>
        <OffthreadVideo src={url} muted transparent style={style} />
      </div>
    );
  }
  return (
    <div style={wrapper}>
      <Img src={url} style={style} />
    </div>
  );
};
