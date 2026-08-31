# 音效库目录

由 `python tools/build_catalog.py` 扫描真实注册表生成，**请勿手改**。

本文件把两件事分开写，**不要混着看**：

1. **系统支持的音效类型**：协议层面的分类（`libraries/sound_library.py`），
   跟本地有没有文件无关；0 个文件的类型也会列出来，数量写 0。
2. **本地实际存在的音效文件**：来自 `asset_manifest.json`，并且逐个做过
   `os.path.exists`。清单里指向已删除文件的条目列在「失效条目」里，不算可用。

- 支持的类型：13 个
- 本地可用文件：241 个
- 失效条目：0 个

## 支持的类型

| category | 名称 | 建议轨道 | 本地文件数 | 用途 |
| --- | --- | --- | --- | --- |
| `bgm` | 背景音乐 BGM | `A1` | 1 | 整段铺底的音乐，通常需要 fade in / out 与较低音量 |
| `tts` | 语音 / 配音 | `A2` | 2 | TTS 合成或录制的人声旁白 |
| `boom` | 低频冲击 Boom | `A3` | 2 | 重低音砸落，配合镜头切换或强调 |
| `impact` | 撞击 Impact | `A3` | 41 | 打击、爆点，最常用的卡点音效 |
| `whoosh` | 呼啸 Whoosh | `A3` | 3 | 快速划过的风声，配合甩镜 / 位移转场 |
| `riser` | 上升 Riser | `A3` | 2 | 情绪上扬的铺垫音，落点前使用 |
| `glass` | 玻璃 Glass | `A3` | 15 | 玻璃碎裂 / 清脆质感 |
| `metal` | 金属 Metal | `A3` | 20 | 金属碰撞、刀剑质感 |
| `wood` | 木质 Wood | `A3` | 20 | 木头敲击、闷响质感 |
| `footstep` | 脚步 Footstep | `A3` | 25 | 不同地面的脚步声，做拟音用 |
| `ui` | 界面 UI | `A3` | 100 | 点击、切换、提示等短音，做转场点缀 |
| `soft` | 轻柔 Soft | `A3` | 10 | 柔和的短音，适合字幕出现 / 轻提示 |
| `imported` | 导入 Imported | `A3` | 0 | 用户从外部导入的音频，未归类 |

本地一个文件都没有的类型：`imported`。这不是 bug，是「支持但没素材」，导入音频到 `assets/audio/<category>/` 即可。

## 本地文件清单

### `bgm` · 背景音乐 BGM（1 个）

| asset id | 文件 | 时长 |
| --- | --- | --- |
| `sfx_bgm_001` | `assets/audio/bgm/bgm_demo.wav` | 16.000s |

### `tts` · 语音 / 配音（2 个）

| asset id | 文件 | 时长 |
| --- | --- | --- |
| `sfx_tts_001` | `assets/audio/tts/tts_20260830_115834_啊啊啊啊.wav` | 1.699s |
| `sfx_tts_004` | `assets/audio/tts/voice_en_female.wav` | 3.414s |

### `boom` · 低频冲击 Boom（2 个）

| asset id | 文件 | 时长 |
| --- | --- | --- |
| `sfx_boom_001` | `assets/audio/boom/boom_low_01.wav` | 1.200s |
| `sfx_boom_002` | `assets/audio/boom/boom_punch_01.wav` | 0.800s |

### `impact` · 撞击 Impact（41 个）

