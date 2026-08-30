/**
 * TransitionRendererRegistry 与各转场 plan 的单元测试。
 *
 * 运行：
 *   node --test src/transitions/registry.test.ts
 *
 * transitions/ 整条依赖链刻意保持纯 .ts（renderer 返回层描述而不是 JSX），
 * 所以 Node 的原生类型剥离能直接加载注册表来断言。
 */

import assert from "node:assert/strict";
import { test } from "node:test";
import type { TimelineElement } from "../lib/timeline.ts";
import { isCoveredByTransition } from "../lib/timeline.ts";
import { TransitionRendererRegistry, transitionRenderers } from "./index.ts";
import type { SideLayer, TransitionLayerSpec, VeilLayer } from "./types.ts";
import { makeTransitionContext } from "./types.ts";
import { wipeClip } from "./wipe.ts";
import { glitchBandClip } from "./glitch.ts";

/** Demo 里真实存在的那条转场：clip_001 → clip_002，5.75 → 6.25。 */
const demoTransition: TimelineElement = {
  id: "transition_001",
  type: "transition",
  track: "V1",
  name: "whip",
  from: "clip_001",
  to: "clip_002",
  start: 5.75,
  duration: 0.5,
  params: { direction: "left", intensity: 0.8, blur: 0.6 },
};

const transition = (
  name: string,
  params: Record<string, unknown> = {},
  extra: Partial<TimelineElement> = {},
): TimelineElement => ({
  id: `tr_${name}`,
  type: "transition",
  name,
  from: "clip_001",
  to: "clip_002",
  start: 5.75,
  duration: 0.5,
  params,
  ...extra,
});

const sides = (layers: TransitionLayerSpec[]): SideLayer[] =>
  layers.filter((l): l is SideLayer => l.kind === "side");

const veils = (layers: TransitionLayerSpec[]): VeilLayer[] =>
  layers.filter((l): l is VeilLayer => l.kind === "veil");

const ALL_NAMES = [
  "fade",
  "crossfade",
  "flash",
  "whip",
  "zoom",
  "wipe",
  "slide",
  "push",
  "spin",
  "blur",
  "glitch",
];

// ---------------------------------------------------------------- 注册表本体

test("registry 的 register / get / has / unregister", () => {
  const registry = new TransitionRendererRegistry();
  assert.equal(registry.has("noop"), false);
  registry.register({ name: "noop", render: () => [] });
  assert.equal(registry.has("noop"), true);
  assert.ok(registry.get("noop"));
  assert.equal(registry.unregister("noop"), true);
  assert.equal(registry.unregister("noop"), false);
});

test("没有 name 的条目不会被注册", () => {
  const registry = new TransitionRendererRegistry();
  registry.register({ name: "", render: () => [] });
  assert.deepEqual(registry.names(), []);
});

test("registry 解析出全部 11 个已实现转场", () => {
  assert.equal(transitionRenderers.all().length, 11);
});

test("已注册的名字必须与 Python TransitionDefinition.renderer 一致", () => {
  // 这份名单就是 libraries/transition_library.py 的 BUILTIN_TRANSITIONS。
  // 任何一侧改名，这条测试必须同时改，否则 name 对不上就会静默退回 crossfade。
  assert.deepEqual([...transitionRenderers.names()].sort(), [...ALL_NAMES].sort());
});

test("每个已知转场都能 resolve 到自己", () => {
  for (const name of ALL_NAMES) {
    assert.equal(transitionRenderers.resolve(name)?.name, name, name);
  }
});

test("未知转场 get 返回 undefined，但 resolve 退回 crossfade", () => {
  assert.equal(transitionRenderers.get("super_wipe"), undefined);
  assert.equal(transitionRenderers.has("super_wipe"), false);
  assert.equal(transitionRenderers.resolve("super_wipe")?.name, "crossfade");
  assert.equal(transitionRenderers.resolve(undefined)?.name, "crossfade");
});

test("兜底 renderer 不允许被摘掉，否则未知转场就是黑帧", () => {
  assert.equal(transitionRenderers.fallback, "crossfade");
  assert.equal(transitionRenderers.unregister("crossfade"), false);
  assert.ok(transitionRenderers.has("crossfade"));
});

// ---------------------------------------------------------------- 时间语义

