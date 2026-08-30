"""TimelineModel 的 API 测试。

对应指令第五 / 六 / 七 / 九条：
- 模型是 GUI 与 JSON 之间的唯一中介，所有改动都必须经过它的方法
- 每种元素类型的创建 / 读取 / 修改 / 删除都要能走通
- 非法输入不许把异常抛给 GUI，必须变成结构化错误
"""

from __future__ import annotations

import copy

import pytest

from core import timeline as tl
from core.migrations import detect_version


# ---------------------------------------------------------------- 基础

def test_新模型是空项目(model):
    assert model.elements() == []
    assert detect_version(model.timeline) == 1
    assert model.timeline["time_unit"] == "seconds"
    assert model.tracks(), "默认轨道必须存在"


def test_to_dict_是深拷贝(model, timeline):
    model.set_timeline(timeline)
    exported = model.to_dict()
    exported["elements"][0]["start"] = 999.0
    assert model.get_element("clip_001")["start"] == 0.0, "改导出结果不该影响模型"


def test_from_dict_与_to_dict_成对(model, timeline):
    model.from_dict(timeline, "灌入")
    assert len(model.elements()) == 2
    again = model.to_dict()
    model.from_dict(again, "再灌一次")
    assert len(model.elements()) == 2


def test_from_dict_吃_v2_文档会自动降级(model, timeline):
    from core.migrations import migrate_v1_to_v2

    model.from_dict(migrate_v1_to_v2(timeline), "吃 v2")
    assert detect_version(model.timeline) == 1, "运行时仍然是 v1"
    clip = model.get_element("clip_001")
    assert clip["start"] == 0.0 and clip["duration"] == 5.0, "扁平时间已还原"
    assert clip["source"] == {"start": 0.0, "end": 5.0}


def test_to_v2_dict_给出_v2_视图(model, timeline):
    model.set_timeline(timeline)
    v2 = model.to_v2_dict()
    assert detect_version(v2) == 2
    assert v2["elements"][0]["timing"] == {"start": 0.0, "duration": 5.0}


def test_降级丢分组时报告里必须写明(model, timeline):
    """v1 没有 group 概念，丢是允许的，静默丢不行（指令第三十三条）。"""
    from core.migrations import migrate_v1_to_v2

    v2 = migrate_v1_to_v2(timeline)
    v2["elements"][0]["group"] = "grp_001"
    report = model.from_dict(v2, "吃带分组的 v2")
    losses = report.get("downgrade_losses") or []
    assert [item["field"] for item in losses] == ["group"], \
        f"降级损失没被报出来：{sorted(report)}"
    assert losses[0]["element"] == "clip_001"


def test_无损降级时不写多余的损失字段(model, timeline):
    from core.migrations import migrate_v1_to_v2

    report = model.from_dict(migrate_v1_to_v2(timeline), "吃 v2")
    assert "downgrade_losses" not in report



# ---------------------------------------------------------------- Video

def test_video_增删改查(model):
    element = tl.make_video("clip_001", "video_001", "V1", start=1.0, source_start=0.0, source_end=4.0)
    new_id = model.add_element(element)
    assert new_id == "clip_001"

    got = model.get_element("clip_001")
    assert got["type"] == "video"
    assert got["timing"] if False else got["start"] == 1.0   # v1 运行时是扁平的
    assert got["source"] == {"start": 0.0, "end": 4.0}
    # 没动过 transform → JSON 里没有这个字段，但生效值仍是 1.0
    assert "transform" not in got
    assert model.get_effective_transform(got)["scale"] == 1.0

    model.set_element_field("clip_001", ["transform", "scale"], 1.5)
    assert model.get_element("clip_001")["transform"]["scale"] == 1.5

    model.remove_element("clip_001")
    assert model.get_element("clip_001") is None


def test_video_移动会改开始时间与轨道(model, timeline):
    model.set_timeline(timeline)
    model.move_element("clip_001", 3.0, "V2")
    clip = model.get_element("clip_001")
    assert clip["start"] == 3.0
    assert clip["track"] == "V2"