| asset id | 文件 | 时长 |
| --- | --- | --- |
| `sfx_impact_001` | `assets/audio/impact/impact_01.wav` | 0.600s |
| `sfx_impact_002` | `assets/audio/impact/impactBell_heavy_000.ogg` | 1.480s |
| `sfx_impact_003` | `assets/audio/impact/impactBell_heavy_001.ogg` | 1.741s |
| `sfx_impact_004` | `assets/audio/impact/impactBell_heavy_002.ogg` | 0.697s |
| `sfx_impact_005` | `assets/audio/impact/impactBell_heavy_003.ogg` | 0.654s |
| `sfx_impact_006` | `assets/audio/impact/impactBell_heavy_004.ogg` | 0.301s |
| `sfx_impact_007` | `assets/audio/impact/impactGeneric_light_000.ogg` | 0.139s |
| `sfx_impact_008` | `assets/audio/impact/impactGeneric_light_001.ogg` | 0.118s |
| `sfx_impact_009` | `assets/audio/impact/impactGeneric_light_002.ogg` | 0.140s |
| `sfx_impact_010` | `assets/audio/impact/impactGeneric_light_003.ogg` | 0.138s |
| `sfx_impact_011` | `assets/audio/impact/impactGeneric_light_004.ogg` | 0.140s |
| `sfx_impact_012` | `assets/audio/impact/impactMining_000.ogg` | 0.937s |
| `sfx_impact_013` | `assets/audio/impact/impactMining_001.ogg` | 0.869s |
| `sfx_impact_014` | `assets/audio/impact/impactMining_002.ogg` | 0.805s |
| `sfx_impact_015` | `assets/audio/impact/impactMining_003.ogg` | 0.992s |
| `sfx_impact_016` | `assets/audio/impact/impactMining_004.ogg` | 0.830s |
| `sfx_impact_017` | `assets/audio/impact/impactPlate_heavy_000.ogg` | 0.489s |
| `sfx_impact_018` | `assets/audio/impact/impactPlate_heavy_001.ogg` | 0.352s |
| `sfx_impact_019` | `assets/audio/impact/impactPlate_heavy_002.ogg` | 0.494s |
| `sfx_impact_020` | `assets/audio/impact/impactPlate_heavy_003.ogg` | 0.347s |
| `sfx_impact_021` | `assets/audio/impact/impactPlate_heavy_004.ogg` | 0.559s |
| `sfx_impact_022` | `assets/audio/impact/impactPlate_light_000.ogg` | 0.542s |
| `sfx_impact_023` | `assets/audio/impact/impactPlate_light_001.ogg` | 0.655s |
| `sfx_impact_024` | `assets/audio/impact/impactPlate_light_002.ogg` | 0.489s |
| `sfx_impact_025` | `assets/audio/impact/impactPlate_light_003.ogg` | 0.528s |
| `sfx_impact_026` | `assets/audio/impact/impactPlate_light_004.ogg` | 0.657s |
| `sfx_impact_027` | `assets/audio/impact/impactPlate_medium_000.ogg` | 0.609s |
| `sfx_impact_028` | `assets/audio/impact/impactPlate_medium_001.ogg` | 0.616s |
| `sfx_impact_029` | `assets/audio/impact/impactPlate_medium_002.ogg` | 0.515s |
| `sfx_impact_030` | `assets/audio/impact/impactPlate_medium_003.ogg` | 0.654s |
| `sfx_impact_031` | `assets/audio/impact/impactPlate_medium_004.ogg` | 0.534s |
| `sfx_impact_032` | `assets/audio/impact/impactPunch_heavy_000.ogg` | 0.649s |
| `sfx_impact_033` | `assets/audio/impact/impactPunch_heavy_001.ogg` | 0.536s |
| `sfx_impact_034` | `assets/audio/impact/impactPunch_heavy_002.ogg` | 0.457s |
| `sfx_impact_035` | `assets/audio/impact/impactPunch_heavy_003.ogg` | 0.474s |
| `sfx_impact_036` | `assets/audio/impact/impactPunch_heavy_004.ogg` | 0.536s |
| `sfx_impact_037` | `assets/audio/impact/impactPunch_medium_000.ogg` | 0.431s |
| `sfx_impact_038` | `assets/audio/impact/impactPunch_medium_001.ogg` | 0.405s |
| `sfx_impact_039` | `assets/audio/impact/impactPunch_medium_002.ogg` | 0.541s |
| `sfx_impact_040` | `assets/audio/impact/impactPunch_medium_003.ogg` | 0.455s |
| `sfx_impact_041` | `assets/audio/impact/impactPunch_medium_004.ogg` | 0.543s |

### `whoosh` · 呼啸 Whoosh（3 个）

| asset id | 文件 | 时长 |
| --- | --- | --- |
| `sfx_whoosh_001` | `assets/audio/whoosh/swish_01.wav` | 0.300s |
| `sfx_whoosh_002` | `assets/audio/whoosh/whoosh_long_01.wav` | 0.900s |
| `sfx_whoosh_003` | `assets/audio/whoosh/whoosh_short_01.wav` | 0.450s |

### `riser` · 上升 Riser（2 个）

| asset id | 文件 | 时长 |
| --- | --- | --- |
| `sfx_riser_001` | `assets/audio/riser/downlifter_01.wav` | 1.000s |
| `sfx_riser_002` | `assets/audio/riser/riser_up_01.wav` | 1.560s |

