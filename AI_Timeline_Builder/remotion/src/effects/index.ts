/**
 * Effect Renderer 的装配点。
 *
 * 加一个新特效只需要两步：
 * 1. Python 侧 libraries/effect_library.py 里加定义（含 renderer 名）
 * 2. 这里加一个文件并注册进来
 *
 * TimelineModel / Validator / Property Panel / TimelineVideo 都不需要动。
 */

import { EffectRendererRegistry } from "./registry.ts";
import { blur } from "./blur.ts";
import { bounce } from "./bounce.ts";
import { brightness } from "./brightness.ts";
import { contrast } from "./contrast.ts";
import { flash } from "./flash.ts";
import { glitch } from "./glitch.ts";
import { motionBlur } from "./motionBlur.ts";
import { pulse } from "./pulse.ts";
import { rgbSplit } from "./rgbSplit.ts";
import { saturation } from "./saturation.ts";
import { shake } from "./shake.ts";
import { spin } from "./spin.ts";
import { vignette } from "./vignette.ts";
import { zoom } from "./zoom.ts";

/** 全局注册表。名字必须与 Python EffectDefinition.renderer 一致。 */
export const effectRenderers = new EffectRendererRegistry().registerAll([
  // geometry
  zoom,
  shake,
  spin,
  bounce,
  pulse,
  // visual（同样折叠进 geometry，只是改的是滤镜通道）
  blur,
  motionBlur,
  brightness,
  contrast,
  saturation,
  // screen
  flash,
  vignette,
  rgbSplit,
  glitch,
]);

export { EffectRendererRegistry } from "./registry.ts";
export * from "./types.ts";
