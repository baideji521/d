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


# ---------------------------------------------------------------- Edge provider
# 这一组全部离线可跑：只验能力自述、参数映射与时间戳拼装，不发一个网络请求。


def test_edge_provider_已注册且不抢默认位():
    assert "edge" in vc.provider_ids()
    # 默认仍然是 system：老调用方行为不能被换掉（要 Edge 得显式要）
    assert isinstance(vc.get_provider(), vc.SystemVoiceProvider)
    assert isinstance(vc.get_provider("edge"), vc.EdgeVoiceProvider)


def test_edge_provider_如实声明能力():
    provider = vc.get_provider("edge")
    caps = provider.capabilities()
    # 服务只回句级边界，所以逐词时间戳必须报 False
    assert caps["supports_word_timestamps"] is False
    assert caps["supports_speed"] and caps["supports_pitch"] and caps["supports_energy"]
    # 这条链路不发 SSML，没有 style / emotion，不许虚报
    assert caps["supports_style"] is False and caps["supports_emotion"] is False
    assert caps["supports_ssml"] is False
    assert provider.get_styles() == ["natural"]
    assert provider.requires_network is True and provider.requires_credentials is False


def test_edge_参数映射():
    p = vc.EdgeVoiceProvider
    assert p._rate(1.0) == "+0%" and p._rate(1.08) == "+8%" and p._rate(0.9) == "-10%"
    assert p._pitch(0.0) == "+0Hz" and p._pitch(1.0) == "+12Hz" and p._pitch(-1.0) == "-12Hz"
    # 半音夹在 ±4，换算后再夹到 ±50Hz，不许让音色变形
    assert p._pitch(99.0) == "+48Hz"
    # energy 经 VoiceProfile 映射成 stability = 1 - energy
    assert p._volume(0.5) == "+0%"          # energy 0.5 → 不动
    assert p._volume(0.25) == "+15%"        # energy 0.75 → 更有劲
    assert p._volume(1.0) == "-30%"         # energy 0 → 最轻，且被夹住


def test_edge_空文本直接失败且不联网():
    result = vc.get_provider("edge").generate(vc.VoiceRequest(text="   "))
    assert result.ok is False and result.audio_path == "" and result.error


def test_edge_句级真值撑起句内词时间戳():
    """句边界是引擎给的真值，句内按比例摊开：词不能跨句、末词对齐句尾。"""
    sentences = [
        {"text": "Wait, what?", "start": 0.10, "end": 2.00},
        {"text": "No way this actually worked!", "start": 2.00, "end": 4.45},
    ]
    words = vc.EdgeVoiceProvider._words("Wait, what?! No way this actually worked!", sentences, 4.45)
    assert words, "有句级边界时必须给出逐词时间戳"
    assert words[0]["start"] == 0.10, "第一句要从引擎给的句首开始"
    assert abs(words[-1]["end"] - 4.45) < 1e-6, "末词要严格落在末句句尾"
    for word in words:
        assert word["start"] <= word["end"]
    # 第一句的词不能溢出到第二句里去
    first_sentence = [w for w in words if w["end"] <= 2.0 + 1e-6]
    assert first_sentence, "第一句的词被算到第二句里了"


def test_edge_句子压线时词表仍然单调且不超出音频():
    """真机实测发现的坑：引擎给的句子区间会互相压线、还会超出音频时长。

    这两种情况都会让 caption_group 的逐词高亮来回跳，所以 _words 要收口。
    """
    sentences = [
        {"text": "Wait, what?", "start": 0.10, "end": 2.00},
        {"text": "No way this actually worked!", "start": 1.80, "end": 3.70},
    ]
    words = vc.EdgeVoiceProvider._words("Wait, what?! No way this actually worked!",
                                        sentences, 3.60)
    assert words
    previous = -1.0
    for word in words:
        assert word["start"] <= word["end"], word
        assert word["start"] >= previous - 1e-6, f"词表不单调：{word}"
        previous = word["end"]
    assert words[-1]["end"] <= 3.60 + 1e-6, "末词不许超出音频实际时长"


def test_edge_没有句级边界时退回整段估算():
    words = vc.EdgeVoiceProvider._words("Hello there friend", [], 1.5)
    assert [w["text"] for w in words] == ["Hello", "there", "friend"]
    assert abs(words[-1]["end"] - 1.5) < 1e-6


@pytest.mark.skipif(not vc.get_provider("system").available(), reason="本机没有系统语音合成")
def test_中文目标路径能真的合成出音频(tmp_path):
    """真跑一次 SAPI：中文台词做出来的文件名不能把配音链路打断。

    字幕逐行配音的产物名来自台词本身（core/tts.output_path），
    所以「路径带中文」是常态而不是边角情况。
    """
    target = tmp_path / "中文目录" / "第一行台词.wav"
    result = vc.get_provider("system").generate(
        vc.VoiceRequest(text="Okay, let us see what happens here.", out_path=str(target))
    )
    assert result.ok, result.error
    assert target.is_file() and target.stat().st_size > 1024


def test_首选顺序把_edge_放在_sapi_前面而且兜得住():
    assert vc.PREFERRED_ORDER[0] == "edge" and "system" in vc.PREFERRED_ORDER
    # 一个都不可用时也要给出 system，而不是 None（调用方不必判空）
    assert vc.best_provider(order=("不存在的家",)) is vc.get_provider("system")
    chosen = vc.best_provider()
    assert chosen is not None and chosen.available() or chosen.id == "system"
