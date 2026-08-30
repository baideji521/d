/**
 * Timeline JSON 的类型定义与求值工具。
 *
 * 这里的语义必须与 Python 侧 core/timeline.py 完全一致，否则预览和成品会不一样：
 * - 时间单位一律是秒，帧只在本文件的 toFrames() 里出现
 * - x / y 是归一化的中心点坐标（0..1）
 * - 关键帧的 time 相对元素自身起点
 */

export type Easing = "linear" | "easeIn" | "easeOut" | "easeInOut";

export type Keyframe = {
  time: number;
  value: number;
  easing?: Easing;
};

export type Transform = {
  x?: number;
  y?: number;
  scale?: number;
  rotation?: number;
  opacity?: number;
};

export type TextStyle = {
  fontFamily?: string;
  fontSize?: number;
  fontWeight?: number;
  color?: string;
  backgroundColor?: string;
  align?: "left" | "center" | "right";
  lineHeight?: number;
  letterSpacing?: number;
  stroke?: { width?: number; color?: string };
  shadow?: { x?: number; y?: number; blur?: number; color?: string };
};

export type Word = { text: string; start: number; end: number };

export type ElementType =
  | "video"
  | "overlay"
  | "text"
  | "caption"
  | "caption_group"
  | "audio"
  | "effect"
  | "transition"
  | "freeze";

export type TimelineElement = {
  id: string;
  type: ElementType;
  track?: string;
  label?: string;
  start?: number;
  duration?: number;
  asset?: string;
  source?: { start: number; end: number };
  speed?: number;
  transform?: Transform;
  keyframes?: Record<string, Keyframe[]>;
  animation?: string;
  z_index?: number;
  audio?: { enabled?: boolean; volume?: number };
  volume?: number;
  fade?: { in?: number; out?: number };
  content?: { text?: string; words?: Word[] };
  style?: TextStyle;
  caption_style?: string;
  template?: string;
  highlight?: { color?: string; backgroundColor?: string; scale?: number };
  name?: string;
  target?: string;
  params?: Record<string, unknown>;
  easing?: Easing;
  from?: string;
  to?: string;
  source_time?: number;
  note?: string;
};

export type Track = {
  id: string;
  name: string;
  kind: "video" | "text" | "audio";
  locked?: boolean;
  hidden?: boolean;
};

export type Timeline = {
  version: number;
  time_unit: "seconds";
  meta: {
    name: string;
    fps: number;
    width: number;
    height: number;
    duration?: number;
    background?: string;
  };
  tracks: Track[];
  elements: TimelineElement[];
};

export type AssetEntry = {
  id: string;
  name?: string;
  type: string;
  path: string;
  duration?: number;
  width?: number;
  height?: number;
  fps?: number;
};

export type AssetManifest = {
  version: number;
  assets: AssetEntry[];
};

/** 秒 → 帧。与 Python 侧 seconds_to_frames 使用相同的四舍五入。 */
export const toFrames = (seconds: number, fps: number): number =>
  Math.round(seconds * fps);

/** 至少 1 帧，避免 durationInFrames=0 让 Remotion 报错。 */
export const toDurationFrames = (seconds: number, fps: number): number =>
  Math.max(1, toFrames(seconds, fps));

export const applyEasing = (t: number, easing: Easing = "linear"): number => {
  const clamped = Math.min(1, Math.max(0, t));
  switch (easing) {
    case "easeIn":
      return clamped * clamped;
    case "easeOut":
      return 1 - (1 - clamped) * (1 - clamped);
    case "easeInOut":
      return clamped < 0.5
        ? 2 * clamped * clamped
        : 1 - 2 * (1 - clamped) * (1 - clamped);
    default:
      return clamped;
  }
};

const NEUTRAL: Record<string, number> = {
  scale: 1,
  x: 0.5,
  y: 0.5,
  rotation: 0,
  opacity: 1,
  blur: 0,
  brightness: 1,
  contrast: 1,
  saturation: 1,
};

