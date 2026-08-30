"""Effect Registry：特效的结构化定义、分类、目标约束与参数校验。

这是 Effect 这条链路的**唯一权威来源**：

    EffectRegistry → metadata → parameters → validation → GUI 控件 → renderer 标识

设计约束（阶段 6 指令第十一条）：
Registry 只负责「定义 / 参数 / 分类 / 校验 / renderer 身份」，
**不负责** currentFrame、interpolate、render —— 那些是 Runtime 的事。
所以本文件里不会出现任何时间计算。

与 Remotion 的对接只靠一个字符串：

    Python EffectDefinition.renderer  ==  remotion/src/effects/registry.ts 里注册的 name

两边不共享代码，只共享这个名字。

EffectDefinition / ParameterDefinition 都实现了 Mapping 协议，
因此既能 `definition.supported_targets` 这样结构化访问，
也能 `definition["label"]` / `definition.get("params")` 兼容既有 GUI 代码。
这是刻意的：不为了引入 Registry 就去改一堆调用点。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Dict, Iterator, List, Optional, Sequence

from libraries.param_spec import (
    PARAM_TYPES,
    ParameterDefinition,
    error_report,
    normalize_param_type,
    ok_report,
    validate_params,
)

# 参数定义与参数校验是 Effect / Transition 共用的，实现在 libraries/param_spec.py。
# 这里重新导出，既有 `from libraries.effect_registry import ParameterDefinition`
# 的调用点不受影响。
__all__ = [
    "CATEGORIES",
    "CATEGORY_LABELS",
    "PARAM_TYPES",
    "EffectDefinition",
    "EffectRegistry",
    "ParameterDefinition",
    "normalize_param_type",
]

# ---------------------------------------------------------------- 分类

#: 标准分类。含义按「作用在什么层面」划分，不是按视觉风格划分。
#: - geometry 改元素的位置/缩放/旋转
#: - visual   改元素的画质滤镜（模糊、亮度、饱和度…）
#: - screen   盖在整个画面上，不属于任何单个元素
#: - overlay  依赖素材文件，写进 Timeline 时是 overlay 元素而非 effect 元素
#: - audio    作用于音频元素
CATEGORIES = ("geometry", "visual", "screen", "overlay", "audio")

CATEGORY_LABELS: Dict[str, str] = {
    "geometry": "几何（位移/缩放/旋转）",
    "visual": "画质（滤镜）",
    "screen": "全屏",
    "overlay": "素材叠加",
    "audio": "音频",
}


# ---------------------------------------------------------------- 特效定义



class EffectDefinition(Mapping):
    """一个特效的完整定义。"""

    def __init__(self, raw: Dict[str, Any]) -> None:
        self._raw = dict(raw)
        self._parameters = [ParameterDefinition(p) for p in self._raw.get("params", [])]
        # 归一化后的参数表写回底层 dict，GUI 读到的 type 也就是内部名字
        self._raw["params"] = [dict(p) for p in self._parameters]
        self._by_key = {p.name: p for p in self._parameters}

    # ---- Mapping 协议

    def __getitem__(self, key: str) -> Any:
        return self._raw[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._raw)

    def __len__(self) -> int:
        return len(self._raw)

    def __repr__(self) -> str:  # pragma: no cover - 仅调试用
        return f"EffectDefinition({self.name}/{self.category})"

    # ---- 结构化访问

    @property
    def name(self) -> str:
        """写入 Timeline JSON 的稳定标识，也是 Remotion 侧查表的键。"""
        return str(self._raw.get("name", ""))

    @property
    def display_name(self) -> str:
        return str(self._raw.get("label", self.name))

    @property
    def category(self) -> str:
        return str(self._raw.get("category", ""))

    @property
    def display_category(self) -> str:
        """GUI 库面板的中文分组。没写就退回标准分类的中文名。"""
        return str(self._raw.get("display_category") or CATEGORY_LABELS.get(self.category, ""))

    @property
    def description(self) -> str:
        return str(self._raw.get("description", ""))

    @property
    def parameters(self) -> List[ParameterDefinition]:
        return list(self._parameters)

    @property
    def supported_targets(self) -> List[str]:
        """可以作用于哪些元素 type。空列表 = 不能作为 type=effect 的 target。"""
        return [str(t) for t in self._raw.get("supported_targets", [])]

    @property
    def renderer(self) -> str:
        """Remotion 侧 renderer 的名字。空 = 尚无 renderer。"""
        return str(self._raw.get("renderer", ""))

    @property
    def scope(self) -> str:
        """element = 作用于单个元素；screen = 盖在整屏；asset = 依赖素材。"""
        explicit = self._raw.get("scope")
        if explicit:
            return str(explicit)
        return {"screen": "screen", "overlay": "asset"}.get(self.category, "element")

    @property
    def kind(self) -> str:
        """program = 写成 type=effect；material = 写成 type=overlay。"""
        return str(self._raw.get("kind", "program"))

    @property
    def element_type(self) -> str:
        """这个特效落到 Timeline JSON 里是什么 type。"""
        return "effect" if self.kind == "program" else "overlay"

    @property
    def default_duration(self) -> float:
        try:
            return float(self._raw.get("default_duration", 0.5))
        except (TypeError, ValueError):
            return 0.5

    # ---- 参数

    def parameter(self, key: str) -> Optional[ParameterDefinition]:
        return self._by_key.get(key)

    def default_params(self) -> Dict[str, Any]:
        """一份完整默认 params。注意：调用方决定要不要写进 JSON。"""
        return {p.name: p.default for p in self._parameters}

    def fill_defaults(self, params: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """给缺失的参数补默认值，返回**新** dict。

        指令第十七条：默认值只在读取时补，不许回写 Timeline JSON，
        否则 JSON 就不再是用户真正指定的东西了。
        """
        merged = self.default_params()
        if isinstance(params, dict):
            merged.update(params)
        return merged

    def accepts_target(self, element_type: str) -> bool:
        return element_type in self.supported_targets


# ---------------------------------------------------------------- Registry


class EffectRegistry:
    """特效注册表。

    注册进来的定义会按 name 建索引；重复 name 后注册覆盖前者
    （自定义 JSON 覆盖内置定义就是靠这个）。
    """

    def __init__(self, definitions: Optional[Sequence[Dict[str, Any]]] = None) -> None:
        self._definitions: Dict[str, EffectDefinition] = {}
        for definition in definitions or []:
            self.register(definition)

    # ------------------------------------------------------------ 增删

    def register(self, definition: Any) -> Optional[EffectDefinition]:
        """注册一个特效。没有 name 的定义直接忽略（返回 None），不抛异常。"""
        if isinstance(definition, EffectDefinition):
            entry = definition
        elif isinstance(definition, Mapping):
            entry = EffectDefinition(dict(definition))
        else:
            return None
        if not entry.name:
            return None
        self._definitions[entry.name] = entry
        return entry

    def unregister(self, name: str) -> bool:
        return self._definitions.pop(name, None) is not None

    # ------------------------------------------------------------ 查询

    def get(self, name: str) -> Optional[EffectDefinition]:
        return self._definitions.get(name)

    def has(self, name: str) -> bool:
        return name in self._definitions

    def all(self) -> List[EffectDefinition]:
        return list(self._definitions.values())

    def names(self) -> List[str]:
        return list(self._definitions.keys())

    def categories(self) -> List[str]:
        """实际用到的标准分类，按 CATEGORIES 的顺序返回。"""
        used = {d.category for d in self._definitions.values() if d.category}
        return [c for c in CATEGORIES if c in used]

    def by_category(self, category: str) -> List[EffectDefinition]:
        return [d for d in self._definitions.values() if d.category == category]

    def renderers(self) -> Dict[str, str]:
        """name → renderer 映射。renderer 为空的不列入。"""
        return {d.name: d.renderer for d in self._definitions.values() if d.renderer}

    def without_renderer(self) -> List[str]:
        """只有 metadata、还没有 renderer 的特效。"""
        return sorted(d.name for d in self._definitions.values() if not d.renderer)

    # ------------------------------------------------------------ 校验

    def validate(self, name: str, params: Any = None) -> Dict[str, Any]:
        """校验 name + params。永远返回结构化结果，永远不抛异常。

        指令第六条：GUI 拿到的必须是数据，不是 traceback。
        参数校验本身走 param_spec.validate_params，与 Transition 共用同一份实现。
        """
        definition = self._definitions.get(name)
        if definition is None:
            return error_report(
                "UNKNOWN_EFFECT",
                f"特效 {name} 未在 EffectRegistry 注册",
                "effect",
                str(name),
            )
        return validate_params(definition.parameters, params, "effect", name)

    def validate_target(self, name: str, element_type: str) -> Dict[str, Any]:
        """校验 target 元素的类型是否被这个特效支持。"""
        definition = self._definitions.get(name)
        if definition is None:
            return error_report(
                "UNKNOWN_EFFECT",
                f"特效 {name} 未在 EffectRegistry 注册",
                "effect",
                str(name),
            )
        if definition.accepts_target(element_type):
            return ok_report()
        allowed = " / ".join(definition.supported_targets) or "（无）"
        return error_report(
            "UNSUPPORTED_TARGET",
            f"{name} 只能作用于 {allowed}，不能作用于 {element_type}",
            "effect",
            name,
            parameter="target",
        )

    # ------------------------------------------------------------ 导出


    def export_definitions(self) -> Dict[str, Any]:
        """导出给 Remotion / 文档参考。渲染端按 name 查自己的表，不依赖这份数据。"""
        return {"version": 1, "effects": [dict(d) for d in self.all()]}
