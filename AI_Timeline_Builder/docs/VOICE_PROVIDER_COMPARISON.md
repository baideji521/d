# 配音方案对比（真机实测）

生成时间：2026-08-31 21:53:18　脚本：`out/acceptance/voice_ab.py`

每个音色都用同样 6 段英文文本真合成一次（共 30 条，成功 30 条），
指标全部由 ffmpeg 的 `astats` / `ebur128` / `silencedetect` 量出来，
原始数据在 `out/acceptance/reports/voice_ab.json`，音频在 `out/acceptance/render/voice_ab/`。

**「像不像真人」是主观的，本文件不打主观分**：只给客观量 + 引擎类型，
结论那一节说清每个量意味着什么。

## 1. 六段测试文本

- **普通解说**：`Okay, let's see what happens here.`
- **惊讶**：`Wait, what?! No way this actually worked!`
- **高潮**：`And then, out of nowhere, everything completely changed!`
- **快速连续解说**：`So she picks the red one…`
- **情绪转折**：`At first, everything looked completely normal. But then… things got really weird.`
- **TikTok 风格**：`Bro, there is absolutely no way this is about to happen.`

## 2. 汇总（6 段的平均值）

### Microsoft Zira Desktop（SAPI 拼接合成（离线））

- provider：`system`　成功 6/6
- 平均时长 4.2s　平均语速 3.18 词/秒（扣掉静音）
- 集成响度 -20.4 LUFS　响度范围 LRA 3.9 LU　平均 RMS -21.23 dB
- 最大真峰值 -3.5 dBFS　削波条数 0
- 静音占比 0.36　单条合成耗时 0.87s
- 时间戳来源 estimated　词表自检 通过

### en-US-AvaNeural（Edge 神经网络（Expressive / Caring））

- provider：`edge`　成功 6/6
- 平均时长 3.66s　平均语速 3.31 词/秒（扣掉静音）
- 集成响度 -20.93 LUFS　响度范围 LRA 0.83 LU　平均 RMS -21.77 dB
- 最大真峰值 -3.7 dBFS　削波条数 0
- 静音占比 0.27　单条合成耗时 3.46s
- 时间戳来源 sentence　词表自检 通过

### en-US-EmmaNeural（Edge 神经网络（Cheerful / Clear））

- provider：`edge`　成功 6/6
- 平均时长 3.15s　平均语速 3.29 词/秒（扣掉静音）
- 集成响度 -17.9 LUFS　响度范围 LRA 7.03 LU　平均 RMS -18.18 dB
- 最大真峰值 -3.4 dBFS　削波条数 0
- 静音占比 0.17　单条合成耗时 3.04s
- 时间戳来源 sentence　词表自检 通过

### en-US-AriaNeural（Edge 神经网络（Positive / Confident））

- provider：`edge`　成功 6/6
- 平均时长 4.08s　平均语速 3.06 词/秒（扣掉静音）
- 集成响度 -20.25 LUFS　响度范围 LRA 1.15 LU　平均 RMS -22.05 dB
- 最大真峰值 -2.2 dBFS　削波条数 0
- 静音占比 0.32　单条合成耗时 3.7s
- 时间戳来源 sentence　词表自检 通过

### en-US-JennyNeural（Edge 神经网络（Friendly / Considerate））

- provider：`edge`　成功 6/6
- 平均时长 4.08s　平均语速 3.41 词/秒（扣掉静音）
- 集成响度 -21.2 LUFS　响度范围 LRA 1.38 LU　平均 RMS -22.67 dB
- 最大真峰值 -1.1 dBFS　削波条数 0
- 静音占比 0.38　单条合成耗时 3.39s
- 时间戳来源 sentence　词表自检 通过

## 3. 逐条明细

