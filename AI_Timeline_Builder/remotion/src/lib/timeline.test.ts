/**
 * lib/timeline.ts 的单元测试。
 *
 * 运行：
 *   node --test src/lib/timeline.test.ts
 * （Node 24 原生支持 .ts 类型剥离，不需要额外的测试框架）
 */

import assert from "node:assert/strict";
import { test } from "node:test";
import type { Timeline, TimelineElement } from "./timeline.ts";
import {
  applyEasing,
  baseGeometry,
  evaluateKeyframes,
  isCoveredByTransition,
  masterVolume,
  resolveValue,
  resolveVolume,
  timelineDuration,
  toDurationFrames,
  toFrames,
  trackZIndex,
  transitionsFor,
} from "./timeline.ts";

const clipA: TimelineElement = {
  id: "clip_001",
  type: "video",
  track: "V1",
  start: 0,
  duration: 6.25,
  asset: "video_001",
  source: { start: 0, end: 6.25 },
};

const clipB: TimelineElement = {
  id: "clip_002",
  type: "video",
  track: "V1",
  start: 5.75,
  duration: 6,
  asset: "video_002",
  source: { start: 0, end: 6 },
};

const whip: TimelineElement = {
  id: "transition_001",
  type: "transition",
  track: "V1",
  name: "whip",
  from: "clip_001",
  to: "clip_002",
  start: 5.75,
  duration: 0.5,
};

const other: TimelineElement = {
  id: "text_001",
  type: "text",
  track: "T2",
  start: 1,
  duration: 2,
};

test("秒→帧只有一种换算：四舍五入", () => {
  assert.equal(toFrames(0, 30), 0);
  assert.equal(toFrames(5.75, 30), 173);
  assert.equal(toFrames(0.5, 30), 15);
  assert.equal(toFrames(1 / 30, 30), 1);
});

test("时长换算至少 1 帧，避免 durationInFrames=0", () => {
  assert.equal(toDurationFrames(0, 30), 1);
  assert.equal(toDurationFrames(0.001, 30), 1);
  assert.equal(toDurationFrames(0.5, 30), 15);
});

test("transitionsFor 只认 from / to 引用", () => {
  assert.deepEqual(
    transitionsFor(clipA, [whip]).map((t) => t.id),
    ["transition_001"],
  );
  assert.deepEqual(
    transitionsFor(clipB, [whip]).map((t) => t.id),
    ["transition_001"],
  );
  assert.deepEqual(transitionsFor(other, [whip]), []);
});

test("参与转场的片段只在转场时间窗内让位（P0-1 回归）", () => {
  // 转场窗 [5.75, 6.25)
  assert.equal(isCoveredByTransition(clipA, [whip], 0), false, "开头必须自己渲染");
  assert.equal(isCoveredByTransition(clipA, [whip], 5.74), false, "转场前一刻仍要渲染");
  assert.equal(isCoveredByTransition(clipA, [whip], 5.75), true, "转场起点让位");
  assert.equal(isCoveredByTransition(clipA, [whip], 6.24), true, "转场内让位");
  assert.equal(isCoveredByTransition(clipA, [whip], 6.25), false, "转场结束立刻恢复");

  assert.equal(isCoveredByTransition(clipB, [whip], 6.25), false, "to 侧转场后自己渲染");
  assert.equal(isCoveredByTransition(clipB, [whip], 11), false, "to 侧尾部自己渲染");

  assert.equal(isCoveredByTransition(other, [whip], 5.9), false, "无关元素不受影响");
  assert.equal(isCoveredByTransition(clipA, [], 5.9), false, "没有转场时永不让位");
});