test("progress 在窗口两端与中点的取值", () => {
  assert.equal(makeTransitionContext(demoTransition, 5.75, 30).progress, 0);
  assert.equal(makeTransitionContext(demoTransition, 6.0, 30).progress, 0.5);
  assert.equal(makeTransitionContext(demoTransition, 6.25, 30).progress, 1);
});

test("5.75 / 6.25 这种浮点边界不会溢出 0..1", () => {
  for (const now of [5.749999, 5.75, 5.750001, 6.249999, 6.25, 6.250001]) {
    const { progress } = makeTransitionContext(demoTransition, now, 30);
    assert.ok(progress >= 0 && progress <= 1, `${now} → ${progress}`);
  }
  assert.equal(makeTransitionContext(demoTransition, 5.749999, 30).progress, 0);
  assert.equal(makeTransitionContext(demoTransition, 6.250001, 30).progress, 1);
});

test("localTime 是相对转场起点的秒数", () => {
  const ctx = makeTransitionContext(demoTransition, 6.0, 30);
  assert.ok(Math.abs(ctx.localTime - 0.25) < 1e-9);
  assert.equal(ctx.duration, 0.5);
  assert.equal(ctx.fps, 30);
});

test("duration = 0 不会除零", () => {
  const ctx = makeTransitionContext(transition("fade", {}, { duration: 0 }), 5.75, 30);
  assert.ok(Number.isFinite(ctx.progress));
  assert.ok(ctx.duration > 0);
});

test("duration 为负数时被兜成极小正数，progress 仍在 0..1", () => {
  const ctx = makeTransitionContext(transition("fade", {}, { duration: -1 }), 6.0, 30);
  assert.ok(Number.isFinite(ctx.progress));
  assert.ok(ctx.progress >= 0 && ctx.progress <= 1);
});

test("start 为负数时不影响 progress 的夹取", () => {
  const ctx = makeTransitionContext(
    transition("fade", {}, { start: -2, duration: 1 }),
    0,
    30,
  );
  assert.equal(ctx.progress, 1);
});

test("easing 缺省是 linear，params.easing 会被采用", () => {
  assert.equal(makeTransitionContext(transition("crossfade"), 6.0, 30).eased, 0.5);
  const eased = makeTransitionContext(
    transition("crossfade", { easing: "easeIn" }),
    6.0,
    30,
  ).eased;
  assert.equal(eased, 0.25);
});

// ---------------------------------------------------------------- 黑帧

test("每个转场在任意进度上都有可见内容（黑帧防线）", () => {
  for (const name of ALL_NAMES) {
    const entry = transitionRenderers.get(name);
    assert.ok(entry, name);
    for (let step = 0; step <= 20; step += 1) {
      const now = 5.75 + (0.5 * step) / 20;
      // 显式标注：assert.ok 是断言函数，同一作用域里的推断变量会被 TS7022 判为循环
      const layers: TransitionLayerSpec[] = entry.render(
        makeTransitionContext(transition(name), now, 30),
      );
      assert.ok(layers.length > 0, `${name} @ ${now} 没有任何层`);
      const visibleSide = sides(layers).some((l) => l.alpha > 0);
      const opaqueVeil = veils(layers).some((l) => l.opacity > 0.99);
      assert.ok(
        visibleSide || opaqueVeil,
        `${name} @ ${now} 既没有可见画面也没有中间色`,
      );
    }
  }
});

test("窗口外的片段不被转场接管（阶段 2 P0-1 回归）", () => {
  const clip: TimelineElement = { id: "clip_001", type: "video" };
  const list = [demoTransition];
  assert.equal(isCoveredByTransition(clip, list, 0), false);
  assert.equal(isCoveredByTransition(clip, list, 5.74), false);
  assert.equal(isCoveredByTransition(clip, list, 5.75), true);
  assert.equal(isCoveredByTransition(clip, list, 6.24), true);
  assert.equal(isCoveredByTransition(clip, list, 6.25), false);
  assert.equal(isCoveredByTransition(clip, list, 10), false);
});

test("与转场无关的片段永远不让位", () => {
  const other: TimelineElement = { id: "clip_009", type: "video" };
  assert.equal(isCoveredByTransition(other, [demoTransition], 6.0), false);
});

// ---------------------------------------------------------------- 各转场 plan

test("crossfade：两侧 alpha 互补，恒等于 1", () => {
  const entry = transitionRenderers.get("crossfade");
  assert.ok(entry);
  for (const now of [5.75, 6.0, 6.25]) {
    const layers = sides(entry.render(makeTransitionContext(transition("crossfade"), now, 30)));
    assert.equal(layers.length, 2);
    assert.ok(Math.abs(layers[0].alpha + layers[1].alpha - 1) < 1e-9);
  }
});

