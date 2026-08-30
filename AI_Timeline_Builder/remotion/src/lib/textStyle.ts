/**
 * 文字样式 → CSS。Text 与 Caption 共用，保证两者外观参数含义一致。
 * 描边用 -webkit-text-stroke 加 paint-order，这样描边不会盖住字面。
 */

import type React from "react";
import type { TextStyle } from "./timeline";

export const textStyleToCss = (style: TextStyle = {}): React.CSSProperties => {
  const stroke = style.stroke ?? {};
  const shadow = style.shadow ?? {};
  const css: React.CSSProperties = {
    fontFamily: style.fontFamily ?? "Arial",
    fontSize: style.fontSize ?? 64,
    fontWeight: style.fontWeight ?? 700,
    color: style.color ?? "#FFFFFF",
    textAlign: style.align ?? "center",
    lineHeight: style.lineHeight ?? 1.2,
    letterSpacing: style.letterSpacing ? `${style.letterSpacing}px` : undefined,
    whiteSpace: "pre-wrap",
    margin: 0,
  };
  if (style.backgroundColor) {
    css.backgroundColor = style.backgroundColor;
    css.padding = "16px 32px";
    css.borderRadius = 12;
  }
  if (stroke.width && stroke.width > 0) {
    (css as Record<string, unknown>).WebkitTextStrokeWidth = `${stroke.width}px`;
    (css as Record<string, unknown>).WebkitTextStrokeColor = stroke.color ?? "#000000";
    (css as Record<string, unknown>).paintOrder = "stroke fill";
  }
  if (shadow.blur !== undefined || shadow.x !== undefined || shadow.y !== undefined) {
    css.textShadow = `${shadow.x ?? 0}px ${shadow.y ?? 0}px ${shadow.blur ?? 0}px ${
      shadow.color ?? "rgba(0,0,0,0.6)"
    }`;
  }
  return css;
};

/** 长句拆两行，与 Python 侧 _split_two_lines 规则一致。 */
export const splitTwoLines = (text: string): string => {
  if (text.includes("\n") || text.length < 12) {
    return text;
  }
  const parts = text.split(" ");
  if (parts.length < 2) {
    const middle = Math.floor(text.length / 2);
    return `${text.slice(0, middle)}\n${text.slice(middle)}`;
  }
  const index = Math.floor(parts.length / 2);
  return `${parts.slice(0, index).join(" ")}\n${parts.slice(index).join(" ")}`;
};