test("easing 四条曲线的端点与中点", () => {
  for (const easing of ["linear", "easeIn", "easeOut", "easeInOut"] as const) {
    assert.equal(applyEasing(0, easing), 0, `${easing} 起点`);
    assert.equal(applyEasing(1, easing), 1, `${easing} 终点`);
  }
  assert.equal(applyEasing(0.5, "linear"), 0.5);
  assert.equal(applyEasing(0.5, "easeIn"), 0.25);
  assert.equal(applyEasing(0.5, "easeOut"), 0.75);
  assert.equal(applyEasing(0.5, "easeInOut"), 0.5);
  // 越界要夹紧
  assert.equal(applyEasing(-1, "linear"), 0);
  assert.equal(applyEasing(2, "linear"), 1);
});

test("关键帧：区间外端点保持，区间内按后一个关键帧的 easing 插值", () => {
  const kfs = [
    { time: 0, value: 1 },
    { time: 0.3, value: 1.35, easing: "linear" as const },
    { time: 0.6, value: 1, easing: "linear" as const },
  ];
  assert.equal(evaluateKeyframes(kfs, -1, 0), 1, "起点前保持首值");
  assert.equal(evaluateKeyframes(kfs, 0, 0), 1);
  assert.equal(Math.abs(evaluateKeyframes(kfs, 0.15, 0) - 1.175) < 1e-9, true, "中点线性插值");
  assert.equal(evaluateKeyframes(kfs, 0.3, 0), 1.35);
  assert.equal(evaluateKeyframes(kfs, 9, 0), 1, "终点后保持末值");
  assert.equal(evaluateKeyframes([], 0.5, 0.42), 0.42, "无关键帧时用 fallback");
});

test("resolveValue：关键帧优先，其次 transform，最后中性值", () => {
  const withTransform: TimelineElement = {
    id: "e",
    type: "overlay",
    transform: { scale: 2, opacity: 0.5 },
  };
  assert.equal(resolveValue(withTransform, "scale", 0), 2, "取 transform");
  assert.equal(resolveValue(withTransform, "rotation", 0), 0, "中性值 rotation=0");
  assert.equal(resolveValue({ id: "e", type: "overlay" }, "scale", 0), 1, "中性值 scale=1");
  assert.equal(resolveValue({ id: "e", type: "overlay" }, "x", 0), 0.5, "中性值 x=0.5");

  const animated: TimelineElement = {
    id: "e",
    type: "overlay",
    transform: { scale: 2 },
    keyframes: { scale: [{ time: 0, value: 1 }, { time: 1, value: 3 }] },
  };
  assert.equal(resolveValue(animated, "scale", 0.5), 2, "关键帧覆盖 transform");
  assert.equal(resolveValue(animated, "scale", 0), 1);
});

// ---------------------------------------------------------------- 稀疏 JSON
//
// 阶段 6.5：JSON 只保存显式编辑意图，transform / speed / audio / keyframes
// 缺省是常态。Runtime 必须在字段不存在时用默认值，而不是崩或者画错。

test("稀疏元素（没有 transform / keyframes）几何求值等于全默认元素", () => {
  const sparseClip: TimelineElement = {
    id: "clip_001",
    type: "video",
    track: "V1",
    asset: "video_003",
    start: 0,
    duration: 285.1,
  };
  const fullClip: TimelineElement = {
    ...sparseClip,
    transform: { x: 0.5, y: 0.5, scale: 1, rotation: 0, opacity: 1 },
    speed: 1,
    audio: { enabled: true, volume: 1 },
    keyframes: {},
  };
  assert.deepEqual(baseGeometry(sparseClip, 0), baseGeometry(fullClip, 0));
  assert.deepEqual(baseGeometry(sparseClip, 12.5), baseGeometry(fullClip, 12.5));
});

test("只写了一个分量的 transform，其余分量取默认值", () => {
  const clip: TimelineElement = {
    id: "clip_001",
    type: "video",
    transform: { scale: 1.2 },
  };
  const geometry = baseGeometry(clip, 0);
  assert.equal(geometry.scale, 1.2, "显式值生效");
  assert.equal(geometry.x, 0.5);
  assert.equal(geometry.y, 0.5);
  assert.equal(geometry.rotation, 0);
  assert.equal(geometry.opacity, 1);
});

