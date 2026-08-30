import { Config } from "@remotion/cli/config";

// 素材路径由 asset_manifest.json 决定，这里只配编码相关参数
Config.setVideoImageFormat("jpeg");
Config.setOverwriteOutput(true);
Config.setChromiumOpenGlRenderer("angle");