### `glass` · 玻璃 Glass（15 个）

| asset id | 文件 | 时长 |
| --- | --- | --- |
| `sfx_glass_001` | `assets/audio/glass/impactGlass_heavy_000.ogg` | 0.241s |
| `sfx_glass_002` | `assets/audio/glass/impactGlass_heavy_001.ogg` | 0.429s |
| `sfx_glass_003` | `assets/audio/glass/impactGlass_heavy_002.ogg` | 0.247s |
| `sfx_glass_004` | `assets/audio/glass/impactGlass_heavy_003.ogg` | 0.172s |
| `sfx_glass_005` | `assets/audio/glass/impactGlass_heavy_004.ogg` | 0.399s |
| `sfx_glass_006` | `assets/audio/glass/impactGlass_light_000.ogg` | 0.210s |
| `sfx_glass_007` | `assets/audio/glass/impactGlass_light_001.ogg` | 0.210s |
| `sfx_glass_008` | `assets/audio/glass/impactGlass_light_002.ogg` | 0.210s |
| `sfx_glass_009` | `assets/audio/glass/impactGlass_light_003.ogg` | 0.210s |
| `sfx_glass_010` | `assets/audio/glass/impactGlass_light_004.ogg` | 0.210s |
| `sfx_glass_011` | `assets/audio/glass/impactGlass_medium_000.ogg` | 0.543s |
| `sfx_glass_012` | `assets/audio/glass/impactGlass_medium_001.ogg` | 0.543s |
| `sfx_glass_013` | `assets/audio/glass/impactGlass_medium_002.ogg` | 0.543s |
| `sfx_glass_014` | `assets/audio/glass/impactGlass_medium_003.ogg` | 0.543s |
| `sfx_glass_015` | `assets/audio/glass/impactGlass_medium_004.ogg` | 0.543s |

### `metal` · 金属 Metal（20 个）

| asset id | 文件 | 时长 |
| --- | --- | --- |
| `sfx_metal_001` | `assets/audio/metal/impactMetal_heavy_000.ogg` | 0.168s |
| `sfx_metal_002` | `assets/audio/metal/impactMetal_heavy_001.ogg` | 0.359s |
| `sfx_metal_003` | `assets/audio/metal/impactMetal_heavy_002.ogg` | 0.117s |
| `sfx_metal_004` | `assets/audio/metal/impactMetal_heavy_003.ogg` | 0.207s |
| `sfx_metal_005` | `assets/audio/metal/impactMetal_heavy_004.ogg` | 0.134s |
| `sfx_metal_006` | `assets/audio/metal/impactMetal_light_000.ogg` | 0.351s |
| `sfx_metal_007` | `assets/audio/metal/impactMetal_light_001.ogg` | 0.252s |
| `sfx_metal_008` | `assets/audio/metal/impactMetal_light_002.ogg` | 0.236s |
| `sfx_metal_009` | `assets/audio/metal/impactMetal_light_003.ogg` | 0.482s |
| `sfx_metal_010` | `assets/audio/metal/impactMetal_light_004.ogg` | 0.213s |
| `sfx_metal_011` | `assets/audio/metal/impactMetal_medium_000.ogg` | 0.272s |
| `sfx_metal_012` | `assets/audio/metal/impactMetal_medium_001.ogg` | 0.143s |
| `sfx_metal_013` | `assets/audio/metal/impactMetal_medium_002.ogg` | 0.119s |
| `sfx_metal_014` | `assets/audio/metal/impactMetal_medium_003.ogg` | 0.254s |
| `sfx_metal_015` | `assets/audio/metal/impactMetal_medium_004.ogg` | 0.109s |
| `sfx_metal_016` | `assets/audio/metal/impactTin_medium_000.ogg` | 0.159s |
| `sfx_metal_017` | `assets/audio/metal/impactTin_medium_001.ogg` | 0.174s |
| `sfx_metal_018` | `assets/audio/metal/impactTin_medium_002.ogg` | 0.134s |
| `sfx_metal_019` | `assets/audio/metal/impactTin_medium_003.ogg` | 0.215s |
| `sfx_metal_020` | `assets/audio/metal/impactTin_medium_004.ogg` | 0.179s |

### `wood` · 木质 Wood（20 个）

