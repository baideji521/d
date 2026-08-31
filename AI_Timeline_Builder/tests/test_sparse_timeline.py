"""Canonical Sparse Serialization 的测试（阶段 6.5 第二十七条）。

覆盖 Test 1–14：默认值省略、嵌套清理、active track、Effect/Transition 不受影响、
Round Trip、以及「JSON 变干净但 Runtime 行为不变」。
"""

from __future__ import annotations

import copy
import json
import os

import pytest

from core import sparse
from core import timeline as tl

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _clip(**kwargs) -> dict:
    return tl.make_video("clip_001", "video_003", "V1", start=0.0, source_start=0.0,
                         source_end=285.1, **kwargs)


# ---------------------------------------------------------------- Test 1


def test_1_只导入一个视频时没有任何默认字段(model):
    model.add_element(_clip())
    exported = model.to_dict()
    clip = exported["elements"][0]
    for absent in ("transform", "speed", "audio", "keyframes"):
        assert absent not in clip, f"{absent} 不该出现在导出 JSON 里"
    assert set(clip) == {"id", "type", "track", "asset", "start", "duration", "source"}


def test_1_导出的顶层结构就是协议要求的那几项(model):
    model.add_element(_clip())
    exported = model.to_dict()
    assert set(exported) == {"version", "time_unit", "meta", "tracks", "elements"}
    assert exported["version"] == 1
    assert exported["time_unit"] == "seconds"
    assert set(exported["meta"]) == {"name", "fps", "width", "height", "duration"}


# ---------------------------------------------------------------- Test 2


def test_2_只改_scale_时_transform_里只有_scale(model):
    model.add_element(_clip())
    model.set_element_field("clip_001", ["transform", "scale"], 1.2)
    clip = model.to_dict()["elements"][0]
    assert clip["transform"] == {"scale": 1.2}
    for absent in ("speed", "audio", "keyframes"):
        assert absent not in clip


# ---------------------------------------------------------------- Test 3


def test_3_只改_volume_时_audio_里只有_volume(model):
    model.add_element(_clip())
    model.set_element_field("clip_001", ["transform", "scale"], 1.2)
    model.set_element_field("clip_001", ["audio", "volume"], 0.6)
    clip = model.to_dict()["elements"][0]
    assert clip["transform"] == {"scale": 1.2}
    assert clip["audio"] == {"volume": 0.6}
    assert "enabled" not in clip["audio"], "enabled=true 是默认值，没必要写"


def test_3_显式关闭音频要保留(model):
    model.add_element(_clip())
    model.set_element_field("clip_001", ["audio", "enabled"], False)
    clip = model.to_dict()["elements"][0]
    assert clip["audio"] == {"enabled": False}


# ---------------------------------------------------------------- Test 4


def test_4_只改_speed_时只有_speed(model):
    model.add_element(_clip())
    model.set_element_field("clip_001", ["speed"], 1.5)
    clip = model.to_dict()["elements"][0]
    assert clip["speed"] == 1.5
    assert "transform" not in clip and "audio" not in clip


# ---------------------------------------------------------------- Test 5


def test_5_改回默认值后字段被删除(model):
    """default elision：1 → 1.2 写进去，1.2 → 1 再删掉。"""
    model.add_element(_clip())
    model.set_element_field("clip_001", ["transform", "scale"], 1.2)
    assert model.to_dict()["elements"][0]["transform"] == {"scale": 1.2}

    model.set_element_field("clip_001", ["transform", "scale"], 1.0)
    assert "transform" not in model.to_dict()["elements"][0]


def test_5_speed_与_volume_也能回到默认(model):
    model.add_element(_clip())
    model.set_element_field("clip_001", ["speed"], 2.0)
    model.set_element_field("clip_001", ["audio", "volume"], 0.5)
    model.set_element_field("clip_001", ["speed"], 1.0)
    model.set_element_field("clip_001", ["audio", "volume"], 1.0)
    clip = model.to_dict()["elements"][0]
    assert "speed" not in clip and "audio" not in clip


def test_5_只回到默认的那个分量被删其它保留(model):
    model.add_element(_clip())
    model.set_element_field("clip_001", ["transform", "scale"], 1.2)
    model.set_element_field("clip_001", ["transform", "opacity"], 0.4)
    model.set_element_field("clip_001", ["transform", "scale"], 1.0)
    assert model.to_dict()["elements"][0]["transform"] == {"opacity": 0.4}