test("fade：前半段只画 from，后半段只画 to，中间色最浓", () => {
  const entry = transitionRenderers.get("fade");
  assert.ok(entry);
  const early = entry.render(makeTransitionContext(transition("fade"), 5.8, 30));
  assert.deepEqual(sides(early).map((l) => l.role), ["from"]);
  const late = entry.render(makeTransitionContext(transition("fade"), 6.2, 30));
  assert.deepEqual(sides(late).map((l) => l.role), ["to"]);
  const middle = entry.render(makeTransitionContext(transition("fade"), 6.0, 30));
  assert.equal(veils(middle)[0].opacity, 1);
  assert.equal(veils(middle)[0].color, "#000000");
  // 两端中间色必须完全透明，否则窗口边界会闪一下
  assert.equal(veils(entry.render(makeTransitionContext(transition("fade"), 5.75, 30)))[0].opacity, 0);
  assert.equal(veils(entry.render(makeTransitionContext(transition("fade"), 6.25, 30)))[0].opacity, 0);
});

test("flash 与 fade 同算法，只差默认中间色", () => {
  const entry = transitionRenderers.get("flash");
  assert.ok(entry);
  const layers = entry.render(makeTransitionContext(transition("flash"), 6.0, 30));
  assert.equal(veils(layers)[0].color, "#FFFFFF");
  const custom = entry.render(
    makeTransitionContext(transition("flash", { color: "#FF0000", intensity: 0.5 }), 6.0, 30),
  );
  assert.equal(veils(custom)[0].color, "#FF0000");
  assert.equal(veils(custom)[0].opacity, 0.5);
});

test("whip：两侧位移方向相反，direction 决定符号", () => {
  const entry = transitionRenderers.get("whip");
  assert.ok(entry);
  const layers = sides(
    entry.render(makeTransitionContext(transition("whip", { direction: "right" }), 6.0, 30)),
  );
  assert.ok((layers[0].offset ?? [0, 0])[0] > 0);
  assert.ok((layers[1].offset ?? [0, 0])[0] < 0);
});

test("whip：未知 direction 退回 left，不抛错", () => {
  const entry = transitionRenderers.get("whip");
  assert.ok(entry);
  const layers = sides(
    entry.render(makeTransitionContext(transition("whip", { direction: "斜着" }), 6.0, 30)),
  );
  assert.ok((layers[0].offset ?? [0, 0])[0] < 0);
});

test("slide 旧片段不动，push 旧片段被推走", () => {
  const slideEntry = transitionRenderers.get("slide");
  const pushEntry = transitionRenderers.get("push");
  assert.ok(slideEntry && pushEntry);
  const slideLayers = sides(
    slideEntry.render(makeTransitionContext(transition("slide"), 6.0, 30)),
  );
  const pushLayers = sides(pushEntry.render(makeTransitionContext(transition("push"), 6.0, 30)));
  assert.deepEqual(slideLayers[0].offset, [0, 0]);
  assert.notDeepEqual(pushLayers[0].offset, [0, 0]);
  // 两者的新片段位移一致
  assert.deepEqual(slideLayers[1].offset, pushLayers[1].offset);
});

test("slide / push 两侧都不透明，不会出现叠影", () => {
  for (const name of ["slide", "push"]) {
    const entry = transitionRenderers.get(name);
    assert.ok(entry);
    for (const layer of sides(entry.render(makeTransitionContext(transition(name), 6.0, 30)))) {
      assert.equal(layer.alpha, 1, name);
    }
  }
});

test("zoom：from 推进、to 拉出，终点回到 1 倍", () => {
  const entry = transitionRenderers.get("zoom");
  assert.ok(entry);
  const end = sides(entry.render(makeTransitionContext(transition("zoom", { scale: 2 }), 6.25, 30)));
  assert.equal(end[0].scale, 2);
  assert.equal(end[1].scale, 1);
  const begin = sides(
    entry.render(makeTransitionContext(transition("zoom", { scale: 2 }), 5.75, 30)),
  );
  assert.equal(begin[0].scale, 1);
  assert.equal(begin[1].scale, 2);
});

