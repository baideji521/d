/**
 * Transition Renderer 的装配点。
 *
 * 加一个新转场只需要两步：
 * 1. Python 侧 libraries/transition_library.py 里加定义（含 category）
 * 2. 这里加一个文件并注册进来
 *
 * TimelineModel / Validator / Property Panel / TimelineVideo / TransitionLayer
 * 都不需要动。
 */

import { TransitionRendererRegistry } from "./registry.ts";
import { blur } from "./blur.ts";
import { crossfade } from "./crossfade.ts";
import { fade } from "./fade.ts";
import { flash } from "./flash.ts";
import { glitch } from "./glitch.ts";
import { push, slide } from "./slide.ts";
import { spin } from "./spin.ts";
import { whip } from "./whip.ts";
import { wipe } from "./wipe.ts";
import { zoom } from "./zoom.ts";

/** 全局注册表。名字必须与 Python TransitionDefinition.renderer 一致。 */
export const transitionRenderers = new TransitionRendererRegistry()
  .registerAll([
    // basic
    fade,
    crossfade,
    // impact
    flash,
    whip,
    zoom,
    // geometric
    wipe,
    slide,
    push,
    // stylized
    spin,
    blur,
    glitch,
  ])
  // 未知转场退回 crossfade：转场窗口内两侧片段已让位，
  // 这里什么都不画就是黑帧。拦截未知名字是 Validator 的事。
  .setFallback("crossfade");

export { TransitionRendererRegistry } from "./registry.ts";
export * from "./types.ts";
