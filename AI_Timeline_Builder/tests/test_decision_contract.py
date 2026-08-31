"""AI 契约（指令第三十三 ~ 三十六条）的测试。

盯四件事：

1. **只有一条契约**：AI 输出 = EditingDecision，形状由
   `schemas/editing_decision_schema.json` 说了算；
2. **入口闸门**：TSX / ffmpeg / 绝对路径在进 Planner 之前就被拦下；
3. **Runtime 不读理由**：reason / confidence / decision_id 不进渲染数据；
4. **可追溯**：每个产出元素都能查回是哪条决策做的。
"""

from __future__ import annotations

import json
import os

import pytest

from core import editing_planner as ep
from core import provenance as pv
from libraries.asset_registry import AssetRegistry

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMAS = os.path.join(ROOT, "schemas")


@pytest.fixture
def registry() -> AssetRegistry:
    return AssetRegistry(
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


@pytest.fixture
def planner(libraries, registry) -> ep.EditingPlanner:
    return ep.EditingPlanner(
        effects=libraries.effect, transitions=libraries.transition, assets=registry
    )


# ---------------------------------------------------------------- Schema


def test_决策_schema_存在且动作枚举与白名单一致():
    schema = ep.load_decision_schema(SCHEMAS)
    assert schema is not None
    actions = schema["definitions"]["decision"]["properties"]["action"]["enum"]
    assert actions == list(ep.ACTIONS), "Schema 的动作枚举必须等于 Planner 白名单"


def test_能力目录里的示例决策自己就能过_schema():
    """文档里给 AI 看的例子如果自己都不合法，AI 学到的就是错的。"""
    path = os.path.join(ROOT, "docs", "AI_CAPABILITIES.json")
    if not os.path.isfile(path):
        pytest.skip("能力目录还没生成")
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    shape = payload["actions"]["decision_shape"]
    issues = ep.decision_payload_issues({"decisions": [shape]}, SCHEMAS)
    assert [i.code for i in issues if i.code != "DECISION_SCHEMA_UNAVAILABLE"] == []


def test_编造的动作过不了_schema():
    issues = ep.decision_payload_issues(
        {"decisions": [{"action": "make_it_viral"}]}, SCHEMAS
    )
    codes = {i.code for i in issues}
    assert "DECISION_SCHEMA" in codes or "DECISION_SCHEMA_UNAVAILABLE" in codes


def test_直接给时间线_json_不算决策():
    """AI 交上来一份 Timeline JSON 就该被当场拒绝，而不是「先试着渲染看看」。"""
    issues = ep.decision_payload_issues(
        {"meta": {"fps": 30}, "elements": [], "tracks": []}, SCHEMAS
    )
    assert issues, "缺 decisions 字段必须报错"


# ---------------------------------------------------------------- 内容闸门


@pytest.mark.parametrize(
    "payload, code",
    [
        ({"decisions": [{"action": "effect", "reason": "写个 <AbsoluteFill> 就行"}]},
         "AI_OUTPUT_TSX"),
        ({"decisions": [{"action": "sfx", "reason": "用 ffmpeg -i 混一下"}]},
         "AI_OUTPUT_FFMPEG"),
        ({"decisions": [{"action": "overlay",
                         "parameters": {"asset": "C:\\videos\\demo.mp4"}}]},
         "AI_OUTPUT_ABSOLUTE_PATH"),
    ],
)
def test_越界内容被拦下(payload, code):
    assert code in {i.code for i in ep.forbidden_issues(payload)}


def test_正常决策不会被闸门误伤():
    payload = {
        "decisions": [
            {"action": "zoom", "target": "clip_001", "start": 1.0,
             "parameters": {"scale_to": 1.2}, "reason": "强调这一下"}
        ]
    }
    assert ep.forbidden_issues(payload) == []


def test_parameters_与_params_都能读():
    a = ep.EditingDecision.from_dict({"action": "zoom", "parameters": {"scale_to": 1.3}})
    b = ep.EditingDecision.from_dict({"action": "zoom", "params": {"scale_to": 1.3}})
    assert a.params == b.params == {"scale_to": 1.3}
    # 落盘用规范键名
    assert "parameters" in a.to_dict()


# ---------------------------------------------------------------- 溯源


def test_决策号自动补齐并记住元素归属(planner, timeline):
    decisions = [
        ep.EditingDecision("zoom", "clip_001", 1.0, 0.5, {"scale_to": 1.2}, "强调"),
        ep.EditingDecision("sfx", "", 1.0, 0.6, {"category": "impact"}, "配一下"),
    ]
    result = planner.plan(timeline, decisions)
    assert result.ok, result.report()
    assert [d.decision_id for d in decisions] == ["dec_001", "dec_002"]
    owners = set(result.element_owner.values())
    assert owners == {"dec_001", "dec_002"}


def test_复合动作展开出的元素都归同一条决策(planner, timeline):
    decision = ep.EditingDecision(
        "highlight", "clip_001", 1.0, 1.0, {"text": "THIS"}, "高光"
    )
    result = planner.plan(timeline, [decision])
    assert result.ok, result.report()
    assert len(result.elements) == 4
    assert set(result.element_owner.values()) == {"dec_001"}


def test_被拒的决策也能对上账(planner, timeline):
    result = planner.plan(timeline, [{"action": "effect", "parameters": {"name": "喵喵光"}}])
    assert not result.ok
    assert result.errors[0].decision_id == "dec_001"


def test_渲染数据里没有置信度与决策号(planner, timeline):
    """Runtime 只读渲染需要的字段（指令第三十五条）。"""
    decision = ep.EditingDecision(
        "zoom", "clip_001", 1.0, 0.5, {"scale_to": 1.2}, "强调", 0.42
    )
    result = planner.plan(timeline, [decision])
    for element in result.elements:
        assert "confidence" not in element
        assert "decision_id" not in element
    # 理由留在 note 里给人看，Remotion 不读它
    assert result.elements[0]["note"] == "强调"


def test_溯源日志记录理由与置信度且能反查(planner, timeline, tmp_path):
    decisions = [
        ep.EditingDecision("zoom", "clip_001", 1.0, 0.5, {"scale_to": 1.2}, "强调", 0.9),
    ]
    result = planner.plan(timeline, decisions)
    log = pv.DecisionLog()
    pv.record_plan(log, result, decisions, source="ai", input_ref={"marker": 1.0})
    assert len(log) == 1

    element_id = result.elements[0]["id"]
    record = log.of_element(element_id)
    assert record is not None
    assert record.reason == "强调"
    assert record.confidence == 0.9
    assert record.input_ref == {"marker": 1.0}

    path = os.path.join(str(tmp_path), pv.LOG_FILENAME)
    log.save(path)
    again = pv.DecisionLog.load(path)
    assert again.to_dict() == log.to_dict()


def test_日志与时间线是两份文件(planner, timeline, tmp_path):
    """删掉决策日志渲染结果必须一模一样 —— 它不该是渲染输入。"""
    decisions = [ep.EditingDecision("zoom", "clip_001", 1.0, 0.5, {"scale_to": 1.2}, "强调")]
    result = planner.plan(timeline, decisions)
    exported = json.dumps(result.timeline, ensure_ascii=False, sort_keys=True)
    assert "confidence" not in exported
    assert "decision_id" not in exported
    assert "decisions" not in exported


def test_不认识的来源退成_unknown():
    log = pv.DecisionLog()
    record = log.add("zoom", source="GPT-5")
    assert record.source == "unknown"
    assert log.by_source("unknown") == [record]


def test_没有对应决策的元素查回_none():
    log = pv.DecisionLog()
    log.add("zoom", elements=["effect_001"])
    assert log.of_element("caption_009") is None


def test_决策号不会重号():
    log = pv.DecisionLog()
    log.add("zoom", decision_id="dec_002")
    assert log.add("sfx").decision_id == "dec_001"
    assert log.add("caption").decision_id == "dec_003"
