"""TransitionRegistry 的单元测试（阶段 7 第二十三 / 二十四条）。

覆盖：Registry 增删查 / TransitionDefinition 元数据 / 参数校验 /
from-to 六种组合 / 未知转场 / 时间窗口边界 / 既有 Demo 兼容 / Validator 接线。

注意本文件只测 Registry 与 Validator。「最终画面对不对」在
remotion/src/transitions/registry.test.ts 里测，两边都过也只能说明
数据层与计划层正确，真实 MP4 要等阶段 15。
"""

from __future__ import annotations

import json
import os

import pytest

from core import timeline as tl
from libraries.transition_library import (
    BUILTIN_TRANSITIONS,
    SUPPORTED_SIDES,
    TransitionLibrary,
)
from libraries.transition_registry import (
    CATEGORIES,
    CATEGORY_LABELS,
    PARAM_TYPES,
    ParameterDefinition,
    TransitionDefinition,
    TransitionRegistry,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: Remotion 侧 registry.test.ts 里断言的同一份名单，两边必须一致
EXPECTED_NAMES = [
    "fade",
    "crossfade",
    "flash",
    "whip",
    "zoom",
    "wipe",
    "slide",
    "push",
    "spin",
    "blur",
    "glitch",
]


@pytest.fixture
def registry() -> TransitionLibrary:
    return TransitionLibrary(os.path.join(ROOT, "assets"))


def _transition(
    name: str = "whip",
    params=None,
    from_id: str = "clip_001",
    to_id: str = "clip_002",
    start: float = 4.75,
    duration: float = 0.5,
) -> dict:
    return tl.make_transition(
        "tr_001",
        name,
        from_id,
        to_id,
        start=start,
        duration=duration,
        params=params if params is not None else {},
    )


# ---------------------------------------------------------------- Registry 本体


def test_内置转场数量与名单(registry: TransitionLibrary) -> None:
    assert len(BUILTIN_TRANSITIONS) == 11
    assert registry.names() == EXPECTED_NAMES


def test_register_get_has_all(registry: TransitionLibrary) -> None:
    total = len(registry.all())
    definition = registry.register(
        {
            "name": "test_tr",
            "label": "测试转场",
            "category": "basic",
            "default_duration": 0.4,
            "renderer": "test_tr",
            "supported_from": ["video"],
            "supported_to": ["video"],
            "params": [],
        }
    )
    assert definition is not None
    assert registry.has("test_tr")
    assert registry.get("test_tr").display_name == "测试转场"
    assert len(registry.all()) == total + 1
    assert "test_tr" in registry.names()


def test_unregister(registry: TransitionLibrary) -> None:
    assert registry.unregister("whip") is True
    assert registry.has("whip") is False
    assert registry.unregister("whip") is False


def test_register_忽略无名定义与非字典() -> None:
    reg = TransitionRegistry()
    assert reg.register({"label": "没有 name"}) is None
    assert reg.register("fade") is None
    assert reg.register(None) is None
    assert reg.all() == []


def test_同名后注册覆盖前者() -> None:
    reg = TransitionRegistry(
        [
            {"name": "fade", "label": "旧", "category": "basic", "params": []},
            {"name": "fade", "label": "新", "category": "impact", "params": []},
        ]
    )
    assert len(reg.all()) == 1
    assert reg.get("fade").display_name == "新"
    assert reg.get("fade").category == "impact"


def test_get_未注册返回_None(registry: TransitionLibrary) -> None:
    assert registry.get("不存在的转场") is None
    assert registry.has("不存在的转场") is False


def test_categories_按标准顺序返回(registry: TransitionLibrary) -> None:
    assert registry.categories() == list(CATEGORIES)
    for category in CATEGORIES:
        assert registry.by_category(category), category


def test_每个转场的_category_都是标准分类(registry: TransitionLibrary) -> None:
    for definition in registry.all():
        assert definition.category in CATEGORIES, definition.name


def test_全部转场都有_renderer(registry: TransitionLibrary) -> None:
    """指令第五条：renderer 是与 Remotion 对接的唯一字符串，不能空着。"""
    assert registry.without_renderer() == []
    renderers = registry.renderers()
    assert len(renderers) == 11
    # 约定 renderer 名等于 name，Remotion 侧 index.ts 注册的键与之一致
    assert all(name == renderer for name, renderer in renderers.items())


def test_registry_不做时间计算() -> None:
    """指令：Registry 只管定义与校验，progress / 插值属于 Runtime。"""
    import libraries.transition_registry as module

    source = open(module.__file__, "r", encoding="utf-8").read()
    for banned in ("def progress", "interpolate", "fps", "frame"):
        assert banned not in source, banned


def test_TransitionRegistry_与_EffectRegistry_不是同一个类() -> None:
    """指令第三条：两者刻意不合并 —— Effect 一个 target，Transition 两侧。"""
    from libraries.effect_registry import EffectRegistry

    assert not issubclass(TransitionRegistry, EffectRegistry)
    assert not issubclass(EffectRegistry, TransitionRegistry)
    assert not hasattr(TransitionDefinition({"name": "x"}), "supported_targets")
    assert hasattr(TransitionDefinition({"name": "x"}), "supported_from")


# ---------------------------------------------------------------- Definition


def test_definition_元数据齐全(registry: TransitionLibrary) -> None:
    whip = registry.get("whip")
    assert whip.name == "whip"
    assert whip.display_name == "Whip 甩镜"
    assert whip.category == "impact"
    assert whip.display_category == "冲击"
    assert whip.description
    assert whip.renderer == "whip"
    assert whip.default_duration == 0.5
    assert whip.supported_from == SUPPORTED_SIDES
    assert whip.supported_to == SUPPORTED_SIDES
    assert [p.name for p in whip.parameters] == ["direction", "intensity", "blur"]


def test_definition_还能当_dict_用(registry: TransitionLibrary) -> None:
    """GUI 里既有 definition["label"] 的写法必须继续可用。"""
    whip = registry.get("whip")
    assert whip["label"] == "Whip 甩镜"
    assert whip["name"] == "whip"
    assert whip.get("不存在", "兜底") == "兜底"
    assert isinstance(dict(whip), dict)
    assert "params" in dict(whip)


def test_没写_display_category_时退回标准分类中文名() -> None:
    definition = TransitionDefinition({"name": "x", "category": "geometric", "params": []})
    assert definition.display_category == CATEGORY_LABELS["geometric"]


def test_default_duration_脏数据退回兜底() -> None:
    definition = TransitionDefinition({"name": "x", "default_duration": "很久", "params": []})
    assert definition.default_duration == 0.5


def test_default_params_与_fill_defaults(registry: TransitionLibrary) -> None:
    assert registry.default_params("whip") == {
        "direction": "left",
        "intensity": 0.8,
        "blur": 0.6,
    }
    merged = registry.get("whip").fill_defaults({"direction": "up"})
    assert merged == {"direction": "up", "intensity": 0.8, "blur": 0.6}


def test_fill_defaults_不回写_JSON(registry: TransitionLibrary) -> None:
    """指令第十七条同款要求：默认值读取时补，绝不写回 Timeline JSON。"""
    element = _transition("whip", {})
    registry.get("whip").fill_defaults(element["params"])
    assert element["params"] == {}


def test_default_duration_与_param_spec_查询(registry: TransitionLibrary) -> None:
    assert registry.default_duration("flash") == 0.3
    assert registry.default_duration("不存在") == 0.5
    assert registry.label_of("不存在") == "不存在"
    spec = registry.param_spec("glitch", "slices")
    assert spec.type == "int" and spec.minimum == 2 and spec.maximum == 60
    assert registry.param_spec("不存在", "slices") is None


def test_参数类型都在白名单内(registry: TransitionLibrary) -> None:
    for definition in registry.all():
        for param in definition.parameters:
            assert param.type in PARAM_TYPES, (definition.name, param.name, param.type)


def test_参数的_ui_推断(registry: TransitionLibrary) -> None:
    by_key = {p.name: p for p in registry.get("whip").parameters}
    assert by_key["direction"].ui == "combo"
    assert by_key["intensity"].ui == "slider"  # 有 min/max
    assert registry.get("fade").parameters[0].ui == "color"


# ---------------------------------------------------------------- 参数校验


def test_validate_合法参数(registry: TransitionLibrary) -> None:
    report = registry.validate("whip", {"direction": "left", "intensity": 0.8, "blur": 0.6})
    assert report["valid"] is True
    assert report["errors"] == [] and report["warnings"] == []


def test_validate_缺参数只是警告(registry: TransitionLibrary) -> None:
    report = registry.validate("whip", {})
    assert report["valid"] is True
    codes = {w["code"] for w in report["warnings"]}
    assert codes == {"MISSING_PARAMETER"}


def test_validate_参数为_None_等同空(registry: TransitionLibrary) -> None:
    assert registry.validate("whip", None)["valid"] is True


def test_validate_类型错误(registry: TransitionLibrary) -> None:
    report = registry.validate("whip", {"intensity": "很强"})
    assert report["valid"] is False
    assert report["errors"][0]["code"] == "TYPE_MISMATCH"
    assert report["errors"][0]["parameter"] == "intensity"
    assert report["errors"][0]["transition"] == "whip"


def test_validate_布尔不能当数字(registry: TransitionLibrary) -> None:
    assert registry.validate("whip", {"intensity": True})["errors"][0]["code"] == "TYPE_MISMATCH"


def test_validate_int_参数拒绝小数(registry: TransitionLibrary) -> None:
    assert registry.validate("glitch", {"slices": 3.5})["errors"][0]["code"] == "TYPE_MISMATCH"
    assert registry.validate("glitch", {"slices": 3.0})["valid"] is True


def test_validate_超范围(registry: TransitionLibrary) -> None:
    low = registry.validate("blur", {"amount": -1.0})
    high = registry.validate("blur", {"amount": 999.0})
    assert low["errors"][0]["code"] == "OUT_OF_RANGE"
    assert high["errors"][0]["code"] == "OUT_OF_RANGE"


def test_validate_枚举非法(registry: TransitionLibrary) -> None:
    report = registry.validate("wipe", {"direction": "斜着"})
    assert report["errors"][0]["code"] == "INVALID_OPTION"


def test_validate_未知参数是警告(registry: TransitionLibrary) -> None:
    report = registry.validate("fade", {"color": "#000000", "玄学": 1})
    assert report["valid"] is True
    assert [w["code"] for w in report["warnings"]] == ["UNKNOWN_PARAMETER"]


def test_validate_params_不是对象(registry: TransitionLibrary) -> None:
    report = registry.validate("fade", ["#000000"])
    assert report["errors"][0]["code"] == "INVALID_PARAMS"


def test_validate_未知转场(registry: TransitionLibrary) -> None:
    report = registry.validate("超级魔法转场", {})
    assert report["valid"] is False
    assert report["errors"][0]["code"] == "UNKNOWN_TRANSITION"


def test_validate_永不抛异常(registry: TransitionLibrary) -> None:
    """指令：结构化结果给 GUI，绝不抛到界面上。"""
    for params in (None, {}, [], "字符串", 42, {"direction": None}, {"blur": [1]}):
        report = registry.validate("whip", params)
        assert set(report) == {"valid", "errors", "warnings"}


def test_默认参数全部合法(registry: TransitionLibrary) -> None:
    for definition in registry.all():
        assert registry.validate(definition.name, definition.default_params())["valid"] is True


# ---------------------------------------------------------------- from / to


def test_合法_from_合法_to(registry: TransitionLibrary) -> None:
    assert registry.validate_pair("whip", "video", "video")["valid"] is True
    assert registry.validate_pair("whip", "freeze", "video")["valid"] is True
    assert registry.validate_pair("whip", "video", "freeze")["valid"] is True


def test_from_类型不支持(registry: TransitionLibrary) -> None:
    report = registry.validate_pair("whip", "audio", "video")
    assert report["valid"] is False
    assert report["errors"][0]["code"] == "UNSUPPORTED_SIDE"
    assert report["errors"][0]["parameter"] == "from"


def test_to_类型不支持(registry: TransitionLibrary) -> None:
    report = registry.validate_pair("whip", "video", "text")
    assert report["errors"][0]["parameter"] == "to"


def test_两侧都不支持时报两条(registry: TransitionLibrary) -> None:
    report = registry.validate_pair("whip", "audio", "audio")
    assert [e["parameter"] for e in report["errors"]] == ["from", "to"]


def test_accepts_from_to(registry: TransitionLibrary) -> None:
    whip = registry.get("whip")
    for element_type in SUPPORTED_SIDES:
        assert whip.accepts_from(element_type) and whip.accepts_to(element_type)
    assert whip.accepts_from("audio") is False
    assert whip.accepts_to("overlay") is False


def test_validate_pair_未知转场(registry: TransitionLibrary) -> None:
    report = registry.validate_pair("不存在", "video", "video")
    assert report["errors"][0]["code"] == "UNKNOWN_TRANSITION"


def test_supported_sides_来自真实渲染能力(registry: TransitionLibrary) -> None:
    """指令第九条：侧类型限制必须来自 renderer 真实能力，不许凭空限制。

    remotion/src/transitions/TransitionLayer.tsx 的 side() 用 VideoLayer 渲染两侧，
    VideoLayer 只认 video（asset）与 freeze（target），所以只有这两个。
    """
    assert SUPPORTED_SIDES == ["video", "freeze"]
    layer = os.path.join(ROOT, "remotion", "src", "transitions", "TransitionLayer.tsx")
    source = open(layer, "r", encoding="utf-8").read()
    assert "VideoLayer" in source


# ---------------------------------------------------------------- 时间窗口边界
#
# Registry 本身不做时间计算，这一节验证的是 Validator 对时间的判断，
# 以及 v1 Schema 层已经挡住的边界（指令第十条：先看 Runtime，别写死结论）。


def test_转场时长超过邻居一半只是警告(validator, timeline) -> None:
    """有人就是要做长溶解，不能判死。"""
    timeline["elements"].append(_transition("fade", {}, duration=4.0, start=3.0))
    issues = validator.validate(timeline)
    hit = [i for i in issues if i.rule_id == "RULE_TRANSITION_003"]
    assert hit and not hit[0].is_error()


def test_浮点边界_5_75_到_6_25_不触发时长告警(validator, timeline) -> None:
    """Demo 用的正是 5.75 + 0.5 → 6.25，恰好等于 5s 片段的一半，不能误报。"""
    timeline["elements"].append(_transition("whip", {}, start=5.75, duration=2.5))
    issues = validator.validate(timeline)
    assert [i for i in issues if i.rule_id == "RULE_TRANSITION_003"] == []


def test_duration_为_0_被_Schema_层挡住(validator, timeline) -> None:
    """指令第十条：不用在语义层重复判，v1 Schema 已声明 duration > 0。"""
    timeline["elements"].append(_transition("whip", {}, duration=0.0))
    issues = validator.validate(timeline)
    assert [i for i in issues if i.rule_id.startswith("SCHEMA")]


def test_负_duration_与负_start_被_Schema_层挡住(validator, timeline) -> None:
    timeline["elements"].append(_transition("whip", {}, start=-1.0, duration=-0.5))
    issues = validator.validate(timeline)
    assert [i for i in issues if i.rule_id.startswith("SCHEMA")]


def test_转场超出时间线末尾不判错(validator, timeline) -> None:
    """当前 Runtime 用 sampleTime 钳制，越界退化为定格而不是黑帧，
    所以不写死 transition.end <= timeline.duration。"""
    timeline["elements"].append(_transition("crossfade", {}, start=9.8, duration=0.5))
    issues = validator.validate(timeline)
    assert [i for i in issues if i.rule_id.startswith("RULE_TRANSITION") and i.is_error()] == []


# ---------------------------------------------------------------- Validator 接线


def test_validator_拦截未知转场(validator, timeline) -> None:
    """既有 _validate_transition 完全没检查过 name，这是阶段 7 补的真实缺口。"""
    timeline["elements"].append(_transition("超级魔法转场", {}))
    issues = validator.validate(timeline)
    hit = [i for i in issues if i.rule_id == "RULE_TRANSITION_004"]
    assert hit and hit[0].is_error()
    assert hit[0].path == ["name"]


def test_validator_from_不存在(validator, timeline) -> None:
    timeline["elements"].append(_transition("whip", {}, from_id="不存在"))
    issues = validator.validate(timeline)
    hit = [i for i in issues if i.rule_id == "RULE_TRANSITION_001"]
    assert hit and hit[0].path == ["from"]


def test_validator_to_不存在(validator, timeline) -> None:
    timeline["elements"].append(_transition("whip", {}, to_id="不存在"))
    issues = validator.validate(timeline)
    hit = [i for i in issues if i.rule_id == "RULE_TRANSITION_001"]
    assert hit and hit[0].path == ["to"]


def test_validator_from_等于_to(validator, timeline) -> None:
    timeline["elements"].append(_transition("whip", {}, to_id="clip_001"))
    issues = validator.validate(timeline)
    hit = [i for i in issues if i.rule_id == "RULE_TRANSITION_002"]
    assert hit and hit[0].is_error()


def test_validator_两侧类型不支持(validator, timeline) -> None:
    timeline["elements"].append(
        tl.make_audio("bgm_001", "audio_001", "A1", start=0.0, duration=5.0)
    )
    timeline["elements"].append(_transition("whip", {}, to_id="bgm_001"))
    issues = validator.validate(timeline)
    hit = [i for i in issues if i.rule_id == "RULE_TRANSITION_005"]
    assert hit and hit[0].is_error()


def test_validator_参数错误(validator, timeline) -> None:
    timeline["elements"].append(_transition("whip", {"intensity": 99.0}))
    issues = validator.validate(timeline)
    hit = [i for i in issues if i.rule_id == "RULE_TRANSITION_006"]
    assert hit and hit[0].is_error()
    assert hit[0].path == ["params", "intensity"]


def test_validator_未知参数是警告(validator, timeline) -> None:
    timeline["elements"].append(_transition("whip", {"玄学": 1}))
    issues = validator.validate(timeline)
    hit = [i for i in issues if i.rule_id == "RULE_TRANSITION_007"]
    assert hit and not hit[0].is_error()


def test_validator_不为缺省参数刷告警(validator, timeline) -> None:
    timeline["elements"].append(_transition("whip", {}))
    issues = validator.validate(timeline)
    assert [i for i in issues if i.rule_id == "RULE_TRANSITION_007"] == []


def test_validator_合法转场零问题(validator, timeline, registry) -> None:
    timeline["elements"].append(_transition("whip", registry.default_params("whip")))
    issues = validator.validate(timeline)
    assert [i for i in issues if i.rule_id.startswith("RULE_TRANSITION")] == []


def test_未知转场时不再重复报参数错(validator, timeline) -> None:
    """name 不认识就没有参数表，再报一堆参数错只会淹掉真正的问题。"""
    timeline["elements"].append(_transition("超级魔法转场", {"玄学": 1}))
    issues = validator.validate(timeline)
    rules = {i.rule_id for i in issues}
    assert "RULE_TRANSITION_004" in rules
    assert "RULE_TRANSITION_006" not in rules
    assert "RULE_TRANSITION_007" not in rules


def test_新增转场不需要改_Validator(validator, timeline, libraries) -> None:
    """阶段 7 的验收点：注册一个新转场就能直接过校验。"""
    libraries.transition.register(
        {
            "name": "curtain",
            "label": "Curtain 幕布",
            "category": "geometric",
            "default_duration": 0.6,
            "renderer": "curtain",
            "supported_from": ["video", "freeze"],
            "supported_to": ["video", "freeze"],
            "params": [
                {"key": "softness", "label": "柔和度", "type": "number", "default": 0.3,
                 "min": 0.0, "max": 1.0, "step": 0.05},
            ],
        }
    )
    timeline["elements"].append(_transition("curtain", {"softness": 0.5}))
    issues = validator.validate(timeline)
    assert [i for i in issues if i.rule_id.startswith("RULE_TRANSITION")] == []

    timeline["elements"][-1]["params"] = {"softness": 9.0}
    issues = validator.validate(timeline)
    assert [i for i in issues if i.rule_id == "RULE_TRANSITION_006"]


def test_rules_json_声明了全部_TRANSITION_规则() -> None:
    with open(os.path.join(ROOT, "schemas", "rules.json"), "r", encoding="utf-8") as handle:
        rules = json.load(handle)["rules"]
    declared = {r["id"]: r["level"] for r in rules if r["id"].startswith("RULE_TRANSITION")}
    assert declared == {
        "RULE_TRANSITION_001": "error",
        "RULE_TRANSITION_002": "error",
        "RULE_TRANSITION_003": "warning",
        "RULE_TRANSITION_004": "error",
        "RULE_TRANSITION_005": "error",
        "RULE_TRANSITION_006": "error",
        "RULE_TRANSITION_007": "warning",
    }


# ---------------------------------------------------------------- 既有兼容性


def test_既有_JSON_形状仍被接受(registry: TransitionLibrary) -> None:
    """指令第二条：v1 里 name/from/to/start/duration/params 的写法必须继续可用。"""
    element = {
        "id": "tr_001",
        "type": "transition",
        "track": "V1",
        "name": "whip",
        "from": "clip_001",
        "to": "clip_002",
        "start": 5.75,
        "duration": 0.5,
        "params": {"direction": "left", "intensity": 0.8, "blur": 0.6},
    }
    assert registry.has(element["name"])
    assert registry.validate(element["name"], element["params"])["valid"] is True
    assert registry.validate_pair(element["name"], "video", "video")["valid"] is True


def test_真实_timeline_json_里的转场全部已注册(registry: TransitionLibrary) -> None:
    """指令第二十四条：既有综合 Demo 必须继续过。

    盯的是 `tests/fixtures/demo_timeline.json` —— 它由 `tools/build_fixtures.py`
    生成、进版本库、由 `tests/test_fixtures.py` 守着，是 Demo 的**权威副本**。
    `remotion/timeline.json` 只是「最后一次导出」的产物（导一次就被覆盖一次），
    所以它只被要求「里面出现的转场必须都已注册」，不要求它一定含转场。
    """
    fixture = os.path.join(ROOT, "tests", "fixtures", "demo_timeline.json")
    assert os.path.isfile(fixture), "Demo 权威副本没了，先跑 tools/build_fixtures.py build"
    with open(fixture, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    transitions = [e for e in data.get("elements", []) if e.get("type") == "transition"]
    assert transitions, "Demo 里应当至少有一个转场"

    exported = os.path.join(ROOT, "remotion", "timeline.json")
    if os.path.isfile(exported):
        with open(exported, "r", encoding="utf-8") as handle:
            live = json.load(handle)
        transitions += [e for e in live.get("elements", []) if e.get("type") == "transition"]
        elements = list(data.get("elements", [])) + list(live.get("elements", []))
    else:
        elements = list(data.get("elements", []))

    by_id = {e.get("id"): e for e in elements}
    for element in transitions:
        assert registry.has(element.get("name")), element
        assert registry.validate(element["name"], element.get("params"))["valid"] is True
        report = registry.validate_pair(
            element["name"],
            by_id[element["from"]]["type"],
            by_id[element["to"]]["type"],
        )
        assert report["valid"] is True, report


def test_真实_Demo_过_Validator_没有转场错误(validator) -> None:
    """Demo 权威副本 + 最后一次导出的产物，都不许有转场级 error。"""
    paths = [os.path.join(ROOT, "tests", "fixtures", "demo_timeline.json"),
             os.path.join(ROOT, "remotion", "timeline.json")]
    checked = 0
    for path in paths:
        if not os.path.isfile(path):
            continue
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        issues = validator.validate(data)
        assert [i for i in issues
                if i.rule_id.startswith("RULE_TRANSITION") and i.is_error()] == [], path
        checked += 1
    assert checked, "两份 Demo JSON 都不在，验收无从谈起"


def test_export_definitions_是纯_JSON(registry: TransitionLibrary) -> None:
    exported = registry.export_definitions()
    assert exported["version"] == 1
    assert len(exported["transitions"]) == 11
    json.dumps(exported, ensure_ascii=False)  # 不可序列化就直接抛


def test_display_categories_保留中文分组(registry: TransitionLibrary) -> None:
    groups = registry.display_categories()
    assert set(groups) == {"基础", "冲击", "几何", "风格"}
    assert registry.get("whip").display_category == "冲击"


def test_ParameterDefinition_与_Effect_侧同一个类() -> None:
    """参数校验只有一份实现，两个 Registry 共用，避免长期漂移。"""
    from libraries.effect_registry import ParameterDefinition as EffectParam

    assert ParameterDefinition is EffectParam


def test_transition_schema_声明了新字段() -> None:
    path = os.path.join(ROOT, "schemas", "transition_schema.json")
    with open(path, "r", encoding="utf-8") as handle:
        schema = json.load(handle)
    text = json.dumps(schema, ensure_ascii=False)
    for field in ("supported_from", "supported_to", "renderer", "display_category"):
        assert field in text, field
