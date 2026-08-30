"""core/timeline.py 的纯函数与工厂测试。

对应指令第五十一条 Test 1（Video）与 Test 2（Overlay）的字段验证，
以及 Keyframe / Easing 的语义 —— 这套语义必须与 Remotion 侧
remotion/src/lib/timeline.ts 完全一致，两边各有一份测试互相对账。
"""

from __future__ import annotations

import pytest

from core import timeline as tl


# ---------------------------------------------------------------- 时间协议

def test_对外协议只用秒():
    data = tl.empty_timeline()
    assert data["time_unit"] == "seconds"
    assert tl.TIME_UNIT == "seconds"
    # 任何工厂产物都不许出现以帧为单位的时间字段
    # （keyframes 里的 frame 只是命名，值仍是秒，所以按整个 key 比对而不是子串）
    banned = {"frame", "from_frame", "durationInFrames", "duration_in_frames", "trimBefore", "trimAfter"}
    for element in (
        tl.make_video("v", "a"),
        tl.make_overlay("o", "a"),
        tl.make_text("t", "hi"),
        tl.make_caption("c", "hi"),
        tl.make_audio("au", "a"),
        tl.make_effect("e", "zoom", {}),
        tl.make_transition("tr", "fade", "v", "v2", 1.0, 0.5, {}),
        tl.make_freeze("f", "v", 1.0, 2.0),
    ):
        offending = banned & set(element.keys())
        assert not offending, f"{element['type']} 出现了帧单位字段 {offending}"


# ---------------------------------------------------------------- Test 1 Video

def test_video_时间线时间与源时间严格分离():
    element = tl.make_video(
        "clip_001", "video_001", track="V1", start=10.0, source_start=20.68, source_end=25.68
    )
    # 成片时间
    assert element["start"] == 10.0
    assert element["duration"] == 5.0
    # 源素材时间，与成片时间无关
    assert element["source"] == {"start": 20.68, "end": 25.68}
    assert tl.element_end(element) == 15.0


def test_video_duration_由源区间与速度推出():
    normal = tl.make_video("v", "a", source_start=0.0, source_end=4.0, speed=1.0)
    fast = tl.make_video("v", "a", source_start=0.0, source_end=4.0, speed=2.0)
    slow = tl.make_video("v", "a", source_start=0.0, source_end=4.0, speed=0.5)
    assert normal["duration"] == 4.0
    assert fast["duration"] == 2.0, "2 倍速时成片时长减半"
    assert slow["duration"] == 8.0, "0.5 倍速时成片时长加倍"


def test_video_只写用户意图不预填默认值():
    """阶段 6.5：工厂不再把 transform / speed / audio / keyframes 预填进 JSON。"""
    element = tl.make_video("clip_001", "video_001")
    assert element["type"] == "video"
    assert element["asset"] == "video_001"
    for absent in ("speed", "audio", "transform", "keyframes"):
        assert absent not in element, f"{absent} 是默认值，不该写进 JSON"
    # 但最终生效值必须一点没变
    assert tl.effective_speed(element) == 1.0
    assert tl.effective_audio(element) == {"enabled": True, "volume": 1.0}
    assert tl.effective_transform(element) == {
        "x": 0.5, "y": 0.5, "scale": 1.0, "rotation": 0.0, "opacity": 1.0
    }
    assert tl.effective_keyframes(element) == {}


def test_video_非默认速度才写进_JSON():
    assert tl.make_video("v", "a", speed=2.0)["speed"] == 2.0
    assert "speed" not in tl.make_video("v", "a", speed=1.0)


# ---------------------------------------------------------------- Test 2 Overlay

def test_overlay_transform_默认时不出现但生效值齐全():
    element = tl.make_overlay("overlay_001", "image_001", track="V3", start=24.0, duration=0.8)
    assert element["type"] == "overlay"
    assert element["start"] == 24.0
    assert element["duration"] == 0.8
    assert "transform" not in element, "没动过 transform 就不该有这个字段"
    for key in ("x", "y", "scale", "rotation", "opacity"):
        assert key in tl.effective_transform(element), f"生效值缺 {key}"
    assert "source" not in element, "Overlay 不该有 source 区间"


# ---------------------------------------------------------------- Test 5 Freeze

def test_freeze_四要素齐全():
    element = tl.make_freeze("freeze_001", target="clip_001", source_time=24.0, start=24.0, duration=1.5)
    assert element["type"] == "freeze"
    assert element["target"] == "clip_001", "冻结哪个素材"
    assert element["source_time"] == 24.0, "冻源素材哪一刻"
    assert element["start"] == 24.0, "成片从哪开始冻"
    assert element["duration"] == 1.5, "冻多久"


# ---------------------------------------------------------------- Test 3 Effect

def test_effect_结构():
    element = tl.make_effect(
        "effect_001", "zoom", {"scale_from": 1.0, "scale_to": 1.35}, start=24.0, duration=0.6,
        target="clip_001", easing="easeOut",
    )
    assert element["type"] == "effect"
    assert element["name"] == "zoom"
    assert element["start"] == 24.0
    assert element["duration"] == 0.6
    assert element["easing"] == "easeOut"
    assert element["target"] == "clip_001"
    assert element["params"]["scale_to"] == 1.35


def test_effect_不指定_target_时不写该字段():
    element = tl.make_effect("effect_002", "shake", {})
    assert "target" not in element


