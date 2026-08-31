"""Timeline DSL v2 的 Schema 与 v1 ⇄ v2 迁移测试。

阶段 5 的定位：v1 仍是运行时格式，v2 是已定稿的目标协议。
所以这里要证明三件事：

1. v2 schema 本身合法，且能严格分派 11 种元素类型
2. 现有 Demo（v1）迁到 v2 后能通过 v2 schema —— 说明 v2 没有误杀已有合法字段
3. v1 → v2 → v1 逐字段无损，不会静默丢字段
"""

from __future__ import annotations

import copy
import json
import os

import jsonschema
import pytest

from core import timeline as tl
from core.migrations import (
    detect_version,
    migrate_to_v1,
    migrate_to_v2,
    migrate_v1_to_v2,
    migrate_v2_to_v1,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
V2_PATH = os.path.join(ROOT, "schemas", "timeline_schema_v2.json")


@pytest.fixture(scope="module")
def v2_schema() -> dict:
    with open(V2_PATH, "r", encoding="utf-8") as handle:
        return json.load(handle)


@pytest.fixture
def v2_validator(v2_schema):
    return jsonschema.Draft7Validator(v2_schema)


def errors_of(v2_validator, document) -> list:
    return [
        f"{'/'.join(str(p) for p in e.absolute_path) or '根'}: {e.message}"
        for e in v2_validator.iter_errors(document)
    ]


@pytest.fixture
def rich_v1() -> dict:
    """一条把 9 种 v1 元素类型全用上的时间线。"""
    data = tl.empty_timeline("完整 Demo")
    e = data["elements"]
    e.append(tl.make_video("clip_001", "video_001", "V1", start=0.0, source_start=0.0, source_end=5.0))
    e.append(tl.make_video("clip_002", "video_002", "V1", start=5.0, source_start=1.5, source_end=6.5, speed=1.0))
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
    e.append(tl.make_audio("audio_002", "sfx_001", "A3", start=8.5, duration=0.5, volume=0.9))
    e.append(tl.make_freeze("freeze_001", "clip_002", source_time=2.0, start=9.0, duration=1.0))
    e.append(
        tl.make_effect("effect_001", "zoom", {"scale_from": 1.0, "scale_to": 1.35},
                       track="V1", start=7.0, duration=0.6, target="clip_002", easing="easeOut")
    )
    e.append(
        tl.make_transition("transition_001", "whip", "clip_001", "clip_002",
                           start=4.5, duration=0.5, params={"direction": "left", "intensity": 0.8})
    )
    return data


# ---------------------------------------------------------------- Schema 本身

def test_v2_schema_是合法的_draft7(v2_schema):
    jsonschema.Draft7Validator.check_schema(v2_schema)


def test_v2_声明了_11_种元素类型(v2_schema):
    variants = v2_schema["definitions"]["element"]["oneOf"]
    names = set()
    for ref in variants:
        key = ref["$ref"].rsplit("/", 1)[-1]
        names.add(v2_schema["definitions"][key]["properties"]["type"]["const"])
    assert names == {
        "video", "image", "overlay", "audio", "text",
        "caption", "caption_group", "freeze", "effect", "transition", "group",
    }


def test_v2_每个元素变体都关掉了未知字段(v2_schema):
    for ref in v2_schema["definitions"]["element"]["oneOf"]:
        key = ref["$ref"].rsplit("/", 1)[-1]
        variant = v2_schema["definitions"][key]
        assert variant.get("additionalProperties") is False, f"{key} 没有关闭 additionalProperties"


def test_v2_版本号锁死为_2(v2_schema):
    assert v2_schema["properties"]["version"]["const"] == 2
    assert v2_schema["properties"]["time_unit"]["const"] == "seconds"


# ---------------------------------------------------------------- 迁移正确性

def test_版本探测():
    assert detect_version({"version": 1}) == 1
    assert detect_version({"version": 2}) == 2
    assert detect_version({}) == 1, "没有 version 的老项目文件按 v1 处理"
    assert detect_version({"version": "坏值"}) == 1


def test_v1_迁到_v2_后能通过_v2_schema(rich_v1, v2_validator):
    upgraded = migrate_v1_to_v2(rich_v1)
    assert errors_of(v2_validator, upgraded) == []


def test_真实_Demo_迁到_v2_也能通过(v2_validator):
    """用磁盘上真实存在的 Demo，而不是测试里造的数据。

    权威副本是 `tests/fixtures/demo_timeline.json`（进版本库、有生成器守着）；
    `remotion/timeline.json` 是最后一次导出的产物，存在就一起验。
    """
    paths = [os.path.join(ROOT, "tests", "fixtures", "demo_timeline.json"),
             os.path.join(ROOT, "remotion", "timeline.json")]
    checked = 0
    for path in paths:
        if not os.path.isfile(path):
            continue
        with open(path, "r", encoding="utf-8") as handle:
            exported = json.load(handle)
        upgraded = migrate_to_v2(exported)
        assert errors_of(v2_validator, upgraded) == [], path
        checked += 1
    assert checked, "两份 Demo JSON 都不在，验收无从谈起"


def test_时间从扁平变成_timing(rich_v1):
    upgraded = migrate_v1_to_v2(rich_v1)
    clip = next(e for e in upgraded["elements"] if e["id"] == "clip_001")
    assert clip["timing"] == {"start": 0.0, "duration": 5.0}
    assert "start" not in clip and "duration" not in clip


def test_source_从_start_end_变成_start_duration(rich_v1):
    upgraded = migrate_v1_to_v2(rich_v1)
    clip = next(e for e in upgraded["elements"] if e["id"] == "clip_002")
    # v1 是 source {start: 1.5, end: 6.5}
    assert clip["source"] == {"start": 1.5, "duration": 5.0}


def test_speed_收进_playback(rich_v1):
    # 阶段 6.5 之后 speed=1 不再写进 v1 JSON，这里显式设一个非默认速度
    for element in rich_v1["elements"]:
        if element["id"] == "clip_001":
            element["speed"] = 2.0
    upgraded = migrate_v1_to_v2(rich_v1)
    clip = next(e for e in upgraded["elements"] if e["id"] == "clip_001")
    assert clip["playback"] == {"speed": 2.0}
    assert "speed" not in clip


def test_effect_平铺字段收进_effect_子对象(rich_v1):
    upgraded = migrate_v1_to_v2(rich_v1)
    effect = next(e for e in upgraded["elements"] if e["id"] == "effect_001")
    assert effect["effect"]["name"] == "zoom"
    assert effect["effect"]["params"]["scale_to"] == 1.35
    assert effect["effect"]["easing"] == "easeOut"
    assert effect["target"] == "clip_002", "target 留在元素上，不进 effect 子对象"
    for dead in ("name", "params", "easing"):
        assert dead not in effect


def test_transition_平铺字段收进_transition_子对象(rich_v1):
    upgraded = migrate_v1_to_v2(rich_v1)
    transition = next(e for e in upgraded["elements"] if e["id"] == "transition_001")
    assert transition["transition"]["name"] == "whip"
    assert transition["transition"]["params"]["direction"] == "left"
    assert transition["from"] == "clip_001"
    assert transition["to"] == "clip_002"
    for dead in ("name", "params"):
        assert dead not in transition


def test_freeze_四要素在_v2_里仍然齐全(rich_v1):
    upgraded = migrate_v1_to_v2(rich_v1)
    freeze = next(e for e in upgraded["elements"] if e["id"] == "freeze_001")
    assert freeze["target"] == "clip_002"
    assert freeze["source_time"] == 2.0
    assert freeze["timing"] == {"start": 9.0, "duration": 1.0}


def test_逐词时间戳在迁移中保持绝对时间(rich_v1):
    upgraded = migrate_v1_to_v2(rich_v1)
    group = next(e for e in upgraded["elements"] if e["id"] == "captiongroup_001")
    assert group["content"]["words"][0] == {"text": "逐", "start": 3.0, "end": 3.3}


def test_缺_track_的手写_v1_会被补上默认轨(v2_validator):
    data = tl.empty_timeline("手写")
    data["elements"].append(
        {"id": "t1", "type": "text", "start": 1.0, "duration": 2.0, "content": {"text": "hi"}}
    )
    upgraded = migrate_v1_to_v2(data)
    assert upgraded["elements"][0]["track"] == "T2"
    assert errors_of(v2_validator, upgraded) == []


# ---------------------------------------------------------------- Round Trip

ROUNDTRIP_KEYS = (
    "id", "type", "track", "start", "duration", "asset", "source", "speed",
    "transform", "keyframes", "audio", "volume", "fade", "content", "style",
    "caption_style", "template", "highlight", "name", "params", "easing",
    "target", "source_time", "from", "to", "label", "note", "z_index", "animation",
)


def test_round_trip_v1_v2_v1_逐字段无损(rich_v1):
    original = copy.deepcopy(rich_v1)
    back = migrate_v2_to_v1(migrate_v1_to_v2(original))

    assert back["version"] == 1
    assert back["time_unit"] == "seconds"
    assert len(back["elements"]) == len(original["elements"])
    assert back["tracks"] == original["tracks"]

    before = {e["id"]: e for e in original["elements"]}
    after = {e["id"]: e for e in back["elements"]}
    assert set(before) == set(after), "元素 id 集合必须一致"

    for element_id, source_element in before.items():
        target = after[element_id]
        # 不允许静默丢字段
        assert set(source_element.keys()) == set(target.keys()), (
            f"{element_id} 字段集合变了：少了 {set(source_element) - set(target)}，"
            f"多了 {set(target) - set(source_element)}"
        )
        for key in ROUNDTRIP_KEYS:
            if key in source_element:
                assert target[key] == source_element[key], f"{element_id}.{key} 往返后变了"


def test_round_trip_v2_v1_v2_稳定(rich_v1, v2_validator):
    once = migrate_v1_to_v2(rich_v1)
    twice = migrate_v1_to_v2(migrate_v2_to_v1(once))
    assert once == twice, "v2 → v1 → v2 必须回到同一份 v2"
    assert errors_of(v2_validator, twice) == []


def test_migrate_to_v2_对已是_v2_的输入是幂等的(rich_v1):
    once = migrate_to_v2(rich_v1)
    assert migrate_to_v2(once) == once


def test_migrate_to_v1_对已是_v1_的输入是幂等的(rich_v1):
    assert migrate_to_v1(rich_v1) == rich_v1


def test_迁移不会改动输入(rich_v1):
    snapshot = copy.deepcopy(rich_v1)
    migrate_v1_to_v2(rich_v1)
    migrate_to_v1(rich_v1)
    assert rich_v1 == snapshot, "迁移必须是纯函数，不许原地改调用方的数据"


# ---------------------------------------------------------------- v2 严格性

def test_v2_拦下未知字段(rich_v1, v2_validator):
    upgraded = migrate_v1_to_v2(rich_v1)
    upgraded["elements"][0]["effect_name"] = "zoom"   # 阶段 4 清掉的那个死字段
    assert errors_of(v2_validator, upgraded), "v2 必须拦下未声明的字段"


def test_v2_拦下扁平时间(rich_v1, v2_validator):
    upgraded = migrate_v1_to_v2(rich_v1)
    upgraded["elements"][0]["start"] = 0.0   # v2 只认 timing.start
    assert errors_of(v2_validator, upgraded)


def test_v2_拦下缺少必填项(rich_v1, v2_validator):
    upgraded = migrate_v1_to_v2(rich_v1)
    del upgraded["elements"][0]["source"]
    assert errors_of(v2_validator, upgraded)


def test_v2_拦下未知元素类型(rich_v1, v2_validator):
    upgraded = migrate_v1_to_v2(rich_v1)
    upgraded["elements"][0]["type"] = "不存在的类型"
    assert errors_of(v2_validator, upgraded)


def test_v2_transition_必须带_from_to_与_transition(v2_schema):
    element = {
        "id": "tr", "type": "transition", "track": "V1",
        "timing": {"start": 1.0, "duration": 0.5},
        "from": "a", "to": "b", "transition": {"name": "fade", "params": {}},
    }
    validator = jsonschema.Draft7Validator(
        {"$ref": "#/definitions/transitionElement", "definitions": v2_schema["definitions"]}
    )
    assert list(validator.iter_errors(element)) == []
    for missing in ("from", "to", "transition"):
        broken = {k: v for k, v in element.items() if k != missing}
        assert list(validator.iter_errors(broken)), f"缺 {missing} 应该被拦下"


def test_v2_image_与_group_可用(v2_validator):
    data = tl.empty_timeline("新类型")
    data = migrate_v1_to_v2(data)
    data["elements"] = [
        {
            "id": "image_001", "type": "image", "track": "V2",
            "timing": {"start": 0.0, "duration": 2.0}, "asset": "image_001",
        },
        {
            "id": "group_001", "type": "group",
            "timing": {"start": 0.0, "duration": 2.0},
            "children": ["image_001"], "template": "HIGH_POINT",
        },
    ]
    assert errors_of(v2_validator, data) == []


# ---------------------------------------------------------------- 与校验器打通

def test_校验器按版本选_schema(validator, rich_v1):
    assert validator.schema_for(rich_v1)["$id"] == "timeline_schema.json"
    assert validator.schema_for(migrate_v1_to_v2(rich_v1))["$id"] == "timeline_schema_v2.json"


def test_v2_文档也能走同一个校验入口(validator, rich_v1):
    upgraded = migrate_v1_to_v2(rich_v1)
    report = validator.validate_report(upgraded)
    assert report["version"] == 2
    assert report["valid"], report["errors"]


def test_v2_文档的语义错误也能定位到元素(validator, rich_v1):
    upgraded = migrate_v1_to_v2(rich_v1)
    next(e for e in upgraded["elements"] if e["id"] == "clip_001")["asset"] = "不存在的素材"
    assert validator.invalid_element_ids(upgraded).get("clip_001") == "error"


def test_v2_文档的_schema_错误也能定位到元素(validator, rich_v1):
    upgraded = migrate_v1_to_v2(rich_v1)
    next(e for e in upgraded["elements"] if e["id"] == "clip_001")["timing"]["duration"] = -1.0
    assert validator.invalid_element_ids(upgraded).get("clip_001") == "error"
