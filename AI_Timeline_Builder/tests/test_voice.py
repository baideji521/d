"""core/voice.py 的测试。

重点不是「能不能出声」（那要真机 Windows TTS），而是：

1. Provider 接口是**可替换**的：换一家 TTS 不需要动上层链路；
2. 逐词时间戳的来源必须如实标注（estimated / provider），不许假装真实；
3. words → caption_group 的产物必须能过 Validator；
4. provider 做不到的参数要能被列出来，不许悄悄忽略。
"""

from __future__ import annotations

import pytest

from core import voice as vc


# ---------------------------------------------------------------- 时间戳估算

def test_估算的词覆盖整段时长():
    words = vc.estimate_word_timestamps("This is absolutely crazy", 2.0)
    assert [w["text"] for w in words] == ["This", "is", "absolutely", "crazy"]
    assert words[0]["start"] == 0.0
    assert words[-1]["end"] == pytest.approx(2.0)
    # 严格递增、首尾相接
    for previous, current in zip(words, words[1:]):
        assert previous["end"] == pytest.approx(current["start"])


def test_长词占的时间更多():
    words = vc.estimate_word_timestamps("a absolutely", 1.0)
    short = words[0]["end"] - words[0]["start"]
    long = words[1]["end"] - words[1]["start"]
    assert long > short


def test_能从偏移量开始():
    words = vc.estimate_word_timestamps("hello world", 1.0, start=5.0)
    assert words[0]["start"] == 5.0
    assert words[-1]["end"] == pytest.approx(6.0)


def test_没有内容就不造数据():
    assert vc.estimate_word_timestamps("", 2.0) == []
    assert vc.estimate_word_timestamps("hi", 0.0) == []
    assert vc.estimate_word_timestamps("hi", -1.0) == []


def test_中文按字切():
    words = vc.split_words("你好 world!")
    assert words == ["你", "好", "world", "!"]


# ---------------------------------------------------------------- 字幕组

def test_逐词时间戳能变成_caption_group(validator, timeline):
    words = vc.estimate_word_timestamps("THIS IS ABSOLUTELY CRAZY", 1.6, start=1.0)
    element = vc.words_to_caption_group(words, "captiongroup_001")
    assert element["type"] == "caption_group"
    assert element["start"] == pytest.approx(1.0)
    assert element["duration"] == pytest.approx(1.6)

    timeline["elements"].append(element)
    errors = validator.errors_only(timeline)
    assert errors == [], "\n".join(i.display() for i in errors)


def test_强调只落在高亮样式上不污染_word(validator, timeline):
    """v1 schema 的 word 只允许 text / start / end，往里塞字段会被 Schema 拦下。"""
    words = vc.estimate_word_timestamps("THIS IS IT", 1.0)
    element = vc.words_to_caption_group(words, "captiongroup_001", emphasis=["THIS"])
    assert all(set(w) == {"text", "start", "end"} for w in element["content"]["words"])
    assert element["highlight"]["scale"] > 1.0

    timeline["elements"].append(element)
    assert validator.errors_only(timeline) == []


def test_空词表返回空_dict():
    assert vc.words_to_caption_group([]) == {}
    assert vc.words_to_caption_group([{"text": "  ", "start": 0, "end": 1}]) == {}


# ---------------------------------------------------------------- Provider

def test_系统_provider_已注册():
    assert "system" in vc.provider_ids()
    assert isinstance(vc.get_provider(), vc.SystemVoiceProvider)
    assert vc.get_provider("不存在的家") is None


def test_系统_provider_如实说自己没有逐词时间戳():
    provider = vc.get_provider("system")
    assert provider.supports_word_timestamps is False
    assert provider.get_styles() == ["natural"], "系统 TTS 没有风格概念，不许虚报"


def test_做不到的参数会被列出来():
    provider = vc.get_provider("system")
    request = vc.VoiceRequest(text="hi", style="dramatic", emotion="excited", pitch=3.0)
    missing = provider.unsupported(request)
    assert set(missing) >= {"style", "emotion", "pitch"}
    # 默认值不算「用户要求过」
    assert vc.get_provider("system").unsupported(vc.VoiceRequest(text="hi")) == []


def test_空文本直接失败且不产生文件():
    result = vc.get_provider("system").generate(vc.VoiceRequest(text="   "))
    assert result.ok is False
    assert result.audio_path == ""
    assert result.error


def test_可以插入第三方_provider_而不动上层():
    """这是这一层存在的理由：换 TTS 不改链路。"""

    class FakeCloudProvider(vc.VoiceProvider):
        id = "fake_cloud"
        label = "假云端 TTS（测试用）"
        supports_word_timestamps = True
        supported_params = ("voice_id", "language", "style", "emotion", "speed")

        def generate(self, request):
            return vc.VoiceResult(
                True,
                audio_path="assets/audio/tts/fake.wav",
                duration=1.0,
                words=[
                    {"text": "This", "start": 0.0, "end": 0.18},
                    {"text": "is", "start": 0.18, "end": 0.29},
                ],
                timing_source="provider",
                provider=self.id,
            )

        def get_voices(self, language: str = ""):
            return [{"name": "Aria", "culture": "en-US", "gender": "female"}]

    vc.register_provider(FakeCloudProvider())
    try:
        provider = vc.get_provider("fake_cloud")
        result = provider.generate(vc.VoiceRequest(text="This is", style="dramatic"))
        assert result.timing_source == "provider"
        element = vc.words_to_caption_group(result.words, "captiongroup_001")
        assert [w["text"] for w in element["content"]["words"]] == ["This", "is"]
        assert provider.unsupported(vc.VoiceRequest(text="x", style="dramatic")) == []
        assert {p["id"] for p in vc.catalog()} >= {"system", "fake_cloud"}
    finally:
        vc._PROVIDERS.pop("fake_cloud", None)


def test_参数白名单与风格表覆盖指令要求():
    assert set(vc.VOICE_PARAMS) >= {
        "provider", "voice_id", "language", "gender", "style",
        "emotion", "speed", "pitch", "stability", "similarity",
    }
    assert {"energetic", "excited", "dramatic", "friendly", "natural", "calm",
            "storytelling"} <= set(vc.STYLES)
    assert ("en-US", "en-GB") == vc.PRIMARY_LANGUAGES
    assert "female" in vc.GENDERS
