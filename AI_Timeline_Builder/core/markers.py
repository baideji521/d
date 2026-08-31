"""时间线标记（Marker）。

Marker 是**纯标注**：给人看的时间点（高潮在哪、该切镜了、这里要加音效），
不参与渲染，Remotion 完全忽略它。所以它不进 elements，而是挂在 meta 上：

    "meta": { ..., "markers": [ {"time": 12.5, "type": "highlight", "label": "高潮"} ] }

为什么放 meta 而不是新开一个顶层字段：
- 顶层字段要改 v1/v2 两份 schema 的根结构，还要过 migration，动静太大
- meta 本来就是"项目级信息"的家（fps / 分辨率 / 背景色），标记属于同一类
- 没有标记时整个 markers 键**不出现**，稀疏性不受影响

老 JSON 没有 markers 键 → markers_of() 返回空列表，什么都不会坏；
新 JSON 带 markers → 老代码读 meta 时会忽略这个键（Remotion 只读 fps/宽高/背景）。
这就是"兼容扩展"的含义。
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

#: 标记类型 → 中文名 / 颜色。颜色给 GUI 画三角旗用。
MARKER_TYPES: Dict[str, Dict[str, str]] = {
    "normal": {"label": "普通", "color": "#8fa3bf"},
    "highlight": {"label": "高潮", "color": "#ff6b6b"},
    "transition": {"label": "转场", "color": "#4fd1c5"},
    "caption": {"label": "字幕", "color": "#ffe347"},
    "sfx": {"label": "音效", "color": "#b794f4"},
    "ai_highlight": {"label": "AI 精彩点", "color": "#f6ad55"},
    # 配音派生的标记（VoiceDirector → VoicePlanCompiler 写入）。
    # 单独两类而不是复用 ai_highlight：报告和 EditingPlanner 要能分清
    # 「这是声音里的重音」和「这是画面上的精彩点」，两者该配的动作不一样。
    "voice_peak": {"label": "配音重音", "color": "#f687b3"},
    "voice_pause": {"label": "配音停顿", "color": "#63b3ed"},
}

DEFAULT_TYPE = "normal"


def type_label(marker_type: str) -> str:
    return MARKER_TYPES.get(str(marker_type), {}).get("label", str(marker_type))


def type_color(marker_type: str) -> str:
    return MARKER_TYPES.get(str(marker_type), {}).get("color", "#8fa3bf")


def normalize(marker: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """把一条标记规整成 {time, type, label?}；不合法就返回 None。

    label 为空时**不写这个键**（稀疏原则：默认值不落盘）。
    """
    if not isinstance(marker, dict):
        return None
    try:
        time = round(max(0.0, float(marker.get("time"))), 3)
    except (TypeError, ValueError):
        return None
    marker_type = str(marker.get("type") or DEFAULT_TYPE)
    if marker_type not in MARKER_TYPES:
        marker_type = DEFAULT_TYPE
    result: Dict[str, Any] = {"time": time, "type": marker_type}
    label = marker.get("label")
    if isinstance(label, str) and label.strip():
        result["label"] = label.strip()
    return result


def markers_of(timeline: Dict[str, Any]) -> List[Dict[str, Any]]:
    """读出标记列表（按时间排序）。没有 markers 键就是空列表。"""
    meta = timeline.get("meta") if isinstance(timeline, dict) else None
    raw = (meta or {}).get("markers") if isinstance(meta, dict) else None
    if not isinstance(raw, list):
        return []
    cleaned = [m for m in (normalize(item) for item in raw) if m]
    return sorted(cleaned, key=lambda m: m["time"])


def marker_times(timeline: Dict[str, Any]) -> List[float]:
    """只要时间点，喂给磁吸系统。"""
    return [float(m["time"]) for m in markers_of(timeline)]


def set_markers(timeline: Dict[str, Any], markers: Iterable[Dict[str, Any]]) -> None:
    """写回标记列表。空列表时**删掉整个键**，不留 "markers": []。"""
    meta = timeline.setdefault("meta", {})
    cleaned = [m for m in (normalize(item) for item in markers) if m]
    cleaned.sort(key=lambda m: m["time"])
    if cleaned:
        meta["markers"] = cleaned
    else:
        meta.pop("markers", None)


def add_marker(timeline: Dict[str, Any], time: float,
               marker_type: str = DEFAULT_TYPE, label: str = "") -> Optional[Dict[str, Any]]:
    """加一条标记。同一时刻同一类型只保留一条（避免连点加出一堆重复）。"""
    marker = normalize({"time": time, "type": marker_type, "label": label})
    if marker is None:
        return None
    existing = [
        m for m in markers_of(timeline)
        if not (abs(m["time"] - marker["time"]) < 1e-6 and m["type"] == marker["type"])
    ]
    existing.append(marker)
    set_markers(timeline, existing)
    return marker


def remove_marker_at(timeline: Dict[str, Any], time: float,
                     tolerance: float = 0.05) -> Optional[Dict[str, Any]]:
    """删掉最接近给定时刻的一条标记（容差内）。返回被删的那条。"""
    markers = markers_of(timeline)
    if not markers:
        return None
    best = min(markers, key=lambda m: abs(m["time"] - float(time)))
    if abs(best["time"] - float(time)) > tolerance:
        return None
    set_markers(timeline, [m for m in markers if m is not best])
    return best


def nearest_marker(timeline: Dict[str, Any], time: float,
                   direction: int = 1) -> Optional[Dict[str, Any]]:
    """找下一个 / 上一个标记，用于"跳到下一个标记"。

    direction > 0 找严格更晚的，< 0 找严格更早的。
    """
    markers = markers_of(timeline)
    if direction >= 0:
        later = [m for m in markers if m["time"] > float(time) + 1e-9]
        return later[0] if later else None
    earlier = [m for m in markers if m["time"] < float(time) - 1e-9]
    return earlier[-1] if earlier else None