def test_video_裁剪会同步_source_区间(model, timeline):
    model.set_timeline(timeline)
    # clip_001: start=0 duration=5 source 0→5
    model.resize_element("clip_001", 1.0, 3.0)
    clip = model.get_element("clip_001")
    assert clip["start"] == 1.0
    assert clip["duration"] == 3.0
    assert clip["source"]["start"] == 1.0, "左边缘右移，源起点同步右移"
    assert clip["source"]["end"] == 4.0


def test_改速度后成片时长重算(model, timeline):
    model.set_timeline(timeline)
    model.set_element_field("clip_001", ["speed"], 2.0)
    assert model.get_element("clip_001")["duration"] == 2.5, "源 5 秒 2 倍速 = 成片 2.5 秒"


def test_update_element_批量改顶层字段只压一次撤销(model, timeline):
    model.set_timeline(timeline)
    before = model.can_undo()
    assert model.update_element("clip_001", {"label": "开场", "z_index": 5}, "改两个字段")
    clip = model.get_element("clip_001")
    assert clip["label"] == "开场" and clip["z_index"] == 5
    model.undo()
    clip = model.get_element("clip_001")
    assert "label" not in clip and "z_index" not in clip, "一次撤销要把两个字段都撤掉"
    assert before or True


def test_update_element_对不存在的元素返回_False(model):
    assert model.update_element("没有这个元素", {"label": "x"}) is False


def test_duplicate_element_接在原元素后面(model, timeline):
    model.set_timeline(timeline)
    new_id = model.duplicate_element("clip_001")
    clone = model.get_element(new_id)
    assert new_id != "clip_001"
    assert clone["start"] == 5.0, "复制品紧接原元素之后"
    assert clone["asset"] == "video_001"


# ---------------------------------------------------------------- Image / Overlay

def test_overlay_的_timing_asset_transform(model):
    element = tl.make_overlay("overlay_001", "image_001", "V3", start=2.0, duration=0.8)
    model.add_element(element)
    got = model.get_element("overlay_001")
    assert got["asset"] == "image_001"
    assert (got["start"], got["duration"]) == (2.0, 0.8)
    assert "transform" not in got, "默认 transform 不进 JSON"
    for key in ("x", "y", "scale", "rotation", "opacity"):
        assert key in model.get_effective_transform(got)
    assert "source" not in got


def test_overlay_可以改_transform_各分量(model):
    model.add_element(tl.make_overlay("overlay_001", "image_001"))
    for key, value in (("x", 0.7), ("y", 0.4), ("scale", 1.2), ("rotation", 10.0), ("opacity", 0.5)):
        model.set_element_field("overlay_001", ["transform", key], value)
    transform = model.get_element("overlay_001")["transform"]
    assert transform == {"x": 0.7, "y": 0.4, "scale": 1.2, "rotation": 10.0, "opacity": 0.5}


# ---------------------------------------------------------------- Audio

def test_audio_的_timing_source_volume_fade(model):
    element = tl.make_audio("audio_001", "audio_001", "A1", start=0.0, duration=4.0, volume=0.8)
    model.add_element(element)
    got = model.get_element("audio_001")
    assert got["type"] == "audio"
    assert got["volume"] == 0.8
    assert got["source"]["start"] == 0.0

    model.set_element_field("audio_001", ["fade", "in"], 0.3)
    model.set_element_field("audio_001", ["fade", "out"], 0.5)
    assert model.get_element("audio_001")["fade"] == {"in": 0.3, "out": 0.5}


def test_audio_裁剪也同步_source(model):
    model.add_element(tl.make_audio("audio_001", "audio_001", "A1", start=0.0, duration=4.0))
    model.resize_element("audio_001", 0.0, 2.0)
    got = model.get_element("audio_001")
    assert got["duration"] == 2.0
    assert got["source"]["end"] == 2.0