| asset id | 文件 | 时长 |
| --- | --- | --- |
| `sfx_wood_001` | `assets/audio/wood/impactPlank_medium_000.ogg` | 0.779s |
| `sfx_wood_002` | `assets/audio/wood/impactPlank_medium_001.ogg` | 0.779s |
| `sfx_wood_003` | `assets/audio/wood/impactPlank_medium_002.ogg` | 0.779s |
| `sfx_wood_004` | `assets/audio/wood/impactPlank_medium_003.ogg` | 0.779s |
| `sfx_wood_005` | `assets/audio/wood/impactPlank_medium_004.ogg` | 0.779s |
| `sfx_wood_006` | `assets/audio/wood/impactWood_heavy_000.ogg` | 0.313s |
| `sfx_wood_007` | `assets/audio/wood/impactWood_heavy_001.ogg` | 0.313s |
| `sfx_wood_008` | `assets/audio/wood/impactWood_heavy_002.ogg` | 0.313s |
| `sfx_wood_009` | `assets/audio/wood/impactWood_heavy_003.ogg` | 0.313s |
| `sfx_wood_010` | `assets/audio/wood/impactWood_heavy_004.ogg` | 0.313s |
| `sfx_wood_011` | `assets/audio/wood/impactWood_light_000.ogg` | 0.266s |
| `sfx_wood_012` | `assets/audio/wood/impactWood_light_001.ogg` | 0.266s |
| `sfx_wood_013` | `assets/audio/wood/impactWood_light_002.ogg` | 0.266s |
| `sfx_wood_014` | `assets/audio/wood/impactWood_light_003.ogg` | 0.266s |
| `sfx_wood_015` | `assets/audio/wood/impactWood_light_004.ogg` | 0.266s |
| `sfx_wood_016` | `assets/audio/wood/impactWood_medium_000.ogg` | 0.333s |
| `sfx_wood_017` | `assets/audio/wood/impactWood_medium_001.ogg` | 0.333s |
| `sfx_wood_018` | `assets/audio/wood/impactWood_medium_002.ogg` | 0.333s |
| `sfx_wood_019` | `assets/audio/wood/impactWood_medium_003.ogg` | 0.333s |
| `sfx_wood_020` | `assets/audio/wood/impactWood_medium_004.ogg` | 0.333s |

### `footstep` · 脚步 Footstep（25 个）

| asset id | 文件 | 时长 |
| --- | --- | --- |
| `sfx_footstep_001` | `assets/audio/footstep/footstep_carpet_000.ogg` | 0.145s |
| `sfx_footstep_002` | `assets/audio/footstep/footstep_carpet_001.ogg` | 0.145s |
| `sfx_footstep_003` | `assets/audio/footstep/footstep_carpet_002.ogg` | 0.145s |
| `sfx_footstep_004` | `assets/audio/footstep/footstep_carpet_003.ogg` | 0.145s |
| `sfx_footstep_005` | `assets/audio/footstep/footstep_carpet_004.ogg` | 0.145s |
| `sfx_footstep_006` | `assets/audio/footstep/footstep_concrete_000.ogg` | 0.106s |
| `sfx_footstep_007` | `assets/audio/footstep/footstep_concrete_001.ogg` | 0.108s |
| `sfx_footstep_008` | `assets/audio/footstep/footstep_concrete_002.ogg` | 0.113s |
| `sfx_footstep_009` | `assets/audio/footstep/footstep_concrete_003.ogg` | 0.110s |
| `sfx_footstep_010` | `assets/audio/footstep/footstep_concrete_004.ogg` | 0.114s |
| `sfx_footstep_011` | `assets/audio/footstep/footstep_grass_000.ogg` | 0.778s |
| `sfx_footstep_012` | `assets/audio/footstep/footstep_grass_001.ogg` | 0.674s |
| `sfx_footstep_013` | `assets/audio/footstep/footstep_grass_002.ogg` | 0.692s |
| `sfx_footstep_014` | `assets/audio/footstep/footstep_grass_003.ogg` | 0.669s |
| `sfx_footstep_015` | `assets/audio/footstep/footstep_grass_004.ogg` | 0.590s |
| `sfx_footstep_016` | `assets/audio/footstep/footstep_snow_000.ogg` | 0.374s |
| `sfx_footstep_017` | `assets/audio/footstep/footstep_snow_001.ogg` | 0.374s |
| `sfx_footstep_018` | `assets/audio/footstep/footstep_snow_002.ogg` | 0.374s |
| `sfx_footstep_019` | `assets/audio/footstep/footstep_snow_003.ogg` | 0.374s |
| `sfx_footstep_020` | `assets/audio/footstep/footstep_snow_004.ogg` | 0.374s |
| `sfx_footstep_021` | `assets/audio/footstep/footstep_wood_000.ogg` | 0.250s |
| `sfx_footstep_022` | `assets/audio/footstep/footstep_wood_001.ogg` | 0.252s |
| `sfx_footstep_023` | `assets/audio/footstep/footstep_wood_002.ogg` | 0.251s |
| `sfx_footstep_024` | `assets/audio/footstep/footstep_wood_003.ogg` | 0.252s |
| `sfx_footstep_025` | `assets/audio/footstep/footstep_wood_004.ogg` | 0.248s |

