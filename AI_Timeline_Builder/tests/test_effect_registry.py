"""EffectRegistry 的单元测试（阶段 6 第二十条）。

覆盖：Registry 增删查 / Definition 元数据 / Parameter 定义 / 参数校验 /
target 校验 / 未知特效 / 既有 JSON 的兼容性 / Validator 接线。
"""

from __future__ import annotations

import copy
import json
import os

import pytest

from core import timeline as tl
from libraries.effect_library import (
    MATERIAL_EFFECTS,
    PROGRAM_EFFECTS,
    VISUAL_TARGETS,
    EffectLibrary,
)
from libraries.effect_registry import (
    CATEGORIES,
    PARAM_TYPES,
    EffectDefinition,
    EffectRegistry,
    ParameterDefinition,
    normalize_param_type,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def registry() -> EffectLibrary:
    return EffectLibrary(os.path.join(ROOT, "assets"))


def _effect_element(name: str, params=None, target: str = "clip_001") -> dict:
    return tl.make_effect(
        "fx_001",
        name,
        params if params is not None else {},
        track="V1",
        start=1.0,
        duration=0.6,
        target=target,
    )


# ---------------------------------------------------------------- Registry 本体


def test_register_get_has_all(registry: EffectLibrary) -> None:
    total = len(registry.all())
    definition = registry.register(
        {
            "name": "test_fx",
            "label": "测试特效",
            "kind": "program",
            "category": "geometry",
            "default_duration": 0.5,
            "renderer": "test_fx",
            "supported_targets": ["video"],
            "params": [],
        }
    )
    assert definition is not None
    assert registry.has("test_fx")
    assert registry.get("test_fx").display_name == "测试特效"
    assert len(registry.all()) == total + 1
    assert "test_fx" in registry.names()


def test_unregister(registry: EffectLibrary) -> None:
    assert registry.unregister("zoom") is True
    assert registry.has("zoom") is False
    assert registry.unregister("zoom") is False


def test_register_忽略无名定义与非字典() -> None:
    reg = EffectRegistry()
    assert reg.register({"label": "没有 name"}) is None
    assert reg.register("zoom") is None
    assert reg.register(None) is None
    assert reg.all() == []


def test_同名后注册覆盖前者() -> None:
    reg = EffectRegistry(
        [
            {"name": "zoom", "label": "旧", "default_duration": 0.5, "params": []},
            {"name": "zoom", "label": "新", "default_duration": 0.5, "params": []},
        ]
    )
    assert len(reg.all()) == 1
    assert reg.get("zoom").display_name == "新"


def test_categories_只返回实际用到的且按标准顺序(registry: EffectLibrary) -> None:
    categories = registry.categories()
    assert categories == ["geometry", "visual", "screen", "overlay"]
    # audio 分类已定义但当前仓库里还没有音频特效，必须如实不出现
    assert "audio" in CATEGORIES
    assert registry.by_category("audio") == []


def test_by_category_覆盖全部特效(registry: EffectLibrary) -> None:
    counted = sum(len(registry.by_category(c)) for c in CATEGORIES)
    assert counted == len(registry.all())


def test_每个特效的分类都是标准分类(registry: EffectLibrary) -> None:
    for definition in registry.all():
        assert definition.category in CATEGORIES, definition.name


# ---------------------------------------------------------------- Definition


def test_内置特效数量() -> None:
    assert len(PROGRAM_EFFECTS) == 14
    assert len(MATERIAL_EFFECTS) == 10


def test_program_与_material_分流(registry: EffectLibrary) -> None:
    assert len(registry.program_effects()) == 14
    assert len(registry.material_effects()) == 10
    assert len(registry.all()) == 24


def test_definition_元数据齐全(registry: EffectLibrary) -> None:
    zoom = registry.get("zoom")
    assert zoom.name == "zoom"
    assert zoom.display_name == "Zoom 推拉"
    assert zoom.category == "geometry"
    assert zoom.description
    assert zoom.renderer == "zoom"
    assert zoom.scope == "element"
    assert zoom.kind == "program"
    assert zoom.element_type == "effect"
    assert zoom.default_duration == 0.6
    assert [p.name for p in zoom.parameters] == [
        "scale_from",
        "scale_to",
        "origin_x",
        "origin_y",
    ]


def test_definition_仍然可以当_dict_用(registry: EffectLibrary) -> None:
    """既有 GUI 代码是按 dict 访问的，引入 Registry 不许把它们打断。"""
    zoom = registry.get("zoom")
    assert zoom["name"] == "zoom"
    assert zoom["label"] == "Zoom 推拉"
    assert zoom.get("default_duration") == 0.6
    assert isinstance(zoom.get("params"), list)
    assert zoom["params"][0]["key"] == "scale_from"
    assert dict(zoom)["kind"] == "program"


def test_screen_类特效的_scope(registry: EffectLibrary) -> None:
    for name in ("flash", "vignette", "rgb_split", "glitch"):
        definition = registry.get(name)
        assert definition.category == "screen"
        assert definition.scope == "screen"


def test_素材特效不能作为_effect_元素(registry: EffectLibrary) -> None:
    fire = registry.get("fire")
    assert fire.kind == "material"
    assert fire.element_type == "overlay"
    assert fire.supported_targets == []
    assert fire.scope == "asset"
    assert fire.renderer == ""


def test_renderers_与_without_renderer(registry: EffectLibrary) -> None:
    renderers = registry.renderers()
    assert len(renderers) == 14
    assert renderers["motion_blur"] == "motion_blur"
    # 素材特效只有 metadata，靠 overlay 元素渲染，没有 effect renderer
    assert registry.without_renderer() == sorted(e["name"] for e in MATERIAL_EFFECTS)


def test_renderer_名与特效名一致(registry: EffectLibrary) -> None:
    """两侧靠 name 对接，renderer 一旦改名就必须显式改这里。"""
    for definition in registry.program_effects():
        assert definition.renderer == definition.name


# ---------------------------------------------------------------- Parameter


def test_parameter_定义字段(registry: EffectLibrary) -> None:
    param = registry.get("zoom").parameter("scale_to")
    assert param.name == "scale_to"
    assert param.display_name == "结束 Scale"
    assert param.type == "number"
    assert param.default == 1.35
    assert param.minimum == 0.1
    assert param.maximum == 5.0
    assert param.step == 0.01
    assert param.ui == "slider"


def test_parameter_枚举与颜色(registry: EffectLibrary) -> None:
    decay = registry.get("flash").parameter("decay")
    assert decay.type == "enum"
    assert decay.options == ["linear", "easeIn", "easeOut", "easeInOut"]
    assert decay.ui == "combo"
    color = registry.get("flash").parameter("color")
    assert color.type == "color"
    assert color.ui == "color"


def test_parameter_整数类型(registry: EffectLibrary) -> None:
    slices = registry.get("glitch").parameter("slices")
    assert slices.type == "int"
    assert slices.default == 12


def test_每个参数的类型都在受支持范围内(registry: EffectLibrary) -> None:
    for definition in registry.all():
        for param in definition.parameters:
            assert param.type in PARAM_TYPES, f"{definition.name}.{param.name}"


def test_类型别名会被归一化() -> None:
    assert normalize_param_type("integer") == "int"
    assert normalize_param_type("boolean") == "bool"
    assert normalize_param_type("str") == "string"
    assert normalize_param_type("number") == "number"
    definition = EffectDefinition(
        {
            "name": "x",
            "params": [{"key": "n", "label": "N", "type": "integer", "default": 1}],
        }
    )
    assert definition.parameter("n").type == "int"
    # 归一化结果也要写回 dict 视图，否则 GUI 读到的还是别名
    assert definition["params"][0]["type"] == "int"


def test_default_params_与_fill_defaults(registry: EffectLibrary) -> None:
    zoom = registry.get("zoom")
    assert zoom.default_params() == {
        "scale_from": 1.0,
        "scale_to": 1.35,
        "origin_x": 0.5,
        "origin_y": 0.45,
    }
    filled = zoom.fill_defaults({"scale_to": 2.0})
    assert filled["scale_to"] == 2.0
    assert filled["scale_from"] == 1.0


def test_fill_defaults_不回写原始数据(registry: EffectLibrary) -> None:
    """指令第十七条：默认值只在读取时补，Timeline JSON 必须还是用户指定的东西。"""
    original = {"scale_to": 2.0}
    snapshot = copy.deepcopy(original)
    registry.get("zoom").fill_defaults(original)
    assert original == snapshot


def test_library_的_default_params_与_param_spec(registry: EffectLibrary) -> None:
    assert registry.default_params("zoom")["scale_to"] == 1.35
    assert registry.default_params("不存在") == {}
    assert registry.param_spec("zoom", "scale_to")["min"] == 0.1
    assert registry.param_spec("zoom", "不存在") is None
    assert registry.param_spec("不存在", "scale_to") is None
    assert registry.label_of("zoom") == "Zoom 推拉"
    assert registry.label_of("不存在") == "不存在"


# ---------------------------------------------------------------- 参数校验


def test_validate_合法参数(registry: EffectLibrary) -> None:
    report = registry.validate("zoom", registry.default_params("zoom"))
    assert report == {"valid": True, "errors": [], "warnings": []}


def test_validate_缺参数只是警告(registry: EffectLibrary) -> None:
    report = registry.validate("zoom", {"scale_from": 1.0})
    assert report["valid"] is True
    codes = {w["code"] for w in report["warnings"]}
    assert codes == {"MISSING_PARAMETER"}
    assert len(report["warnings"]) == 3


def test_validate_params_为空等价于全部缺省(registry: EffectLibrary) -> None:
    assert registry.validate("zoom", None)["valid"] is True
    assert registry.validate("zoom", {})["valid"] is True


def test_validate_类型错误(registry: EffectLibrary) -> None:
    report = registry.validate("zoom", {"scale_to": "一点四倍"})
    assert report["valid"] is False
    assert report["errors"][0]["code"] == "TYPE_MISMATCH"
    assert report["errors"][0]["parameter"] == "scale_to"


def test_validate_布尔不能当数字用(registry: EffectLibrary) -> None:
    """Python 里 True 是 int 的子类，必须显式挡住，否则脏数据静默通过。"""
    report = registry.validate("zoom", {"scale_to": True})
    assert report["valid"] is False
    assert report["errors"][0]["code"] == "TYPE_MISMATCH"


def test_validate_超范围(registry: EffectLibrary) -> None:
    high = registry.validate("zoom", {"scale_to": 99.0})
    low = registry.validate("zoom", {"scale_to": -1.0})
    assert high["valid"] is False and low["valid"] is False
    assert high["errors"][0]["code"] == "OUT_OF_RANGE"
    assert "0.1～5.0" in high["errors"][0]["message"]


def test_validate_边界值算合法(registry: EffectLibrary) -> None:
    assert registry.validate("zoom", {"scale_to": 0.1})["valid"] is True
    assert registry.validate("zoom", {"scale_to": 5.0})["valid"] is True


def test_validate_整数参数拒绝小数(registry: EffectLibrary) -> None:
    assert registry.validate("glitch", {"slices": 12})["valid"] is True
    assert registry.validate("glitch", {"slices": 12.0})["valid"] is True
    report = registry.validate("glitch", {"slices": 12.5})
    assert report["valid"] is False
    assert report["errors"][0]["code"] == "TYPE_MISMATCH"


def test_validate_枚举取值(registry: EffectLibrary) -> None:
    assert registry.validate("flash", {"decay": "easeOut"})["valid"] is True
    report = registry.validate("flash", {"decay": "弹跳"})
    assert report["valid"] is False
    assert report["errors"][0]["code"] == "INVALID_OPTION"


def test_validate_未知参数只是警告(registry: EffectLibrary) -> None:
    report = registry.validate("zoom", dict(registry.default_params("zoom"), 玄学=1))
    assert report["valid"] is True
    assert report["warnings"][0]["code"] == "UNKNOWN_PARAMETER"
    assert report["warnings"][0]["parameter"] == "玄学"


def test_validate_params_不是对象(registry: EffectLibrary) -> None:
    for bad in ([1, 2], "zoom", 3.14):
        report = registry.validate("zoom", bad)
        assert report["valid"] is False
        assert report["errors"][0]["code"] == "INVALID_PARAMS"


def test_validate_多个错误同时报出(registry: EffectLibrary) -> None:
    report = registry.validate("zoom", {"scale_from": 99.0, "scale_to": "字符串"})
    assert len({e["parameter"] for e in report["errors"]}) == 2


def test_validate_从不抛异常(registry: EffectLibrary) -> None:
    """GUI 拿到的必须是数据，不是 traceback（第六条）。"""
    for params in (None, {}, {"scale_to": None}, {"scale_to": [1]}, {"scale_to": {}}):
        report = registry.validate("zoom", params)
        assert set(report) == {"valid", "errors", "warnings"}


def test_每个内置特效的默认参数都自校验通过(registry: EffectLibrary) -> None:
    """默认值本身违反自己声明的范围，是最容易长期潜伏的错误。"""
    for definition in registry.all():
        report = registry.validate(definition.name, definition.default_params())
        assert report["valid"] is True, (definition.name, report["errors"])
        assert report["warnings"] == []


# ---------------------------------------------------------------- 未知特效


def test_未知特效返回结构化错误而不是崩溃(registry: EffectLibrary) -> None:
    report = registry.validate("super_magic_zoom", {"foo": 1})
    assert report["valid"] is False
    assert report["errors"][0]["code"] == "UNKNOWN_EFFECT"
    assert report["errors"][0]["effect"] == "super_magic_zoom"


def test_未知特效的_target_校验也不崩(registry: EffectLibrary) -> None:
    report = registry.validate_target("super_magic_zoom", "video")
    assert report["valid"] is False
    assert report["errors"][0]["code"] == "UNKNOWN_EFFECT"


# ---------------------------------------------------------------- target


def test_supported_targets_取自_TimelineVideo_的可视类型(registry: EffectLibrary) -> None:
    assert registry.get("zoom").supported_targets == VISUAL_TARGETS
    assert "audio" not in VISUAL_TARGETS


@pytest.mark.parametrize("element_type", ["video", "image", "overlay"])
def test_zoom_可以作用于视觉元素(registry: EffectLibrary, element_type: str) -> None:
    assert registry.validate_target("zoom", element_type)["valid"] is True
    assert registry.get("zoom").accepts_target(element_type) is True


def test_zoom_不能作用于音频(registry: EffectLibrary) -> None:
    report = registry.validate_target("zoom", "audio")
    assert report["valid"] is False
    assert report["errors"][0]["code"] == "UNSUPPORTED_TARGET"
    assert "audio" in report["errors"][0]["message"]
    assert registry.get("zoom").accepts_target("audio") is False


def test_素材特效拒绝任何_target(registry: EffectLibrary) -> None:
    assert registry.validate_target("fire", "video")["valid"] is False


# ---------------------------------------------------------------- 既有兼容性


def test_既有_JSON_形状仍被接受(registry: EffectLibrary) -> None:
    """指令第二条：v1 Runtime 里 name/params/easing/target 的写法必须继续可用。"""
    element = {
        "id": "fx_001",
        "type": "effect",
        "track": "V1",
        "name": "zoom",
        "start": 24.0,
        "duration": 0.6,
        "easing": "easeOut",
        "target": "clip_001",
        "params": {"scale_from": 1.0, "scale_to": 1.35},
    }
    assert registry.has(element["name"])
    assert registry.validate(element["name"], element["params"])["valid"] is True
    assert registry.validate_target(element["name"], "video")["valid"] is True


def test_make_effect_产出的元素能过_Registry(registry: EffectLibrary) -> None:
    for definition in registry.program_effects():
        element = _effect_element(definition.name, registry.default_params(definition.name))
        assert element["type"] == "effect"
        assert registry.validate(element["name"], element["params"])["valid"] is True


def test_真实_timeline_json_里的特效全部已注册(registry: EffectLibrary) -> None:
    """Demo 权威副本（tests/fixtures/demo_timeline.json）必须有特效且全部已注册。

    `remotion/timeline.json` 是「最后一次导出」的产物，导一次就被覆盖一次，
    所以它只被要求「里面出现的特效必须已注册」。
    """
    fixture = os.path.join(ROOT, "tests", "fixtures", "demo_timeline.json")
    assert os.path.isfile(fixture), "Demo 权威副本没了，先跑 tools/build_fixtures.py build"
    with open(fixture, "r", encoding="utf-8") as handle:
        effects = [e for e in json.load(handle).get("elements", [])
                   if e.get("type") == "effect"]
    assert effects, "Demo 里应当至少有一个特效"
    exported = os.path.join(ROOT, "remotion", "timeline.json")
    if os.path.isfile(exported):
        with open(exported, "r", encoding="utf-8") as handle:
            effects += [e for e in json.load(handle).get("elements", [])
                        if e.get("type") == "effect"]
    for element in effects:
        assert registry.has(element.get("name")), element
        assert registry.get(element["name"]).element_type == "effect"
        assert registry.validate(element["name"], element.get("params"))["valid"] is True


def test_export_definitions_是纯_JSON(registry: EffectLibrary) -> None:
    exported = registry.export_definitions()
    assert exported["version"] == 1
    assert len(exported["effects"]) == 24
    json.dumps(exported, ensure_ascii=False)  # 不可序列化就直接抛


def test_display_categories_保留中文分组(registry: EffectLibrary) -> None:
    """GUI 库面板按中文分组显示，标准分类不能把它顶掉。"""
    groups = registry.display_categories()
    assert "运动" in groups
    assert "素材特效" in groups
    assert registry.get("zoom").display_category == "运动"


def test_没写_display_category_时退回标准分类中文名() -> None:
    definition = EffectDefinition({"name": "x", "category": "geometry", "params": []})
    assert definition.display_category == "几何（位移/缩放/旋转）"


# ---------------------------------------------------------------- Validator 接线


def test_validator_拦截未知特效(validator, timeline) -> None:
    timeline["elements"].append(_effect_element("super_magic_zoom"))
    issues = validator.validate(timeline)
    rules = {i.rule_id for i in issues if i.is_error()}
    assert "RULE_EFFECT_001" in rules


def test_validator_拦截超范围参数(validator, timeline) -> None:
    timeline["elements"].append(_effect_element("zoom", {"scale_to": 99.0}))
    issues = validator.validate(timeline)
    hit = [i for i in issues if i.rule_id == "RULE_EFFECT_004"]
    assert hit and hit[0].is_error()
    assert hit[0].element_id == "fx_001"
    assert hit[0].path == ["params", "scale_to"]


def test_validator_拦截错类型的_target(validator, timeline) -> None:
    timeline["elements"].append(
        tl.make_audio("bgm_001", "audio_001", "A1", start=0.0, duration=5.0)
    )
    timeline["elements"].append(_effect_element("zoom", target="bgm_001"))
    issues = validator.validate(timeline)
    hit = [i for i in issues if i.rule_id == "RULE_EFFECT_003"]
    assert hit and hit[0].is_error()


def test_validator_target_不存在仍是警告(validator, timeline) -> None:
    timeline["elements"].append(_effect_element("zoom", target="不存在"))
    issues = validator.validate(timeline)
    hit = [i for i in issues if i.rule_id == "RULE_EFFECT_002"]
    assert hit and not hit[0].is_error()


def test_validator_未知参数是警告(validator, timeline) -> None:
    timeline["elements"].append(_effect_element("zoom", {"玄学": 1}))
    issues = validator.validate(timeline)
    hit = [i for i in issues if i.rule_id == "RULE_EFFECT_005"]
    assert hit and not hit[0].is_error()


def test_validator_不为缺省参数刷告警(validator, timeline) -> None:
    """params 留空是合法写法，Runtime 会补默认值，不该每个参数报一条。"""
    timeline["elements"].append(_effect_element("zoom", {}))
    issues = validator.validate(timeline)
    assert [i for i in issues if i.rule_id == "RULE_EFFECT_005"] == []


def test_validator_拦截素材特效写成_effect(validator, timeline) -> None:
    timeline["elements"].append(_effect_element("fire"))
    issues = validator.validate(timeline)
    hit = [i for i in issues if i.rule_id == "RULE_EFFECT_006"]
    assert hit and hit[0].is_error()


def test_validator_合法特效零问题(validator, timeline, registry) -> None:
    timeline["elements"].append(_effect_element("zoom", registry.default_params("zoom")))
    issues = validator.validate(timeline)
    assert [i for i in issues if i.rule_id.startswith("RULE_EFFECT")] == []


def test_新增特效不需要改_Validator(validator, timeline, libraries) -> None:
    """阶段 6 的验收点：注册一个新特效就能直接过校验。"""
    libraries.effect.register(
        {
            "name": "warp",
            "label": "Warp 扭曲",
            "kind": "program",
            "category": "geometry",
            "default_duration": 0.4,
            "renderer": "warp",
            "supported_targets": ["video"],
            "params": [
                {"key": "amount", "label": "强度", "type": "number", "default": 0.3,
                 "min": 0.0, "max": 1.0, "step": 0.05},
            ],
        }
    )
    timeline["elements"].append(_effect_element("warp", {"amount": 0.5}))
    issues = validator.validate(timeline)
    assert [i for i in issues if i.rule_id.startswith("RULE_EFFECT")] == []

    timeline["elements"][-1]["params"] = {"amount": 9.0}
    issues = validator.validate(timeline)
    assert [i for i in issues if i.rule_id == "RULE_EFFECT_004"]


def test_rules_json_声明了全部_EFFECT_规则() -> None:
    with open(os.path.join(ROOT, "schemas", "rules.json"), "r", encoding="utf-8") as handle:
        rules = json.load(handle)["rules"]
    declared = {r["id"]: r["level"] for r in rules if r["id"].startswith("RULE_EFFECT")}
    assert declared == {
        "RULE_EFFECT_001": "error",
        "RULE_EFFECT_002": "warning",
        "RULE_EFFECT_003": "error",
        "RULE_EFFECT_004": "error",
        "RULE_EFFECT_005": "warning",
        "RULE_EFFECT_006": "error",
    }


def test_ParameterDefinition_可以单独使用() -> None:
    param = ParameterDefinition({"key": "v", "label": "值", "type": "bool", "default": True})
    assert param.check(True) == []
    assert param.check(1)[0]["code"] == "TYPE_MISMATCH"
    assert param.ui == "checkbox"
    assert param.minimum is None and param.maximum is None