# ---------------------------------------------------------------- Text

def test_text_的_content_style_timing(model):
    model.add_element(tl.make_text("text_001", "WHAT?!", "T2", start=8.0, duration=1.0))
    got = model.get_element("text_001")
    assert got["content"]["text"] == "WHAT?!"
    assert (got["start"], got["duration"]) == (8.0, 1.0)

    model.set_element_field("text_001", ["content", "text"], "改了")
    model.set_element_field("text_001", ["style", "fontSize"], 120)
    model.set_element_field("text_001", ["style", "stroke", "width"], 6)
    got = model.get_element("text_001")
    assert got["content"]["text"] == "改了"
    assert got["style"]["fontSize"] == 120
    assert got["style"]["stroke"]["width"] == 6


# ---------------------------------------------------------------- Caption

def test_caption_与_caption_group_是两种元素(model):
    model.add_element(tl.make_caption("caption_001", "一句字幕", "T1", start=1.0, duration=2.0))
    words = [
        {"text": "What", "start": 5.0, "end": 5.3},
        {"text": "are", "start": 5.3, "end": 5.6},
        {"text": "you", "start": 5.6, "end": 6.1},
    ]
    model.add_element(tl.make_caption_group("captiongroup_001", words, "T1"))

    caption = model.get_element("caption_001")
    group = model.get_element("captiongroup_001")
    assert caption["type"] == "caption" and group["type"] == "caption_group"
    assert group["content"]["words"] == words
    assert group["start"] == 5.0
    assert group["duration"] == pytest.approx(1.1, abs=1e-3)


def test_caption_group_整体平移时逐词时间同步搬走(model):
    words = [
        {"text": "a", "start": 5.0, "end": 5.5},
        {"text": "b", "start": 5.5, "end": 6.0},
    ]
    model.add_element(tl.make_caption_group("captiongroup_001", words, "T1"))
    model.move_element("captiongroup_001", 7.0)
    moved = model.get_element("captiongroup_001")["content"]["words"]
    assert moved[0]["start"] == 7.0 and moved[0]["end"] == 7.5
    assert moved[1]["start"] == 7.5 and moved[1]["end"] == 8.0


def test_caption_可改样式与高亮(model):
    model.add_element(tl.make_caption("caption_001", "字幕", "T1", start=1.0, duration=2.0))
    model.set_element_field("caption_001", ["caption_style"], "karaoke")
    model.set_element_field("caption_001", ["highlight", "color"], "#FF0000")
    got = model.get_element("caption_001")
    assert got["caption_style"] == "karaoke"
    assert got["highlight"]["color"] == "#FF0000"


# ---------------------------------------------------------------- Freeze

def test_freeze_的_target_source_time_timing(model, timeline):
    model.set_timeline(timeline)
    model.add_element(tl.make_freeze("freeze_001", "clip_001", source_time=2.0, start=5.0, duration=1.5))
    got = model.get_element("freeze_001")
    assert got["target"] == "clip_001"
    assert got["source_time"] == 2.0
    assert (got["start"], got["duration"]) == (5.0, 1.5)


def test_删除视频会级联删掉引用它的_freeze(model, timeline):
    model.set_timeline(timeline)
    model.add_element(tl.make_freeze("freeze_001", "clip_001", 2.0, 5.0, 1.5))
    model.remove_element("clip_001")
    assert model.get_element("freeze_001") is None


# ---------------------------------------------------------------- Effect

def test_add_effect_与_remove_effect(model, timeline):
    model.set_timeline(timeline)
    effect_id = model.add_effect(
        "zoom", {"scale_from": 1.0, "scale_to": 1.35},
        start=2.0, duration=0.6, target="clip_001", easing="easeOut",
    )
    effect = model.get_element(effect_id)
    assert effect["type"] == "effect"
    assert effect["name"] == "zoom"
    assert effect["params"]["scale_to"] == 1.35
    assert effect["easing"] == "easeOut"
    assert effect["target"] == "clip_001"
    assert (effect["start"], effect["duration"]) == (2.0, 0.6)

    assert model.effects(target="clip_001") and len(model.effects()) == 1
    assert model.remove_effect(effect_id) is True
    assert model.get_element(effect_id) is None


