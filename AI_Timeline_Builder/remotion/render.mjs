/**
 * 命令行渲染入口。
 *
 * 用法：
 *   node render.mjs                                    用 timeline.json 渲染到 out/video.mp4
 *   node render.mjs --timeline=xxx.json --out=y.mp4    指定输入输出
 *   node render.mjs --codec=vp8 --scale=0.5            换编码 / 降分辨率快速预览
 *
 * 关键点：inputProps 直接就是 timeline.json 的内容，
 * 与 GUI 里看到的 JSON 完全一致，中间没有任何转换。
 */

import { bundle } from "@remotion/bundler";
import { renderMedia, selectComposition } from "@remotion/renderer";
import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

// 必须用 fileURLToPath 解码：import.meta.url 里中文路径是 percent 编码的，
// 直接取 pathname 会得到 %E5%B7%A5%E5%85%B7 这种找不到的目录。
const here = path.dirname(fileURLToPath(import.meta.url));

const parseArgs = () => {
  const result = {};
  for (const arg of process.argv.slice(2)) {
    const match = /^--([^=]+)=(.*)$/.exec(arg);
    if (match) {
      result[match[1]] = match[2];
    } else if (arg.startsWith("--")) {
      result[arg.slice(2)] = "true";
    }
  }
  return result;
};

const readJson = (file) => JSON.parse(fs.readFileSync(file, "utf-8"));

const main = async () => {
  const args = parseArgs();
  const timelinePath = path.resolve(here, args.timeline ?? "timeline.json");
  const manifestPath = path.resolve(here, args.manifest ?? "asset_manifest.json");
  const outputPath = path.resolve(here, args.out ?? path.join("out", "video.mp4"));

  if (!fs.existsSync(timelinePath)) {
    console.error(`找不到 Timeline JSON：${timelinePath}`);
    process.exit(1);
  }

  const timeline = readJson(timelinePath);
  const manifest = fs.existsSync(manifestPath)
    ? readJson(manifestPath)
    : { version: 1, assets: [] };

  console.log(`Timeline：${timeline.meta?.name ?? "未命名"}`);
  console.log(
    `规格：${timeline.meta?.width}x${timeline.meta?.height} @ ${timeline.meta?.fps}fps，` +
      `元素 ${timeline.elements?.length ?? 0} 个，素材 ${manifest.assets.length} 个`,
  );

  const inputProps = { timeline, manifest };

  console.log("正在打包 Remotion 工程…");
  const serveUrl = await bundle({
    entryPoint: path.resolve(here, "src/index.ts"),
    onProgress: (progress) => {
      if (progress % 25 === 0) {
        console.log(`打包 ${progress}%`);
      }
    },
  });

  const composition = await selectComposition({
    serveUrl,
    id: "TimelineVideo",
    inputProps,
  });

  console.log(
    `合成信息：${composition.width}x${composition.height} @ ${composition.fps}fps，` +
      `${composition.durationInFrames} 帧（${(
        composition.durationInFrames / composition.fps
      ).toFixed(2)}s）`,
  );

  fs.mkdirSync(path.dirname(outputPath), { recursive: true });

  let lastReported = -1;
  await renderMedia({
    composition,
    serveUrl,
    codec: args.codec ?? "h264",
    outputLocation: outputPath,
    inputProps,
    scale: args.scale ? Number(args.scale) : 1,
    concurrency: args.concurrency ? Number(args.concurrency) : null,
    onProgress: ({ progress }) => {
      const percent = Math.round(progress * 100);
      if (percent !== lastReported && percent % 5 === 0) {
        lastReported = percent;
        console.log(`渲染 ${percent}%`);
      }
    },
  });

  console.log(`渲染完成：${outputPath}`);
};

main().catch((error) => {
  console.error("渲染失败：", error);
  process.exit(1);
});