# ---------------------------------------------------------------- Test 4 Transition

def test_transition_必须绑定两个片段():
    element = tl.make_transition(
        "transition_001", "whip", "clip_A", "clip_B", start=4.5, duration=0.5,
        params={"direction": "left", "intensity": 0.8},
    )
    assert element["type"] == "transition"
    assert element["from"] == "clip_A"
    assert element["to"] == "clip_B"
    assert element["start"] == 4.5
    assert element["duration"] == 0.5
    assert element["params"]["direction"] == "left"


# ---------------------------------------------------------------- Test 6 CaptionGroup

def test_caption_group_按首尾词推出时间范围():
    words = [
        {"text": "What", "start": 12.32, "end": 12.60},
        {"text": "are", "start": 12.60, "end": 12.82},
        {"text": "you", "start": 12.82, "end": 13.52},
    ]
    element = tl.make_caption_group("captiongroup_001", words)
    assert element["type"] == "caption_group"
    assert element["start"] == 12.32
    assert element["duration"] == pytest.approx(1.2, abs=1e-3)
    assert element["content"]["words"] == words
    assert element["highlight"]["color"] == "#FFE347"


def test_caption_group_深拷贝_words_不与调用方共享():
    words = [{"text": "a", "start": 0.0, "end": 0.5}]
    element = tl.make_caption_group("cg", words)
    words[0]["text"] = "改了"
    assert element["content"]["words"][0]["text"] == "a"


def test_caption_与_text_是两种类型():
    assert tl.make_caption("c", "hi")["type"] == "caption"
    assert tl.make_text("t", "hi")["type"] == "text"


# ---------------------------------------------------------------- Easing

@pytest.mark.parametrize("easing", tl.EASINGS)
def test_easing_端点固定(easing):
    assert tl.apply_easing(0.0, easing) == 0.0
    assert tl.apply_easing(1.0, easing) == 1.0


def test_easing_中点与越界():
    assert tl.apply_easing(0.5, "linear") == 0.5
    assert tl.apply_easing(0.5, "easeIn") == 0.25
    assert tl.apply_easing(0.5, "easeOut") == 0.75
    assert tl.apply_easing(0.5, "easeInOut") == 0.5
    assert tl.apply_easing(-1.0, "linear") == 0.0
    assert tl.apply_easing(2.0, "linear") == 1.0


# ---------------------------------------------------------------- Keyframe

def test_关键帧时间相对元素起点_区间外端点保持():
    kfs = [
        {"time": 0.0, "value": 1.0},
        {"time": 0.3, "value": 1.35, "easing": "linear"},
        {"time": 0.6, "value": 1.0, "easing": "linear"},
    ]
    assert tl.evaluate_keyframes(kfs, -1.0, 0.0) == 1.0
    assert tl.evaluate_keyframes(kfs, 0.15, 0.0) == pytest.approx(1.175)
    assert tl.evaluate_keyframes(kfs, 0.3, 0.0) == 1.35
    assert tl.evaluate_keyframes(kfs, 9.0, 0.0) == 1.0
    assert tl.evaluate_keyframes([], 0.5, 0.42) == 0.42


def test_resolve_animated_value_优先级():
    element = {"transform": {"scale": 2.0}}
    assert tl.resolve_animated_value(element, "scale", 0.0) == 2.0
    assert tl.resolve_animated_value(element, "rotation", 0.0) == 0.0
    assert tl.resolve_animated_value({}, "scale", 0.0) == 1.0
    assert tl.resolve_animated_value({}, "x", 0.0) == 0.5

    animated = {
        "transform": {"scale": 2.0},
        "keyframes": {"scale": [{"time": 0.0, "value": 1.0}, {"time": 1.0, "value": 3.0}]},
    }
    assert tl.resolve_animated_value(animated, "scale", 0.0) == 1.0
    assert tl.resolve_animated_value(animated, "scale", 0.5) == 2.0


# ---------------------------------------------------------------- 派生信息

def test_总时长是所有元素结束时间的最大值(timeline):
    assert tl.timeline_duration(timeline) == 10.0
    timeline["elements"].append(tl.make_text("text_001", "hi", start=9.0, duration=3.0))
    assert tl.timeline_duration(timeline) == 12.0


def test_轨道顺序决定_z_index(timeline):
    assert tl.track_z_index(timeline, "A1") == 0
    assert tl.track_z_index(timeline, "V1") == 30
    assert tl.track_z_index(timeline, "T2") == 80
    assert tl.track_z_index(timeline, "不存在") == 0


def test_元素_id_不冲突(timeline):
    assert tl.next_element_id(timeline, "video") == "clip_003"
    assert tl.next_element_id(timeline, "effect") == "effect_001"


def test_按轨道取元素并按时间排序(timeline):
    timeline["elements"].insert(0, tl.make_video("clip_003", "video_001", "V1", start=2.0))
    ids = [e["id"] for e in tl.elements_on_track(timeline, "V1")]
    assert ids == ["clip_001", "clip_003", "clip_002"]
    assert tl.elements_on_track(timeline, "A1") == []


def test_元素类型与轨道种类的对应表完整():
    for type_name in tl.ELEMENT_TYPE_LABELS:
        assert type_name in tl.TYPE_TRACK_KIND, f"{type_name} 没有声明允许的轨道种类"
