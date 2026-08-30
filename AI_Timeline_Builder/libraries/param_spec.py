"""参数定义与参数校验的共享实现。

Effect 和 Transition 是两种不同的语义（一个 target vs 两个 target），
Registry 必须分开（阶段 7 指令第三条）。
但「参数怎么声明、怎么校验」是同一件事 —— 两套实现必然会漂移，
所以这一层抽出来共用。

导出给 libraries/effect_registry.py 与 libraries/transition_registry.py。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Dict, Iterator, List, Optional, Sequence

#: 参数类型。别名统一收敛到这套内部名字，
#: 这样自定义 JSON 写 "integer" 或 "boolean" 也能被接受。
PARAM_TYPES = ("number", "int", "bool", "string", "enum", "color", "asset")

_TYPE_ALIASES: Dict[str, str] = {
    "integer": "int",
    "boolean": "bool",
    "str": "string",
    "text": "string",
}


def normalize_param_type(raw: Any) -> str:
    name = str(raw or "").strip()
    return _TYPE_ALIASES.get(name, name)


class ParameterDefinition(Mapping):
    """单个参数的定义。

    底层就是既有参数表那份 dict（key/label/type/default/min/max/step/options），
    这里只是给它加上结构化访问和校验能力。
    实现 Mapping 协议，既有按 dict 访问的 GUI 代码不受影响。
    """

    def __init__(self, raw: Dict[str, Any]) -> None:
        self._raw = dict(raw)
        self._raw["type"] = normalize_param_type(self._raw.get("type"))

    # ---- Mapping 协议：让老代码继续把它当 dict 用

    def __getitem__(self, key: str) -> Any:
        return self._raw[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._raw)

    def __len__(self) -> int:
        return len(self._raw)

    def __repr__(self) -> str:  # pragma: no cover - 仅调试用
        return f"ParameterDefinition({self.name}:{self.type})"

    # ---- 结构化访问

    @property
    def name(self) -> str:
        """参数在 params 里的键名。"""
        return str(self._raw.get("key", ""))

    @property
    def display_name(self) -> str:
        return str(self._raw.get("label", self.name))

    @property
    def type(self) -> str:
        return str(self._raw.get("type", ""))

    @property
    def default(self) -> Any:
        return self._raw.get("default")

    @property
    def minimum(self) -> Optional[float]:
        value = self._raw.get("min")
        return None if value is None else float(value)

    @property
    def maximum(self) -> Optional[float]:
        value = self._raw.get("max")
        return None if value is None else float(value)

    @property
    def step(self) -> Optional[float]:
        value = self._raw.get("step")
        return None if value is None else float(value)

    @property
    def options(self) -> List[str]:
        return [str(o) for o in self._raw.get("options", [])]

    @property
    def ui(self) -> str:
        """GUI 该用什么控件。没显式声明就按类型推一个合理默认。"""
        explicit = self._raw.get("ui")
        if explicit:
            return str(explicit)
        if self.type in ("number", "int"):
            return "slider" if (self.minimum is not None and self.maximum is not None) else "spin"
        return {"bool": "checkbox", "enum": "combo", "color": "color", "asset": "asset"}.get(
            self.type, "line"
        )

    # ---- 校验

    def check(self, value: Any) -> List[Dict[str, str]]:
        """校验一个取值，返回错误列表（空 = 合法）。不抛异常。"""
        kind = self.type
        if kind == "bool":
            if not isinstance(value, bool):
                return [self._error("TYPE_MISMATCH", "必须是 true / false")]
            return []
        if kind in ("number", "int"):
            # bool 是 int 的子类，但 1 当成数字参数是数据错误，不要放过
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return [self._error("TYPE_MISMATCH", "必须是数字")]
            if kind == "int" and isinstance(value, float) and value != int(value):
                return [self._error("TYPE_MISMATCH", "必须是整数")]
            return self._check_range(float(value))
        if kind == "enum":
            if not isinstance(value, str):
                return [self._error("TYPE_MISMATCH", "必须是字符串")]
            if self.options and value not in self.options:
                return [
                    self._error(
                        "INVALID_OPTION",
                        f"只能是 {' / '.join(self.options)}，收到 {value}",
                    )
                ]
            return []
        if kind in ("string", "color", "asset"):
            if not isinstance(value, str):
                return [self._error("TYPE_MISMATCH", "必须是字符串")]
            return []
        # 未知类型不做判断，交给 schema 层；这里不能自己造错
        return []

    def _check_range(self, value: float) -> List[Dict[str, str]]:
        low, high = self.minimum, self.maximum
        if low is not None and value < low:
            return [self._error("OUT_OF_RANGE", self._range_message())]
        if high is not None and value > high:
            return [self._error("OUT_OF_RANGE", self._range_message())]
        return []

    def _range_message(self) -> str:
        low, high = self.minimum, self.maximum
        if low is not None and high is not None:
            return f"必须在 {low}～{high} 范围内"
        if low is not None:
            return f"必须不小于 {low}"
        return f"必须不大于 {high}"

    def _error(self, code: str, message: str) -> Dict[str, str]:
        return {"code": code, "parameter": self.name, "message": f"{self.display_name}：{message}"}


def ok_report() -> Dict[str, Any]:
    return {"valid": True, "errors": [], "warnings": []}


def error_report(code: str, message: str, subject_key: str, subject: str,
                 parameter: str = "") -> Dict[str, Any]:
    """单条错误的报告。subject_key 是 "effect" 或 "transition"。"""
    return {
        "valid": False,
        "errors": [
            {"code": code, "parameter": parameter, subject_key: subject, "message": message}
        ],
        "warnings": [],
    }


def validate_params(
    parameters: Sequence[ParameterDefinition],
    params: Any,
    subject_key: str,
    subject: str,
) -> Dict[str, Any]:
    """按参数表校验一份 params。永远返回结构化结果，永远不抛异常。

    - 缺参数 → warning MISSING_PARAMETER（Runtime 会补默认值）
    - 类型 / 范围 / 枚举不对 → error
    - 参数表之外的键 → warning UNKNOWN_PARAMETER
    """
    if params is None:
        params = {}
    if not isinstance(params, dict):
        return error_report(
            "INVALID_PARAMS",
            f"params 必须是对象，收到 {type(params).__name__}",
            subject_key,
            subject,
        )

    errors: List[Dict[str, str]] = []
    warnings: List[Dict[str, str]] = []
    by_key = {p.name: p for p in parameters}

    for parameter in parameters:
        if parameter.name not in params:
            warnings.append(
                {
                    "code": "MISSING_PARAMETER",
                    "parameter": parameter.name,
                    subject_key: subject,
                    "message": f"{parameter.display_name} 缺省，将使用默认值 {parameter.default}",
                }
            )
            continue
        for issue in parameter.check(params[parameter.name]):
            issue[subject_key] = subject
            errors.append(issue)

    for key in params:
        if key not in by_key:
            warnings.append(
                {
                    "code": "UNKNOWN_PARAMETER",
                    "parameter": str(key),
                    subject_key: subject,
                    "message": f"参数 {key} 不在 {subject} 的参数表中，渲染时会被忽略",
                }
            )

    return {"valid": not errors, "errors": errors, "warnings": warnings}
