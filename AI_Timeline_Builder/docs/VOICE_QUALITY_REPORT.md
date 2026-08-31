# 英文女声配音质量报告

所有数字来自实跑（Windows SAPI 真合成 + ffprobe + Remotion 渲染）。
**系统正确性**与**音质**分开判定：架构通了不等于声音好听，
这一点指令第三十九条要求如实分开写。

## 1. 这次用的是什么

- provider：`system`（系统自带语音（Windows SAPI））
- 档位：`female_energetic`
- 语言：en-US
- 性别：female
- 音色：Microsoft Zira Desktop
- 文案：`And this is the exact moment everything goes completely wrong!`

本机可用的 en-US 音色：

- Microsoft Zira Desktop（en-US / Female）

## 2. 档位参数落地情况（不伪装）

- 真的生效：speed, pause
- **被忽略**：pitch, style, emotion, energy

能力表：

- `supports_word_timestamps`：**不支持**
- `supports_speed`：支持
- `supports_pitch`：**不支持**
- `supports_style`：**不支持**
- `supports_emotion`：**不支持**
- `supports_energy`：**不支持**
- `supports_ssml`：**不支持**

系统语音只有 Rate（语速）。情绪 / 音高 / 风格 / 能量这几维在它上面**根本不存在**，所以档位里那些数值这次没有生效 —— 它们进了 ignored 列表，而不是被悄悄塞进请求里假装调过。接云端 provider（能力表里这几项为真）时，同一个档位会自动开始生效，上层一行都不用改。

## 3. 合成产物（实测）

- 文件：`assets\audio\tts\voice_en_female.wav`
- 时长：3.413741s
- 采样率 / 声道：22050Hz / 1ch（pcm_s16le）
- 体积：150592 字节
- 平均响度：-19.9dB

## 4. 逐词时间戳

- 来源：`estimated`
- 词数：11
- 标记：FALLBACK_ALIGNMENT

`FALLBACK_ALIGNMENT`：Windows SAPI **不返回**逐词时间戳，所以这份时间戳是按字符数比例估算的（长词占的时间多、标点后留停顿）。
它够做逐词高亮字幕（差几十毫秒看不出来），**不够做口型对齐**。
接了能返回真实时间戳的 provider 后，`timing_source` 会变成 `provider`，这个标记自动消失。

前几个词的实际时间戳：

```json
[
  {"text": "And", "start": 0.5, "end": 0.69},
  {"text": "this", "start": 0.69, "end": 0.943},
  {"text": "is", "start": 0.943, "end": 1.069},
  {"text": "the", "start": 1.069, "end": 1.259},
  {"text": "exact", "start": 1.259, "end": 1.575},
  {"text": "moment", "start": 1.575, "end": 1.954},
  …
]
```

## 5. VoicePlan（导演层，不进 Timeline）

- 段数：1

1. `And this is the exact moment everything goes completely wrong!` → 情绪 shock / 强度 0.9 / 语速 1.102

这些字段**没有一个**出现在 Timeline JSON 里 —— Timeline 只有 `asset` / `start` / `duration` / 字幕时间。

## 6. 真实渲染闭环

- 时间线：`voice_en_female.json`，校验 通过
- 成片：`out\acceptance\render\voice\voice_en_female.mp4`
- 画面：1080×1920，132 帧，4.4s
- 响度：-21.5dB，非预期黑帧 0
- 探针 failures：（无）

## 7. 已知局限（不当 PASS）

1. **音质**：Windows SAPI 的 Zira 是 2013 年前后的拼接式合成，念英文清楚但**没有真正的激情起伏**。要「爆点解说」那种效果必须接云端 provider。本轮判定是 `ARCHITECTURE PASS + QUALITY LIMITATION`。
2. **逐词时间戳是估算**（见第 4 节），不可用于口型对齐。
3. **云端 provider 没有实跑**：`CloudVoiceProvider` 是适配器基类，本仓库没有任何凭据，`available()` 为 False。它的价值是把接入点固定下来，不是「已经支持云端 TTS」。
4. 情绪 / 音高 / 风格这三维在本机 provider 上**完全没有生效**（第 2 节）。
5. 断句与情绪判定是启发式（标点 + 全大写 + 转折词表），不是语义理解；对短视频口播够用，对文学文本会判得很粗。

