# Timeline JSON 示例

由 `python tools/build_catalog.py` 扫描真实注册表生成，**请勿手改**。

示例不是手写的：全部由 `core/timeline.py` 的 `make_*` 构造，再经
`core/sparse.py` 序列化，最后过一遍 `TimelineValidator`。
所以「示例语法过时了」这件事不可能发生。

## 协议要点

- Timeline JSON 表达的是**剪辑意图**；怎么画由 Remotion 决定。AI 只产 JSON，永不产 TSX。
- **稀疏**：字段等于 Runtime 默认值就不写。`speed=1`、`volume=1`、全默认 `transform`、
  空 `keyframes` 都属于噪声。
- 时间单位是秒（`time_unit=seconds`），帧数由 `meta.fps` 换算。
- `asset` 写的是 asset id，导出时会连同 `remotion/asset_manifest.json` 一起带过去。
- `meta.width` / `meta.height` 决定画布，见 `RESOLUTION_GUIDE.md`。

## 最小单视频

只有一个片段。没有 `speed`、没有 `volume`、没有 `transform`、没有 `keyframes`——缺省就是默认值，写出来只是噪声。

- 校验结果：校验通过（0 error）

```json
{
  "version": 1,
  "time_unit": "seconds",
  "meta": {
    "name": "single_video",
    "fps": 30,
    "width": 1080,
    "height": 1920,
    "duration": 4.0
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
      "asset": "video_001",
      "start": 0.0,
      "duration": 4.0,
      "source": {
        "start": 0.0,
        "end": 4.0
      }
    }
  ]
}
```

## 两段视频 + 转场

转场窗口必须落在两个片段的重叠区间内；`params` 为空表示全用注册表默认值。

- 校验结果：校验通过（0 error）

```json
{
  "version": 1,
  "time_unit": "seconds",
  "meta": {
    "name": "two_clips_transition",
    "fps": 30,
    "width": 1080,
    "height": 1920,
    "duration": 6.0
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
      "asset": "video_001",
      "start": 0.0,
      "duration": 3.0,
      "source": {
        "start": 0.0,
        "end": 3.0
      }
    },
    {
      "id": "clip_002",
      "type": "video",
      "track": "V1",
      "asset": "video_002",
      "start": 2.5,
      "duration": 3.5,
      "source": {
        "start": 0.0,
        "end": 3.5
      }
    },
    {
      "id": "transition_001",
      "type": "transition",
      "track": "V1",
      "name": "whip",
      "from": "clip_001",
      "to": "clip_002",
      "start": 2.5,
      "duration": 0.5
    }
  ]
}
```

## 视频 + 特效

程序特效用 `type=effect`，靠 `target` 绑定被作用的片段；`params` 只写和默认值不同的项。

- 校验结果：校验通过（0 error）

```json
{
  "version": 1,
  "time_unit": "seconds",
  "meta": {
    "name": "video_with_effect",
    "fps": 30,
    "width": 1080,
    "height": 1920,
    "duration": 4.0
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
      "asset": "video_001",
      "start": 0.0,
      "duration": 4.0,
      "source": {
        "start": 0.0,
        "end": 4.0
      }
    },
    {
      "id": "effect_001",
      "type": "effect",
      "track": "V1",
      "name": "zoom",
      "start": 1.0,
      "duration": 0.6,
      "easing": "easeInOut",
      "params": {
        "scale_to": 1.5
      },
      "target": "clip_001"
    }
  ]
}
```

## 视频 + BGM + 音效

BGM 在 A1、音效在 A3；`fade` 只写非零的一侧，`volume` 等于 1 时不写。

- 校验结果：校验通过（0 error）