# ---------------------------------------------------------------- Test 6


def test_6_空嵌套对象被删除():
    element = {
        "id": "clip_001",
        "type": "video",
        "track": "V1",
        "start": 0.0,
        "duration": 5.0,
        "transform": {},
        "audio": {},
        "fade": {},
        "keyframes": {},
        "params": {},
    }
    result = sparse.sparse_element(element)
    for absent in ("transform", "audio", "fade", "keyframes", "params"):
        assert absent not in result, absent


def test_6_全是默认值的嵌套对象也被删除():
    element = {
        "id": "clip_001",
        "type": "video",
        "transform": dict(tl.DEFAULT_TRANSFORM),
        "audio": dict(tl.DEFAULT_AUDIO),
        "fade": dict(tl.DEFAULT_FADE),
    }
    result = sparse.sparse_element(element)
    assert set(result) == {"id", "type"}


def test_6_空关键帧曲线被删除():
    element = {"id": "x", "type": "video", "keyframes": {"scale": [], "x": []}}
    assert "keyframes" not in sparse.sparse_element(element)


def test_6_删掉最后一个关键帧后字段消失(model):
    model.add_element(_clip())
    model.add_keyframe("clip_001", "scale", 0.0, 1.0)
    assert "keyframes" in model.to_dict()["elements"][0]
    model.remove_keyframe("clip_001", "scale", 0)
    assert "keyframes" not in model.get_element("clip_001")
    assert "keyframes" not in model.to_dict()["elements"][0]


# ---------------------------------------------------------------- Test 7


def test_7_没有元素引用的轨道不进导出_JSON(model):
    model.add_element(_clip())
    exported = model.to_dict()
    assert [t["id"] for t in exported["tracks"]] == ["V1"]
    assert exported["tracks"][0] == {"id": "V1", "name": "V1 主视频", "kind": "video"}
    # 编辑器自己仍然有 9 条预设轨可用
    assert len(model.tracks()) == 9


def test_7_空项目仍然导出一条合法轨道(model):
    exported = model.to_dict()
    assert len(exported["tracks"]) == 1, "Schema 要求 tracks 至少一条"
    assert exported["tracks"][0]["id"] == "V1"


def test_7_用户改过名字的空轨道要保留(model):
    model.add_element(_clip())
    model.rename_track("T1", "我的字幕轨")
    ids = [t["id"] for t in model.to_dict()["tracks"]]
    assert ids == ["V1", "T1"] or ids == ["T1", "V1"]


def test_7_隐藏或锁定过的空轨道要保留(model):
    model.add_element(_clip())
    model.toggle_track_flag("A1", "hidden")
    exported = model.to_dict()
    hit = [t for t in exported["tracks"] if t["id"] == "A1"]
    assert hit and hit[0]["hidden"] is True


def test_7_轨道上的默认开关被省略(model):
    model.add_element(_clip())
    track = model.to_dict()["tracks"][0]
    assert "locked" not in track and "hidden" not in track


# ---------------------------------------------------------------- Test 8 / 9 / 10


def test_8_加第二个视频后_V2_出现(model):
    model.add_element(_clip())
    model.add_element(
        tl.make_video("clip_002", "video_004", "V2", start=0.0, source_start=0.0, source_end=3.0)
    )
    assert [t["id"] for t in model.to_dict()["tracks"]] == ["V1", "V2"]


def test_9_加图片后_overlay_轨道出现(model):
    model.add_element(_clip())
    model.add_element(tl.make_overlay("overlay_001", "image_001", "V3", start=1.0, duration=2.0))
    ids = [t["id"] for t in model.to_dict()["tracks"]]
    assert ids == ["V1", "V3"]


def test_10_加字幕后文字轨道出现(model):
    model.add_element(_clip())
    model.add_element(tl.make_caption("caption_001", "第一句", "T1", start=0.5, duration=1.2))
    exported = model.to_dict()
    ids = [t["id"] for t in exported["tracks"]]
    assert ids == ["V1", "T1"]
    assert [t["kind"] for t in exported["tracks"] if t["id"] == "T1"] == ["text"]


