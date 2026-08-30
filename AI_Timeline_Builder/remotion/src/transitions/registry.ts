/**
 * TransitionRendererRegistry：Remotion 侧按 transition.name 查 renderer。
 *
 *   Python TransitionDefinition.renderer ──name──▶ Timeline JSON.name ──name──▶ 这里
 *
 * Python 不执行 TS，这里也不读 Python 的定义文件。唯一的契约就是名字。
 *
 * 未知名字的处理与 Effect **不同**，这一点很重要：
 * 特效查不到可以什么都不画（画面还是好的），
 * 但转场窗口内两个片段都已经让位给 TransitionLayer（isCoveredByTransition），
 * 这里什么都不画就是**黑帧**。所以 resolve() 必须有兜底 renderer。
 * 拦截未知转场是 Validator 的职责（RULE_TRANSITION_004），不是渲染期的。
 */

import type { TransitionEntry } from "./types.ts";

export class TransitionRendererRegistry {
  private entries = new Map<string, TransitionEntry>();
  private fallbackName = "";

  register(entry: TransitionEntry): this {
    if (entry.name) {
      this.entries.set(entry.name, entry);
    }
    return this;
  }

  registerAll(entries: TransitionEntry[]): this {
    for (const entry of entries) {
      this.register(entry);
    }
    return this;
  }

  unregister(name: string): boolean {
    if (name === this.fallbackName) {
      // 兜底 renderer 一旦被摘掉，未知转场就会变黑帧，不允许
      return false;
    }
    return this.entries.delete(name);
  }

  /** 指定兜底 renderer。必须已经注册过。 */
  setFallback(name: string): this {
    if (this.entries.has(name)) {
      this.fallbackName = name;
    }
    return this;
  }

  get fallback(): string {
    return this.fallbackName;
  }

  /** 严格查表：未注册返回 undefined。 */
  get(name?: string): TransitionEntry | undefined {
    return name ? this.entries.get(name) : undefined;
  }

  has(name?: string): boolean {
    return Boolean(name) && this.entries.has(name as string);
  }

  /** 渲染用查表：查不到就退回兜底 renderer，永不返回 undefined（除非表是空的）。 */
  resolve(name?: string): TransitionEntry | undefined {
    return this.get(name) ?? this.entries.get(this.fallbackName);
  }

  all(): TransitionEntry[] {
    return [...this.entries.values()];
  }

  names(): string[] {
    return [...this.entries.keys()];
  }
}
