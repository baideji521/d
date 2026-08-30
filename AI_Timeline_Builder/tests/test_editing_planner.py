"""core/editing_planner.py 的测试。

Planner 是「AI 意图 → Timeline 元素」的唯一通道，所以盯四件事：

1. **不许编造**：未注册的特效 / 转场、库里没有的素材 id，一律 error；
2. **复合意图展开正确**：highlight = 冻帧 + 推镜 + 音效 + 字幕；
3. **产出物必须能过 Validator**（Schema + 语义 + Registry + Rule Engine）；
4. 输入时间线不被修改，时间落在整帧上。
"""

from __future__ import annotations

import copy
import os

import pytest

from core import timeline as tl
from core.editing_planner import ACTIONS, EditingDecision, EditingPlanner
from libraries.asset_registry import AssetRegistry

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def registry() -> AssetRegistry:
    """一份小而真的素材注册表：id 与 conftest 的 FakeAssetManager 对齐。"""
    return AssetRegistry(
        [
            {
                "id": "video_001",
                "type": "video",
                "path": "assets/videos/demo/demo.mp4",
                "name": "demo",
                "category": "demo",
                "duration": 12.0,
            },
            {
                "id": "sfx_001",
                "type": "audio",
                "path": "assets/audio/impact/impact_01.wav",
                "name": "impact_01",
                "category": "impact",
                "duration": 1.2,
            },
            {
                "id": "audio_001",
                "type": "audio",
                "path": "assets/audio/bgm/bgm_demo.wav",
                "name": "bgm_demo",
                "category": "bgm",
                "duration": 16.0,
            },
            {
                "id": "image_001",
                "type": "image",
                "path": "assets/overlays/arrow/arrow_red.png",
                "name": "arrow_red",
                "category": "arrow",
            },
        ]
    )


@pytest.fixture
def planner(libraries, registry) -> EditingPlanner:
    return EditingPlanner(
        effects=libraries.effect,
        transitions=libraries.transition,
        assets=registry,
        fps=30,
    )


# ---------------------------------------------------------------- 决策解析

def test_两种写法都能读():
    a = EditingDecision.from_dict(
        {"action": "zoom", "target": "clip_001", "start": 12.4, "duration": 0.6,
         "params": {"scale_to": 1.2}, "reason": "强调反应瞬间"}
    )
    assert (a.action, a.target, a.start, a.duration) == ("zoom", "clip_001", 12.4, 0.6)
    assert a.reason == "强调反应瞬间"

    b = EditingDecision.from_dict(
        {"decision": "highlight", "time": 24.0,
         "actions": ["freeze_frame", "zoom", "impact_sfx", "caption_emphasis"]}
    )
    assert b.action == "highlight"
    assert b.start == 24.0
    assert b.params["steps"] == ["freeze_frame", "zoom", "impact_sfx", "caption_emphasis"]


def test_脏决策不抛异常():
    assert EditingDecision.from_dict("我要剪辑").action == ""
    assert EditingDecision.from_dict(None).action == ""
    assert EditingDecision.from_dict({"action": "zoom", "start": "十二秒"}).start == 0.0


def test_动作白名单之外一律拒绝(planner, timeline):
    result = planner.plan(timeline, [{"action": "ai_magic", "start": 1.0}])
    assert not result.ok
    assert result.errors[0].code == "UNKNOWN_ACTION"
    assert result.elements == []


# ---------------------------------------------------------------- 不许编造

def test_未注册的特效被拒绝(planner, timeline):
    result = planner.plan(
        timeline, [{"action": "effect", "target": "clip_001", "start": 1.0,
                    "params": {"name": "超级爆炸"}}]
    )
    assert [e.code for e in result.errors] == ["UNKNOWN_EFFECT"]
    assert result.elements == []


def test_素材特效不能当程序特效(planner, timeline):
    """kind=material 的条目必须走 overlay，这在 rules 里也是 RULE_EFFECT_006。"""
    material = next(
        (d for d in planner._effects.all() if d.element_type != "effect"), None
    )
    assert material is not None, "素材特效库是空的，这条测试失去意义"
    result = planner.plan(
        timeline,
        [{"action": "effect", "target": "clip_001", "start": 1.0,
          "params": {"name": material.name}}],
    )
    assert [e.code for e in result.errors] == ["MATERIAL_EFFECT_AS_EFFECT"]


def test_未注册的转场被拒绝(planner, timeline):
    result = planner.plan(
        timeline,
        [{"action": "transition", "start": 5.0,
          "params": {"name": "闪现", "from": "clip_001", "to": "clip_002"}}],
    )
    assert [e.code for e in result.errors] == ["UNKNOWN_TRANSITION"]


