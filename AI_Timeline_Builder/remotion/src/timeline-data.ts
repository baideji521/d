/**
 * 由 AI_Timeline_Builder 的「导出 Remotion」自动生成，请不要手改。
 * 下次导出会整体覆盖本文件。
 */

import type { AssetManifest, Timeline } from "./lib/timeline";

export const TIMELINE: Timeline = {
  "version": 1,
  "time_unit": "seconds",
  "meta": {
    "name": "Demo 项目（参数实验起点）",
    "fps": 30,
    "width": 1080,
    "height": 1920,
    "duration": 15.0,
    "background": "#000000"
  },
  "tracks": [
    {
      "id": "A1",
      "name": "A1 背景音乐",
      "kind": "audio",
      "locked": false,
      "hidden": false
    },
    {
      "id": "A2",
      "name": "A2 人声",
      "kind": "audio",
      "locked": false,
      "hidden": false
    },
    {
      "id": "A3",
      "name": "A3 音效",
      "kind": "audio",
      "locked": false,
      "hidden": false
    },
    {
      "id": "V1",
      "name": "V1 主视频",
      "kind": "video",
      "locked": false,
      "hidden": false
    },
    {
      "id": "V2",
      "name": "V2 视频叠加",
      "kind": "video",
      "locked": false,
      "hidden": false
    },
    {
      "id": "V3",
      "name": "V3 图片/Overlay",
      "kind": "video",
      "locked": false,
      "hidden": false
    },
    {
      "id": "V4",
      "name": "V4 高层 Overlay",
      "kind": "video",
      "locked": false,
      "hidden": false
    },
    {
      "id": "T1",
      "name": "T1 字幕",
      "kind": "text",
      "locked": false,
      "hidden": false
    },
    {
      "id": "T2",
      "name": "T2 普通文字",
      "kind": "text",
      "locked": false,
      "hidden": false
    }
  ],
  "elements": [
    {
      "id": "clip_001",
      "type": "video",
      "track": "V1",
      "asset": "video_001",
      "start": 0.0,
      "duration": 6.0,
      "source": {
        "start": 0.5,
        "end": 6.5
      },
      "transform": {
        "x": 0.5,
        "y": 0.5,
        "scale": 1.0,
        "rotation": 0.0,
        "opacity": 1.0
      },
      "speed": 1.0,
      "audio": {
        "enabled": true,
        "volume": 1.0
      },
      "keyframes": {}
    },
    {
      "id": "clip_002",
      "type": "video",
      "track": "V1",
      "asset": "video_002",
      "start": 6.0,
      "duration": 7.0,
      "source": {
        "start": 1.0,
        "end": 8.0
      },
      "transform": {
        "x": 0.5,
        "y": 0.5,
        "scale": 1.0,
        "rotation": 0.0,
        "opacity": 1.0
      },
      "speed": 1.0,
      "audio": {
        "enabled": true,
        "volume": 1.0
      },
      "keyframes": {}
    },
    {
      "id": "transition_001",
      "type": "transition",
      "track": "V1",
      "name": "whip",
      "from": "clip_001",
      "to": "clip_002",
      "start": 5.75,
      "duration": 0.5,
      "params": {
        "direction": "left",
        "intensity": 0.8,
        "blur": 0.6
      }
    },
    {
      "id": "freeze_001",
      "type": "freeze",
      "track": "V1",
      "target": "clip_002",
      "source_time": 3.0,
      "start": 13.0,
      "duration": 1.5,
      "transform": {
        "x": 0.5,
        "y": 0.5,
        "scale": 1.0,
        "rotation": 0.0,
        "opacity": 1.0
      },
      "keyframes": {}
    },
    {
      "id": "clip_003",
      "type": "video",
      "track": "V2",
      "asset": "video_002",
      "start": 7.0,
      "duration": 5.5,
      "source": {
        "start": 4.0,
        "end": 9.5
      },
      "transform": {
        "x": 0.72,
        "y": 0.22,
        "scale": 0.38,
        "rotation": -4.0,
        "opacity": 1.0
      },
      "speed": 1.0,
      "audio": {
        "enabled": false,
        "volume": 0.0
      },
      "keyframes": {}
    },
    {
      "id": "overlay_001",
      "type": "overlay",
      "track": "V3",
      "asset": "overlay_arrow_001",
      "start": 2.0,
      "duration": 2.5,
      "transform": {
        "x": 0.34,
        "y": 0.46,
        "scale": 0.55,
        "rotation": 12.0,
        "opacity": 1.0
      },
      "keyframes": {
        "opacity": [
          {
            "time": 0.0,
            "value": 0.0,
            "easing": "easeOut"
          },
          {
            "time": 0.3,
            "value": 1.0,
            "easing": "easeOut"
          },
          {
            "time": 2.2,
            "value": 1.0,
            "easing": "linear"
          },
          {
            "time": 2.5,
            "value": 0.0,
            "easing": "easeIn"
          }
        ],
        "scale": [
          {
            "time": 0.0,
            "value": 0.4,
            "easing": "easeOut"
          },
          {
            "time": 0.35,
            "value": 0.62,
            "easing": "easeOut"
          },
          {
            "time": 0.5,
            "value": 0.55,
            "easing": "easeInOut"
          }
        ]
      }
    },
    {
      "id": "captiongroup_001",
      "type": "caption_group",
      "track": "T1",
      "start": 0.4,
      "duration": 3.0,
      "template": "highlight_yellow",
      "caption_style": "highlight_current",
      "content": {
        "words": [
          {
            "text": "这是",
            "start": 0.4,
            "end": 0.9
          },
          {
            "text": "一个",
            "start": 0.9,
            "end": 1.4
          },
          {
            "text": "参数",
            "start": 1.4,
            "end": 2.0
          },
          {
            "text": "实验",
            "start": 2.0,
            "end": 2.6
          },
          {
            "text": "Demo",
            "start": 2.6,
            "end": 3.4
          }
        ]
      },
      "style": {
        "fontFamily": "Arial",
        "fontSize": 64,
        "fontWeight": 800,
        "color": "#FFFFFF",
        "align": "center",
        "stroke": {
          "width": 6,
          "color": "#000000"
        }
      },
      "highlight": {
        "color": "#FFE347",
        "backgroundColor": "",
        "scale": 1.12
      },
      "transform": {
        "x": 0.538,
        "y": 0.753,
        "scale": 1.0,
        "rotation": 0.0,
        "opacity": 1.0
      },
      "keyframes": {}
    },
    {
      "id": "caption_001",
      "type": "caption",
      "track": "T1",
      "start": 4.866667,
      "duration": 2.4,
      "template": "bold_white",
      "caption_style": "plain",
      "content": {
        "text": "改任意参数，预览和 JSON 会同时变"
      },
      "style": {
        "fontFamily": "Arial",
        "fontSize": 64,
        "fontWeight": 900,
        "color": "#FFFFFF",
        "align": "center",
        "lineHeight": 1.2,
        "stroke": {
          "width": 8,
          "color": "#000000"
        },
        "shadow": {
          "x": 0,
          "y": 4,
          "blur": 8,
          "color": "rgba(0,0,0,0.6)"
        }
      },
      "transform": {
        "x": 0.5,
        "y": 0.82,
        "scale": 1.0,
        "rotation": 0,
        "opacity": 1
      },
      "keyframes": {},
      "highlight": {
        "color": "#FFE347",
        "backgroundColor": "",
        "scale": 1.1
      }
    },
    {
      "id": "text_001",
      "type": "text",
      "track": "T2",
      "start": 13.0,
      "duration": 2.0,
      "content": {
        "text": "冻结 + 推进"
      },
      "style": {
        "fontFamily": "Arial",
        "fontSize": 96,
        "fontWeight": 900,
        "color": "#FFFFFF",
        "align": "center",
        "stroke": {
          "width": 8,
          "color": "#000000"
        }
      },
      "transform": {
        "x": 0.5,
        "y": 0.32,
        "scale": 1.0,
        "rotation": 0.0,
        "opacity": 1.0
      },
      "keyframes": {
        "scale": [
          {
            "time": 0.0,
            "value": 0.8,
            "easing": "easeOut"
          },
          {
            "time": 0.12,
            "value": 1.15,
            "easing": "easeOut"
          },
          {
            "time": 0.26,
            "value": 1.0,
            "easing": "easeInOut"
          }
        ]
      }
    },
    {
      "id": "audio_001",
      "type": "audio",
      "track": "A1",
      "asset": "sfx_bgm_001",
      "start": 0.0,
      "duration": 15.0,
      "source": {
        "start": 0.0,
        "end": 15.0
      },
      "speed": 1.0,
      "volume": 0.35,
      "fade": {
        "in": 0.6,
        "out": 1.2
      }
    },
    {
      "id": "audio_002",
      "type": "audio",
      "track": "A3",
      "asset": "sfx_impact_001",
      "start": 5.9,
      "duration": 0.6,
      "source": {
        "start": 0.0,
        "end": 0.6
      },
      "speed": 1.0,
      "volume": 1.0,
      "fade": {
        "in": 0.0,
        "out": 0.0
      }
    },
    {
      "id": "effect_001",
      "type": "effect",
      "track": "V1",
      "name": "zoom",
      "start": 4.6,
      "duration": 1.2,
      "easing": "easeInOut",
      "params": {
        "scale_from": 1.0,
        "scale_to": 1.35,
        "origin_x": 0.5,
        "origin_y": 0.45
      },
      "target": "clip_001"
    },
    {
      "id": "effect_002",
      "type": "effect",
      "track": "V1",
      "name": "shake",
      "start": 6.05,
      "duration": 0.4,
      "easing": "easeOut",
      "params": {
        "amplitude": 0.02,
        "frequency": 18.0,
        "rotation": 1.5
      },
      "target": "clip_002"
    },
    {
      "id": "effect_003",
      "type": "effect",
      "track": "V4",
      "name": "flash",
      "start": 5.95,
      "duration": 0.25,
      "easing": "easeOut",
      "params": {
        "color": "#FFFFFF",
        "intensity": 0.85,
        "decay": "easeOut"
      }
    }
  ]
} as Timeline;