| 音色 | 用例 | 时长 s | LUFS | LRA | 真峰 dBFS | RMS dB | 静音占比 | 词/秒 | 合成耗时 s | 时间戳 |
|---|---|---|---|---|---|---|---|---|---|---|
| Microsoft Zira Desktop | 普通解说 | 3.034 | -21.4 | 20.0 | -3.9 | -22.04 | 0.381 | 3.2 | 0.88 | estimated |
| Microsoft Zira Desktop | 惊讶 | 4.434 | -20.2 | 0.5 | -3.5 | -21.64 | 0.462 | 2.93 | 0.87 | estimated |
| Microsoft Zira Desktop | 高潮 | 4.554 | -20.1 | 0.9 | -3.5 | -20.55 | 0.345 | 2.68 | 0.86 | estimated |
| Microsoft Zira Desktop | 快速连续解说 | 2.364 | -19.9 | 0.0 | -4.1 | -21.54 | 0.314 | 3.7 | 0.83 | estimated |
| Microsoft Zira Desktop | 情绪转折 | 6.643 | -20.2 | 1.2 | -4.6 | -20.75 | 0.377 | 2.9 | 0.89 | estimated |
| Microsoft Zira Desktop | TikTok 风格 | 4.149 | -20.6 | 0.8 | -3.9 | -20.88 | 0.279 | 3.68 | 0.87 | estimated |
| en-US-AvaNeural | 普通解说 | 2.208 | -21.7 | 0.0 | -3.9 | -22.44 | 0.256 | 3.65 | 4.53 | sentence |
| en-US-AvaNeural | 惊讶 | 3.6 | -20.6 | 1.0 | -4.3 | -21.73 | 0.299 | 2.77 | 3.95 | sentence |
| en-US-AvaNeural | 高潮 | 4.248 | -21.0 | 1.7 | -3.7 | -21.54 | 0.278 | 2.61 | 2.98 | sentence |
| en-US-AvaNeural | 快速连续解说 | 1.992 | -21.4 | 0.0 | -4.9 | -22.47 | 0.288 | 4.23 | 3.13 | sentence |
| en-US-AvaNeural | 情绪转折 | 6.192 | -21.0 | 1.5 | -5.3 | -21.67 | 0.284 | 2.71 | 3.17 | sentence |
| en-US-AvaNeural | TikTok 风格 | 3.696 | -19.9 | 0.8 | -4.8 | -20.77 | 0.233 | 3.88 | 3.01 | sentence |
| en-US-EmmaNeural | 普通解说 | 2.136 | -18.2 | 0.0 | -4.2 | -18.71 | 0.166 | 3.37 | 3.18 | sentence |
| en-US-EmmaNeural | 惊讶 | 3.144 | -18.3 | 20.0 | -5.2 | -18.97 | 0.257 | 3.0 | 3.08 | sentence |
| en-US-EmmaNeural | 高潮 | 3.336 | -17.2 | 20.2 | -5.4 | -17.13 | 0.103 | 2.67 | 3.2 | sentence |
| en-US-EmmaNeural | 快速连续解说 | 1.776 | -18.3 | 0.0 | -4.3 | -18.93 | 0.186 | 4.15 | 2.86 | sentence |
| en-US-EmmaNeural | 情绪转折 | 5.04 | -17.7 | 1.1 | -4.3 | -17.72 | 0.203 | 2.99 | 2.91 | sentence |
| en-US-EmmaNeural | TikTok 风格 | 3.456 | -17.7 | 0.9 | -3.4 | -17.62 | 0.102 | 3.54 | 2.99 | sentence |
| en-US-AriaNeural | 普通解说 | 2.952 | -21.1 | 0.0 | -3.5 | -22.83 | 0.366 | 3.2 | 4.58 | sentence |
| en-US-AriaNeural | 惊讶 | 4.512 | -19.3 | 1.2 | -2.2 | -21.66 | 0.413 | 2.64 | 3.35 | sentence |
| en-US-AriaNeural | 高潮 | 4.176 | -20.5 | 2.5 | -4.7 | -21.99 | 0.266 | 2.61 | 3.25 | sentence |
| en-US-AriaNeural | 快速连续解说 | 2.472 | -20.7 | 0.0 | -3.9 | -23.06 | 0.345 | 3.71 | 2.88 | sentence |
| en-US-AriaNeural | 情绪转折 | 6.264 | -20.1 | 1.5 | -3.8 | -21.49 | 0.332 | 2.87 | 3.16 | sentence |
| en-US-AriaNeural | TikTok 风格 | 4.128 | -19.8 | 1.7 | -3.4 | -21.27 | 0.205 | 3.35 | 4.96 | sentence |
| en-US-JennyNeural | 普通解说 | 2.928 | -21.4 | 0.0 | -3.8 | -22.86 | 0.378 | 3.29 | 3.46 | sentence |
| en-US-JennyNeural | 惊讶 | 4.512 | -21.2 | 1.2 | -3.6 | -23.42 | 0.509 | 3.16 | 3.2 | sentence |
| en-US-JennyNeural | 高潮 | 4.176 | -21.2 | 2.5 | -2.0 | -22.08 | 0.261 | 2.59 | 4.56 | sentence |
| en-US-JennyNeural | 快速连续解说 | 2.376 | -21.3 | 0.0 | -5.0 | -23.55 | 0.454 | 4.63 | 3.01 | sentence |
| en-US-JennyNeural | 情绪转折 | 6.312 | -20.9 | 2.2 | -1.1 | -22.03 | 0.366 | 3.0 | 2.93 | sentence |
| en-US-JennyNeural | TikTok 风格 | 4.2 | -21.2 | 2.4 | -5.0 | -22.08 | 0.307 | 3.78 | 3.17 | sentence |

