"""core/timeline_validator.py 的规则测试。

重点：
1. Schema 校验必须真的在跑 —— 缺 jsonschema 时 _validate_schema() 会静默返回空，
   很容易让「0 问题」变成假象，这里显式断言它是活的。
2. schemas/rules.json 声明的每条规则都要有实现，反之实现里的 id 也要有声明。
"""

from __future__ import annotations

import json
import os

import pytest

from core import timeline as tl
from core import timeline_validator as tv

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def ids_of(issues) -> set:
    return {issue.rule_id for issue in issues}


def find(issues, rule_id: str):
    return [i for i in issues if i.rule_id == rule_id]


# ---------------------------------------------------------------- 前置条件

def test_jsonschema_必须可用否则_schema_校验形同虚设():
    assert tv.HAS_JSONSCHEMA, (
        "缺少 jsonschema 依赖，_validate_schema() 会静默跳过，"
        "校验结果只剩语义规则。请 pip install -r requirements.txt"
    )


def test_validator_加载到了_schema_与规则(validator):
    assert validator.all_rules(), "rules.json 没加载到"
    assert validator._schema, "timeline_schema.json 没加载到"


def test_rules_json_与实现一一对应(validator):
    declared = {rule["id"] for rule in validator.all_rules()}
    source = open(
        os.path.join(ROOT, "core", "timeline_validator.py"), "r", encoding="utf-8"
    ).read()
    for rule_id in declared:
        assert f'"{rule_id}"' in source, f"{rule_id} 在 rules.json 声明了但没实现"


# ---------------------------------------------------------------- 合规基线

def test_干净的时间线没有任何问题(validator, timeline):
    issues = validator.validate(timeline)
    assert issues == [], "\n".join(i.display() for i in issues)


def test_demo_风格的完整时间线也应合规(validator, timeline):
    """把各类元素都放上去，确认互相不打架。"""
    e = timeline["elements"]
    e.append(tl.make_overlay("overlay_001", "image_001", "V3", start=6.0, duration=1.0))
    e.append(tl.make_text("text_001", "WHAT?!", "T2", start=8.0, duration=1.0))
    e.append(tl.make_caption("caption_001", "一句字幕", "T1", start=8.0, duration=1.0))
    e.append(
        tl.make_caption_group(
            "captiongroup_001",
            [
                {"text": "逐", "start": 3.0, "end": 3.3},
                {"text": "词", "start": 3.3, "end": 3.6},
            ],
            "T1",
        )
    )
    e.append(tl.make_audio("audio_001", "audio_001", "A1", start=0.0, duration=10.0))
    e.append(tl.make_audio("audio_002", "sfx_001", "A3", start=8.5, duration=0.5))
    e.append(tl.make_freeze("freeze_001", "clip_002", source_time=2.0, start=9.0, duration=1.0))
    e.append(
        tl.make_effect("effect_001", "zoom", {"scale_from": 1.0, "scale_to": 1.35},
                       track="V1", start=7.0, duration=0.6, target="clip_002")
    )
    e.append(
        tl.make_transition("transition_001", "whip", "clip_001", "clip_002",
                           start=4.5, duration=0.5, params={"direction": "left"})
    )
    issues = validator.validate(timeline)
    assert issues == [], "\n".join(i.display() for i in issues)


# ---------------------------------------------------------------- 时间规则

def test_RULE_TIME_001_禁止帧字段(validator, timeline):
    """time_unit 的取值由 Schema 的 const 兜住，元素里混进 frame 字段则由语义层抓。"""
    timeline["elements"][0]["frame"] = 30
    assert "RULE_TIME_001" in ids_of(validator.validate(timeline))


def test_schema_层兜住_time_unit(validator, timeline):
    timeline["time_unit"] = "frames"
    assert "SCHEMA" in ids_of(validator.validate(timeline))


# 以下几项按指令第二十八条属于 Schema 层职责（字段 / 类型 / enum / 范围），
# rules.json 里的同名规则是语义层的兜底，Schema 可用时先由它拦住。

