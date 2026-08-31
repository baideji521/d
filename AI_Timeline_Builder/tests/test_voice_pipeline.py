"""VoiceProfile / VoiceDirector / VoicePlanCompiler 的单元测试。

这些用例不跑真实 TTS（真实闭环由 `out/acceptance/voice_pipeline.py` 负责），
只锁三件事：

1. 档位在不同能力的 provider 上**如实汇报哪些参数被忽略**（指令第十条）
2. 导演层的断句 / 情绪 / 强调 / 停顿是确定性的
3. 编译层只往 Timeline 写该写的字段，且 A2 与 T1 共享同一时间基准
"""

from __future__ import annotations

import pytest

from core import editing_planner as ep
from core import voice as voice_mod
from core import voice_compiler as vc
from core import voice_director as vd
from core import voice_profile as vp

TEXT = "And THIS is the exact moment everything goes completely wrong!"


class PoorProvider(voice_mod.VoiceProvider):
    """只会调语速的 provider（就是系统语音那种）。"""

    id = "poor"
    label = "只有语速"
    supports_speed = True

    def available(self) -> bool:
        return True

    def get_voices(self, language: str = ""):
        return [{"name": "Fake Zira", "culture": "en-US", "gender": "Female"}]


class RichProvider(voice_mod.VoiceProvider):
    """什么都支持的 provider（云端那种）。"""

    id = "rich"
    label = "全能"
    supports_speed = True
    supports_pitch = True
    supports_style = True
    supports_emotion = True
    supports_energy = True
    supports_ssml = True
    supports_word_timestamps = True

    def available(self) -> bool:
        return True

    def get_voices(self, language: str = ""):
        return [
            {"name": "male-1", "culture": "en-US", "gender": "Male"},
            {"name": "female-1", "culture": "en-US", "gender": "Female"},
        ]


# ---------------------------------------------------------------- 档位


def test_七个英文女声档位都在且都是英文女声():
    ids = vp.profile_ids()
    assert len(ids) == 7
    for profile in vp.PROFILES:
        assert profile.language.startswith("en")
        assert profile.gender == "female"


def test_能力不足的_provider_必须如实报告被忽略的参数():
    profile = vp.get_profile("female_excited")
    _request, applied, ignored = profile.apply_to(PoorProvider(), TEXT)
    assert "speed" in applied
    # 系统语音没有情绪 / 音高 / 风格，必须出现在 ignored 里而不是悄悄丢掉
    assert {"emotion", "pitch", "style"} <= set(ignored)


def test_能力齐全的_provider_不该有被忽略的参数():
    profile = vp.get_profile("female_excited")
    _request, applied, ignored = profile.apply_to(RichProvider(), TEXT)
    assert ignored == []
    assert {"speed", "pitch", "style", "emotion", "energy"} <= set(applied)


def test_被忽略的参数不会写进请求():
    profile = vp.get_profile("female_suspense")
    request, _applied, _ignored = profile.apply_to(PoorProvider(), TEXT)
    assert request.emotion == ""
    assert request.pitch == 0.0


def test_挑音色优先语言加性别都对得上():
    profile = vp.get_profile("female_casual")
    assert vp.pick_voice_id(RichProvider(), profile) == "female-1"


def test_不认识的档位返回_none_而不是兜底():
    assert vp.get_profile("male_robot") is None


# ---------------------------------------------------------------- 导演


def test_导演按句子断段并标出全大写强调词():
    plan = vd.direct(TEXT, "female_energetic")
    assert plan.segments
    assert "THIS" in plan.emphasis_words()


def test_感叹句判成激动疑问句判成好奇():
    plan = vd.direct("This is amazing! Why did it happen?", "female_casual")
    emotions = [segment.emotion for segment in plan.segments]
    assert "excited" in emotions
    assert "curious" in emotions


def test_关键词能触发_shock():
    plan = vd.direct("Everything goes completely wrong.", "female_casual")
    assert plan.segments[0].emotion == "shock"


def test_转折词开头的段落停顿更长():
    plan = vd.direct("It looked fine. But everything broke.", "female_casual")
    assert plan.segments[1].pause_before > plan.segments[0].pause_before


def test_悬念档的停顿比随意档长():
    calm = vd.direct("One. Two. Three.", "female_casual")
    tense = vd.direct("One. Two. Three.", "female_suspense")
    assert tense.segments[1].pause_before > calm.segments[1].pause_before


