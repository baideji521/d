/**
 * 字幕。caption_style 决定表现形式，与 GUI 预览端一一对应。
 *
 * 注意 words 里的 start / end 是「绝对时间线秒数」，
 * 而组件内部拿到的 frame 是相对本 Sequence 的，所以要先加回 element.start。
 */

import React from "react";
import { useCurrentFrame, useVideoConfig } from "remotion";
import type { Geometry, TimelineElement, Word } from "../lib/timeline";
import { applyEasing, geometryToStyle } from "../lib/timeline";
import { splitTwoLines, textStyleToCss } from "../lib/textStyle";

type Props = {
  element: TimelineElement;
  geometry: Geometry;
};

export const CaptionLayer: React.FC<Props> = ({ element, geometry }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const localTime = frame / fps;
  const now = (element.start ?? 0) + localTime;
  const duration = Math.max(1e-6, element.duration ?? 1);
  const captionStyle = element.caption_style ?? "plain";
  const baseCss = textStyleToCss(element.style);
  const words = element.content?.words ?? [];

  // 入场动效：折进 geometry，避免和关键帧打架
  let scale = geometry.scale;
  let offsetY = 0;
  if (captionStyle === "pop") {
    const progress = Math.min(1, localTime / Math.min(0.25, duration));
    scale *= 0.7 + 0.3 * applyEasing(progress, "easeOut") + 0.12 * Math.sin(progress * Math.PI);
  } else if (captionStyle === "bounce") {
    const progress = Math.min(1, localTime / Math.min(0.4, duration));
    scale *= 0.85 + 0.15 * applyEasing(progress, "easeOut");
    offsetY = -(1 - progress) * 6 * Math.cos(progress * Math.PI * 2);
  }

  const wrapperStyle: React.CSSProperties = {
    ...geometryToStyle({ ...geometry, scale }),
    transformOrigin: "center center",
  };
  if (offsetY !== 0) {
    wrapperStyle.transform = `${wrapperStyle.transform} translateY(${offsetY}%)`;
  }

  // 整句类
  if (words.length === 0) {
    let text = element.content?.text ?? "";
    if (captionStyle === "char_by_char") {
      const shown = Math.max(0, Math.floor(text.length * Math.min(1, localTime / duration)));
      text = text.slice(0, shown);
    } else if (captionStyle === "two_line") {
      text = splitTwoLines(text);
    }
    if (!text) {
      return null;
    }
    return <div style={{ ...wrapperStyle, ...baseCss }}>{text}</div>;
  }

  // 逐词类
  const highlightColor = element.highlight?.color ?? "#FFE347";
  const highlightBackground = element.highlight?.backgroundColor ?? "";
  const highlightScale = element.highlight?.scale ?? 1;

  const visible: Word[] =
    captionStyle === "word_by_word"
      ? words.filter((word) => word.start <= now)
      : words;

  if (visible.length === 0) {
    return null;
  }

  const { backgroundColor, padding, borderRadius, ...inlineCss } = baseCss;

  return (
    <div
      style={{
        ...wrapperStyle,
        backgroundColor,
        padding,
        borderRadius,
        display: "flex",
        flexDirection: "row",
        alignItems: "baseline",
        justifyContent: "center",
        gap: "0.28em",
        whiteSpace: "nowrap",
      }}
    >
      {visible.map((word, index) => {
        const isCurrent = word.start <= now && now < word.end;
        const isPast = now >= word.end;
        let color = inlineCss.color;
        let wordScale = 1;
        let background: string | undefined;

        if (captionStyle === "highlight_current" && isCurrent) {
          color = highlightColor;
          wordScale = highlightScale;
          background = highlightBackground || undefined;
        } else if (captionStyle === "karaoke" && (isCurrent || isPast)) {
          color = highlightColor;
        }

        return (
          <span
            key={`${word.text}-${index}`}
            style={{
              ...inlineCss,
              color,
              backgroundColor: background,
              display: "inline-block",
              transform: wordScale === 1 ? undefined : `scale(${wordScale})`,
              transformOrigin: "center bottom",
            }}
          >
            {word.text}
          </span>
        );
      })}
    </div>
  );
};