def test_remove_effect_不会误删别的类型(model, timeline):
    model.set_timeline(timeline)
    assert model.remove_effect("clip_001") is False
    assert model.get_element("clip_001") is not None


def test_删除视频会级联删掉针对它的特效(model, timeline):
    model.set_timeline(timeline)
    effect_id = model.add_effect("shake", {}, start=1.0, duration=0.3, target="clip_001")
    model.remove_element("clip_001")
    assert model.get_element(effect_id) is None


# ---------------------------------------------------------------- Transition

def test_add_transition_与_remove_transition(model, timeline):
    model.set_timeline(timeline)
    transition_id = model.add_transition(
        "whip", "clip_001", "clip_002", start=4.5, duration=0.5,
        params={"direction": "left", "intensity": 0.8},
    )
    transition = model.get_element(transition_id)
    assert transition["type"] == "transition"
    assert transition["name"] == "whip"
    assert transition["from"] == "clip_001"
    assert transition["to"] == "clip_002"
    assert (transition["start"], transition["duration"]) == (4.5, 0.5)
    assert transition["params"]["direction"] == "left"

    assert len(model.transitions()) == 1
    assert model.remove_transition(transition_id) is True
    assert model.get_element(transition_id) is None


def test_删除任一侧片段都会级联删掉转场(model, timeline):
    model.set_timeline(timeline)
    transition_id = model.add_transition("fade", "clip_001", "clip_002", 4.5, 0.5)
    model.remove_element("clip_002")
    assert model.get_element(transition_id) is None


# ---------------------------------------------------------------- 关键帧

def test_关键帧增删改(model, timeline):
    model.set_timeline(timeline)
    model.add_keyframe("clip_001", "scale", 0.0, 1.0)
    model.add_keyframe("clip_001", "scale", 0.6, 1.35, easing="easeOut")
    keyframes = model.get_element("clip_001")["keyframes"]["scale"]
    assert [k["time"] for k in keyframes] == [0.0, 0.6]

    model.update_keyframe("clip_001", "scale", 1, 0.4, 1.2, "linear")
    keyframes = model.get_element("clip_001")["keyframes"]["scale"]
    assert keyframes[1] == {"time": 0.4, "value": 1.2, "easing": "linear"}

    model.remove_keyframe("clip_001", "scale", 1)
    assert len(model.get_element("clip_001")["keyframes"]["scale"]) == 1


def test_同一时间点的关键帧会被覆盖而不是叠加(model, timeline):
    model.set_timeline(timeline)
    model.add_keyframe("clip_001", "scale", 0.3, 1.0)
    model.add_keyframe("clip_001", "scale", 0.3, 2.0)
    keyframes = model.get_element("clip_001")["keyframes"]["scale"]
    assert len(keyframes) == 1 and keyframes[0]["value"] == 2.0


def test_白名单外的关键帧参数被拒绝(model, timeline):
    model.set_timeline(timeline)
    model.add_keyframe("clip_001", "不存在的参数", 0.0, 1.0)
    assert "不存在的参数" not in (model.get_element("clip_001").get("keyframes") or {})


# ---------------------------------------------------------------- 撤销 / 重做

def test_撤销重做覆盖增删改(model, timeline):
    model.set_timeline(timeline)
    model.add_element(tl.make_text("text_001", "hi", "T2", start=1.0, duration=1.0))
    assert len(model.elements()) == 3
    model.undo()
    assert len(model.elements()) == 2
    model.redo()
    assert len(model.elements()) == 3

    model.move_element("clip_001", 2.0)
    assert model.get_element("clip_001")["start"] == 2.0
    model.undo()
    assert model.get_element("clip_001")["start"] == 0.0