### `ui` · 界面 UI（100 个）

| asset id | 文件 | 时长 |
| --- | --- | --- |
| `sfx_ui_001` | `assets/audio/ui/back_001.ogg` | 0.064s |
| `sfx_ui_002` | `assets/audio/ui/back_002.ogg` | 0.070s |
| `sfx_ui_003` | `assets/audio/ui/back_003.ogg` | 0.093s |
| `sfx_ui_004` | `assets/audio/ui/back_004.ogg` | 0.073s |
| `sfx_ui_005` | `assets/audio/ui/bong_001.ogg` | 0.123s |
| `sfx_ui_006` | `assets/audio/ui/click_001.ogg` | 0.100s |
| `sfx_ui_007` | `assets/audio/ui/click_002.ogg` | 0.010s |
| `sfx_ui_008` | `assets/audio/ui/click_003.ogg` | 0.010s |
| `sfx_ui_009` | `assets/audio/ui/click_004.ogg` | 0.010s |
| `sfx_ui_010` | `assets/audio/ui/click_005.ogg` | 0.010s |
| `sfx_ui_011` | `assets/audio/ui/close_001.ogg` | 0.148s |
| `sfx_ui_012` | `assets/audio/ui/close_002.ogg` | 0.314s |
| `sfx_ui_013` | `assets/audio/ui/close_003.ogg` | 0.314s |
| `sfx_ui_014` | `assets/audio/ui/close_004.ogg` | 0.323s |
| `sfx_ui_015` | `assets/audio/ui/confirmation_001.ogg` | 0.290s |
| `sfx_ui_016` | `assets/audio/ui/confirmation_002.ogg` | 0.539s |
| `sfx_ui_017` | `assets/audio/ui/confirmation_003.ogg` | 0.322s |
| `sfx_ui_018` | `assets/audio/ui/confirmation_004.ogg` | 0.490s |
| `sfx_ui_019` | `assets/audio/ui/drop_001.ogg` | 0.110s |
| `sfx_ui_020` | `assets/audio/ui/drop_002.ogg` | 0.191s |
| `sfx_ui_021` | `assets/audio/ui/drop_003.ogg` | 0.191s |
| `sfx_ui_022` | `assets/audio/ui/drop_004.ogg` | 0.287s |
| `sfx_ui_023` | `assets/audio/ui/error_001.ogg` | 0.165s |
| `sfx_ui_024` | `assets/audio/ui/error_002.ogg` | 0.165s |
| `sfx_ui_025` | `assets/audio/ui/error_003.ogg` | 0.533s |
| `sfx_ui_026` | `assets/audio/ui/error_004.ogg` | 0.103s |
| `sfx_ui_027` | `assets/audio/ui/error_005.ogg` | 0.500s |
| `sfx_ui_028` | `assets/audio/ui/error_006.ogg` | 0.500s |
| `sfx_ui_029` | `assets/audio/ui/error_007.ogg` | 0.192s |
| `sfx_ui_030` | `assets/audio/ui/error_008.ogg` | 0.139s |
| `sfx_ui_031` | `assets/audio/ui/glass_001.ogg` | 0.278s |
| `sfx_ui_032` | `assets/audio/ui/glass_002.ogg` | 0.125s |
| `sfx_ui_033` | `assets/audio/ui/glass_003.ogg` | 0.124s |
| `sfx_ui_034` | `assets/audio/ui/glass_004.ogg` | 0.692s |
| `sfx_ui_035` | `assets/audio/ui/glass_005.ogg` | 0.111s |
| `sfx_ui_036` | `assets/audio/ui/glass_006.ogg` | 0.111s |
| `sfx_ui_037` | `assets/audio/ui/glitch_001.ogg` | 0.020s |
| `sfx_ui_038` | `assets/audio/ui/glitch_002.ogg` | 0.030s |
| `sfx_ui_039` | `assets/audio/ui/glitch_003.ogg` | 0.010s |
| `sfx_ui_040` | `assets/audio/ui/glitch_004.ogg` | 0.023s |
| `sfx_ui_041` | `assets/audio/ui/maximize_001.ogg` | 0.258s |
| `sfx_ui_042` | `assets/audio/ui/maximize_002.ogg` | 0.258s |
| `sfx_ui_043` | `assets/audio/ui/maximize_003.ogg` | 0.212s |
| `sfx_ui_044` | `assets/audio/ui/maximize_004.ogg` | 0.418s |
| `sfx_ui_045` | `assets/audio/ui/maximize_005.ogg` | 0.526s |
| `sfx_ui_046` | `assets/audio/ui/maximize_006.ogg` | 0.380s |
| `sfx_ui_047` | `assets/audio/ui/maximize_007.ogg` | 0.186s |
| `sfx_ui_048` | `assets/audio/ui/maximize_008.ogg` | 0.225s |
| `sfx_ui_049` | `assets/audio/ui/maximize_009.ogg` | 0.225s |
| `sfx_ui_050` | `assets/audio/ui/minimize_001.ogg` | 0.258s |
| `sfx_ui_051` | `assets/audio/ui/minimize_002.ogg` | 0.258s |
| `sfx_ui_052` | `assets/audio/ui/minimize_003.ogg` | 0.212s |
| `sfx_ui_053` | `assets/audio/ui/minimize_004.ogg` | 0.418s |
| `sfx_ui_054` | `assets/audio/ui/minimize_005.ogg` | 0.526s |
| `sfx_ui_055` | `assets/audio/ui/minimize_006.ogg` | 0.380s |
| `sfx_ui_056` | `assets/audio/ui/minimize_007.ogg` | 0.186s |
| `sfx_ui_057` | `assets/audio/ui/minimize_008.ogg` | 0.225s |
| `sfx_ui_058` | `assets/audio/ui/minimize_009.ogg` | 0.225s |
| `sfx_ui_059` | `assets/audio/ui/open_001.ogg` | 0.148s |
| `sfx_ui_060` | `assets/audio/ui/open_002.ogg` | 0.314s |
| `sfx_ui_061` | `assets/audio/ui/open_003.ogg` | 0.314s |
| `sfx_ui_062` | `assets/audio/ui/open_004.ogg` | 0.323s |
| `sfx_ui_063` | `assets/audio/ui/pluck_001.ogg` | 0.102s |
| `sfx_ui_064` | `assets/audio/ui/pluck_002.ogg` | 0.165s |
| `sfx_ui_065` | `assets/audio/ui/question_001.ogg` | 0.491s |
| `sfx_ui_066` | `assets/audio/ui/question_002.ogg` | 0.333s |
| `sfx_ui_067` | `assets/audio/ui/question_003.ogg` | 0.332s |
| `sfx_ui_068` | `assets/audio/ui/question_004.ogg` | 0.332s |
| `sfx_ui_069` | `assets/audio/ui/scratch_001.ogg` | 0.139s |
| `sfx_ui_070` | `assets/audio/ui/scratch_002.ogg` | 0.139s |
| `sfx_ui_071` | `assets/audio/ui/scratch_003.ogg` | 0.123s |
| `sfx_ui_072` | `assets/audio/ui/scratch_004.ogg` | 0.325s |
| `sfx_ui_073` | `assets/audio/ui/scratch_005.ogg` | 0.325s |
| `sfx_ui_074` | `assets/audio/ui/scroll_001.ogg` | 1.000s |
| `sfx_ui_075` | `assets/audio/ui/scroll_002.ogg` | 1.000s |
| `sfx_ui_076` | `assets/audio/ui/scroll_003.ogg` | 1.000s |
| `sfx_ui_077` | `assets/audio/ui/scroll_004.ogg` | 1.000s |
| `sfx_ui_078` | `assets/audio/ui/scroll_005.ogg` | 1.000s |
| `sfx_ui_079` | `assets/audio/ui/select_001.ogg` | 0.043s |
| `sfx_ui_080` | `assets/audio/ui/select_002.ogg` | 0.043s |
| `sfx_ui_081` | `assets/audio/ui/select_003.ogg` | 0.383s |
| `sfx_ui_082` | `assets/audio/ui/select_004.ogg` | 0.383s |
| `sfx_ui_083` | `assets/audio/ui/select_005.ogg` | 0.383s |
| `sfx_ui_084` | `assets/audio/ui/select_006.ogg` | 1.944s |
| `sfx_ui_085` | `assets/audio/ui/select_007.ogg` | 0.047s |
| `sfx_ui_086` | `assets/audio/ui/select_008.ogg` | 0.047s |
| `sfx_ui_087` | `assets/audio/ui/switch_001.ogg` | 0.618s |
| `sfx_ui_088` | `assets/audio/ui/switch_002.ogg` | 0.611s |
| `sfx_ui_089` | `assets/audio/ui/switch_003.ogg` | 0.500s |
| `sfx_ui_090` | `assets/audio/ui/switch_004.ogg` | 0.500s |
| `sfx_ui_091` | `assets/audio/ui/switch_005.ogg` | 0.612s |
| `sfx_ui_092` | `assets/audio/ui/switch_006.ogg` | 0.611s |
| `sfx_ui_093` | `assets/audio/ui/switch_007.ogg` | 0.614s |
| `sfx_ui_094` | `assets/audio/ui/tick_001.ogg` | 0.023s |
| `sfx_ui_095` | `assets/audio/ui/tick_002.ogg` | 0.023s |
| `sfx_ui_096` | `assets/audio/ui/tick_004.ogg` | 0.055s |
| `sfx_ui_097` | `assets/audio/ui/toggle_001.ogg` | 0.139s |
| `sfx_ui_098` | `assets/audio/ui/toggle_002.ogg` | 0.139s |
| `sfx_ui_099` | `assets/audio/ui/toggle_003.ogg` | 0.139s |
| `sfx_ui_100` | `assets/audio/ui/toggle_004.ogg` | 0.066s |

