# 素材来源与授权

本目录下所有素材都可以商用，无需署名。两类来源：

## 一、CC0 下载素材（Kenney，Creative Commons CC0 1.0）

CC0 = 放弃全部著作权，可任意使用、修改、商用，无需署名。

- `audio/impact/`、`audio/glass/`、`audio/metal/`、`audio/wood/`、`audio/soft/`、`audio/footstep/`
  共 130 个文件，来自 Kenney「Impact Sounds」
  https://kenney.nl/assets/impact-sounds
- `audio/ui/`
  共 100 个文件，来自 Kenney「Interface Sounds」
  https://kenney.nl/assets/interface-sounds

授权原文：https://creativecommons.org/publicdomain/zero/1.0/

原始压缩包内的 `license.txt` 与作者说明可在 Kenney 页面查看。
按素材类别拆分到了不同子目录，文件本身未做任何修改。

## 二、本机用 FFmpeg 合成的素材（无版权问题）

由程序化波形 / 图形生成，不含任何第三方素材，因此不涉及授权。

- `audio/whoosh/`　甩镜音：`whoosh_short_01`、`whoosh_long_01`、`swish_01`
- `audio/riser/`　　上升与下降音：`riser_up_01`、`downlifter_01`
- `audio/boom/`　　低频冲击：`boom_low_01`、`boom_punch_01`
- `transitions/flash/`　　闪白 `flash_white.webm`
- `transitions/lightleak/`　暖色漏光横扫 `light_leak_warm.webm`
- `transitions/streak/`　　速度线 `speed_lines.webm`
- `transitions/glitch/`　　故障条带 `glitch_bars.webm`
- `transitions/dust/`　　　粉尘闪点 `dust_sparkle.webm`
- `transitions/filmburn/`　胶片烧灼扩散环 `film_burn.webm`
- `videos/demo/`、`audio/bgm/`、`audio/impact/impact_01.wav`、`overlays/arrow/`
  Demo 项目用的演示素材，同样是本机生成

`transitions/` 下的 webm 都是 VP9 + Alpha（容器里 `alpha_mode=1`），
可以直接当叠加素材压在画面上；注意 ffprobe 对这类文件的 `pix_fmt` 仍显示 `yuv420p`，
判断是否带透明要看 `alpha_mode` 标签。

## 三、再补素材时的建议来源

都是可商用且有明确授权的站点：

- Kenney https://kenney.nl/assets?category=Audio 　CC0，游戏音效为主，适合做 UI / 冲击音
- Freesound https://freesound.org 　按单个文件看授权，CC0 与 CC-BY 混杂，下载前先确认
- Pixabay https://pixabay.com/sound-effects/ 　自有授权，可商用免署名
- Mixkit https://mixkit.co/free-sound-effects/ 　免费可商用，禁止转售素材本身
- Archive.org https://archive.org 　公共领域内容多，但需逐个核对

下载后放进 `assets/` 对应目录，或者直接用 GUI 的「素材 → 导入素材文件」，
再把来源与授权补记到本文件里。