def test_撤销后选中失效会被清理(model, timeline):
    model.set_timeline(timeline)
    new_id = model.add_element(tl.make_text("text_001", "hi", "T2", start=1.0, duration=1.0))
    assert model.selected_id == new_id
    model.undo()
    assert model.get_element(new_id) is None
    assert model.selected_id != new_id


# ---------------------------------------------------------------- 选中

def test_单选多选与全选(model, timeline):
    model.set_timeline(timeline)
    model.select("clip_001")
    assert model.selection() == ["clip_001"]

    model.toggle_select("clip_002")
    assert model.selection() == ["clip_001", "clip_002"]
    model.toggle_select("clip_001")
    assert model.selection() == ["clip_002"]

    model.select_all()
    assert set(model.selection()) == {"clip_001", "clip_002"}

    model.select_many(["clip_001", "根本不存在"])
    assert model.selection() == ["clip_001"], "不存在的 id 要被过滤掉"


# ---------------------------------------------------------------- 校验打通

def test_模型能直接给出结构化报告(model, timeline, validator):
    model.set_validator(validator)
    model.set_timeline(timeline)
    report = model.validate_report()
    assert report == {"valid": True, "version": 1, "errors": [], "warnings": []}


def test_没注入校验器时_validate_不炸(model, timeline):
    model.set_timeline(timeline)
    assert model.validate() == []
    assert model.validate_report()["valid"] is True


def test_语义错误进_errors_警告进_warnings(model, timeline, validator):
    model.set_validator(validator)
    model.set_timeline(timeline)
    model.set_element_field("clip_001", ["asset"], "不存在的素材")
    report = model.validate_report()
    assert report["valid"] is False
    assert any(e["rule"] == "RULE_ASSET_001" for e in report["errors"])
    assert all(e["element"] == "clip_001" for e in report["errors"])


# ---------------------------------------------------------------- 非法 JSON 不许崩

ILLEGAL_CASES = {
    "type 不存在": lambda d: d["elements"][0].__setitem__("type", "不存在的类型"),
    "duration 是字符串": lambda d: d["elements"][0].__setitem__("duration", "五秒"),
    "duration 为负": lambda d: d["elements"][0].__setitem__("duration", -1.0),
    "duration 为零": lambda d: d["elements"][0].__setitem__("duration", 0.0),
    "start 为负": lambda d: d["elements"][0].__setitem__("start", -3.0),
    "缺少 required": lambda d: d["elements"][0].pop("id"),
    "asset 不存在": lambda d: d["elements"][0].__setitem__("asset", "不存在的素材"),
    "transform 不是对象": lambda d: d["elements"][0].__setitem__("transform", "缩放一点"),
    "tracks 为空": lambda d: d.__setitem__("tracks", []),
    "elements 不是数组": lambda d: d.__setitem__("elements", {}),
    "meta 缺 fps": lambda d: d["meta"].pop("fps"),
}


@pytest.mark.parametrize("label", sorted(ILLEGAL_CASES))
def test_非法_JSON_只产出结构化错误不抛异常(validator, timeline, label):
    broken = copy.deepcopy(timeline)
    ILLEGAL_CASES[label](broken)
    report = validator.validate_report(broken)   # 不许抛
    assert report["valid"] is False, f"{label} 应该被判为不合规"
    assert report["errors"], f"{label} 没给出任何错误"
    for error in report["errors"]:
        assert set(error) == {"rule", "element", "path", "message"}
        assert isinstance(error["message"], str) and error["message"]


def test_未知字段_v1_放过_v2_拦下(validator, timeline):
    """已知且刻意保留的差异，见 SCHEMA_V2_MIGRATION_GAPS.md。

    v1 的 element 定义没有 additionalProperties:false（一旦打开，
    历史项目里所有还没纳入 v2 的字段会被一次性误杀），
    严格化由 v2 承担。
    """
    from core.migrations import migrate_v1_to_v2

    broken = copy.deepcopy(timeline)
    broken["elements"][0]["莫名字段"] = 1
    assert validator.validate_report(broken)["valid"] is True, "v1 目前放过未知字段"

    upgraded = migrate_v1_to_v2(broken)
    assert validator.validate_report(upgraded)["valid"] is False, "v2 必须拦下"


