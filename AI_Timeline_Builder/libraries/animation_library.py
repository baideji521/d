"""Animation Library：动画 = Keyframe 模板。

动画本身不产生新的 Timeline 元素，而是把一组关键帧写进已有元素的 keyframes 字段。
所以「动画」和「关键帧」在 JSON 层面是同一件事，动画只是预设。

keyframes 的 time 单位是「相对元素起点的秒数」，与 timeline_schema.json 一致。
自定义动画放 assets/animations/*.json。
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

BUILTIN_ANIMATIONS: List[Dict[str, Any]] = [
    {
        "id": "anim_fade_in",
        "label": "Fade In 淡入",
        "category": "淡变",
        "duration": 0.3,
        "description": "不透明度 0 → 1",
        "keyframes": {
            "opacity": [
                {"time": 0.0, "value": 0.0, "easing": "linear"},
                {"time": 0.3, "value": 1.0, "easing": "easeOut"},
            ]
        },
    },
    {
        "id": "anim_fade_out",
        "label": "Fade Out 淡出",
        "category": "淡变",
        "duration": 0.3,
        "description": "不透明度 1 → 0，注意关键帧时间要落在元素末尾",
        "keyframes": {
            "opacity": [
                {"time": 0.0, "value": 1.0, "easing": "linear"},
                {"time": 0.3, "value": 0.0, "easing": "easeIn"},
            ]
        },
    },
    {
        "id": "anim_pop",
        "label": "Pop 弹出",
        "category": "缩放",
        "duration": 0.3,
        "description": "先放大过冲再回落，最常用的入场",
        "keyframes": {
            "scale": [
                {"time": 0.0, "value": 0.6, "easing": "linear"},
                {"time": 0.18, "value": 1.12, "easing": "easeOut"},
                {"time": 0.3, "value": 1.0, "easing": "easeInOut"},
            ],
            "opacity": [
                {"time": 0.0, "value": 0.0, "easing": "linear"},
                {"time": 0.12, "value": 1.0, "easing": "easeOut"},
            ],
        },
    },
    {
        "id": "anim_punch_in",
        "label": "Punch In 冲入",
        "category": "缩放",
        "duration": 0.25,
        "description": "开发指令第十七条示例：0.8 → 1.15 → 1.0",
        "keyframes": {
            "scale": [
                {"time": 0.0, "value": 0.8, "easing": "linear"},
                {"time": 0.18, "value": 1.15, "easing": "easeOut"},
                {"time": 0.25, "value": 1.0, "easing": "easeInOut"},
            ]
        },
    },
    {
        "id": "anim_punch_out",
        "label": "Punch Out 冲出",
        "category": "缩放",
        "duration": 0.25,
        "description": "1.0 → 1.15 → 0.8 并淡出",
        "keyframes": {
            "scale": [
                {"time": 0.0, "value": 1.0, "easing": "linear"},
                {"time": 0.1, "value": 1.15, "easing": "easeOut"},
                {"time": 0.25, "value": 0.8, "easing": "easeIn"},
            ],
            "opacity": [
                {"time": 0.1, "value": 1.0, "easing": "linear"},
                {"time": 0.25, "value": 0.0, "easing": "easeIn"},
            ],
        },
    },
    {
        "id": "anim_bounce",
        "label": "Bounce 弹跳",
        "category": "位移",
        "duration": 0.6,
        "description": "垂直方向两次衰减弹跳",
        "keyframes": {
            "y": [
                {"time": 0.0, "value": 0.42, "easing": "linear"},
                {"time": 0.18, "value": 0.5, "easing": "easeIn"},
                {"time": 0.32, "value": 0.46, "easing": "easeOut"},
                {"time": 0.45, "value": 0.5, "easing": "easeIn"},
                {"time": 0.54, "value": 0.485, "easing": "easeOut"},
                {"time": 0.6, "value": 0.5, "easing": "easeIn"},
            ]
        },
    },
    {
        "id": "anim_elastic",
        "label": "Elastic 弹性",
        "category": "缩放",
        "duration": 0.7,
        "description": "多次过冲收敛，比 Pop 更夸张",
        "keyframes": {
            "scale": [
                {"time": 0.0, "value": 0.5, "easing": "linear"},
                {"time": 0.2, "value": 1.25, "easing": "easeOut"},
                {"time": 0.36, "value": 0.92, "easing": "easeInOut"},
                {"time": 0.52, "value": 1.06, "easing": "easeInOut"},
                {"time": 0.66, "value": 0.98, "easing": "easeInOut"},
                {"time": 0.7, "value": 1.0, "easing": "easeOut"},
            ]
        },
    },
    {
        "id": "anim_slide_in",
        "label": "Slide In 滑入",
        "category": "位移",
        "duration": 0.35,
        "description": "从画面左侧外滑入到中心",
        "keyframes": {
            "x": [
                {"time": 0.0, "value": -0.25, "easing": "linear"},
                {"time": 0.35, "value": 0.5, "easing": "easeOut"},
            ],
            "opacity": [
                {"time": 0.0, "value": 0.0, "easing": "linear"},
                {"time": 0.12, "value": 1.0, "easing": "easeOut"},
            ],
        },
    },
    {
        "id": "anim_slide_out",
        "label": "Slide Out 滑出",
        "category": "位移",
        "duration": 0.35,
        "description": "从中心滑出到画面右侧外",
        "keyframes": {
            "x": [
                {"time": 0.0, "value": 0.5, "easing": "linear"},
                {"time": 0.35, "value": 1.25, "easing": "easeIn"},
            ]
        },
    },
    {
        "id": "anim_rotate_in",
        "label": "Rotate In 旋入",
        "category": "旋转",
        "duration": 0.4,
        "description": "带旋转的入场",
        "keyframes": {
            "rotation": [
                {"time": 0.0, "value": -25.0, "easing": "linear"},
                {"time": 0.4, "value": 0.0, "easing": "easeOut"},
            ],
            "scale": [
                {"time": 0.0, "value": 0.7, "easing": "linear"},
                {"time": 0.4, "value": 1.0, "easing": "easeOut"},
            ],
        },
    },
    {
        "id": "anim_rotate_out",
        "label": "Rotate Out 旋出",
        "category": "旋转",
        "duration": 0.4,
        "description": "带旋转的退场",
        "keyframes": {
            "rotation": [
                {"time": 0.0, "value": 0.0, "easing": "linear"},
                {"time": 0.4, "value": 25.0, "easing": "easeIn"},
            ],
            "opacity": [
                {"time": 0.0, "value": 1.0, "easing": "linear"},
                {"time": 0.4, "value": 0.0, "easing": "easeIn"},
            ],
        },
    },
    {
        "id": "anim_shake",
        "label": "Shake 抖动",
        "category": "位移",
        "duration": 0.4,
        "description": "左右快速抖动，纯关键帧实现（与 Effect 的 shake 不同：这个只影响单个元素）",
        "keyframes": {
            "x": [
                {"time": 0.0, "value": 0.5, "easing": "linear"},
                {"time": 0.05, "value": 0.52, "easing": "linear"},
                {"time": 0.1, "value": 0.48, "easing": "linear"},
                {"time": 0.15, "value": 0.515, "easing": "linear"},
                {"time": 0.2, "value": 0.485, "easing": "linear"},
                {"time": 0.3, "value": 0.505, "easing": "linear"},
                {"time": 0.4, "value": 0.5, "easing": "linear"},
            ]
        },
    },
    {
        "id": "anim_pulse",
        "label": "Pulse 呼吸",
        "category": "缩放",
        "duration": 0.8,
        "description": "缩放来回一次，可复制多份做持续呼吸",
        "keyframes": {
            "scale": [
                {"time": 0.0, "value": 1.0, "easing": "linear"},
                {"time": 0.4, "value": 1.08, "easing": "easeInOut"},
                {"time": 0.8, "value": 1.0, "easing": "easeInOut"},
            ]
        },
    },
]


class AnimationLibrary:
    """动画（关键帧模板）库。"""

    def __init__(self, assets_dir: str = "") -> None:
        self._dir = os.path.join(assets_dir, "animations") if assets_dir else ""
        self._items: Dict[str, Dict[str, Any]] = {a["id"]: a for a in BUILTIN_ANIMATIONS}
        self._load_custom()

    def _load_custom(self) -> None:
        if not self._dir or not os.path.isdir(self._dir):
            return
        for entry in sorted(os.listdir(self._dir)):
            if not entry.endswith(".json"):
                continue
            try:
                with open(os.path.join(self._dir, entry), "r", encoding="utf-8") as handle:
                    data = json.load(handle)
            except (OSError, json.JSONDecodeError):
                continue
            items = data.get("animations") or ([data] if data.get("id") else [])
            for item in items:
                if item.get("id"):
                    self._items[item["id"]] = item

    def all(self) -> List[Dict[str, Any]]:
        return list(self._items.values())

    def get(self, animation_id: str) -> Optional[Dict[str, Any]]:
        return self._items.get(animation_id)

    def has(self, animation_id: str) -> bool:
        return animation_id in self._items

    def label_of(self, animation_id: str) -> str:
        item = self._items.get(animation_id)
        return item.get("label", animation_id) if item else animation_id

    def categories(self) -> List[str]:
        return sorted({a.get("category", "") for a in self._items.values() if a.get("category")})

    def scaled_keyframes(self, animation_id: str, target_duration: float) -> Dict[str, Any]:
        """把动画的关键帧按比例拉伸到指定时长。

        比如 0.25s 的 punch_in 想铺满 1s 的元素，就整体乘以 4。
        """
        animation = self._items.get(animation_id)
        if not animation:
            return {}
        base = float(animation.get("duration", 0.0)) or 1.0
        factor = float(target_duration) / base if target_duration > 0 else 1.0
        result: Dict[str, Any] = {}
        for param, points in (animation.get("keyframes") or {}).items():
            result[param] = [
                {
                    "time": round(float(p.get("time", 0.0)) * factor, 3),
                    "value": p.get("value", 0.0),
                    "easing": p.get("easing", "linear"),
                }
                for p in points
            ]
        return result

    def save_animation(self, animation: Dict[str, Any]) -> str:
        """把当前元素的关键帧存成新动画，返回文件路径。"""
        if not self._dir:
            return ""
        os.makedirs(self._dir, exist_ok=True)
        animation_id = animation.get("id") or "anim_custom"
        animation = dict(animation)
        animation["id"] = animation_id
        path = os.path.join(self._dir, f"{animation_id}.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"version": 1, "animations": [animation]}, handle, ensure_ascii=False, indent=2)
        self._items[animation_id] = animation
        return path