test("spin：两侧旋转方向相反，终点归零", () => {
  const entry = transitionRenderers.get("spin");
  assert.ok(entry);
  const layers = sides(
    entry.render(makeTransitionContext(transition("spin", { angle: 90 }), 6.0, 30)),
  );
  assert.equal(layers[0].rotation, 45);
  assert.equal(layers[1].rotation, -45);
  const end = sides(entry.render(makeTransitionContext(transition("spin", { angle: 90 }), 6.25, 30)));
  // -angle * (1 - 1) 得到 -0，用绝对值断言避免 -0 !== 0
  assert.ok(Math.abs(end[1].rotation ?? 0) < 1e-9);
});

test("blur：两端模糊为 0，中点最大", () => {
  const entry = transitionRenderers.get("blur");
  assert.ok(entry);
  const at = (now: number) =>
    sides(entry.render(makeTransitionContext(transition("blur", { amount: 30 }), now, 30)));
  assert.equal(at(5.75)[0].blur, 0);
  assert.equal(at(6.0)[0].blur, 30);
  assert.equal(at(6.25)[0].blur, 0);
});

test("wipe：clip 随进度揭开，方向影响 inset 的边", () => {
  assert.equal(wipeClip([-1, 0], 0), "inset(0 100% 0 0)");
  assert.equal(wipeClip([-1, 0], 100), "inset(0 0% 0 0)");
  assert.equal(wipeClip([1, 0], 25), "inset(0 0 0 75%)");
  assert.equal(wipeClip([0, -1], 25), "inset(0 0 75% 0)");
  assert.equal(wipeClip([0, 1], 25), "inset(75% 0 0 0)");
});

test("wipe：from 恒不透明，to 带 clip", () => {
  const entry = transitionRenderers.get("wipe");
  assert.ok(entry);
  const layers = sides(entry.render(makeTransitionContext(transition("wipe"), 6.0, 30)));
  assert.equal(layers[0].alpha, 1);
  assert.equal(layers[0].clip, undefined);
  assert.equal(layers[1].alpha, 1);
  assert.ok(layers[1].clip);
});

test("glitch：条带数随进度增加，起点只有 from", () => {
  const entry = transitionRenderers.get("glitch");
  assert.ok(entry);
  const at = (now: number) =>
    entry.render(makeTransitionContext(transition("glitch", { slices: 10 }), now, 30));
  const begin = sides(at(5.75));
  assert.deepEqual(begin.map((l) => l.role), ["from", "to"]);
  const end = sides(at(6.25));
  assert.equal(end.length, 11); // 1 个 from + 10 条 to
  assert.ok(sides(at(6.0)).length < end.length);
});

test("glitch：同一进度的条带 clip 是确定的，渲染可复现", () => {
  const first = glitchBandClip(3, 10, 0.7);
  const second = glitchBandClip(3, 10, 0.7);
  assert.equal(first, second);
});

test("glitch：每条 to 层的 key 唯一", () => {
  const entry = transitionRenderers.get("glitch");
  assert.ok(entry);
  const layers = entry.render(makeTransitionContext(transition("glitch", { slices: 8 }), 6.25, 30));
  const keys = layers.map((l) => l.key);
  assert.equal(new Set(keys).size, keys.length);
});

// ---------------------------------------------------------------- 脏参数

test("参数类型不对时退回默认值，不抛错", () => {
  for (const name of ALL_NAMES) {
    const entry = transitionRenderers.get(name);
    assert.ok(entry, name);
    const dirty = {
      direction: 42,
      intensity: "很强",
      blur: null,
      scale: [1, 2],
      angle: {},
      amount: "多",
      slices: "十四",
      color: 0,
    };
    const layers = entry.render(makeTransitionContext(transition(name, dirty), 6.0, 30));
    assert.ok(layers.length > 0, name);
    for (const layer of sides(layers)) {
      assert.ok(Number.isFinite(layer.alpha), `${name}.alpha`);
      assert.ok(Number.isFinite(layer.scale ?? 1), `${name}.scale`);
      assert.ok(Number.isFinite(layer.blur ?? 0), `${name}.blur`);
      assert.ok(Number.isFinite(layer.rotation ?? 0), `${name}.rotation`);
    }
  }
});

test("每个 plan 的 side.role 只能是 from / to", () => {
  for (const name of ALL_NAMES) {
    const entry = transitionRenderers.get(name);
    assert.ok(entry, name);
    for (const layer of sides(entry.render(makeTransitionContext(transition(name), 6.0, 30)))) {
      assert.ok(layer.role === "from" || layer.role === "to", name);
    }
  }
});