def test_引用不存在的_target_与_transition_两端(validator, timeline):
    broken = copy.deepcopy(timeline)
    broken["elements"].append(tl.make_effect("e", "zoom", {}, start=1.0, target="没有这个元素"))
    broken["elements"].append(tl.make_transition("tr1", "fade", "没有", "clip_002", 4.5, 0.5, {}))
    broken["elements"].append(tl.make_transition("tr2", "fade", "clip_001", "也没有", 4.5, 0.5, {}))
    report = validator.validate_report(broken)
    # transition 两端缺失是 error，effect 的 target 缺失按 rules.json 定为 warning
    assert "RULE_TRANSITION_001" in {e["rule"] for e in report["errors"]}
    assert "RULE_EFFECT_002" in {w["rule"] for w in report["warnings"]}
    assert report["valid"] is False


@pytest.mark.parametrize("garbage", [None, [], "字符串", 42, True])
def test_连_dict_都不是的输入也不许崩(validator, garbage):
    report = validator.validate_report(garbage)
    assert report["valid"] is False
    assert report["errors"][0]["rule"] == "SCHEMA"


def test_坏_JSON_灌进模型不会崩(model, timeline, validator):
    """JSON 面板粘一段坏数据的场景。

    两条要求同时成立：
    1. set_timeline() 返回**对原始输入**的结构化错误（净化之前校验）
    2. 进了模型之后，数值字段已被压成真数字 —— 界面在 paintEvent 里
       对它做算术不会抛异常。PyQt 槽里抛异常会直接把进程带走（0xC0000409）。
    """
    model.set_validator(validator)
    broken = copy.deepcopy(timeline)
    broken["elements"][0]["duration"] = "五秒"
    report = model.set_timeline(broken, "灌入坏 JSON")

    assert report["valid"] is False
    assert report["errors"][0]["rule"] == "SCHEMA"
    assert report["errors"][0]["element"] == "clip_001"

    loaded = model.get_element("clip_001")
    assert isinstance(loaded["duration"], (int, float)), "脏值必须被压成数字"
    assert model.duration >= 0, "总时长推导不许抛异常"


@pytest.mark.parametrize(
    "field, garbage",
    [
        ("duration", "五秒"),
        ("start", None),
        ("speed", "两倍"),
        ("duration", [1, 2]),
        ("start", {"a": 1}),
    ],
)
def test_各种脏数值都能被压平(model, timeline, field, garbage):
    broken = copy.deepcopy(timeline)
    broken["elements"][0][field] = garbage
    model.set_timeline(broken, "灌脏值")
    value = model.get_element("clip_001")[field]
    assert isinstance(value, (int, float))


def test_嵌套脏数值也能被压平(model, timeline):
    broken = copy.deepcopy(timeline)
    broken["elements"][0]["source"] = {"start": "零", "end": "五"}
    broken["elements"][0]["transform"] = {"scale": "大一点"}
    broken["elements"][0]["keyframes"] = {"scale": [{"time": "零", "value": "一"}]}
    model.set_timeline(broken, "灌嵌套脏值")
    clip = model.get_element("clip_001")
    assert clip["source"] == {"start": 0.0, "end": 0.0}
    assert clip["transform"]["scale"] == 0.0
    assert clip["keyframes"]["scale"][0] == {"time": 0.0, "value": 0.0}


def test_结构本身坏掉也不崩(model):
    model.set_timeline({"elements": "不是数组", "tracks": "也不是数组"}, "结构全坏")
    assert model.elements() == []
    assert model.tracks(), "轨道会回落到默认值"
    assert model.duration == 0.0