### `soft` · 轻柔 Soft（10 个）

| asset id | 文件 | 时长 |
| --- | --- | --- |
| `sfx_soft_001` | `assets/audio/soft/impactSoft_heavy_000.ogg` | 0.505s |
| `sfx_soft_002` | `assets/audio/soft/impactSoft_heavy_001.ogg` | 0.572s |
| `sfx_soft_003` | `assets/audio/soft/impactSoft_heavy_002.ogg` | 0.572s |
| `sfx_soft_004` | `assets/audio/soft/impactSoft_heavy_003.ogg` | 0.544s |
| `sfx_soft_005` | `assets/audio/soft/impactSoft_heavy_004.ogg` | 0.501s |
| `sfx_soft_006` | `assets/audio/soft/impactSoft_medium_000.ogg` | 0.118s |
| `sfx_soft_007` | `assets/audio/soft/impactSoft_medium_001.ogg` | 0.183s |
| `sfx_soft_008` | `assets/audio/soft/impactSoft_medium_002.ogg` | 0.135s |
| `sfx_soft_009` | `assets/audio/soft/impactSoft_medium_003.ogg` | 0.140s |
| `sfx_soft_010` | `assets/audio/soft/impactSoft_medium_004.ogg` | 0.147s |

### `imported` · 导入 Imported（0 个）

本地暂无文件。

## 写进 Timeline JSON

音效就是 `type=audio` 元素，靠轨道区分用途（BGM→A1，人声→A2，音效→A3）。
`volume` 等于 1 时不写，`fade` 只写非零的那一侧——这是稀疏原则。

```json
{
  "id": "audio_001",
  "type": "audio",
  "track": "A3",
  "asset": "sfx_impact_001",
  "start": 1.2,
  "duration": 0.6,
  "source": {
    "start": 0.0,
    "end": 0.6
  },
  "volume": 0.8,
  "fade": {
    "in": 0.05,
    "out": 0.15
  }
}
```

Remotion 侧由 `remotion/src/elements/AudioLayer.tsx` 执行：`volume` 是基础音量，
`fade.in` / `fade.out` 换算成帧后用 volume 回调做线性淡入淡出。

## 全局输出音量

`meta.master_volume` 是整片输出音量，缺省 1（等于默认值时不落盘），范围 0~4，0 = 整片静音。
最终音量 = 元素 `volume` × fade 系数 × `meta.master_volume`。

注意：预览窗口**没有音频通路**，所以播放器上的音量 / 静音控件调的是导出音量，
改了以后预览听不出区别，要在渲染出的 MP4 上验证。