def test_10_字幕的偏下摆位必须保留(model):
    """transform.y=0.82 与 Runtime 默认 0.5 不同，省掉它字幕就跑到画面中间了。"""
    model.add_element(tl.make_caption("caption_001", "第一句", "T1", start=0.0, duration=1.2))
    caption = model.to_dict()["elements"][0]
    assert caption["transform"] == {"y": 0.82}


def test_10_文字的偏下摆位必须保留(model):
    model.add_element(tl.make_text("text_001", "标题", "T2", start=0.0, duration=1.0))
    assert model.to_dict()["elements"][0]["transform"] == {"y": 0.7}


# ---------------------------------------------------------------- Test 11 / 12


def test_11_effect_的编辑意图不被删除(model):
    model.add_element(_clip())
    model.add_effect("zoom", {"scale_to": 1.35}, start=2.0, duration=0.6, target="clip_001")
    effect = [e for e in model.to_dict()["elements"] if e["type"] == "effect"][0]
    assert effect["name"] == "zoom"
    assert effect["target"] == "clip_001"
    assert effect["start"] == 2.0 and effect["duration"] == 0.6
    assert effect["params"] == {"scale_to": 1.35}
    assert effect["easing"] == "easeInOut", "与 Runtime 默认 linear 不同，必须保留"


def test_11_effect_的空_params_可以省略(model):
    """所有消费方都写 `element.get("params") or {}` / `params ?? {}`，省掉是安全的。"""
    model.add_element(_clip())
    model.add_effect("flash", {}, start=1.0, duration=0.3, target="clip_001")
    effect = [e for e in model.to_dict()["elements"] if e["type"] == "effect"][0]
    assert "params" not in effect


def test_12_transition_的编辑意图不被删除(model):
    model.add_element(_clip())
    model.add_element(
        tl.make_video("clip_002", "video_004", "V1", start=5.0, source_start=0.0, source_end=5.0)
    )
    model.add_transition("whip", "clip_001", "clip_002", 4.75, 0.5, {"direction": "left"})
    transition = [e for e in model.to_dict()["elements"] if e["type"] == "transition"][0]
    assert transition["name"] == "whip"
    assert transition["from"] == "clip_001" and transition["to"] == "clip_002"
    assert transition["start"] == 4.75 and transition["duration"] == 0.5
    assert transition["params"] == {"direction": "left"}


# ---------------------------------------------------------------- Test 13 Round Trip


def test_13_sparse_进去_sparse_出来(model):
    model.add_element(_clip())
    model.set_element_field("clip_001", ["transform", "scale"], 1.2)
    first = model.to_dict()

    model.from_dict(copy.deepcopy(first), "回灌")
    second = model.to_dict()
    assert second == first, "读进去再导出，字段不能变多"


def test_13_反复往返不会长出字段(model):
    model.add_element(_clip())
    current = model.to_dict()
    for _ in range(3):
        model.from_dict(copy.deepcopy(current), "往返")
        nxt = model.to_dict()
        assert nxt == current
        current = nxt


def test_13_真实_Demo_往返稳定(model):
    path = os.path.join(ROOT, "tests", "fixtures", "demo_timeline.json")
    assert os.path.isfile(path), "Demo 权威副本没了，先跑 tools/build_fixtures.py build"
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    model.from_dict(data, "灌入 Demo")
    first = model.to_dict()
    model.from_dict(copy.deepcopy(first), "再灌一次")
    assert model.to_dict() == first


def test_13_稀疏_JSON_能过校验(validator, model):
    model.add_element(_clip())
    issues = validator.validate(model.to_dict())
    assert [i for i in issues if i.is_error() and i.rule_id.startswith("SCHEMA")] == []


def test_13_稀疏_Demo_能过校验(validator, model):
    path = os.path.join(ROOT, "tests", "fixtures", "demo_timeline.json")
    assert os.path.isfile(path), "Demo 权威副本没了，先跑 tools/build_fixtures.py build"
    with open(path, "r", encoding="utf-8") as handle:
        model.from_dict(json.load(handle), "灌入 Demo")
    issues = validator.validate(model.to_dict())
    # 素材类问题与稀疏化无关：测试用的是替身素材库，Demo 的素材不在里面
    hit = [i for i in issues if i.is_error() and not i.rule_id.startswith("RULE_ASSET")]
    assert hit == [], [i.message for i in hit]


