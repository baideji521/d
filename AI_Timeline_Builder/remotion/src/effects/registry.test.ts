/**
 * EffectRendererRegistry 的单元测试。
 *
 * 运行：
 *   node --test src/effects/registry.test.ts
 *
 * 注意：effects/index.ts 整条依赖链刻意保持纯 .ts（screen 特效用
 * React.createElement 而非 JSX），否则 Node 的原生类型剥离加载不了注册表。
 */

import assert from "node:assert/strict";
import { test } from "node:test";
import type { Geometry, TimelineElement } from "../lib/timeline.ts";
import { EffectRendererRegistry, effectRenderers } from "./index.ts";
import { makeEffectContext } from "./types.ts";
import {
  SCREEN_EFFECT_NAMES,
  applyGeometryEffect,
  foldEffects,
} from "./programEffects.ts";

const neutral = (): Geometry => ({
  x: 0.5,
  y: 0.5,
  scale: 1,
  rotation: 0,
  opacity: 1,
  blur: 0,
  brightness: 1,
  saturation: 1,
});

const effect = (
  name: string,
  params: Record<string, unknown> = {},
  extra: Partial<TimelineElement> = {},
): TimelineElement => ({
  id: `fx_${name}`,
  type: "effect",
  name,
  start: 10,
  duration: 1,
  easing: "linear",
  params,
  ...extra,
});

// ---------------------------------------------------------------- 注册表本体

test("registry 的 register / get / has / unregister", () => {
  const registry = new EffectRendererRegistry();
  assert.equal(registry.has("noop"), false);
  registry.register({ name: "noop", kind: "geometry", apply: (g) => g });
  assert.equal(registry.has("noop"), true);
  assert.equal(registry.get("noop")?.kind, "geometry");
  assert.equal(registry.unregister("noop"), true);
  assert.equal(registry.unregister("noop"), false);
  assert.equal(registry.get("noop"), undefined);
});

test("没有 name 的条目不会被注册", () => {
  const registry = new EffectRendererRegistry();
  registry.register({ name: "", kind: "geometry", apply: (g) => g });
  assert.deepEqual(registry.names(), []);
});

test("registry 解析出全部 14 个已实现特效", () => {
  assert.equal(effectRenderers.all().length, 14);
  const geometry = effectRenderers.all().filter((e) => e.kind === "geometry");
  const screen = effectRenderers.all().filter((e) => e.kind === "screen");
  assert.equal(geometry.length, 10);
  assert.equal(screen.length, 4);
});

test("已注册的名字必须与 Python EffectDefinition.renderer 一致", () => {
  // 这份名单就是 libraries/effect_library.py 的 _PROGRAM_META。
  // 任何一侧改名，这条测试必须同时改，否则 name 对不上就静默不渲染。
  const expected = [
    "zoom",
    "shake",
    "spin",
    "bounce",
    "pulse",
    "blur",
    "motion_blur",
    "brightness",
    "contrast",
    "saturation",
    "flash",
    "vignette",
    "rgb_split",
    "glitch",
  ];
  assert.deepEqual([...effectRenderers.names()].sort(), [...expected].sort());
});

test("kindOf 区分 geometry / screen / unknown", () => {
  assert.equal(effectRenderers.kindOf("zoom"), "geometry");
  assert.equal(effectRenderers.kindOf("flash"), "screen");
  assert.equal(effectRenderers.kindOf("super_magic_zoom"), "unknown");
  assert.equal(effectRenderers.kindOf(undefined), "unknown");
});

test("geometry() / screen() 不会串类", () => {
  assert.equal(effectRenderers.geometry("flash"), undefined);
  assert.equal(effectRenderers.screen("zoom"), undefined);
  assert.ok(effectRenderers.geometry("zoom"));
  assert.ok(effectRenderers.screen("flash"));
});

test("SCREEN_EFFECT_NAMES 从注册表推导，不再是手写名单", () => {
  assert.deepEqual([...SCREEN_EFFECT_NAMES].sort(), [
    "flash",
    "glitch",
    "rgb_split",
    "vignette",
  ]);
});

// ---------------------------------------------------------------- 未知特效

test("未知特效安全失败：geometry 原样返回，不抛错", () => {
  const before = neutral();
  const after = applyGeometryEffect(before, effect("super_magic_zoom"), 10.5, 30);
  assert.deepEqual(after, before);
});

test("未知特效不影响同批次里已知特效的折叠", () => {
  const geometry = foldEffects(
    neutral(),
    [
      effect("super_magic_zoom", {}, { target: "clip_001" }),
      effect("zoom", { scale_from: 1, scale_to: 2 }, { target: "clip_001" }),
    ],
    { id: "clip_001", type: "video" },
    10.5,
    30,
  );
  assert.equal(geometry.scale, 1.5);
});

// ---------------------------------------------------------------- 上下文

test("makeEffectContext 的 progress / eased / localTime", () => {
  const ctx = makeEffectContext(effect("zoom"), 10.25, 30);
  assert.equal(ctx.localTime, 0.25);
  assert.equal(ctx.progress, 0.25);
  assert.equal(ctx.eased, 0.25); // easing=linear
  assert.equal(ctx.duration, 1);
  assert.equal(ctx.fps, 30);
});

test("progress 被夹在 0..1，超出时长不会越界", () => {
  assert.equal(makeEffectContext(effect("zoom"), 9, 30).progress, 0);
  assert.equal(makeEffectContext(effect("zoom"), 99, 30).progress, 1);
});