@pytest.mark.parametrize(
    "mutate, why",
    [
        (lambda e: e.__setitem__("start", -1.0), "start 不得为负"),
        (lambda e: e.__setitem__("duration", 0.0), "duration 必须大于 0"),
        # 阶段 6.5 之后默认 transform 不再预填，这里显式写整个对象
        (lambda e: e.__setitem__("transform", {"scale": 0.0}), "scale 必须大于 0"),
        (lambda e: e.__setitem__("transform", {"opacity": 2.0}), "opacity 上限 1"),
        (lambda e: e.__setitem__("keyframes", {"不存在的参数": [{"time": 0.0, "value": 1.0}]}),
         "keyframes 参数名白名单"),
    ],
)
def test_schema_层兜住数值范围(validator, timeline, mutate, why):
    mutate(timeline["elements"][0])
    assert "SCHEMA" in ids_of(validator.validate(timeline)), why


def test_schema_层兜住音量范围(validator, timeline):
    timeline["elements"].append(
        tl.make_audio("a", "audio_001", "A1", start=0.0, duration=2.0, volume=9.0)
    )
    assert "SCHEMA" in ids_of(validator.validate(timeline))



def test_RULE_VIDEO_003_source_start_必须小于_end(validator, timeline):
    timeline["elements"][0]["source"] = {"start": 5.0, "end": 2.0}
    assert "RULE_VIDEO_003" in ids_of(validator.validate(timeline))


def test_RULE_VIDEO_001_source_end_不得超过素材长度(validator, timeline):
    # 素材 video_001 时长 12 秒
    timeline["elements"][0]["source"] = {"start": 0.0, "end": 20.0}
    timeline["elements"][0]["duration"] = 20.0
    assert "RULE_VIDEO_001" in ids_of(validator.validate(timeline))


def test_RULE_VIDEO_004_duration_与源区间不一致时只是警告(validator, timeline):
    timeline["elements"][0]["duration"] = 4.0  # source 是 0→5
    issues = find(validator.validate(timeline), "RULE_VIDEO_004")
    assert issues, "应该发出 duration 与源区间不一致的提示"
    assert all(not i.is_error() for i in issues), "这条只该是 warning"


# ---------------------------------------------------------------- 素材与轨道

def test_RULE_ASSET_001_asset_必须在素材库里(validator, timeline):
    timeline["elements"][0]["asset"] = "根本不存在的素材"
    assert "RULE_ASSET_001" in ids_of(validator.validate(timeline))


def test_RULE_ASSET_001_缺少_asset(validator, timeline):
    del timeline["elements"][0]["asset"]
    assert "RULE_ASSET_001" in ids_of(validator.validate(timeline))


def test_RULE_TRACK_001_track_必须存在(validator, timeline):
    timeline["elements"][0]["track"] = "V99"
    assert "RULE_TRACK_001" in ids_of(validator.validate(timeline))


def test_RULE_TRACK_002_类型与轨道不匹配只是警告(validator, timeline):
    timeline["elements"][0]["track"] = "A1"  # 视频放音频轨
    issues = find(validator.validate(timeline), "RULE_TRACK_002")
    assert issues
    assert all(not i.is_error() for i in issues)


def test_RULE_TRACK_003_需要落轨的元素缺_track(validator, timeline):
    """阶段 6.5 验收发现：视频元素不写 track 时一条问题都不报。

    时间轴按 track 分道绘制，没有 track 的元素在编辑器里画不出来，
    Z 序也没有依据（Runtime 的 trackZIndex 只会拿到 -1），
    等于用户「丢了一个片段」却什么提示都没有。
    """
    del timeline["elements"][0]["track"]
    issues = find(validator.validate(timeline), "RULE_TRACK_003")
    assert issues, "缺 track 必须给出结构化提示"
    assert all(not i.is_error() for i in issues), "Runtime 仍能渲染，所以是警告不是错误"


def test_effect_transition_没有_track_不该被误报(validator, timeline):
    """effect / transition 本来就不落轨，不能因为新规则被连带误报。"""
    timeline["elements"].append(
        tl.make_transition("tr", "fade", "clip_001", "clip_002", 4.5, 0.5, {})
    )
    timeline["elements"].append(tl.make_effect("fx", "zoom", {}, start=0.0, duration=1.0))
    assert find(validator.validate(timeline), "RULE_TRACK_003") == []


# ---------------------------------------------------------------- 非有限数字