def test_13_v1_v2_迁移语义不受影响(model):
    model.add_element(_clip())
    model.set_element_field("clip_001", ["speed"], 2.0)
    v2 = model.to_v2_dict()
    clip = v2["elements"][0]
    assert clip["timing"]["start"] == 0.0
    assert clip["playback"] == {"speed": 2.0}
    assert "transform" not in clip, "v1 没有 transform，v2 也不该凭空长出来"


# ---------------------------------------------------------------- Test 14 Runtime 默认值


def test_14_effective_值补齐了全部默认(model):
    model.add_element(_clip())
    clip = model.get_element("clip_001")
    assert model.get_effective_transform(clip) == {
        "x": 0.5, "y": 0.5, "scale": 1.0, "rotation": 0.0, "opacity": 1.0
    }
    assert model.get_effective_speed(clip) == 1.0
    assert model.get_effective_audio(clip) == {"enabled": True, "volume": 1.0}
    assert model.get_effective_keyframes(clip) == {}


def test_14_effective_dict_是完整快照(model):
    model.add_element(_clip())
    snapshot = model.to_effective_dict()["elements"][0]
    assert snapshot["transform"] == dict(tl.DEFAULT_TRANSFORM)
    assert snapshot["speed"] == 1.0
    assert snapshot["audio"] == dict(tl.DEFAULT_AUDIO)
    # 但这是快照，不能污染模型
    assert "transform" not in model.get_element("clip_001")


def test_14_remotion_运行时对缺省字段有兜底():
    """指令第十七条：字段不存在时用默认值，不能崩。逐个核对源码里的兜底。"""
    checks = [
        (os.path.join("src", "elements", "VideoLayer.tsx"), "element.speed ?? 1"),
        (os.path.join("src", "elements", "VideoLayer.tsx"), "audio.volume ?? 1"),
        (os.path.join("src", "elements", "VideoLayer.tsx"), "element.audio ?? {}"),
        (os.path.join("src", "elements", "AudioLayer.tsx"), "element.volume ?? 1"),
        (os.path.join("src", "elements", "AudioLayer.tsx"), "element.speed ?? 1"),
        (os.path.join("src", "lib", "timeline.ts"), "element.transform ?? {}"),
        (os.path.join("src", "TimelineVideo.tsx"), 'meta.background ?? "#000000"'),
        (os.path.join("src", "effects", "types.ts"), "effect.params ?? {}"),
        (os.path.join("src", "transitions", "types.ts"), "transition.params ?? {}"),
    ]
    for relative, needle in checks:
        path = os.path.join(ROOT, "remotion", relative)
        with open(path, "r", encoding="utf-8") as handle:
            assert needle in handle.read(), f"{relative} 缺少兜底 {needle}"


def test_14_没有默认值的元素画面参数与补齐后一致(model):
    """JSON 变干净 ≠ Runtime 行为改变：稀疏元素与补齐元素的求值结果必须相同。"""
    model.add_element(_clip())
    sparse_clip = model.get_element("clip_001")
    full_clip = sparse.effective_element(sparse_clip)
    for param in ("x", "y", "scale", "rotation", "opacity"):
        assert tl.resolve_animated_value(sparse_clip, param, 0.0) == tl.resolve_animated_value(
            full_clip, param, 0.0
        ), param


# ---------------------------------------------------------------- 防止误删（第二十八条）


@pytest.mark.parametrize(
    "field, value",
    [
        ("speed", 0.5),
        ("volume", 0.0),
    ],
)
def test_falsy_但非默认的顶层值不能被删(field, value):
    element = {"id": "x", "type": "video", field: value}
    assert sparse.sparse_element(element)[field] == value


@pytest.mark.parametrize(
    "group, key, value",
    [
        ("transform", "opacity", 0.0),
        ("transform", "scale", 0.0),
        ("transform", "x", 0.0),
        ("audio", "volume", 0.0),
        ("audio", "enabled", False),
        ("fade", "in", 0.5),
    ],
)
def test_falsy_但非默认的嵌套值不能被删(group, key, value):
    element = {"id": "x", "type": "video", group: {key: value}}
    assert sparse.sparse_element(element)[group] == {key: value}


def test_布尔和数字不混为一谈():
    """`enabled: 1` 不是 `enabled: true`，不能被当成默认值删掉。"""
    element = {"id": "x", "type": "video", "audio": {"enabled": 1}}
    assert sparse.sparse_element(element)["audio"] == {"enabled": 1}


