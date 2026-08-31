/**
 * 由 AI_Timeline_Builder 的「导出 Remotion」自动生成，请不要手改。
 * 下次导出会整体覆盖本文件。
 */

import type { AssetManifest, Timeline } from "./lib/timeline";

export const TIMELINE: Timeline = {
  "version": 1,
  "time_unit": "seconds",
  "meta": {
    "name": "未命名项目",
    "fps": 60.0,
    "width": 720,
    "height": 1280,
    "duration": 1.5
  },
  "tracks": [
    {
      "id": "V1",
      "name": "V1 主视频",
      "kind": "video"
    }
  ],
  "elements": [
    {
      "id": "clip_001",
      "type": "video",
      "track": "V1",
      "asset": "video_005",
      "start": 0.35,
      "duration": 1.15,
      "source": {
        "start": 26.85,
        "end": 28.0
      }
    }
  ]
} as Timeline;

export const ASSET_MANIFEST: AssetManifest = {
  "version": 1,
  "assets": [
    {
      "id": "video_005",
      "name": "video_各种搞笑素材，免费拿走_#素材分..._top_0_1",
      "type": "video",
      "path": "assets/videos/imported/video_各种搞笑素材，免费拿走_#素材分..._top_0_1.mp4",
      "duration": 70.774,
      "width": 720,
      "height": 1280,
      "fps": 30.0
    }
  ]
};