test("duration 为 0 时不会除零", () => {
  const ctx = makeEffectContext(effect("zoom", {}, { duration: 0 }), 10, 30);
  assert.ok(Number.isFinite(ctx.progress));
});

// ---------------------------------------------------------------- 具体算法

test("zoom：中点 scale 取 from/to 的中值，并按 origin 补偿位移", () => {
  const g = applyGeometryEffect(
    neutral(),
    effect("zoom", { scale_from: 1, scale_to: 2, origin_x: 0, origin_y: 1 }),
    10.5,
    30,
  );
  assert.equal(g.scale, 1.5);
  assert.equal(g.x, 0.5 + 0.5 * 0.5);
  assert.equal(g.y, 0.5 - 0.5 * 0.5);
});

test("blur / brightness / saturation 折叠进对应通道", () => {
  assert.equal(
    applyGeometryEffect(neutral(), effect("blur", { radius_from: 0, radius_to: 10 }), 10.5, 30)
      .blur,
    5,
  );
  assert.equal(
    applyGeometryEffect(
      neutral(),
      effect("brightness", { value_from: 1, value_to: 2 }),
      10.5,
      30,
    ).brightness,
    1.5,
  );
  assert.equal(
    applyGeometryEffect(
      neutral(),
      effect("saturation", { value_from: 1, value_to: 0 }),
      10.5,
      30,
    ).saturation,
    0.5,
  );
});

test("contrast 走亮度近似：偏移量折半", () => {
  const g = applyGeometryEffect(
    neutral(),
    effect("contrast", { value_from: 1, value_to: 2 }),
    11,
    30,
  );
  assert.equal(g.brightness, 1.5);
});

test("参数类型不对时退回默认值，不抛错", () => {
  const g = applyGeometryEffect(
    neutral(),
    effect("zoom", { scale_from: "一倍", scale_to: null }),
    11,
    30,
  );
  assert.ok(Number.isFinite(g.scale));
});

test("renderer 不得就地修改传入的 geometry", () => {
  const before = neutral();
  applyGeometryEffect(before, effect("zoom", { scale_from: 1, scale_to: 3 }), 11, 30);
  assert.deepEqual(before, neutral());
});

test("glitch 在同一进度下结果确定，渲染可复现", () => {
  const entry = effectRenderers.screen("glitch");
  assert.ok(entry);
  const ctx = makeEffectContext(effect("glitch", { intensity: 0.6, slices: 8 }), 10.5, 30);
  const first = entry.Component({ ctx });
  const second = entry.Component({ ctx });
  assert.deepEqual(JSON.stringify(first), JSON.stringify(second));
});

test("强度为 0 的全屏特效什么都不渲染", () => {
  const entry = effectRenderers.screen("vignette");
  assert.ok(entry);
  const ctx = makeEffectContext(effect("vignette", { intensity: 0 }), 10.5, 30);
  assert.equal(entry.Component({ ctx }), null);
});

test("rgb_split 必须真的画东西，不能靠 backdrop-filter 空转", () => {
  // 阶段 6.5 回归：旧实现只设 backdropFilter: drop-shadow(...)，
  // 渲染出来与无特效基线逐像素完全相同（drop-shadow 被不透明 backdrop 全遮住）。
  const entry = effectRenderers.screen("rgb_split");
  assert.ok(entry);
  const ctx = makeEffectContext(effect("rgb_split", { offset: 8, angle: 0 }), 10.5, 30);
  const node = entry.Component({ ctx }) as {
    props: { children: { props: { style: Record<string, unknown> } }[] };
  } | null;
  assert.ok(node, "offset=8 必须渲染出内容");
  const layers = node.props.children.flat();
  assert.equal(layers.length, 2, "红 / 蓝两层都要在");
  const serialized = JSON.stringify(layers);
  assert.ok(!serialized.includes("backdropFilter"), "不许再依赖 backdrop-filter");
  for (const layer of layers) {
    const style = layer.props.style;
    assert.ok(String(style.backgroundColor).startsWith("rgba("), "必须自己画颜色");
    assert.equal(style.mixBlendMode, "screen");
    assert.ok(String(style.transform).startsWith("translate("), "必须有方向偏移");
  }
  // 两层偏移方向相反，否则不会出现色边
  assert.notEqual(
    layers[0].props.style.transform,
    layers[1].props.style.transform,
  );
});

test("rgb_split offset 低于 0.5 视为不生效", () => {
  const entry = effectRenderers.screen("rgb_split");
  assert.ok(entry);
  const ctx = makeEffectContext(effect("rgb_split", { offset: 0, angle: 0 }), 10.5, 30);
  assert.equal(entry.Component({ ctx }), null);
});

test("rgb_split 的 offset 越大色差越浓，但不超过上限", () => {
  const entry = effectRenderers.screen("rgb_split");
  assert.ok(entry);
  const alphaOf = (offset: number) => {
    const ctx = makeEffectContext(effect("rgb_split", { offset }), 10.5, 30);
    const node = entry.Component({ ctx }) as {
      props: { children: { props: { style: Record<string, unknown> } }[] };
    };
    const color = String(node.props.children.flat()[0].props.style.backgroundColor);
    return Number(color.slice(color.lastIndexOf(",") + 1, -1));
  };
  assert.ok(alphaOf(60) > alphaOf(8));
  assert.ok(alphaOf(60) <= 0.45);
});