@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_RULE_NUMBER_001_拦住_NaN_与_Infinity(validator, timeline, value):
    """阶段 6.5 验收发现：NaN 能过 Schema，且让后续所有数值检查静默失效。

    NaN 的任何比较都是 False，`duration > 0`、`start + duration <= 总时长`
    这些判断全部「通过」，最后在 Runtime 里变成 NaN 帧数。
    """
    timeline["elements"][0]["duration"] = value
    issues = validator.validate(timeline)
    assert "RULE_NUMBER_001" in ids_of(issues)
    assert any(i.is_error() for i in find(issues, "RULE_NUMBER_001"))


def test_RULE_NUMBER_001_也覆盖嵌套字段(validator, timeline):
    timeline["elements"][0]["transform"] = {"scale": float("nan")}
    assert "RULE_NUMBER_001" in ids_of(validator.validate(timeline))


def test_正常时间线不会误报_RULE_NUMBER_001(validator, timeline):
    assert find(validator.validate(timeline), "RULE_NUMBER_001") == []


# ---------------------------------------------------------------- 时间上界


def test_RULE_TIME_003_拦住天文数字时长(validator, timeline):
    """duration=1e18 能过 Schema（只有 minimum），会让 Runtime 算出 3e19 帧。"""
    timeline["elements"][0]["duration"] = 1e18
    issues = validator.validate(timeline)
    assert "RULE_TIME_003" in ids_of(issues)
    assert all(i.is_error() for i in find(issues, "RULE_TIME_003"))


def test_RULE_TIME_003_也拦_start(validator, timeline):
    timeline["elements"][0]["start"] = 1e9
    assert "RULE_TIME_003" in ids_of(validator.validate(timeline))


def test_RULE_TIME_003_正常时长不报(validator, timeline):
    assert find(validator.validate(timeline), "RULE_TIME_003") == []


def test_RULE_TIME_003_边界值_24小时不报(validator, timeline):
    from core.timeline_validator import MAX_TIMELINE_SECONDS

    timeline["elements"][0]["duration"] = MAX_TIMELINE_SECONDS
    assert find(validator.validate(timeline), "RULE_TIME_003") == []


# ---------------------------------------------------------------- Transition

def test_RULE_TRANSITION_001_from_to_必须指向存在的片段(validator, timeline):
    timeline["elements"].append(
        tl.make_transition("tr", "fade", "clip_001", "根本没有", 4.5, 0.5, {})
    )
    assert "RULE_TRANSITION_001" in ids_of(validator.validate(timeline))


def test_RULE_TRANSITION_002_from_与_to_不得相同(validator, timeline):
    timeline["elements"].append(
        tl.make_transition("tr", "fade", "clip_001", "clip_001", 4.5, 0.5, {})
    )
    assert "RULE_TRANSITION_002" in ids_of(validator.validate(timeline))


def test_RULE_TRANSITION_003_时长过长只是警告(validator, timeline):
    # 两个片段都是 5 秒，转场 4 秒远超一半
    timeline["elements"].append(
        tl.make_transition("tr", "fade", "clip_001", "clip_002", 3.0, 4.0, {})
    )
    issues = find(validator.validate(timeline), "RULE_TRANSITION_003")
    assert issues
    assert all(not i.is_error() for i in issues)


# ---------------------------------------------------------------- Effect / Freeze

def test_RULE_EFFECT_001_特效名必须在库里(validator, timeline):
    timeline["elements"].append(tl.make_effect("e", "根本没这个特效", {}, start=1.0))
    assert "RULE_EFFECT_001" in ids_of(validator.validate(timeline))


def test_RULE_EFFECT_002_target_必须存在(validator, timeline):
    timeline["elements"].append(
        tl.make_effect("e", "zoom", {}, start=1.0, target="不存在的元素")
    )
    assert "RULE_EFFECT_002" in ids_of(validator.validate(timeline))


def test_RULE_FREEZE_001_target_必须指向视频片段(validator, timeline):
    timeline["elements"].append(tl.make_freeze("f", "不存在", 1.0, 6.0))
    assert "RULE_FREEZE_001" in ids_of(validator.validate(timeline))


def test_RULE_FREEZE_002_source_time_必须落在源区间内(validator, timeline):
    # clip_001 的 source 是 0→5，冻 9 秒处不合法
    timeline["elements"].append(tl.make_freeze("f", "clip_001", 9.0, 6.0))
    assert "RULE_FREEZE_002" in ids_of(validator.validate(timeline))


# ---------------------------------------------------------------- 文本与字幕

