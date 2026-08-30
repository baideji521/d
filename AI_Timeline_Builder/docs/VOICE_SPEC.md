# VOICE_SPEC —— 配音（TTS）

实现在 `core/voice.py`。设计前提：**不绑定任何一家 TTS**。
`VoiceProvider` 是抽象基类，系统自带的 SAPI 只是其中一个实现
（`SystemVoiceProvider`，包在 `core/tts.py` 外面）。

## 请求参数

`VOICE_PARAMS = provider voice_id language gender style emotion speed pitch
stability similarity`

- 主语言：`PRIMARY_LANGUAGES = en-US, en-GB`（本项目的成片面向英文短视频）。
- `GENDERS = female male neutral`
- `STYLES = natural energetic excited dramatic friendly calm storytelling`

Provider 只声明**自己真的支持**的参数（`supported_params`），
`unsupported(request)` 会把「你传了但我不支持」的参数列出来。
系统 SAPI 的 `get_styles()` 只返回 `["natural"]` —— 不假装支持情绪风格。

## 返回结果

`VoiceResult = {ok, audio_path, duration, words, timing_source, provider, error}`

`timing_source` 是这一层最关键的字段：

- `"engine"` —— 引擎真的给了词级时间戳；
- `"estimated"` —— 由 `estimate_word_timestamps()` 按字符数加权推的
  （标点权重 2.0），**只是估算**。

系统 SAPI 拿不到词级时间戳，所以它的结果永远是 `estimated`。
把估算标成引擎真值属于伪造验证结论，明确禁止。

## 接到时间线上

`words_to_caption_group(words, element_id, track="T1", emphasis=None)`
把词表转成 `caption_group` 元素；词只保留 `text/start/end`，
其它字段不往 JSON 里塞。

配音音频本身按 `audio` 元素放 `A2` 轨（见 AUDIO_SPEC.md）。

## 注册与查询

`register_provider()` / `get_provider(id)` / `provider_ids()` / `catalog()`。
`catalog()` 是给 `docs/AI_CAPABILITIES.json` 用的结构化能力表 ——
AI 只能从这里挑 provider 与参数，不能凭空发明。