export const ASSET_MANIFEST: AssetManifest = {
  "version": 1,
  "assets": [
    {
      "id": "overlay_arrow_001",
      "name": "arrow_red",
      "type": "overlay",
      "path": "assets/overlays/arrow/arrow_red.png",
      "duration": 0,
      "width": 512,
      "height": 512,
      "fps": 25.0
    },
    {
      "id": "sfx_bgm_001",
      "name": "bgm_demo",
      "type": "audio",
      "path": "assets/audio/bgm/bgm_demo.wav",
      "duration": 16.0,
      "width": 0,
      "height": 0,
      "fps": 0
    },
    {
      "id": "sfx_impact_001",
      "name": "impact_01",
      "type": "audio",
      "path": "assets/audio/impact/impact_01.wav",
      "duration": 0.6,
      "width": 0,
      "height": 0,
      "fps": 0
    },
    {
      "id": "video_001",
      "name": "demo_a",
      "type": "video",
      "path": "assets/videos/demo/demo_a.mp4",
      "duration": 10.0,
      "width": 1080,
      "height": 1920,
      "fps": 30.0
    },
    {
      "id": "video_002",
      "name": "demo_b",
      "type": "video",
      "path": "assets/videos/demo/demo_b.mp4",
      "duration": 10.0,
      "width": 1080,
      "height": 1920,
      "fps": 30.0
    }
  ]
};
