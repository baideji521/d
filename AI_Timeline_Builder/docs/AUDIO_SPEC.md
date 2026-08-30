# AUDIO_SPEC —— 音频

实现在 `core/timeline.py`（默认值与 `make_audio`）、`core/sparse.py`（落盘规则）、
`remotion/src` 的 AudioLayer / VideoLayer 与 `masterVolume()`。

## 两种声源

1. **video 元素内嵌音轨** —— 字段 `audio = {enabled, volume}`，
   默认 `{enabled: true, volume: 1.0}`。
2. **独立 audio 元素** —— 放 `A1`（背景音乐）/ `A2`（人声）/ `A3`（音效）轨，
   字段 `volume`（默认 1.0）、`fade = {in, out}`（默认 `{0,0}`）、
   `source = {start, end}` 指定用素材的哪一段。

## 全局输出音量

`meta.master_volume`，默认 1.0，范围 0..4（Schema 与 Runtime 一致）。
元素音量与全局音量**相乘**。

- 这是**导出音量**：预览没有音频通路（本工程不做音频解码播放），
  预览面板那个滑块改的就是 `meta.master_volume`。
- `0` 表示整片静音，是有意义的设置，必须落盘；等于 1 时不落盘。

## 稀疏规则里的陷阱

`volume: 0`、`audio.enabled: false`、`master_volume: 0` 都**不是**「没设置」。
省略只在「值 == 默认值」时发生，所以这些值一定会写进 JSON。
反过来，`volume: 1` / `fade: {in:0,out:0}` 必须被删掉。

## 真实验证口径

音频是否真的生效，只认 ffmpeg 实测：

- `mean_volume`（volumedetect）—— 应当出声的成片必须高于 -50 dB；
  声明静音的必须测不到可听信号。
- `astats` —— 逐通道统计，写进 `out/acceptance/reports/AUDIO_ANALYSIS.md`。
- 同一条时间线只改 `meta.master_volume` 渲两份，比响度差 —— 这是全局音量生效的证据。

fixture 探针（`python tools/build_fixtures.py probe`）会为每份成片记录
`has_audio_stream` / `mean_volume`，并按 JSON 推出的「该不该出声」判定。