def test_编造的素材_id_被拒绝(planner, timeline):
    result = planner.plan(
        timeline, [{"action": "music", "start": 0.0, "params": {"asset": "bgm_不存在"}}]
    )
    assert [e.code for e in result.errors] == ["ASSET_NOT_FOUND"]


def test_没有注册表时如实记警告而不是假装通过(timeline):
    bare = EditingPlanner()
    result = bare.plan(
        timeline, [{"action": "effect", "target": "clip_001", "start": 1.0,
                    "params": {"name": "随便写的"}}]
    )
    assert result.ok  # 没有 Registry 就无法判断，不能报错
    assert [w.code for w in result.warnings] == ["REGISTRY_UNAVAILABLE"]


# ---------------------------------------------------------------- 复合意图

def test_highlight_展开成四个动作(planner, timeline):
    result = planner.plan(
        timeline,
        [{"decision": "highlight", "time": 6.0, "params": {"text": "THIS IS IT"},
          "reason": "反应瞬间"}],
    )
    assert result.ok, [e.to_dict() for e in result.errors]
    kinds = [e["type"] for e in result.elements]
    assert kinds == ["freeze", "effect", "audio", "caption"]
    # 理由必须留痕，方便人复核 AI 的判断
    assert all(e.get("note") == "反应瞬间" for e in result.elements)


def test_highlight_的推镜用_zoom_且参数合法(planner, timeline):
    result = planner.plan(timeline, [{"decision": "highlight", "time": 6.0}])
    effect = next(e for e in result.elements if e["type"] == "effect")
    assert effect["name"] == "zoom"
    report = planner._effects.validate("zoom", effect["params"])
    assert report["errors"] == []


def test_highlight_没给文案时跳过字幕并说明(planner, timeline):
    result = planner.plan(timeline, [{"decision": "highlight", "time": 6.0}])
    assert [e["type"] for e in result.elements] == ["freeze", "effect", "audio"]
    assert [w.code for w in result.warnings] == ["CAPTION_TEXT_MISSING"]


def test_highlight_能只跑指定步骤(planner, timeline):
    result = planner.plan(
        timeline, [{"decision": "highlight", "time": 6.0, "actions": ["zoom"]}]
    )
    assert [e["type"] for e in result.elements] == ["effect"]


def test_音效从素材库里挑而不是编(planner, timeline):
    result = planner.plan(timeline, [{"action": "sfx", "start": 3.0}])
    assert result.ok
    assert result.elements[0]["asset"] == "sfx_001"
    assert result.elements[0]["track"] == "A3"


# ---------------------------------------------------------------- 定位与吸帧

def test_不给_target_时按时间点找片段(planner, timeline):
    """AI 只说时间，不必知道片段 id。"""
    result = planner.plan(timeline, [{"action": "freeze", "start": 7.0, "duration": 1.0}])
    assert result.ok
    assert result.elements[0]["target"] == "clip_002"


def test_时间点上没有片段就如实报错(planner, timeline):
    result = planner.plan(timeline, [{"action": "freeze", "start": 99.0}])
    assert [e.code for e in result.errors] == ["TARGET_NOT_FOUND"]


def test_所有时间吸附到整帧(planner, timeline):
    """AI 给的 1.31s / 0.55s 必须落到帧边界上。

    注意 JSON 里的秒数保留三位小数（全项目工厂函数的既有约定），
    所以 16 帧写出来是 0.533 而不是 0.533333 —— 判定要用项目自己的
    秒↔帧换算器，而不是要求十进制精确等于 frames/fps。
    """
    from core import time_utils as tu

    result = planner.plan(
        timeline, [{"action": "effect", "target": "clip_001", "start": 1.31,
                    "duration": 0.55, "params": {"name": "zoom"}}]
    )
    effect = result.elements[0]
    assert effect["start"] == pytest.approx(1.3, abs=1e-6)
    assert tu.seconds_to_frames(effect["start"], 30) == 39
    # 0.55s → 16 帧（snap_to_frame 走 round 半偶），写盘取三位小数
    assert tu.seconds_to_frames(effect["duration"], 30) == 16
    assert abs(effect["duration"] - 16 / 30) <= 0.0005


