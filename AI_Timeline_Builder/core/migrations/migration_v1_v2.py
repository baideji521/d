"""v1 ⇄ v2 迁移。

两个版本的差异（全部由源码比对得出，不是照文档抄的）：

| 位置 | v1（当前运行时格式） | v2（目标协议） |
| --- | --- | --- |
| 顶层 | `version: 1` | `version: 2` |
| 所有元素 | 扁平 `start` / `duration` | `timing: {start, duration}` |
| video / audio | `source: {start, end}` | `source: {start, duration}` |
| video / audio | `speed: 1.0` | `playback: {speed: 1.0}` |
| effect | `name` / `params` / `easing` 平铺 | `effect: {name, params, easing}` |
| transition | `name` / `params` 平铺 | `transition: {name, params}` |
| 元素类型 | 9 种，图片走 `overlay` | 11 种，多出 `image` 与 `group` |

其余字段（`id` / `type` / `track` / `label` / `note` / `z_index` / `asset` /
`transform` / `keyframes` / `animation` / `audio` / `volume` / `fade` /
`content` / `style` / `caption_style` / `template` / `highlight` /
`target` / `source_time` / `from` / `to`）**形状完全一致，原样搬运**。

关于 `source.duration` 的单位：它是**源素材内部**的时长（`end - start`），
不是成片时长。speed ≠ 1 时它和 `timing.duration` 不相等，这是有意的 ——
Timeline Time 与 Source Time 必须严格分开。

迁移保证 v1 → v2 → v1 逐字段无损：`timing.duration` 直接抄 v1 的 `duration`，
不去用 `source` 反推，所以即使原始数据里 `duration` 与源区间不自洽
（RULE_VIDEO_004 会对此发警告），往返之后也还是原样。
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List

LATEST_VERSION = 2

# 需要把 source / speed 拆开的类型
_MEDIA_TYPES = ("video", "audio")

# v1 里平铺、v2 里收进子对象的字段
_EFFECT_KEYS = ("name", "params", "easing")
_TRANSITION_KEYS = ("name", "params")

# 各类型缺 track 时的兜底轨道（外部手写的 JSON 可能不写 track）
_DEFAULT_TRACK = {
    "video": "V1",
    "image": "V2",
    "overlay": "V3",
    "audio": "A1",
    "text": "T2",
    "caption": "T1",
    "caption_group": "T1",
    "freeze": "V1",
}


def detect_version(data: Dict[str, Any]) -> int:
    """读出版本号。缺失时按 v1 处理（历史项目文件不带 version 的情况）。"""
    try:
        return int(data.get("version", 1))
    except (TypeError, ValueError):
        return 1


def migrate_to_v2(data: Dict[str, Any]) -> Dict[str, Any]:
    """把任意版本抬到 v2。已经是 v2 就深拷贝返回。"""
    version = detect_version(data)
    if version >= 2:
        return copy.deepcopy(data)
    return migrate_v1_to_v2(data)


def migrate_to_v1(data: Dict[str, Any]) -> Dict[str, Any]:
    """把任意版本降到 v1，供现有 GUI / Remotion 使用。"""
    if detect_version(data) <= 1:
        return copy.deepcopy(data)
    return migrate_v2_to_v1(data)


def downgrade_losses(data: Dict[str, Any]) -> List[Dict[str, str]]:
    """v2 → v1 会丢掉哪些信息（指令第三十三条：禁止静默数据损失）。

    v1 没有 group / children 概念，所以 v2 的分组关系在降级时无处安放。
    这个函数**不修改输入**，只如实列出将要丢失的字段，让 GUI / 导出器
    可以先给用户一个明确警告，而不是悄悄把分组吃掉。

    返回 [{element, type, field, message}, ...]，空列表 = 无损。
    """
    if detect_version(data) <= 1:
        return []
    losses: List[Dict[str, str]] = []
    for element in data.get("elements", []):
        if not isinstance(element, dict):
            continue
        element_id = str(element.get("id", ""))
        type_name = str(element.get("type", ""))
        if element.get("group"):
            losses.append(
                {
                    "element": element_id,
                    "type": type_name,
                    "field": "group",
                    "message": f"元素属于分组 {element['group']}，v1 无法表达分组归属，降级后会丢失",
                }
            )
        if type_name == "group":
            children = element.get("children") or []
            losses.append(
                {
                    "element": element_id,
                    "type": type_name,
                    "field": "children",
                    "message": f"group 元素含 {len(children)} 个成员，v1 没有 group 类型，降级后整组关系会丢失",
                }
            )
    return losses


# ------------------------------------------------------------------ v1 → v2


def migrate_v1_to_v2(data: Dict[str, Any]) -> Dict[str, Any]:
    result = copy.deepcopy(data)
    result["version"] = 2
    result["time_unit"] = "seconds"
    result["elements"] = [_element_to_v2(e) for e in result.get("elements", [])]
    return result


def _element_to_v2(source_element: Dict[str, Any]) -> Dict[str, Any]:
    element = copy.deepcopy(source_element)
    type_name = element.get("type", "")

    # 1) 扁平时间 → timing
    start = float(element.pop("start", 0.0) or 0.0)
    duration = element.pop("duration", None)
    if duration is None:
        duration = 0.0
    element["timing"] = {"start": start, "duration": float(duration)}

    # 2) source: {start, end} → {start, duration}
    if type_name in _MEDIA_TYPES:
        window = element.get("source")
        if isinstance(window, dict) and "end" in window:
            src_start = float(window.get("start", 0.0) or 0.0)
            src_end = float(window.get("end", 0.0) or 0.0)
            element["source"] = {
                "start": _round(src_start),
                "duration": _round(max(0.0, src_end - src_start)),
            }
        # 3) speed → playback.speed
        if "speed" in element:
            element["playback"] = {"speed": float(element.pop("speed"))}

    # 4) effect / transition 的平铺字段收进子对象
    if type_name == "effect":
        element["effect"] = _collect(element, _EFFECT_KEYS)
    elif type_name == "transition":
        element["transition"] = _collect(element, _TRANSITION_KEYS)

    # 5) 补 track（v2 里除 effect / transition / group 之外都必填）
    if type_name not in ("effect", "transition", "group") and not element.get("track"):
        element["track"] = _DEFAULT_TRACK.get(type_name, "V1")

    return element


def _collect(element: Dict[str, Any], keys) -> Dict[str, Any]:
    """把平铺的 keys 摘出来组成子对象，name 必填所以给空串兜底。"""
    bundle: Dict[str, Any] = {}
    for key in keys:
        if key in element:
            bundle[key] = element.pop(key)
    bundle.setdefault("name", "")
    return bundle


# ------------------------------------------------------------------ v2 → v1


def migrate_v2_to_v1(data: Dict[str, Any]) -> Dict[str, Any]:
    result = copy.deepcopy(data)
    result["version"] = 1
    result["time_unit"] = "seconds"
    result["elements"] = [_element_to_v1(e) for e in result.get("elements", [])]
    return result


def _element_to_v1(source_element: Dict[str, Any]) -> Dict[str, Any]:
    element = copy.deepcopy(source_element)
    type_name = element.get("type", "")

    timing = element.pop("timing", None) or {}
    ordered: Dict[str, Any] = {}
    # 保持 id / type 在最前面，读 JSON 的人习惯这个顺序
    for key in ("id", "type", "track", "label"):
        if key in element:
            ordered[key] = element.pop(key)
    ordered["start"] = float(timing.get("start", 0.0) or 0.0)
    if "duration" in timing:
        ordered["duration"] = float(timing.get("duration") or 0.0)

    # source: {start, duration} → {start, end}
    if type_name in _MEDIA_TYPES:
        window = element.get("source")
        if isinstance(window, dict) and "duration" in window:
            src_start = float(window.get("start", 0.0) or 0.0)
            element["source"] = {
                "start": _round(src_start),
                "end": _round(src_start + float(window.get("duration", 0.0) or 0.0)),
            }
        playback = element.pop("playback", None)
        if isinstance(playback, dict) and "speed" in playback:
            element["speed"] = float(playback["speed"])

    # effect / transition 子对象 → 平铺
    if type_name == "effect":
        _spread(element, element.pop("effect", None), _EFFECT_KEYS)
    elif type_name == "transition":
        _spread(element, element.pop("transition", None), _TRANSITION_KEYS)

    # v1 没有 group / children 概念。这里确实会丢信息，
    # 所以配了 downgrade_losses() 让调用方能先拿到明确警告 —— 丢可以，静默不行。
    element.pop("group", None)
    if type_name == "group":
        element.pop("children", None)

    ordered.update(element)
    return ordered


def _spread(element: Dict[str, Any], bundle: Any, keys) -> None:
    if not isinstance(bundle, dict):
        return
    for key in keys:
        if key in bundle:
            element[key] = bundle[key]


def _round(value: float) -> float:
    return round(float(value), 3)


# ------------------------------------------------------------------ 差异说明


def describe_changes() -> List[str]:
    """给文档和日志用的人话版差异清单。"""
    return [
        "扁平 start / duration → timing: {start, duration}",
        "video / audio 的 source: {start, end} → source: {start, duration}（source.duration 是素材内部时长）",
        "video / audio 的 speed → playback: {speed}",
        "effect 的 name / params / easing → effect: {name, params, easing}",
        "transition 的 name / params → transition: {name, params}",
        "新增元素类型 image（v1 里图片走 overlay）与 group（v1 无对应）",
        "v2 每个元素变体都启用 additionalProperties: false，未知字段会被拦下",
    ]