def test_sparse_element_不修改入参():
    element = {"id": "x", "type": "video", "speed": 1.0, "transform": {"scale": 1.0}}
    before = copy.deepcopy(element)
    sparse.sparse_element(element)
    assert element == before


# ---------------------------------------------------------------- 轨道预设合并


def test_merge_editor_tracks_补回预设且保留已有顺序():
    merged = sparse.merge_editor_tracks([{"id": "V1", "name": "自定义主轨", "kind": "video"}])
    ids = [t["id"] for t in merged]
    assert len(merged) == 9
    assert set(ids) == {t["id"] for t in tl.DEFAULT_TRACKS}
    assert merged[ids.index("V1")]["name"] == "自定义主轨", "已有轨道的属性不能被预设覆盖"
    # V1 仍然排在 V2 / T1 之前，层级关系不变
    assert ids.index("V1") < ids.index("V2") < ids.index("T1")


def test_merge_editor_tracks_保留自定义轨道():
    merged = sparse.merge_editor_tracks([{"id": "V9", "name": "特殊轨", "kind": "video"}])
    assert "V9" in [t["id"] for t in merged]
    assert len(merged) == 10


def test_加载稀疏_JSON_后编辑器仍有九条轨道(model):
    model.from_dict(
        {
            "version": 1,
            "time_unit": "seconds",
            "meta": {"name": "极简", "fps": 30, "width": 1080, "height": 1920},
            "tracks": [{"id": "V1", "name": "V1 主视频", "kind": "video"}],
            "elements": [_clip()],
        },
        "灌入极简 JSON",
    )
    assert len(model.tracks()) == 9, "编辑器预设必须补回来"
    assert [t["id"] for t in model.to_dict()["tracks"]] == ["V1"], "导出仍然只有活跃轨道"


def test_active_track_ids_只看元素引用(model):
    model.add_element(_clip())
    model.add_element(tl.make_caption("caption_001", "字", "T1", start=0.0, duration=1.0))
    assert sparse.active_track_ids(model.timeline) == {"V1", "T1"}
    assert model.active_track_ids() == ["V1", "T1"]


# ---------------------------------------------------------------- JSON 面板


def test_json_面板文本就是稀疏_JSON(model):
    model.add_element(_clip())
    text = model.to_json_text()
    assert json.loads(text) == model.to_dict()
    assert '"transform"' not in text
    assert '"keyframes"' not in text


# ---------------------------------------------------------------- 安全区档位


def test_安全区通用档不落盘(model):
    """通用档就是默认值，写进 JSON 等于凭空多一个字段。"""
    model.add_element(_clip())
    model.set_meta("safe_area", {"preset": "generic"})
    assert "safe_area" not in model.to_dict()["meta"]


def test_安全区平台档要落盘并且能改回默认(model):
    model.add_element(_clip())
    model.set_meta("safe_area", {"preset": "tiktok"})
    assert model.to_dict()["meta"]["safe_area"] == {"preset": "tiktok"}
    # 改回通用 = 恢复默认 → 字段必须再消失（稀疏规则第三条）
    model.set_meta("safe_area", {"preset": "generic"})
    assert "safe_area" not in model.to_dict()["meta"]


def test_安全区带额外键时整体保留(model):
    """只有「纯默认档位」才省。多写了别的键说明用户另有意图，不能删。"""
    model.add_element(_clip())
    model.set_meta("safe_area", {"preset": "generic", "note": "自己量的"})
    assert model.to_dict()["meta"]["safe_area"]["note"] == "自己量的"


# ---------------------------------------------------------------- 面板只读



def test_属性面板源码里不允许对元素_setdefault():
    """光是打开属性面板就不该往元素里写默认值。

    历史缺陷：`element.setdefault("audio", {...})` 让「选中一个刚导入的视频」
    这一个动作就把 audio 默认值写进了 JSON，稀疏化因此失效。
    面板一律只读生效值（tl.effective_*）或本地兜底字典。
    """
    source = open(os.path.join(ROOT, "gui", "property_panel.py"), encoding="utf-8").read()
    offenders = [
        line.strip()
        for line in source.splitlines()
        if "setdefault(" in line and ("element." in line or "style." in line)
    ]
    assert offenders == [], f"属性面板不许写回默认值：{offenders}"