def test_RULE_TEXT_001_文字不得为空(validator, timeline):
    timeline["elements"].append(tl.make_text("t", "   ", start=1.0))
    assert "RULE_TEXT_001" in ids_of(validator.validate(timeline))


def test_RULE_CAPTION_001_字幕必须有_text_或_words(validator, timeline):
    caption = tl.make_caption("c", "", start=1.0)
    timeline["elements"].append(caption)
    assert "RULE_CAPTION_001" in ids_of(validator.validate(timeline))


def test_RULE_CAPTION_002_逐词时间必须递增不重叠(validator, timeline):
    bad = tl.make_caption_group(
        "cg",
        [
            {"text": "a", "start": 1.0, "end": 2.0},
            {"text": "b", "start": 1.5, "end": 2.5},  # 与上一个重叠
        ],
    )
    timeline["elements"].append(bad)
    assert "RULE_CAPTION_002" in ids_of(validator.validate(timeline))


def test_逐词时间正常时不报错(validator, timeline):
    good = tl.make_caption_group(
        "cg",
        [
            {"text": "What", "start": 1.0, "end": 1.28},
            {"text": "are", "start": 1.28, "end": 1.5},
        ],
    )
    timeline["elements"].append(good)
    assert "RULE_CAPTION_002" not in ids_of(validator.validate(timeline))


# ---------------------------------------------------------------- Keyframe / Transform

def test_RULE_KEYFRAME_001_时间不得超出元素时长(validator, timeline):
    timeline["elements"][0]["keyframes"] = {
        "scale": [{"time": 0.0, "value": 1.0}, {"time": 99.0, "value": 2.0}]
    }
    assert "RULE_KEYFRAME_001" in ids_of(validator.validate(timeline))


# ---------------------------------------------------------------- Audio

def test_RULE_AUDIO_002_淡入淡出总长超过时长时警告(validator, timeline):
    audio = tl.make_audio("a", "audio_001", "A1", start=0.0, duration=1.0)
    audio["fade"] = {"in": 0.8, "out": 0.8}
    timeline["elements"].append(audio)
    issues = find(validator.validate(timeline), "RULE_AUDIO_002")
    assert issues
    assert all(not i.is_error() for i in issues)


# ---------------------------------------------------------------- id 唯一性与定位

def test_RULE_ID_001_id_必须唯一(validator, timeline):
    duplicate = dict(timeline["elements"][0])
    timeline["elements"].append(duplicate)
    assert "RULE_ID_001" in ids_of(validator.validate(timeline))


def test_问题能定位到元素(validator, timeline):
    """语义层与 Schema 层的问题都必须能落到元素 id 上，否则时间线没法标红。"""
    timeline["elements"][0]["asset"] = "不存在的素材"
    assert validator.invalid_element_ids(timeline).get("clip_001") == "error"

    clean = tl.empty_timeline("定位测试")
    clean["elements"].append(tl.make_video("clip_001", "video_001", source_end=5.0))
    clean["elements"][0]["start"] = -5.0  # Schema 层的范围错误
    mapping = validator.invalid_element_ids(clean)
    assert mapping.get("clip_001") == "error", "Schema 错误也要能定位到元素"


def test_errors_only_过滤掉警告(validator, timeline):
    timeline["elements"][0]["duration"] = 4.0  # 只触发 warning
    assert find(validator.validate(timeline), "RULE_VIDEO_004")
    assert validator.errors_only(timeline) == []


# ---------------------------------------------------------------- Schema 层

def test_schema_层能挡住类型错误(validator, timeline):
    timeline["elements"][0]["start"] = "十秒"  # 应该是 number
    assert "SCHEMA" in ids_of(validator.validate(timeline))


def test_schema_层能挡住未知元素类型(validator, timeline):
    timeline["elements"][0]["type"] = "不存在的类型"
    assert "SCHEMA" in ids_of(validator.validate(timeline))


def test_schema_文件本身是合法的_draft7():
    import jsonschema

    for name in sorted(os.listdir(os.path.join(ROOT, "schemas"))):
        if not name.endswith(".json") or name == "rules.json":
            continue
        with open(os.path.join(ROOT, "schemas", name), "r", encoding="utf-8") as handle:
            schema = json.load(handle)
        jsonschema.Draft7Validator.check_schema(schema)
