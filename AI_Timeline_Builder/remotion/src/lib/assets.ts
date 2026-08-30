/**
 * 素材解析：asset id → 可播放的 URL。
 *
 * Timeline JSON 里永远只有 asset id（开发指令第二十四条）。
 * 导出时 AI_Timeline_Builder 会把被引用的素材拷到 remotion/public/ 下，
 * 并保持 asset_manifest.json 里的相对路径不变，所以这里 staticFile(path) 即可。
 */

import { staticFile } from "remotion";
import type { AssetEntry, AssetManifest } from "./timeline";

export const findAsset = (
  manifest: AssetManifest,
  assetId?: string,
): AssetEntry | undefined =>
  assetId ? manifest.assets.find((a) => a.id === assetId) : undefined;

/** 取素材的可访问 URL。找不到返回空字符串，调用方需要自己跳过渲染。 */
export const assetUrl = (manifest: AssetManifest, assetId?: string): string => {
  const asset = findAsset(manifest, assetId);
  if (!asset || !asset.path) {
    return "";
  }
  if (/^https?:\/\//i.test(asset.path)) {
    return asset.path;
  }
  return staticFile(asset.path);
};

export const assetDuration = (
  manifest: AssetManifest,
  assetId?: string,
): number => findAsset(manifest, assetId)?.duration ?? 0;