def test_长句会在从句处再切开():
    long_text = ("We tried the first approach, then the second one, "
                 "and after that we finally found the real problem.")
    plan = vd.direct(long_text, "female_casual")
    assert len(plan.segments) >= 2
    assert all(len(segment.text.split()) <= vd.MAX_WORDS_PER_SEGMENT + 4
               for segment in plan.segments)


def test_导演层不认识的档位直接报错():
    with pytest.raises(ValueError):
        vd.direct(TEXT, "female_unknown")


def test_计划里有高潮提示():
    plan = vd.direct(TEXT, "female_excited")
    hints = vd.plan_hints(plan)
    assert any(hint["kind"] == "peak" for hint in hints)


def test_voiceplan_不含时间戳():
    """导演层不该假装知道时长 —— 时间戳是合成之后才有的。"""
    plan = vd.direct(TEXT, "female_energetic")
    for segment in plan.to_dict()["segments"]:
        assert "start" not in segment
        assert "end" not in segment


# ---------------------------------------------------------------- 编译


def _fake_result(duration: float = 4.0, source: str = "estimated") -> voice_mod.VoiceResult:
    plan = vd.direct(TEXT, "female_energetic")
    words = voice_mod.estimate_word_timestamps(plan.spoken_text(), duration)
    return voice_mod.VoiceResult(
        True, audio_path="C:/fake/voice.wav", duration=duration,
        words=words, timing_source=source, provider="poor",
    )


def test_编译产出_a2_音频与_t1_逐词字幕():
    plan = vd.direct(TEXT, "female_energetic")
    compiled = vc.compile_plan(plan, _fake_result(), "voice_001", start=2.0)
    kinds = {element["type"]: element for element in compiled.elements}
    assert kinds["audio"]["track"] == vc.VOICE_TRACK
    assert kinds["caption_group"]["track"] == vc.CAPTION_TRACK


def test_音频与字幕共享同一时间基准():
    plan = vd.direct(TEXT, "female_energetic")
    compiled = vc.compile_plan(plan, _fake_result(4.0), "voice_001", start=2.0)
    audio = next(e for e in compiled.elements if e["type"] == "audio")
    group = next(e for e in compiled.elements if e["type"] == "caption_group")
    assert audio["start"] == 2.0
    assert compiled.words[0]["start"] >= 2.0
    assert compiled.words[-1]["end"] <= round(2.0 + 4.0, 3) + 1e-6
    assert group["start"] <= compiled.words[0]["start"]


def test_编译不把_provider_私有参数写进时间线():
    plan = vd.direct(TEXT, "female_excited")
    compiled = vc.compile_plan(plan, _fake_result(), "voice_001")
    for element in compiled.elements:
        assert not {"emotion", "intensity", "stability", "profile", "energy"} & set(element)


def test_估算时间戳会被标成_fallback():
    plan = vd.direct(TEXT, "female_energetic")
    compiled = vc.compile_plan(plan, _fake_result(source="estimated"), "voice_001")
    assert vc.FALLBACK_ALIGNMENT in compiled.flags


def test_provider_给的真实时间戳不打_fallback():
    plan = vd.direct(TEXT, "female_energetic")
    compiled = vc.compile_plan(plan, _fake_result(source="provider"), "voice_001")
    assert vc.FALLBACK_ALIGNMENT not in compiled.flags


def test_高潮编译成_voice_peak_标记():
    plan = vd.direct(TEXT, "female_excited")
    compiled = vc.compile_plan(plan, _fake_result(), "voice_001", start=1.0)
    types = {marker["type"] for marker in compiled.markers}
    assert "voice_peak" in types
    for marker in compiled.markers:
        assert marker["time"] >= 1.0


def test_标记时刻落在对应段落的起点上():
    plan = vd.direct("It looked fine. But everything goes wrong!", "female_excited")
    compiled = vc.compile_plan(plan, _fake_result(3.0), "voice_001")
    spans = {span["segment"]: span for span in compiled.segment_spans}
    for marker in compiled.markers:
        assert any(abs(marker["time"] - span["start"]) < 1e-6 for span in spans.values())


def test_合成失败的结果不许编译():
    plan = vd.direct(TEXT, "female_energetic")
    bad = voice_mod.VoiceResult(False, error="没有可用语音")
    with pytest.raises(ValueError):
        vc.compile_plan(plan, bad, "voice_001")


def test_时长为零不许编译():
    plan = vd.direct(TEXT, "female_energetic")
    empty = voice_mod.VoiceResult(True, audio_path="x.wav", duration=0.0)
    with pytest.raises(ValueError):
        vc.compile_plan(plan, empty, "voice_001")


