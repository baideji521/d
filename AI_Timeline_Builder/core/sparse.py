"""Canonical Sparse Serialization：把「用户编辑意图」从「默认配置」里剥出来。

阶段 6.5 的核心模块。三层边界（指令第三条）：

    Timeline JSON        只保存显式编辑状态（本模块的 sparse_* 负责）
    TimelineModel        读 JSON，提供 effective value（core/timeline.py 的 effective_*）
    Remotion Runtime     渲染时补默认值（`element.speed ?? 1` 之类，已有实现）

两条铁律：

1. **只有取值等于 Runtime 默认值时才允许省略。**
   工厂创建时的摆放习惯（text 的 transform.y=0.7、effect 的 easing=easeInOut）
   与 Runtime 默认值不同，省掉它们会改变画面，所以这些字段一律保留。

2. **判断依据是 `value == DEFAULT`，不是 falsy**（指令第二十八条）。
   `opacity=0` / `volume=0` / `speed=0` / `enabled=false` 都是合法的显式取值，
   本模块任何地方都不写 `if not value: remove(...)`。
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional, Set

from core import safe_area as sa
from core import timeline as tl

# ---------------------------------------------------------------- 省略规则

#: 顶层标量字段 → Runtime 默认值。相等才省。
_SCALAR_DEFAULTS: Dict[str, Any] = {
    "speed": tl.DEFAULT_SPEED,
    "volume": tl.DEFAULT_VOLUME,
}

#: 嵌套对象字段 → 各子键的 Runtime 默认值。逐键比较，全部省掉后整个对象删除。
_NESTED_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "transform": tl.DEFAULT_TRANSFORM,
    "audio": tl.DEFAULT_AUDIO,
    "fade": tl.DEFAULT_FADE,
}

#: 没有内容时可以整体删除的容器字段。空 = 没有这项编辑，不是「值为空」。
_EMPTY_CONTAINERS = ("keyframes", "params")

#: animation 的「没有动画」标记就是空串（apply_animation 会写 id，清除时写 ""）。
#: 这不是 falsy 判断 —— "" 是这个字段被文档化的默认值。
_EMPTY_STRING_DEFAULTS = ("animation",)

#: 轨道上默认为 False 的开关
_TRACK_FLAG_DEFAULTS: Dict[str, Any] = {"locked": False, "hidden": False}

#: meta 里可省的字段
_META_DEFAULTS: Dict[str, Any] = {
    "background": tl.DEFAULT_BACKGROUND,
    "master_volume": tl.DEFAULT_MASTER_VOLUME,
}


def _same(value: Any, default: Any) -> bool:
    """值是否等于默认值。

    bool 与数字不能互相当成相等：`enabled: 1` 不等于 `enabled: True`，
    数值上 1 == True 会让这种脏数据被悄悄删掉。
    """
    if isinstance(default, bool):
        return isinstance(value, bool) and value == default
    if isinstance(default, (int, float)):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False
        return abs(float(value) - float(default)) < 1e-9
    return value == default


# ---------------------------------------------------------------- 元素


def sparse_element(element: Dict[str, Any]) -> Dict[str, Any]:
    """返回一个只含显式编辑意图的元素副本。不修改入参。"""
    result = copy.deepcopy(element)

    for key, default in _SCALAR_DEFAULTS.items():
        if key in result and _same(result[key], default):
            del result[key]

    for group, defaults in _NESTED_DEFAULTS.items():
        node = result.get(group)
        if not isinstance(node, dict):
            continue
        for key, default in defaults.items():
            if key in node and _same(node[key], default):
                del node[key]
        # 清完变空对象就整体删掉（指令第二十三条）
        if not node:
            del result[group]

    keyframes = result.get("keyframes")
    if isinstance(keyframes, dict):
        # 空曲线等于没打关键帧
        for param in [k for k, v in keyframes.items() if not isinstance(v, list) or not v]:
            del keyframes[param]

    for key in _EMPTY_CONTAINERS:
        node = result.get(key)
        if isinstance(node, dict) and not node:
            del result[key]

    for key in _EMPTY_STRING_DEFAULTS:
        if result.get(key) == "":
            del result[key]

    return result


def effective_element(element: Dict[str, Any]) -> Dict[str, Any]:
    """返回补齐全部默认值的元素副本（调试 / 快照用，不要写回 JSON）。"""
    result = copy.deepcopy(element)
    if tl.supports_transform(result):
        result["transform"] = tl.effective_transform(result)
        result["keyframes"] = tl.effective_keyframes(result)
    if result.get("type") == "video":
        result["speed"] = tl.effective_speed(result)
        result["audio"] = tl.effective_audio(result)
    if result.get("type") == "audio":
        result["speed"] = tl.effective_speed(result)
        result["volume"] = tl.effective_volume(result)
        result["fade"] = tl.effective_fade(result)
    if result.get("type") in ("effect", "transition"):
        result.setdefault("params", {})
    return result


# ---------------------------------------------------------------- 轨道


def active_track_ids(timeline: Dict[str, Any]) -> Set[str]:
    """真正被引用的轨道 id（指令第十三条）。

    判断依据是 `element.track`，不是「GUI 里有没有这条轨道」。
    转场 / 特效 / 冻结帧自己也带 track 字段，所以 from / to / target
    指向的元素会各自把自己的轨道算进来，不需要额外解引用。
    未来的 Group（阶段 8+）只要它的 children 仍然是带 track 的元素，
    这个函数不用改就能覆盖 —— 本阶段不实现 Group。
    """
    active: Set[str] = set()
    for element in timeline.get("elements", []):
        if not isinstance(element, dict):
            continue
        track_id = element.get("track")
        if isinstance(track_id, str) and track_id:
            active.add(track_id)
    return active


def _is_editor_preset(track: Dict[str, Any]) -> bool:
    """这条轨道是否就是编辑器预设的原样（没改过名字 / 开关）。

    用户自己建的轨道、或者改过名 / 锁过 / 隐藏过的预设轨道，
    都算显式编辑意图，即使上面没有元素也要保留。
    """
    for preset in tl.DEFAULT_TRACKS:
        if preset.get("id") != track.get("id"):
            continue
        if track.get("name") != preset.get("name") or track.get("kind") != preset.get("kind"):
            return False
        for flag, default in _TRACK_FLAG_DEFAULTS.items():
            if not _same(track.get(flag, default), default):
                return False
        return True
    return False


def sparse_tracks(timeline: Dict[str, Any]) -> List[Dict[str, Any]]:
    """导出用的轨道列表：活跃轨道 + 用户显式动过的轨道。

    Schema 要求 tracks 至少一条，所以一个元素都没有时保留主视频轨，
    保证空项目导出的 JSON 依然是合法协议文档。
    """
    active = active_track_ids(timeline)
    result: List[Dict[str, Any]] = []
    for track in timeline.get("tracks", []):
        if not isinstance(track, dict):
            continue
        if track.get("id") in active or not _is_editor_preset(track):
            result.append(_sparse_track(track))
    if result:
        return result
    fallback = tl.get_track(timeline, "V1") or (
        timeline.get("tracks") or [copy.deepcopy(tl.DEFAULT_TRACKS[3])]
    )[0]
    return [_sparse_track(fallback)]


def _sparse_track(track: Dict[str, Any]) -> Dict[str, Any]:
    result = copy.deepcopy(track)
    for flag, default in _TRACK_FLAG_DEFAULTS.items():
        if flag in result and _same(result[flag], default):
            del result[flag]
    return result


def merge_editor_tracks(tracks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """把编辑器预设补回一份轨道列表（指令第十二条）。

    Editor Track Preset 与 Timeline Active Tracks 是两件事：
    导出的 JSON 只留活跃轨道，但编辑器仍然要显示 9 条预设轨，
    否则用户拖第二个视频时无处可放。

    已有轨道的顺序与属性原样保留（用户可能调过顺序，顺序决定 Z-Index），
    缺失的预设轨插到它在预设顺序里该在的位置。
    """
    existing = [copy.deepcopy(t) for t in tracks if isinstance(t, dict) and t.get("id")]
    have = {t["id"] for t in existing}
    preset_order = [p["id"] for p in tl.DEFAULT_TRACKS]

    for index, preset in enumerate(tl.DEFAULT_TRACKS):
        if preset["id"] in have:
            continue
        later = set(preset_order[index + 1:])
        # 插到「预设里排在它后面」的第一条已有轨道之前，保持相对层级
        position = next(
            (i for i, t in enumerate(existing) if t["id"] in later),
            len(existing),
        )
        existing.insert(position, copy.deepcopy(preset))
        have.add(preset["id"])
    return existing


# ---------------------------------------------------------------- 时间线


def sparse_timeline(timeline: Dict[str, Any]) -> Dict[str, Any]:
    """Canonical sparse JSON：保存 / 导出 / 展示都用这一份。"""
    result: Dict[str, Any] = {
        "version": timeline.get("version", tl.SCHEMA_VERSION),
        "time_unit": timeline.get("time_unit", tl.TIME_UNIT),
        "meta": _sparse_meta(timeline.get("meta") or {}),
        "tracks": sparse_tracks(timeline),
        "elements": [
            sparse_element(e) for e in timeline.get("elements", []) if isinstance(e, dict)
        ],
    }
    result["meta"]["duration"] = tl.timeline_duration(timeline)
    return result


def effective_timeline(timeline: Dict[str, Any]) -> Dict[str, Any]:
    """补齐默认值的完整快照（调试用，不要拿去保存）。"""
    result = copy.deepcopy(timeline)
    result["elements"] = [
        effective_element(e) for e in timeline.get("elements", []) if isinstance(e, dict)
    ]
    meta = result.setdefault("meta", {})
    meta.setdefault("background", tl.DEFAULT_BACKGROUND)
    meta["duration"] = tl.timeline_duration(timeline)
    return result


def _sparse_meta(meta: Dict[str, Any]) -> Dict[str, Any]:
    result = copy.deepcopy(meta)
    for key, default in _META_DEFAULTS.items():
        if key in result and _same(result[key], default):
            del result[key]
    # 标记是用户显式意图，原样保留；但空列表等于「没有标记」，不落盘（稀疏规则 6）
    if isinstance(result.get("markers"), list) and not result["markers"]:
        del result["markers"]
    # 安全区档位：通用档就是默认值，写进 JSON 等于凭空多一个字段。
    # 用户改成抖音 / Shorts / Reels 才落盘，改回通用要再删掉。
    safe = result.get("safe_area")
    if isinstance(safe, dict):
        if not safe or (list(safe) == ["preset"]
                        and _same(safe.get("preset"), sa.DEFAULT_PRESET_ID)):
            del result["safe_area"]
    return result


def elided_fields(element: Dict[str, Any]) -> List[str]:
    """这个元素上有哪些字段会被省略。写日志 / 调试用。"""
    before = set(_flatten_keys(element))
    after = set(_flatten_keys(sparse_element(element)))
    return sorted(before - after)


def _flatten_keys(element: Dict[str, Any], prefix: str = "") -> List[str]:
    keys: List[str] = []
    for key, value in element.items():
        path = f"{prefix}{key}"
        keys.append(path)
        if isinstance(value, dict):
            keys.extend(_flatten_keys(value, f"{path}."))
    return keys