test("显式的 0 值不会被当成缺省", () => {
  const clip: TimelineElement = {
    id: "clip_001",
    type: "video",
    transform: { opacity: 0, x: 0 },
  };
  const geometry = baseGeometry(clip, 0);
  assert.equal(geometry.opacity, 0, "opacity=0 是合法显式值");
  assert.equal(geometry.x, 0);
});

test("缺省字段读出来就是 Runtime 默认值", () => {
  const clip: TimelineElement = { id: "clip_001", type: "video" };
  assert.equal(clip.speed ?? 1, 1);
  assert.equal((clip.audio ?? {}).enabled === false, false, "默认不静音");
  assert.equal((clip.audio ?? {}).volume ?? 1, 1);
  assert.equal(clip.volume ?? 1, 1);
  assert.deepEqual(clip.params ?? {}, {});
});

test("稀疏时间线：只有一条活跃轨道也能算 zIndex 与总时长", () => {
  const minimal: Timeline = {
    version: 1,
    time_unit: "seconds",
    meta: { name: "极简", fps: 30, width: 1080, height: 1920 },
    tracks: [{ id: "V1", name: "V1 主视频", kind: "video" }],
    elements: [{ id: "clip_001", type: "video", track: "V1", start: 0, duration: 285.1 }],
  };
  assert.equal(timelineDuration(minimal), 285.1);
  assert.equal(trackZIndex(minimal, "V1"), 0);
  assert.equal(trackZIndex(minimal, "T1"), 0, "不存在的轨道退回 0，不抛异常");
});

const timeline: Timeline = {
  version: 1,
  time_unit: "seconds",
  meta: { name: "T", fps: 30, width: 1080, height: 1920 },
  tracks: [
    { id: "A1", name: "A1", kind: "audio" },
    { id: "V1", name: "V1", kind: "video" },
    { id: "T2", name: "T2", kind: "text" },
  ],
  elements: [clipA, clipB, whip, other],
};

test("总时长 = 所有元素结束时间的最大值", () => {
  assert.equal(timelineDuration(timeline), 11.75);
});

test("轨道顺序决定 zIndex，越靠后越上层", () => {
  assert.equal(trackZIndex(timeline, "A1"), 0);
  assert.equal(trackZIndex(timeline, "V1"), 10);
  assert.equal(trackZIndex(timeline, "T2"), 20);
  assert.equal(trackZIndex(timeline, "不存在"), 0);
});

// 全局输出音量（meta.master_volume）：稀疏 JSON 里通常没有这个字段，
// 缺省必须等于 1，否则老工程一导出就变了音量。

test("没有 master_volume 时全局音量是 1", () => {
  assert.equal(masterVolume(timeline), 1);
});

test("master_volume 生效并夹在 0..4", () => {
  const withVolume = { ...timeline, meta: { ...timeline.meta, master_volume: 0.35 } };
  assert.equal(masterVolume(withVolume), 0.35);
  assert.equal(masterVolume({ ...timeline, meta: { ...timeline.meta, master_volume: -2 } }), 0);
  assert.equal(masterVolume({ ...timeline, meta: { ...timeline.meta, master_volume: 99 } }), 4);
});

test("master_volume 是脏数据时退回 1", () => {
  const dirty = { ...timeline, meta: { ...timeline.meta, master_volume: Number.NaN } };
  assert.equal(masterVolume(dirty), 1);
});

test("元素音量与全局音量相乘", () => {
  assert.equal(resolveVolume(0.8, 0.5), 0.4);
  assert.equal(resolveVolume(1, 1), 1);
  assert.equal(resolveVolume(0.8, 0), 0, "全局静音时任何元素都静音");
  assert.equal(resolveVolume(-1, 1), 0, "负音量按 0 处理，不出现反相");
});