def test_冻结帧的源时刻按变速换算(planner):
    data = tl.empty_timeline("变速")
    clip = tl.make_video("clip_001", "video_001", "V1", 0.0, 2.0, 8.0, speed=2.0)
    data["elements"].append(clip)
    planner_result = planner.plan(data, [{"action": "freeze", "start": 1.0, "duration": 0.5}])
    freeze = planner_result.elements[0]
    # 1 秒 × 2 倍速 = 源素材推进 2 秒，起点 2.0 → 4.0
    assert freeze["source_time"] == pytest.approx(4.0)


# ---------------------------------------------------------------- 剪切与裁剪

def test_cut_把片段切成两段且总长不变(planner, timeline):
    before = tl.get_element(timeline, "clip_001")
    total = tl.as_seconds(before["duration"])
    result = planner.plan(timeline, [{"action": "cut", "target": "clip_001", "start": 2.0}])
    assert result.ok
    head = tl.get_element(result.timeline, "clip_001")
    tail = result.elements[0]
    assert head["duration"] + tail["duration"] == pytest.approx(total)
    # 源区间必须首尾相接，不许丢帧也不许重复
    assert head["source"]["end"] == pytest.approx(tail["source"]["start"])


def test_切点在片段外要报错(planner, timeline):
    result = planner.plan(timeline, [{"action": "cut", "target": "clip_001", "start": 20.0}])
    assert [e.code for e in result.errors] == ["CUT_OUT_OF_RANGE"]


@pytest.mark.parametrize("side, expected_start", [("head", 1.0), ("tail", 0.0)])
def test_trim_裁头与裁尾(planner, timeline, side, expected_start):
    result = planner.plan(
        timeline,
        [{"action": "trim", "target": "clip_001", "params": {"side": side, "seconds": 1.0}}],
    )
    assert result.ok, [e.to_dict() for e in result.errors]
    clip = tl.get_element(result.timeline, "clip_001")
    assert clip["duration"] == pytest.approx(4.0)
    assert clip["start"] == pytest.approx(expected_start)


def test_裁掉整段要报错(planner, timeline):
    result = planner.plan(
        timeline,
        [{"action": "trim", "target": "clip_001", "params": {"seconds": 5.0}}],
    )
    assert [e.code for e in result.errors] == ["TRIM_OUT_OF_RANGE"]


# ---------------------------------------------------------------- 与校验器串起来

def test_输入时间线不被修改(planner, timeline):
    snapshot = copy.deepcopy(timeline)
    planner.plan(timeline, [{"decision": "highlight", "time": 3.0, "params": {"text": "X"}}])
    assert timeline == snapshot


def test_产出的时间线能过校验器(planner, validator, timeline):
    result = planner.plan(
        timeline,
        [
            {"decision": "highlight", "time": 3.0, "params": {"text": "LOOK"}},
            {"action": "transition", "start": 5.0,
             "params": {"name": "crossfade", "from": "clip_001", "to": "clip_002"}},
            {"action": "music", "start": 0.0, "params": {"asset": "audio_001"}, "duration": 8.0},
            {"action": "overlay", "start": 1.0, "duration": 1.0,
             "params": {"asset": "image_001"}},
        ],
    )
    assert result.ok, [e.to_dict() for e in result.errors]
    errors = validator.errors_only(result.timeline)
    assert errors == [], "\n".join(i.display() for i in errors)


def test_安全区字幕会被自动收位(planner, timeline):
    timeline["meta"]["safe_area"] = {"preset": "tiktok"}
    result = planner.plan(
        timeline,
        [{"action": "caption", "start": 1.0, "duration": 1.0,
          "params": {"text": "别被 UI 压住", "safe_area": True}}],
    )
    caption = result.elements[0]
    assert caption["safe_area"] is True
    # make_caption 默认 y=0.82，抖音安全区底边是 0.79，必须被收上来
    assert caption["transform"]["y"] < 0.82


def test_报告结构可直接给_AI_读(planner, timeline):
    result = planner.plan(
        timeline,
        [{"action": "sfx", "start": 1.0}, {"action": "不存在", "start": 2.0}],
    )
    report = result.report()
    assert report["ok"] is False
    assert report["element_count"] == 1
    assert report["errors"][0]["code"] == "UNKNOWN_ACTION"
    assert report["applied"][0]["action"] == "sfx"


def test_动作目录覆盖全部动作():
    from core.editing_planner import action_catalog

    rows = action_catalog()
    assert [r["action"] for r in rows] == list(ACTIONS)
    highlight = next(r for r in rows if r["action"] == "highlight")
    assert highlight["expands_to"] == ["freeze_frame", "zoom", "impact_sfx", "caption_emphasis"]
