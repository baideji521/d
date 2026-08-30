/**
 * 普通文字 / 标题 / 强调文字。与 Caption 是两套独立组件。
 */

import React from "react";
import type { Geometry, TimelineElement } from "../lib/timeline";
import { geometryToStyle } from "../lib/timeline";
import { textStyleToCss } from "../lib/textStyle";

type Props = {
  element: TimelineElement;
  geometry: Geometry;
};

export const TextLayer: React.FC<Props> = ({ element, geometry }) => {
  const text = element.content?.text ?? "";
  if (!text) {
    return null;
  }
  return (
    <div
      style={{
        ...geometryToStyle(geometry),
        ...textStyleToCss(element.style),
        transformOrigin: "center center",
      }}
    >
      {text}
    </div>
  );
};
