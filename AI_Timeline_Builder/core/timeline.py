"""Timeline 数据定义与纯函数工具。

这里不依赖 PyQt，只负责：
- 默认轨道定义
- 各类元素的工厂函数（保证 JSON 字段齐全、命名统一）
- Keyframe 求值与 Easing（GUI 预览与 Remotion 侧使用同一套语义）
- 时间线派生信息（总时长、Z-Index）

设计原则：JSON 就是唯一真相，所有元素都是普通 dict，不做成 Python 类。
这样 GUI → JSON 与 JSON → GUI 两个方向不存在信息损失。
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = 1
TIME_UNIT = "seconds"

# ---------------------------------------------------------------- 默认轨道

# 顺序即从下到上的图层顺序：列表越靠后越靠上层（Z-Index 越大）
DEFAULT_TRACKS: List[Dict[str, Any]] = [
    {"id": "A1", "name": "A1 背景音乐", "kind": "audio", "locked": False, "hidden": False},
    {"id": "A2", "name": "A2 人声", "kind": "audio", "locked": False, "hidden": False},
    {"id": "A3", "name": "A3 音效", "kind": "audio", "locked": False, "hidden": False},
    {"id": "V1", "name": "V1 主视频", "kind": "video", "locked": False, "hidden": False},
    {"id": "V2", "name": "V2 视频叠加", "kind": "video", "locked": False, "hidden": False},
    {"id": "V3", "name": "V3 图片/Overlay", "kind": "video", "locked": False, "hidden": False},
    {"id": "V4", "name": "V4 高层 Overlay", "kind": "video", "locked": False, "hidden": False},
    {"id": "T1", "name": "T1 字幕", "kind": "text", "locked": False, "hidden": False},
    {"id": "T2", "name": "T2 普通文字", "kind": "text", "locked": False, "hidden": False},
]

# Timeline 面板自上而下的显示顺序（与图层顺序相反）
TRACK_DISPLAY_ORDER = ["T2", "T1", "V4", "V3", "V2", "V1", "A3", "A2", "A1"]

# 元素类型 -> 允许放置的轨道 kind
TYPE_TRACK_KIND = {
    "video": "video",
    "overlay": "video",
    "freeze": "video",
    "effect": "video",
    "transition": "video",
    "text": "text",
    "caption": "text",
    "caption_group": "text",
    "audio": "audio",
}

ELEMENT_TYPE_LABELS = {
    "video": "视频片段",
    "overlay": "图片/Overlay",
    "text": "文字",
    "caption": "字幕",
    "caption_group": "逐词字幕",
    "audio": "音频",
    "effect": "特效",
    "transition": "转场",
    "freeze": "冻结帧",
}

KEYFRAME_PARAMS = [
    "scale",
    "x",
    "y",
    "rotation",
    "opacity",
    "blur",
    "brightness",
    "contrast",
    "saturation",
]

KEYFRAME_PARAM_LABELS = {
    "scale": "缩放 Scale",
    "x": "位置 X",
    "y": "位置 Y",
    "rotation": "旋转 Rotation",
    "opacity": "不透明度 Opacity",
    "blur": "模糊 Blur",
    "brightness": "亮度 Brightness",
    "contrast": "对比度 Contrast",
    "saturation": "饱和度 Saturation",
}

# 各 Keyframe 参数的中性值（没有关键帧时的取值）
KEYFRAME_NEUTRAL = {
    "scale": 1.0,
    "x": 0.5,
    "y": 0.5,
    "rotation": 0.0,
    "opacity": 1.0,
    "blur": 0.0,
    "brightness": 1.0,
    "contrast": 1.0,
    "saturation": 1.0,
}

EASINGS = ["linear", "easeIn", "easeOut", "easeInOut"]
EASING_LABELS = {
    "linear": "Linear 线性",
    "easeIn": "EaseIn 缓入",
    "easeOut": "EaseOut 缓出",
    "easeInOut": "EaseInOut 缓入缓出",
}


def default_transform() -> Dict[str, float]:
    """标准 transform：画面居中、原始大小、不旋转、完全不透明。"""
    return {"x": 0.5, "y": 0.5, "scale": 1.0, "rotation": 0.0, "opacity": 1.0}


# ---------------------------------------------------------------- 空时间线


def empty_timeline(
    name: str = "未命名项目",
    fps: float = 30,
    width: int = 1080,
    height: int = 1920,
) -> Dict[str, Any]:
    """创建一条只有默认轨道的空时间线。"""
    return {
        "version": SCHEMA_VERSION,
        "time_unit": TIME_UNIT,
        "meta": {
            "name": name,
            "fps": fps,
            "width": width,
            "height": height,
            "duration": 0.0,
            "background": "#000000",
        },
        "tracks": copy.deepcopy(DEFAULT_TRACKS),
        "elements": [],
    }


# ---------------------------------------------------------------- 元素工厂


def make_video(
    element_id: str,
    asset_id: str,
    track: str = "V1",
    start: float = 0.0,
    source_start: float = 0.0,
    source_end: float = 3.0,
    speed: float = 1.0,
) -> Dict[str, Any]:
    """视频片段。duration 由源区间与速度决定，GUI 会同时展示这三组时间。"""
    duration = max(0.04, (source_end - source_start) / max(0.01, speed))
    return {
        "id": element_id,
        "type": "video",
        "track": track,
        "asset": asset_id,
        "start": round(start, 3),
        "duration": round(duration, 3),
        "source": {"start": round(source_start, 3), "end": round(source_end, 3)},
        "transform": default_transform(),
        "speed": speed,
        "audio": {"enabled": True, "volume": 1.0},
        "keyframes": {},
    }


def make_overlay(
    element_id: str,
    asset_id: str,
    track: str = "V3",
    start: float = 0.0,
    duration: float = 1.0,
) -> Dict[str, Any]:
    """图片 / 透明视频 Overlay。素材特效也走这个类型，靠 asset 区分。"""
    return {
        "id": element_id,
        "type": "overlay",
        "track": track,
        "asset": asset_id,
        "start": round(start, 3),
        "duration": round(duration, 3),
        "transform": default_transform(),
        "keyframes": {},
    }


def make_text(
    element_id: str,
    text: str,
    track: str = "T2",
    start: float = 0.0,
    duration: float = 1.0,
) -> Dict[str, Any]:
    """普通文字 / 标题 / 强调文字。与 Caption 完全分开。"""
    return {
        "id": element_id,
        "type": "text",
        "track": track,
        "start": round(start, 3),
        "duration": round(duration, 3),
        "content": {"text": text},
        "style": {
            "fontFamily": "Arial",
            "fontSize": 96,
            "fontWeight": 900,
            "color": "#FFFFFF",
            "align": "center",
            "stroke": {"width": 8, "color": "#000000"},
        },
        "transform": {"x": 0.5, "y": 0.7, "scale": 1.0, "rotation": 0.0, "opacity": 1.0},
        "keyframes": {},
    }


def make_caption(
    element_id: str,
    text: str,
    track: str = "T1",
    start: float = 0.0,
    duration: float = 1.2,
    template: str = "bold_white",
    caption_style: str = "plain",
) -> Dict[str, Any]:
    """整句字幕。"""
    return {
        "id": element_id,
        "type": "caption",
        "track": track,
        "start": round(start, 3),
        "duration": round(duration, 3),
        "template": template,
        "caption_style": caption_style,
        "content": {"text": text},
        "style": {
            "fontFamily": "Arial",
            "fontSize": 64,
            "fontWeight": 800,
            "color": "#FFFFFF",
            "align": "center",
            "stroke": {"width": 6, "color": "#000000"},
        },
        "transform": {"x": 0.5, "y": 0.82, "scale": 1.0, "rotation": 0.0, "opacity": 1.0},
        "keyframes": {},
    }


def make_caption_group(
    element_id: str,
    words: List[Dict[str, Any]],
    track: str = "T1",
    template: str = "highlight_yellow",
    caption_style: str = "highlight_current",
) -> Dict[str, Any]:
    """逐词字幕。words 里的时间是绝对时间线秒数，start/duration 由首尾词推出。"""
    start = min(w["start"] for w in words) if words else 0.0
    end = max(w["end"] for w in words) if words else start + 0.5
    return {
        "id": element_id,
        "type": "caption_group",
        "track": track,
        "start": round(start, 3),
        "duration": round(max(0.04, end - start), 3),
        "template": template,
        "caption_style": caption_style,
        "content": {"words": copy.deepcopy(words)},
        "style": {
            "fontFamily": "Arial",
            "fontSize": 64,
            "fontWeight": 800,
            "color": "#FFFFFF",
            "align": "center",
            "stroke": {"width": 6, "color": "#000000"},
        },
        "highlight": {"color": "#FFE347", "backgroundColor": "", "scale": 1.12},
        "transform": {"x": 0.5, "y": 0.82, "scale": 1.0, "rotation": 0.0, "opacity": 1.0},
        "keyframes": {},
    }


def make_audio(
    element_id: str,
    asset_id: str,
    track: str = "A3",
    start: float = 0.0,
    duration: float = 1.0,
    source_start: float = 0.0,
    volume: float = 1.0,
) -> Dict[str, Any]:
    """音频。BGM / 人声 / 音效共用此类型，靠轨道区分用途。"""
    return {
        "id": element_id,
        "type": "audio",
        "track": track,
        "asset": asset_id,
        "start": round(start, 3),
        "duration": round(duration, 3),
        "source": {"start": round(source_start, 3), "end": round(source_start + duration, 3)},
        "speed": 1.0,
        "volume": volume,
        "fade": {"in": 0.0, "out": 0.0},
    }


def make_effect(
    element_id: str,
    name: str,
    params: Dict[str, Any],
    track: str = "V1",
    start: float = 0.0,
    duration: float = 0.6,
    target: Optional[str] = None,
    easing: str = "easeInOut",
) -> Dict[str, Any]:
    """程序特效。素材特效请用 make_overlay（type=overlay），两者 type 不同。"""
    element = {
        "id": element_id,
        "type": "effect",
        "track": track,
        "name": name,
        "start": round(start, 3),
        "duration": round(duration, 3),
        "easing": easing,
        "params": copy.deepcopy(params),
    }
    if target:
        element["target"] = target
    return element


def make_transition(
    element_id: str,
    name: str,
    from_id: str,
    to_id: str,
    start: float,
    duration: float,
    params: Dict[str, Any],
    track: str = "V1",
) -> Dict[str, Any]:
    """转场。必须绑定 from / to 两个 Video Clip。"""
    return {
        "id": element_id,
        "type": "transition",
        "track": track,
        "name": name,
        "from": from_id,
        "to": to_id,
        "start": round(start, 3),
        "duration": round(duration, 3),
        "params": copy.deepcopy(params),
    }


def make_freeze(
    element_id: str,
    target: str,
    source_time: float,
    start: float,
    duration: float = 1.5,
    track: str = "V1",
) -> Dict[str, Any]:
    """冻结帧。source_time 是要冻住的源素材时间点。"""
    return {
        "id": element_id,
        "type": "freeze",
        "track": track,
        "target": target,
        "source_time": round(source_time, 3),
        "start": round(start, 3),
        "duration": round(duration, 3),
        "transform": default_transform(),
        "keyframes": {},
    }


# ---------------------------------------------------------------- Easing


def apply_easing(t: float, easing: str = "linear") -> float:
    """把 0..1 的线性进度映射为带缓动的进度。语义与 Remotion 侧保持一致。"""
    t = 0.0 if t < 0 else (1.0 if t > 1 else t)
    if easing == "easeIn":
        return t * t
    if easing == "easeOut":
        return 1.0 - (1.0 - t) * (1.0 - t)
    if easing == "easeInOut":
        if t < 0.5:
            return 2.0 * t * t
        return 1.0 - 2.0 * (1.0 - t) * (1.0 - t)
    return t


def evaluate_keyframes(
    keyframes: List[Dict[str, Any]],
    local_time: float,
    fallback: float,
) -> float:
    """在给定相对时间求关键帧曲线的值。

    keyframes 为 [{time, value, easing}]，time 相对元素起点。
    区间外做端点保持（clamp），区间内按后一个关键帧的 easing 插值。
    """
    if not keyframes:
        return fallback
    points = sorted(keyframes, key=lambda k: float(k.get("time", 0.0)))
    if local_time <= float(points[0].get("time", 0.0)):
        return float(points[0].get("value", fallback))
    if local_time >= float(points[-1].get("time", 0.0)):
        return float(points[-1].get("value", fallback))
    for i in range(len(points) - 1):
        a, b = points[i], points[i + 1]
        ta, tb = float(a.get("time", 0.0)), float(b.get("time", 0.0))
        if ta <= local_time <= tb:
            span = tb - ta
            raw = 0.0 if span <= 0 else (local_time - ta) / span
            eased = apply_easing(raw, b.get("easing", "linear"))
            va, vb = float(a.get("value", fallback)), float(b.get("value", fallback))
            return va + (vb - va) * eased
    return fallback


def resolve_animated_value(
    element: Dict[str, Any],
    param: str,
    local_time: float,
) -> float:
    """取某个参数在给定相对时间的最终值：优先关键帧，其次 transform，最后中性值。"""
    neutral = KEYFRAME_NEUTRAL.get(param, 0.0)
    base = neutral
    transform = element.get("transform") or {}
    if param in transform:
        base = float(transform[param])
    keyframes = (element.get("keyframes") or {}).get(param)
    if keyframes:
        return evaluate_keyframes(keyframes, local_time, base)
    return base


# ---------------------------------------------------------------- 派生信息


def timeline_duration(timeline: Dict[str, Any]) -> float:
    """时间线总时长 = 所有元素结束时间的最大值。"""
    end = 0.0
    for element in timeline.get("elements", []):
        e = float(element.get("start", 0.0)) + float(element.get("duration", 0.0))
        end = max(end, e)
    return round(end, 3)


def track_z_index(timeline: Dict[str, Any], track_id: str) -> int:
    """轨道顺序决定默认 Z-Index：tracks 列表中越靠后越上层。"""
    for index, track in enumerate(timeline.get("tracks", [])):
        if track.get("id") == track_id:
            return index * 10
    return 0


def get_track(timeline: Dict[str, Any], track_id: str) -> Optional[Dict[str, Any]]:
    """按 id 找轨道。"""
    for track in timeline.get("tracks", []):
        if track.get("id") == track_id:
            return track
    return None


def get_element(timeline: Dict[str, Any], element_id: str) -> Optional[Dict[str, Any]]:
    """按 id 找元素。"""
    for element in timeline.get("elements", []):
        if element.get("id") == element_id:
            return element
    return None


def elements_on_track(timeline: Dict[str, Any], track_id: str) -> List[Dict[str, Any]]:
    """取某轨道上的元素，按开始时间排序。"""
    items = [e for e in timeline.get("elements", []) if e.get("track") == track_id]
    return sorted(items, key=lambda e: float(e.get("start", 0.0)))


def element_end(element: Dict[str, Any]) -> float:
    """元素在时间线上的结束时间。"""
    return float(element.get("start", 0.0)) + float(element.get("duration", 0.0))


def next_element_id(timeline: Dict[str, Any], type_name: str) -> str:
    """生成不冲突的元素 id，如 clip_001 / effect_003。"""
    prefix = {
        "video": "clip",
        "overlay": "overlay",
        "text": "text",
        "caption": "caption",
        "caption_group": "captiongroup",
        "audio": "audio",
        "effect": "effect",
        "transition": "transition",
        "freeze": "freeze",
    }.get(type_name, type_name)
    existing = {e.get("id") for e in timeline.get("elements", [])}
    index = 1
    while True:
        candidate = f"{prefix}_{index:03d}"
        if candidate not in existing:
            return candidate
        index += 1
