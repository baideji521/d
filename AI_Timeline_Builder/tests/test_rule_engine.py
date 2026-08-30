"""core/rule_engine.py 与 core/safe_area.py 的规则测试。

盯三件事：

1. 声明 ↔ 实现双向对齐（假合规是最难发现的问题）；
2. 剪辑级规则真的会命中，而且豁免条件真的生效；
3. 安全区只在**显式声明**时约束元素，不去替用户改主意。
"""

from __future__ import annotations

import os

import pytest

from core import rule_engine as re_mod
from core import safe_area as sa
from core import timeline as tl

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RULES_PATH = os.path.join(ROOT, "schemas", "rules.json")


@pytest.fixture
def engine() -> re_mod.RuleEngine:
    return re_mod.RuleEngine(re_mod.load_rule_definitions(RULES_PATH))


def clip(element_id: str, start: float, duration: float, track: str = "V1") -> dict:
    """直接构造视频元素：这里要的是任意时长，不受 make_video 的源区间约束。"""
    return {
        "id": element_id,
        "type": "video",
        "track": track,
        "asset": "video_001",
        "start": start,
        "duration": duration,
        "source": {"start": 0.0, "end": duration},
    }


def timeline_with(*elements) -> dict:
    data = tl.empty_timeline("规则测试")
    data["elements"].extend(elements)
    return data


# ---------------------------------------------------------------- 声明与实现

def test_声明的规则都有实现且没有多余实现():
    report = re_mod.consistency_report(ROOT, RULES_PATH)
    assert report["declared_not_implemented"] == []
    assert report["implemented_not_declared"] == []


def test_豁免条目允许没有实现():
    """RULE_CLIP_002 只描述「收尾片段豁免」，本身不产出问题。"""
    report = re_mod.consistency_report(ROOT, RULES_PATH)
    assert "RULE_CLIP_002" in report["exemptions"]
    assert "RULE_CLIP_002" not in report["declared"]


def test_规则族名能带下划线():
    rule = re_mod.RuleDefinition("RULE_SAFE_AREA_001", "error", "")
    assert rule.category == "SAFE_AREA"
    assert re_mod.RuleDefinition("RULE_CLIP_001", "warning", "").category == "CLIP"


def test_level_只从_rules_json_取(engine):
    assert engine.level_of("RULE_CLIP_001") == "warning"
    assert engine.level_of("RULE_SAFE_AREA_001") == "error"
    # 不认识的规则按最严处理，不许静默当 warning
    assert engine.level_of("RULE_NOT_EXIST_999") == "error"


def test_规则全表按族分组():
    rows = re_mod.rule_catalog(RULES_PATH)
    grouped = re_mod.group_by_category(rows)
    assert "CLIP" in grouped and "SAFE_AREA" in grouped
    assert all(row["id"].startswith("RULE_") for row in rows)


# ---------------------------------------------------------------- 片段长度

def test_超过十五秒的普通片段会报_CLIP_001(engine):
    data = timeline_with(
        clip("clip_001", 0.0, 20.0),
        clip("clip_002", 20.0, 3.0),  # 收尾片段
    )
    ids = [f.rule_id for f in engine.check(data)]
    assert ids == ["RULE_CLIP_001"]
    assert engine.check(data)[0].element_id == "clip_001"


def test_收尾片段超长不报(engine):
    """RULE_CLIP_002：每条轨最后一个片段允许长镜头收尾。"""
    data = timeline_with(clip("clip_001", 0.0, 3.0), clip("clip_002", 3.0, 40.0))
    assert engine.check(data) == []


def test_收尾豁免按轨道各算一次(engine):
    """V1 与 V2 的收尾是分开的，不能因为 V2 有收尾就放过 V1 的超长片段。"""
    data = timeline_with(
        clip("v1_a", 0.0, 30.0, "V1"),
        clip("v1_b", 30.0, 2.0, "V1"),
        clip("v2_a", 0.0, 30.0, "V2"),  # V2 上唯一片段 = 收尾，豁免
    )
    ids = {f.element_id for f in engine.check(data)}
    assert ids == {"v1_a"}