```json
{
  "version": 1,
  "time_unit": "seconds",
  "meta": {
    "name": "video_with_sfx",
    "fps": 30,
    "width": 1080,
    "height": 1920,
    "duration": 4.0
  },
  "tracks": [
    {
      "id": "A1",
      "name": "A1 背景音乐",
      "kind": "audio"
    },
    {
      "id": "A3",
      "name": "A3 音效",
      "kind": "audio"
    },
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
      "asset": "video_001",
      "start": 0.0,
      "duration": 4.0,
      "source": {
        "start": 0.0,
        "end": 4.0
      }
    },
    {
      "id": "audio_001",
      "type": "audio",
      "track": "A1",
      "asset": "sfx_bgm_001",
      "start": 0.0,
      "duration": 4.0,
      "source": {
        "start": 0.0,
        "end": 4.0
      },
      "volume": 0.35,
      "fade": {
        "in": 0.3,
        "out": 0.5
      }
    },
    {
      "id": "audio_002",
      "type": "audio",
      "track": "A3",
      "asset": "sfx_impact_001",
      "start": 1.0,
      "duration": 0.6,
      "source": {
        "start": 0.0,
        "end": 0.6
      },
      "volume": 0.9
    }
  ]
}
```

## 全类型组合

视频 + 转场 + 叠加 + 文字 + 字幕 + 特效 + BGM + 音效，外加两个标记点。标记写在 `meta.markers`，Remotion 会忽略它。

- 校验结果：校验通过（0 error）

```json
{
  "version": 1,
  "time_unit": "seconds",
  "meta": {
    "name": "full_combo",
    "fps": 30,
    "width": 1080,
    "height": 1920,
    "duration": 6.0,
    "markers": [
      {
        "time": 2.6,
        "type": "transition"
      },
      {
        "time": 4.0,
        "type": "highlight",
        "label": "高光"
      }
    ]
  },
  "tracks": [
    {
      "id": "A1",
      "name": "A1 背景音乐",
      "kind": "audio"
    },
    {
      "id": "A3",
      "name": "A3 音效",
      "kind": "audio"
    },
    {
      "id": "V1",
      "name": "V1 主视频",
      "kind": "video"
    },
    {
      "id": "V3",
      "name": "V3 图片/Overlay",
      "kind": "video"
    },
    {
      "id": "T1",
      "name": "T1 字幕",
      "kind": "text"
    },
    {
      "id": "T2",
      "name": "T2 普通文字",
      "kind": "text"
    }
  ],
  "elements": [
    {
      "id": "clip_001",
      "type": "video",
      "track": "V1",
      "asset": "video_001",
      "start": 0.0,
      "duration": 3.0,
      "source": {
        "start": 0.0,
        "end": 3.0
      }
    },
    {
      "id": "clip_002",
      "type": "video",
      "track": "V1",
      "asset": "video_002",
      "start": 2.6,
      "duration": 3.4,
      "source": {
        "start": 0.0,
        "end": 3.4
      }
    },
    {
      "id": "transition_001",
      "type": "transition",
      "track": "V1",
      "name": "crossfade",
      "from": "clip_001",
      "to": "clip_002",
      "start": 2.6,
      "duration": 0.4
    },
    {
      "id": "overlay_001",
      "type": "overlay",
      "track": "V3",
      "asset": "overlay_arrow_001",
      "start": 1.0,
      "duration": 1.5
    },
    {
      "id": "text_001",
      "type": "text",
      "track": "T2",
      "start": 0.2,
      "duration": 2.0,
      "content": {
        "text": "标题"
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
        "y": 0.7
      }
    },
    {
      "id": "caption_001",
      "type": "caption",
      "track": "T1",
      "start": 1.0,
      "duration": 2.5,
      "template": "bold_white",
      "caption_style": "plain",
      "content": {
        "text": "这是一条字幕"
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
      "transform": {
        "y": 0.82
      }
    },
    {
      "id": "effect_001",
      "type": "effect",
      "track": "V1",
      "name": "shake",
      "start": 2.4,
      "duration": 0.4,
      "easing": "easeInOut",
      "target": "clip_001"
    },
    {
      "id": "audio_001",
      "type": "audio",
      "track": "A1",
      "asset": "sfx_bgm_001",
      "start": 0.0,
      "duration": 6.0,
      "source": {
        "start": 0.0,
        "end": 6.0
      },
      "volume": 0.3,
      "fade": {
        "out": 0.8
      }
    },
    {
      "id": "audio_002",
      "type": "audio",
      "track": "A3",
      "asset": "sfx_impact_001",
      "start": 2.6,
      "duration": 0.6,
      "source": {
        "start": 0.0,
        "end": 0.6
      }
    }
  ]
}
```