/** 在相对时间 localTime 求关键帧曲线的值，区间外做端点保持。 */
export const evaluateKeyframes = (
  keyframes: Keyframe[],
  localTime: number,
  fallback: number,
): number => {
  if (!keyframes || keyframes.length === 0) {
    return fallback;
  }
  const points = [...keyframes].sort((a, b) => a.time - b.time);
  if (localTime <= points[0].time) {
    return points[0].value;
  }
  const last = points[points.length - 1];
  if (localTime >= last.time) {
    return last.value;
  }
  for (let i = 0; i < points.length - 1; i += 1) {
    const a = points[i];
    const b = points[i + 1];
    if (localTime >= a.time && localTime <= b.time) {
      const span = b.time - a.time;
      const raw = span <= 0 ? 0 : (localTime - a.time) / span;
      const eased = applyEasing(raw, b.easing ?? "linear");
      return a.value + (b.value - a.value) * eased;
    }
  }
  return fallback;
};

/** 取某参数的最终值：关键帧优先，其次 transform，最后中性值。 */
export const resolveValue = (
  element: TimelineElement,
  param: string,
  localTime: number,
): number => {
  const neutral = NEUTRAL[param] ?? 0;
  const transform = element.transform ?? {};
  const base =
    param in transform
      ? Number((transform as Record<string, unknown>)[param])
      : neutral;
  const keyframes = element.keyframes?.[param];
  if (keyframes && keyframes.length > 0) {
    return evaluateKeyframes(keyframes, localTime, base);
  }
  return base;
};

export type Geometry = {
  x: number;
  y: number;
  scale: number;
  rotation: number;
  opacity: number;
  blur: number;
  brightness: number;
  saturation: number;
};

export const baseGeometry = (
  element: TimelineElement,
  localTime: number,
): Geometry => ({
  x: resolveValue(element, "x", localTime),
  y: resolveValue(element, "y", localTime),
  scale: resolveValue(element, "scale", localTime),
  rotation: resolveValue(element, "rotation", localTime),
  opacity: resolveValue(element, "opacity", localTime),
  blur: resolveValue(element, "blur", localTime),
  brightness: resolveValue(element, "brightness", localTime),
  saturation: resolveValue(element, "saturation", localTime),
});

/** 把 geometry 翻译成 CSS：定位靠 left/top + translate(-50%,-50%)。 */
export const geometryToStyle = (
  geometry: Geometry,
  extra?: React.CSSProperties,
): React.CSSProperties => {
  const filters: string[] = [];
  if (geometry.blur > 0.05) {
    filters.push(`blur(${geometry.blur.toFixed(2)}px)`);
  }
  if (Math.abs(geometry.brightness - 1) > 0.005) {
    filters.push(`brightness(${geometry.brightness.toFixed(3)})`);
  }
  if (Math.abs(geometry.saturation - 1) > 0.005) {
    filters.push(`saturate(${geometry.saturation.toFixed(3)})`);
  }
  return {
    position: "absolute",
    left: `${geometry.x * 100}%`,
    top: `${geometry.y * 100}%`,
    transform: `translate(-50%, -50%) scale(${geometry.scale}) rotate(${geometry.rotation}deg)`,
    opacity: geometry.opacity,
    filter: filters.length > 0 ? filters.join(" ") : undefined,
    ...extra,
  };
};

/** 轨道顺序决定默认 Z-Index，与 Python 侧 track_z_index 一致。 */
export const trackZIndex = (timeline: Timeline, trackId?: string): number => {
  const index = timeline.tracks.findIndex((t) => t.id === trackId);
  return index < 0 ? 0 : index * 10;
};

export const elementEnd = (element: TimelineElement): number =>
  (element.start ?? 0) + (element.duration ?? 0);

export const findElement = (
  timeline: Timeline,
  id?: string,
): TimelineElement | undefined =>
  id ? timeline.elements.find((e) => e.id === id) : undefined;

export const findTrack = (timeline: Timeline, id?: string): Track | undefined =>
  id ? timeline.tracks.find((t) => t.id === id) : undefined;

/** 时间线总时长（秒）。 */
export const timelineDuration = (timeline: Timeline): number =>
  timeline.elements.reduce((acc, element) => Math.max(acc, elementEnd(element)), 0);
