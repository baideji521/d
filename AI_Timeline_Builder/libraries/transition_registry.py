"""Transition Registry：转场的结构化定义、分类、from/to 约束与参数校验。

与 EffectRegistry **刻意不合并**（阶段 7 指令第三条），因为语义不同：

    Effect      = 对一个已有对象施加变化      → 一个 target
    Transition  = 两个对象之间的交接          → from + to

所以这里没有 `target` / `supported_targets`，只有 `from` / `to` /
`supported_from` / `supported_to`，并且多一个 `validate_pair()`。

共用的部分只有「参数怎么声明、怎么校验」——那份实现在 libraries/param_spec.py，
两边共用同一套错误码，避免两份参数校验逻辑长期漂移。

与 Remotion 的对接只靠一个字符串：

    Python TransitionDefinition.renderer == remotion/src/transitions/index.ts 里注册的 name

Registry 只负责「定义 / 参数 / 分类 / 校验 / renderer 身份」，
不负责 progress、插值、渲染 —— 那些是 Runtime 的事，本文件没有时间计算。
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

__all__ = [
    "CATEGORIES",
    "CATEGORY_LABELS",
    "PARAM_TYPES",
    "ParameterDefinition",
    "TransitionDefinition",
    "TransitionRegistry",
    "normalize_param_type",
]

# ---------------------------------------------------------------- 分类

#: 标准分类，按「交接的手法」划分：
#: - basic      平稳交接（透明度 / 中间色）
#: - impact     强冲击（闪、甩、推拉）
#: - geometric  几何遮罩（擦除 / 滑动 / 推移）
#: - stylized   风格化（旋转 / 模糊 / 故障）
CATEGORIES = ("basic", "impact", "geometric", "stylized")

CATEGORY_LABELS: Dict[str, str] = {
    "basic": "基础",
    "impact": "冲击",
    "geometric": "几何",
    "stylized": "风格",
}


# ---------------------------------------------------------------- 定义


class TransitionDefinition(Mapping):
    """一个转场的完整定义。

    实现 Mapping 协议，既有按 dict 访问的 GUI 代码（`definition["label"]`、
    `definition.get("params")`）不受影响。
    """

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
        return f"TransitionDefinition({self.name}/{self.category})"

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
    def renderer(self) -> str:
        """Remotion 侧 renderer 的名字。空 = 尚无 renderer。"""
        return str(self._raw.get("renderer", ""))

    @property
    def default_duration(self) -> float:
        try:
            return float(self._raw.get("default_duration", 0.5))
        except (TypeError, ValueError):
            return 0.5

    @property
    def supported_from(self) -> List[str]:
        """from 侧允许的元素 type。空列表 = 任何类型都不接受。"""
        return [str(t) for t in self._raw.get("supported_from", [])]

    @property
    def supported_to(self) -> List[str]:
        return [str(t) for t in self._raw.get("supported_to", [])]

    @property
    def parameters(self) -> List[ParameterDefinition]:
        return list(self._parameters)

    # ---- 参数

    def parameter(self, key: str) -> Optional[ParameterDefinition]:
        return self._by_key.get(key)

    def default_params(self) -> Dict[str, Any]:
        return {p.name: p.default for p in self._parameters}

    def fill_defaults(self, params: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """给缺失的参数补默认值，返回**新** dict，不回写 Timeline JSON。"""
        merged = self.default_params()
        if isinstance(params, dict):
            merged.update(params)
        return merged

    # ---- from / to

    def accepts_from(self, element_type: str) -> bool:
        return element_type in self.supported_from

    def accepts_to(self, element_type: str) -> bool:
        return element_type in self.supported_to


# ---------------------------------------------------------------- Registry


class TransitionRegistry:
    """转场注册表。重复 name 后注册覆盖前者（自定义 JSON 覆盖内置定义）。"""

    def __init__(self, definitions: Optional[Sequence[Dict[str, Any]]] = None) -> None:
        self._definitions: Dict[str, TransitionDefinition] = {}
        for definition in definitions or []:
            self.register(definition)

    # ------------------------------------------------------------ 增删

    def register(self, definition: Any) -> Optional[TransitionDefinition]:
        """注册一个转场。没有 name 的定义直接忽略（返回 None），不抛异常。"""
        if isinstance(definition, TransitionDefinition):
            entry = definition
        elif isinstance(definition, Mapping):
            entry = TransitionDefinition(dict(definition))
        else:
            return None
        if not entry.name:
            return None
        self._definitions[entry.name] = entry
        return entry

    def unregister(self, name: str) -> bool:
        return self._definitions.pop(name, None) is not None

    # ------------------------------------------------------------ 查询

    def get(self, name: str) -> Optional[TransitionDefinition]:
        return self._definitions.get(name)

    def has(self, name: str) -> bool:
        return name in self._definitions

    def all(self) -> List[TransitionDefinition]:
        return list(self._definitions.values())

    def names(self) -> List[str]:
        return list(self._definitions.keys())

    def categories(self) -> List[str]:
        """实际用到的标准分类，按 CATEGORIES 的顺序返回。"""
        used = {d.category for d in self._definitions.values() if d.category}
        return [c for c in CATEGORIES if c in used]

    def by_category(self, category: str) -> List[TransitionDefinition]:
        return [d for d in self._definitions.values() if d.category == category]

    def renderers(self) -> Dict[str, str]:
        return {d.name: d.renderer for d in self._definitions.values() if d.renderer}

    def without_renderer(self) -> List[str]:
        return sorted(d.name for d in self._definitions.values() if not d.renderer)

    # ------------------------------------------------------------ 校验

    def validate(self, name: str, params: Any = None) -> Dict[str, Any]:
        """校验 name + params。永远返回结构化结果，永远不抛异常。"""
        definition = self._definitions.get(name)
        if definition is None:
            return error_report(
                "UNKNOWN_TRANSITION",
                f"转场 {name} 未在 TransitionRegistry 注册",
                "transition",
                str(name),
            )
        return validate_params(definition.parameters, params, "transition", name)

    def validate_pair(self, name: str, from_type: str, to_type: str) -> Dict[str, Any]:
        """校验 from / to 两侧元素的类型是否被这个转场支持。

        能力边界来自 Remotion 侧 TransitionLayer 用 VideoLayer 渲染两侧这一事实 ——
        只有 video / freeze 能被 VideoLayer 画出来，不是凭空设的限制。
        """
        definition = self._definitions.get(name)
        if definition is None:
            return error_report(
                "UNKNOWN_TRANSITION",
                f"转场 {name} 未在 TransitionRegistry 注册",
                "transition",
                str(name),
            )
        errors: List[Dict[str, str]] = []
        for side, element_type, allowed, accepted in (
            ("from", from_type, definition.supported_from, definition.accepts_from(from_type)),
            ("to", to_type, definition.supported_to, definition.accepts_to(to_type)),
        ):
            if accepted:
                continue
            allow_text = " / ".join(allowed) or "（无）"
            errors.append(
                {
                    "code": "UNSUPPORTED_SIDE",
                    "parameter": side,
                    "transition": name,
                    "message": f"{name} 的 {side} 只能是 {allow_text}，不能是 {element_type}",
                }
            )
        if not errors:
            return ok_report()
        return {"valid": False, "errors": errors, "warnings": []}

    # ------------------------------------------------------------ 导出

    def export_definitions(self) -> Dict[str, Any]:
        """导出给 Remotion / 文档参考。渲染端按 name 查自己的表，不依赖这份数据。"""
        return {"version": 1, "transitions": [dict(d) for d in self.all()]}