def test_刚好十五秒不报(engine):
    data = timeline_with(clip("clip_001", 0.0, 15.0), clip("clip_002", 15.0, 1.0))
    assert engine.check(data) == []


def test_脏输入不许抛异常(engine):
    assert engine.check({"elements": [None, 3, "x"]}) == []
    assert engine.check([]) == []
    assert engine.check({"elements": [{"type": "video", "duration": "很久"}]}) == []


# ---------------------------------------------------------------- 安全区

def test_安全区档位表齐全():
    assert sa.preset_ids() == ["tiktok", "youtube_shorts", "instagram_reels", "generic"]
    for preset_id in sa.preset_ids():
        left, top, right, bottom = sa.box(preset_id)
        assert 0 < left < right < 1
        assert 0 < top < bottom < 1


def test_不认识的档位退回通用档():
    assert sa.insets("不存在") == sa.insets("generic")
    assert sa.timeline_preset({"meta": {"safe_area": {"preset": "喵"}}}) == "generic"
    assert sa.timeline_preset({}) == "generic"


def test_时间线能声明档位():
    data = {"meta": {"safe_area": {"preset": "tiktok"}}}
    assert sa.timeline_preset(data) == "tiktok"


def test_收位只在越界时发生():
    inside = sa.clamp(0.5, 0.5, "tiktok")
    assert inside == (0.5, 0.5)
    x, y = sa.clamp(0.98, 0.95, "tiktok")
    left, top, right, bottom = sa.box("tiktok")
    assert x == pytest.approx(right)
    assert y == pytest.approx(bottom)


def test_没越界的元素不会被塞进_transform():
    """本来在安全区内的元素不该被写入一份等于默认值的 transform（会污染稀疏 JSON）。"""
    element = tl.make_overlay("overlay_001", "image_001", start=0.0, duration=1.0)
    assert sa.clamp_element(element, "tiktok") is False
    assert "transform" not in element


def test_越界的元素会被收进安全区():
    element = tl.make_overlay("overlay_001", "image_001", start=0.0, duration=1.0)
    element["transform"] = {"x": 0.97, "y": 0.5}
    assert sa.clamp_element(element, "tiktok") is True
    _, _, right, _ = sa.box("tiktok")
    assert element["transform"]["x"] == pytest.approx(round(right, 4))
    # 没越界的那一维不许被动
    assert element["transform"].get("y") == 0.5


def test_只有声明了_safe_area_的元素才被检查(engine):
    element = tl.make_text("text_001", "太靠下了", start=0.0, duration=1.0)
    element["transform"] = {"y": 0.95}
    data = timeline_with(element)
    data["meta"]["safe_area"] = {"preset": "tiktok"}
    assert engine.check(data) == []  # 没声明 safe_area，工具不该管

    element["safe_area"] = True
    findings = engine.check(data)
    assert [f.rule_id for f in findings] == ["RULE_SAFE_AREA_001"]
    assert "安全区外" in findings[0].message


def test_声明了_safe_area_且真的在区内就不报(engine):
    element = tl.make_caption("caption_001", "在安全区内", start=0.0, duration=1.0)
    element["transform"] = {"y": 0.75}
    element["safe_area"] = True
    data = timeline_with(element)
    data["meta"]["safe_area"] = {"preset": "tiktok"}
    assert engine.check(data) == []


def test_没有位置语义的元素声明_safe_area_会被指出来(engine):
    element = tl.make_audio("audio_001", "sfx_001", start=0.0, duration=1.0)
    element["safe_area"] = True
    findings = engine.check(timeline_with(element))
    assert [f.rule_id for f in findings] == ["RULE_SAFE_AREA_001"]
    assert "没有位置语义" in findings[0].message


def test_安全区档位表能导出给文档():
    rows = sa.catalog()
    assert {row["id"] for row in rows} == set(sa.preset_ids())
    for row in rows:
        assert set(row["box"]) == {"left", "top", "right", "bottom"}
        assert row["note"]
