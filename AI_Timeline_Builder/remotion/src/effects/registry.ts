/**
 * EffectRendererRegistry：Remotion 侧按 effect.name 查 renderer。
 *
 * 与 Python EffectRegistry 的关系（第十三条）：
 *
 *     Python EffectRegistry.renderer  ──name──▶  Timeline JSON.name  ──name──▶  这里
 *
 * Python 不执行 TS，这里也不读 Python 的定义文件。唯一的契约就是名字。
 * 名字对不上的后果必须是「什么都不渲染」，不能是崩溃（第二十二条）。
 */

import type {
  EffectEntry,
  GeometryEffectEntry,
  ScreenEffectEntry,
} from "./types.ts";

export class EffectRendererRegistry {
  private entries = new Map<string, EffectEntry>();

  register(entry: EffectEntry): this {
    if (entry.name) {
      this.entries.set(entry.name, entry);
    }
    return this;
  }

  registerAll(entries: EffectEntry[]): this {
    for (const entry of entries) {
      this.register(entry);
    }
    return this;
  }

  unregister(name: string): boolean {
    return this.entries.delete(name);
  }

  /** 未注册返回 undefined —— 调用方据此跳过，不要抛错。 */
  get(name?: string): EffectEntry | undefined {
    return name ? this.entries.get(name) : undefined;
  }

  has(name?: string): boolean {
    return Boolean(name) && this.entries.has(name as string);
  }

  all(): EffectEntry[] {
    return [...this.entries.values()];
  }

  names(): string[] {
    return [...this.entries.keys()];
  }

  geometry(name?: string): GeometryEffectEntry | undefined {
    const entry = this.get(name);
    return entry && entry.kind === "geometry" ? entry : undefined;
  }

  screen(name?: string): ScreenEffectEntry | undefined {
    const entry = this.get(name);
    return entry && entry.kind === "screen" ? entry : undefined;
  }

  kindOf(name?: string): "geometry" | "screen" | "unknown" {
    return this.get(name)?.kind ?? "unknown";
  }
}