## 4. 这些数说明什么

- **响度**：Edge 这几个神经网络音色的集成响度在 -21.2 ~ -17.9 LUFS，最响的是 `en-US-EmmaNeural`（-17.9 LUFS）。短视频平台一般按 -14 LUFS 归一，所以**送进 Remotion 前仍然要过一次响度对齐**，不能指望 TTS 直接给到投放响度。
- **削波**：全部 0 条削波，最大真峰值 -1.1 dBFS —— 没有过载，混音时还有余量。
- **停顿**：静音占比最低的是 `en-US-EmmaNeural`（0.17），SAPI 是 0.36。静音多意味着同样的字要占更长的时间轴，卡点剪辑里更容易和画面错开。
- **速度**：合成耗时最短的是 `Microsoft Zira Desktop`（0.87s/条）；SAPI 离线合成 0.87s/条。Edge 要联网，逐行配音的总时长受网络影响。
- **时间戳**：Edge 的流只给 `SentenceBoundary`（句边界），不给 WordBoundary，所以 `timing_source=sentence`：句子起止是引擎真值，句内每个词仍按字符比例摊开；SAPI 连句边界都没有，只能整段估算（`timing_source=estimated`）。两者都会触发 `voice_compiler` 的 FALLBACK_ALIGNMENT 标记，字幕逐词高亮**在字级别上不是真值**，这一点没有被藏起来。

## 5. 选型建议

- **Primary：Edge 神经网络语音（`en-US-EmmaNeural` 或 `en-US-AvaNeural`）**。理由是客观量更适合短视频：响度更高、静音更少、语速更稳，而且是神经网络合成而不是单元拼接。Emma 更亮更紧凑，Ava 更接近常规解说节奏。
- **Fallback：系统 SAPI（`Microsoft Zira Desktop`）**。它离线、不要 key、不受网络影响，但本机英文只有这一个音色，是拼接式合成，静音占比高、语气平。断网 / 内网环境用它保底。
- **切换方式**：`core/voice.py` 的 `PREFERRED_ORDER = ("edge", "system")` + `best_provider()`。Edge 不可用（没装 edge-tts / 断网）时自动退到 SAPI，**退化会写在 provider 字段里**，不会假装还是神经网络语音。
- **还没有的**：逐词真值时间戳、中文神经网络音色实测、离线神经网络方案（Piper / Coqui-XTTS / Kokoro 本机都没有装，见 `FINAL_PRODUCT_ACCEPTANCE.md`的限制清单）。