def test_分词数对不上时退回按比例切并标注():
    plan = vd.direct(TEXT, "female_energetic")
    # 故意给一个词数不匹配的时间戳表
    result = voice_mod.VoiceResult(
        True, audio_path="x.wav", duration=4.0,
        words=[{"text": "And", "start": 0.0, "end": 0.2}],
        timing_source="provider",
    )
    compiled = vc.compile_plan(plan, result, "voice_001")
    assert "SEGMENT_SPAN_APPROXIMATE" in compiled.flags
    assert len(compiled.segment_spans) == len(plan.segments)


# ---------------------------------------------------------------- 标记 → 决策
#
# 指令第十七条：VoiceDirector 不许自己加特效。链路必须是
# voice markers → EditingDecision（白名单）→ EditingPlanner → RuleEngine。


def test_导演层不产出任何特效或元素():
    plan = vd.direct(TEXT, "female_excited")
    payload = plan.to_dict()
    # 计划里只有文案 / 情绪 / 节奏，没有 elements、effects、track 这些渲染概念
    assert not {"elements", "effects", "transitions", "track"} & set(payload)
    for segment in payload.get("segments", []):
        assert not {"effect", "element", "track", "start", "end"} & set(segment)


def test_重音映射出的动作都在白名单里():
    markers = [
        {"time": 1.0, "type": "voice_peak", "label": "THIS"},
        {"time": 3.5, "type": "voice_peak", "label": "wrong"},
    ]
    bundle = ep.decisions_from_voice_markers(markers)
    assert len(bundle.decisions) == 2
    for decision in bundle.decisions:
        assert decision.action in ep.ACTIONS
        assert decision.reason


def test_停顿标记不映射动作只留说明():
    markers = [{"time": 2.0, "type": "voice_pause", "label": "停顿 0.18s"}]
    bundle = ep.decisions_from_voice_markers(markers)
    assert bundle.decisions == []
    assert [n.code for n in bundle.notes] == ["VOICE_MARKER_NO_ACTION"]


def test_挨太近的重音只保留第一个():
    markers = [
        {"time": 1.0, "type": "voice_peak"},
        {"time": 1.1, "type": "voice_peak"},
        {"time": 2.0, "type": "voice_peak"},
    ]
    bundle = ep.decisions_from_voice_markers(markers)
    assert [d.start for d in bundle.decisions] == [1.0, 2.0]
    assert any(n.code == "VOICE_PEAK_TOO_CLOSE" for n in bundle.notes)


def test_重音数量上限生效():
    markers = [{"time": float(i), "type": "voice_peak"} for i in range(5)]
    bundle = ep.decisions_from_voice_markers(markers, limit=2)
    assert len(bundle.decisions) == 2
    assert any(n.code == "VOICE_PEAK_LIMIT" for n in bundle.notes)


def test_配音重音可以额外配音效():
    markers = [{"time": 1.0, "type": "voice_peak"}]
    bundle = ep.decisions_from_voice_markers(markers, with_sfx=True)
    assert [d.action for d in bundle.decisions] == ["zoom", "sfx"]


def test_重音决策经过_planner_与_ruleengine(libraries, validator, timeline):
    """完整走一遍：标记 → 决策 → Planner → Validator（含 RuleEngine）。"""
    from libraries.asset_registry import AssetRegistry

    registry = AssetRegistry(
        [
            {
                "id": "sfx_001",
                "type": "audio",
                "path": "assets/audio/impact/impact_01.wav",
                "name": "impact_01",
                "category": "impact",
                "duration": 1.2,
            }
        ]
    )
    planner = ep.EditingPlanner(
        effects=libraries.effect, transitions=libraries.transition, assets=registry
    )
    markers = [{"time": 1.0, "type": "voice_peak", "label": "THIS"}]
    bundle = ep.decisions_from_voice_markers(markers, with_sfx=True)
    result = planner.plan(timeline, bundle.decisions)
    assert result.ok, result.report()
    kinds = [element["type"] for element in result.elements]
    assert kinds == ["effect", "audio"]
    assert result.elements[0]["name"] == "zoom"
    errors = validator.errors_only(result.timeline)
    assert not errors, [issue.message for issue in errors]


def test_编造的标记类型不会绕过白名单():
    markers = [{"time": 1.0, "type": "make_it_pop"}]
    bundle = ep.decisions_from_voice_markers(markers)
    assert bundle.decisions == []
    assert bundle.notes[0].code == "VOICE_MARKER_NO_ACTION"

